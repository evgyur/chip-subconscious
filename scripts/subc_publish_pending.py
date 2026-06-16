#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, re, secrets, shutil, urllib.parse, urllib.request
from pathlib import Path
from subc_common import redact, latest_approval_event

ROOM = Path('/home/hermes/.hermes/profiles/subc/room')
ENV = Path('/home/hermes/.hermes/.env')
STATE = ROOM / 'posted_pending_intents.json'
RESOLVED_DECISION_DIRS = {
    'approved': 'approved_builds',
    'rejected': 'archive',
    'cooled': 'archive',
    'archived': 'archive',
}


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


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {'posted': {}, 'tokens': {}}


def save_state(s):
    tmp = STATE.with_suffix(STATE.suffix + '.tmp')
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(STATE)


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for idx in range(1, 1000):
        candidate = path.with_name(f'{path.stem}.{idx}{path.suffix}')
        if not candidate.exists():
            return candidate
    raise RuntimeError(f'could not allocate unique path under {path.parent}')


def reconcile_resolved_pending_files(room: Path, state: dict) -> list[dict]:
    """Move already-decided intent YAMLs out of pending_intents.

    Telegram callbacks normally transition the file immediately, but the
    publisher is the last safe checkpoint before the walk digest. If a stale
    resolved file is left behind, do not let it masquerade as a pending intent.
    """
    pending_dir = room / 'pending_intents'
    posted = state.setdefault('posted', {})
    if not pending_dir.exists():
        return []

    moved: list[dict] = []
    for path in sorted(pending_dir.glob('*.yaml')):
        iid = path.stem
        entry = posted.get(iid) or {}
        decision = entry.get('decision')
        dest_rel = RESOLVED_DECISION_DIRS.get(decision)
        if not dest_rel:
            continue

        canonical_dir = room / dest_rel
        canonical_dir.mkdir(parents=True, exist_ok=True)
        canonical = canonical_dir / path.name
        if decision == 'approved' and not latest_approval_event(room, iid):
            quarantine_dir = room / 'archive' / 'resolved_pending_intents'
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            dest = _unique_path(quarantine_dir / f'{path.stem}.unverified_approved{path.suffix}')
            mode = 'quarantine_unverified_decision'
            entry['path'] = str(dest)
        elif canonical.exists():
            quarantine_dir = room / 'archive' / 'resolved_pending_intents'
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            dest = _unique_path(quarantine_dir / f'{path.stem}.{decision}{path.suffix}')
            mode = 'quarantine_duplicate'
            entry['path'] = str(canonical)
        else:
            dest = canonical
            mode = 'canonical_transition'
            entry['path'] = str(dest)

        shutil.move(str(path), str(dest))
        entry.setdefault('resolved_pending_files', []).append(str(dest))
        moved.append({'intent_id': iid, 'decision': decision, 'from': str(path), 'to': str(dest), 'mode': mode})
    return moved


def should_publish_pending(iid: str, posted: dict) -> bool:
    entry = posted.get(iid)
    if not entry:
        return True
    if entry.get('decision') in RESOLVED_DECISION_DIRS:
        return False
    # A stored token/message without confirmed reply_markup is not a usable
    # approval card. Repost so Chip gets visible ✅/❌ buttons.
    return not (entry.get('message_id') and entry.get('reply_markup_sent') is True)


def token_for_intent(iid: str, state: dict) -> str:
    tokens = state.setdefault('tokens', {})
    for token, mapped in tokens.items():
        if mapped == iid:
            return token
    for _ in range(10):
        token = secrets.token_hex(12)
        if token not in tokens or tokens[token] == iid:
            tokens[token] = iid
            return token
    raise RuntimeError(f'could not allocate unique callback token for {iid}')


def reply_markup_for(iid: str, state: dict) -> dict:
    token = token_for_intent(iid, state)
    return {
        'inline_keyboard': [[
            {'text': '✅ Да', 'callback_data': f'subc:y:{token}'},
            {'text': '❌ Нет', 'callback_data': f'subc:n:{token}'},
        ]]
    }


def _bullets(items: list[str], fallback: str = '—') -> str:
    if not items:
        return fallback
    return '\n'.join(f'• {item}' for item in items)


_STANDARD_RU = {
    'No production mutation from SUBCONSCIOUS': 'Не меняем прод из слоя наблюдения',
    'No service restart': 'Не перезапускаем сервисы',
    'No secrets/grants/auth changes': 'Не трогаем секреты, доступы и ключи',
    'Read-only evidence reviewed': 'Проверены только безопасные факты, без изменений системы',
    'Decision recorded as approved/rejected/cooled': 'Решение записано: да / нет / отложить',
    'If approved, handoff packet includes tests and rollback': 'Если одобрено — есть пакет задачи с проверками и откатом',
}

_INTENT_RU = {
    'intent_hermes-cross-session-recall-gap': {
        'title': 'Автоматически вспоминать важный контекст перед ответом в Telegram',
        'problem': 'Hermes в Telegram часто начинает новую сессию без прошлых договорённостей. Из-за этого приходится вручную искать старый контекст — это ровно та боль, которая постоянно бесит Чипа.',
        'suggested': 'Сделать безопасную предварительную проверку перед ответом: найти недавние релевантные сессии, коротко собрать открытые обещания и подложить этот контекст основному Hermes, не выдавая слой наблюдения за основного агента.',
        'evidence': [
            'В нескольких прошлых сессиях повторялась одна и та же проблема: Hermes теряет контекст между Telegram-сессиями.',
            'Текущий надёжный способ — вручную вызывать поиск по сессиям; автоматического вспоминания перед ответом пока нет.',
        ],
    },
    'intent_secret-hygiene-transcript-surface': {
        'title': 'Проверить, не светятся ли секреты в памяти и логах',
        'problem': 'В долговременной памяти и пересказах сессий могут встречаться значения, похожие на ключи или токены. Риск — случайно снова показать их в чате или логах.',
        'suggested': 'Сделать безопасный отчёт без раскрытия значений: где есть похожие на секреты места, что убрать из памяти и что при необходимости ротировать. Ничего не удалять и не ротировать без отдельного одобрения.',
        'evidence': [
            'Слой наблюдения уже видел риск секретов в transcript/memory-поверхностях.',
            'Значения нужно держать скрытыми: показывать только redacted-отчёт и план действий.',
        ],
    },
}


