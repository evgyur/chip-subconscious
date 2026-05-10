#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, re, urllib.parse, urllib.request
from pathlib import Path
from subc_common import redact
from subc_paths import room_path, hermes_home

ENV = hermes_home() / '.env'

def env_token():
    vals = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            if line and not line.lstrip().startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN')

def _yaml_unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    return value.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')

def scalar(text, key):
    m = re.search(rf'^{re.escape(key)}:\s*(.*?)\s*$', text, re.M)
    return _yaml_unquote(m.group(1)) if m else ''

def list_items(text: str, key: str, limit: int | None = None) -> list[str]:
    items: list[str] = []
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() == f'{key}:':
            for row in lines[idx + 1:]:
                if not row.startswith('  - '):
                    break
                items.append(_yaml_unquote(row[4:]))
                if limit is not None and len(items) >= limit:
                    return items
            break
    return items

def evidence_summaries(text: str, limit: int = 2) -> list[str]:
    out: list[str] = []
    for m in re.finditer(r'^\s+summary:\s*(.*?)\s*$', text, re.M):
        summary = _yaml_unquote(m.group(1))
        if summary:
            out.append(summary)
        if len(out) >= limit:
            break
    return out

def load_state(state_path: Path):
    if state_path.exists():
        return json.loads(state_path.read_text())
    return {'posted': {}, 'tokens': {}}

def save_state(state_path: Path, s):
    state_path.write_text(json.dumps(s, ensure_ascii=False, indent=2) + '\n')

def token_for_intent(iid: str, state: dict) -> str:
    tokens = state.setdefault('tokens', {})
    for token, mapped in tokens.items():
        if mapped == iid:
            return token
    digest = hashlib.sha1(iid.encode('utf-8')).hexdigest()
    for size in (12, 16, 20, 32, 40):
        token = digest[:size]
        if token not in tokens or tokens[token] == iid:
            tokens[token] = iid
            return token
    raise RuntimeError(f'could not allocate unique callback token for {iid}')

def reply_markup_for(iid: str, state: dict) -> dict:
    token = token_for_intent(iid, state)
    return {'inline_keyboard': [[
        {'text': '✅ Yes', 'callback_data': f'subc:y:{token}'},
        {'text': '❌ No', 'callback_data': f'subc:n:{token}'},
    ]]}

def _bullets(items: list[str], fallback: str = '—') -> str:
    if not items:
        return fallback
    return '\n'.join(f'• {item}' for item in items)

def format_message(iid: str, text: str) -> str:
    title = scalar(text, 'title') or iid
    problem = scalar(text, 'problem')
    suggested = scalar(text, 'suggested_build')
    confidence = scalar(text, 'confidence')
    evidence = evidence_summaries(text, limit=2)
    non_goals = list_items(text, 'non_goals', limit=3)
    acceptance = list_items(text, 'acceptance_criteria', limit=3)
    msg = f"""💡 Proposed intent

{title}

Problem:
{problem or 'A signal crossed the threshold and needs a human decision.'}

Why it surfaced:
{_bullets(evidence, '• Repeated or high-confidence signal found by SUBCONSCIOUS.')}

Suggested build:
{suggested or 'Review the signal and decide whether to create a build task.'}

Non-goals:
{_bullets(non_goals)}

Done when:
{_bullets(acceptance)}

Confidence: {confidence or '—'}
id: {iid}

Tap ✅ Yes to approve, or ❌ No to archive."""
    return redact(msg)

def send(token, chat_id, thread_id, text, reply_markup=None):
    base = f'https://api.telegram.org/bot{token}/sendMessage'
    data = {'chat_id': chat_id, 'message_thread_id': thread_id, 'text': text[:3900]}
    if reply_markup is not None:
        data['reply_markup'] = json.dumps(reply_markup, ensure_ascii=False)
    req = urllib.request.Request(base, data=urllib.parse.urlencode(data).encode(), headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def main():
    room = room_path()
    topics = json.loads((room / 'telegram_topics.json').read_text())
    chat_id = topics['chat_id']
    thread_id = topics['topics']['pending_intents']['message_thread_id']
    token = env_token()
    if not token:
        print('WARN: TELEGRAM_BOT_TOKEN unavailable; pending intents not published')
        return 0
    state_path = room / 'posted_pending_intents.json'
    state = load_state(state_path)
    posted = state.setdefault('posted', {})
    count = 0
    for path in sorted((room / 'pending_intents').glob('*.yaml')):
        iid = path.stem
        if iid in posted:
            continue
        text = path.read_text()
        msg = format_message(iid, text)
        markup = reply_markup_for(iid, state)
        res = send(token, chat_id, thread_id, msg, markup)
        posted[iid] = {'message_id': res.get('result', {}).get('message_id'), 'path': str(path), 'callback_token': markup['inline_keyboard'][0][0]['callback_data'].rsplit(':', 1)[-1]}
        count += 1
    save_state(state_path, state)
    print(f'published_pending_intents={count}')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