def _has_cyrillic(text: str) -> bool:
    return bool(re.search(r'[А-Яа-яЁё]', text or ''))


def _localize_item(item: str) -> str:
    return _STANDARD_RU.get(item, item)


def _localize_list(items: list[str]) -> list[str]:
    return [_localize_item(item) for item in items]


def format_message(iid: str, text: str, source: Path | str | None = None) -> str:
    """Backward-compatible public API name for formatting pending intent cards."""
    return format_plain_ru_message(iid, text, source)


def format_plain_ru_message(iid: str, text: str, source: Path | str | None = None) -> str:
    title = scalar(text, 'title') or iid
    problem = scalar(text, 'problem')
    suggested = scalar(text, 'suggested_build')
    confidence = scalar(text, 'confidence')
    evidence = evidence_summaries(text, limit=2)
    non_goals = list_items(text, 'non_goals', limit=3)
    acceptance = list_items(text, 'acceptance_criteria', limit=3)

    ru = _INTENT_RU.get(iid, {})
    title = ru.get('title') or (title if _has_cyrillic(title) else f'Проверить сигнал: {iid}')
    problem = ru.get('problem') or (problem if _has_cyrillic(problem) else 'Система заметила повторяющийся сигнал. Нужно решить, превращать ли его в задачу.')
    suggested = ru.get('suggested') or (suggested if _has_cyrillic(suggested) else 'Разобрать сигнал, подтвердить пользу и при одобрении оформить отдельную задачу с проверками.')
    evidence = ru.get('evidence') or [item for item in evidence if _has_cyrillic(item)]
    non_goals = _localize_list(non_goals)
    acceptance = _localize_list(acceptance)

    msg = f"""💡 Идея на решение

{title}

В чём дело:
{problem or 'Сигнал набрал порог, надо решить: делать задачу или нет.'}

Почему это всплыло:
{_bullets(evidence, '• Есть повторяющийся/сильный сигнал в комнате SUBCONSCIOUS.')}

Что предлагаю сделать:
{suggested or 'Посмотреть сигнал и решить, превращать ли его в задачу.'}

Чего не делаем:
{_bullets(non_goals)}

Готово, если:
{_bullets(acceptance)}

Уверенность: {confidence or '—'}
id: {iid}

Нажми ✅ Да — передать в одобренные задачи, или ❌ Нет — убрать в архив."""
    return redact(msg)


def send(token, chat_id, thread_id, text, reply_markup=None):
    base = f'https://api.telegram.org/bot{token}/sendMessage'
    data = {'chat_id': chat_id, 'message_thread_id': thread_id, 'text': text[:3900]}
    if reply_markup is not None:
        data['reply_markup'] = json.dumps(reply_markup, ensure_ascii=False)
    req = urllib.request.Request(
        base,
        data=urllib.parse.urlencode(data).encode(),
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def message_link(chat_id, thread_id, message_id):
    if not message_id:
        return ''
    chat = str(chat_id)
    if chat.startswith('-100'):
        internal = chat[4:]
    elif chat.startswith('100'):
        internal = chat[3:]
    else:
        return ''
    if thread_id:
        return f'https://t.me/c/{internal}/{thread_id}/{message_id}'
    return f'https://t.me/c/{internal}/{message_id}'


def main():
    global ROOM, STATE
    ap = argparse.ArgumentParser()
    ap.add_argument('--room', default=str(ROOM))
    args = ap.parse_args()
    ROOM = Path(args.room)
    STATE = ROOM / 'posted_pending_intents.json'
    topics = json.loads((ROOM / 'telegram_topics.json').read_text())
    chat_id = topics['chat_id']
    thread_id = topics['topics']['pending_intents']['message_thread_id']
    state = load_state()
    posted = state.setdefault('posted', {})
    reconciled = reconcile_resolved_pending_files(ROOM, state)
    token = env_token()
    if not token:
        if reconciled:
            save_state(state)
        print('ERROR: TELEGRAM_BOT_TOKEN unavailable; pending intents not published')
        print(f'reconciled_resolved_pending={len(reconciled)}')
        return 1 if list((ROOM / 'pending_intents').glob('*.yaml')) else 0
    count = 0
    for path in sorted((ROOM / 'pending_intents').glob('*.yaml')):
        iid = path.stem
        if not should_publish_pending(iid, posted):
            continue
        text = path.read_text()
        msg = format_plain_ru_message(iid, text)
        markup = reply_markup_for(iid, state)
        res = send(token, chat_id, thread_id, msg, markup)
        result = res.get('result') or {}
        message_id = result.get('message_id')
        posted[iid] = {
            'message_id': message_id,
            'path': str(path),
            'callback_token': markup['inline_keyboard'][0][0]['callback_data'].rsplit(':', 1)[-1],
            'chat_id': chat_id,
            'thread_id': thread_id,
            'message_link': message_link(chat_id, thread_id, message_id),
            'reply_markup_sent': bool(result.get('reply_markup')),
        }
        save_state(state)
        count += 1
    save_state(state)
    print(f'published_pending_intents={count} reconciled_resolved_pending={len(reconciled)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
