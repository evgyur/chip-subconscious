#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, urllib.parse, urllib.request
from pathlib import Path
from subc_common import now_iso, load_json, redact, write_json

ROUTES={'board':'signal_board','walk':'walk_logs','intent':'pending_intents','build':'approved_builds','archive':'archive'}
ENV = Path('/home/hermes/.hermes/.env')
BOARD_STATE = 'posted_signal_board.json'


def env_token():
    vals = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            if line and not line.lstrip().startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN')


def load_topics(room: Path) -> tuple[str, dict]:
    data = json.loads((room / 'telegram_topics.json').read_text())
    return data.get('chat_id', os.environ.get('SUBC_TELEGRAM_CHAT_ID', '0')), data['topics']


def route_target(room: Path, route: str) -> dict:
    chat_id, topics = load_topics(room)
    topic = topics[ROUTES[route]]
    thread_id = topic['message_thread_id']
    return {
        'target': f'telegram:{chat_id}:{thread_id}',
        'chat_id': chat_id,
        'thread_id': thread_id,
        'topic_name': topic.get('name', ROUTES[route]),
    }


def _lane(summary: dict, name: str) -> list[dict]:
    return list((summary.get('lanes') or {}).get(name) or [])


def _fmt_items(items: list[dict], limit: int = 5) -> str:
    if not items:
        return '┈ нет'
    rows = []
    for item in items[:limit]:
        score = item.get('score', '—')
        rows.append(f"┈ {item.get('title') or item.get('id')} · score={score} · `{item.get('id')}`")
    if len(items) > limit:
        rows.append(f'┈ ещё {len(items) - limit}')
    return '\n'.join(rows)


def format_signal_board(summary: dict) -> str:
    lanes = summary.get('lanes') or {}
    ready = _lane(summary, 'ready_pending_approval')
    blocked = _lane(summary, 'blocked_ready')
    watching = _lane(summary, 'watching')
    approved = _lane(summary, 'approved')
    cooling = _lane(summary, 'cooling')
    archived = _lane(summary, 'archived')
    updated = summary.get('updated_at') or now_iso()
    if ready or blocked or watching:
        headline = f'зрелые сигналы: ready={len(ready)}, blocked={len(blocked)}, watching={len(watching)}.'
    else:
        headline = 'новых зрелых сигналов сейчас нет; текущие сигналы уже approved / cooling / archived.'
    msg = f"""🧠 SUBCONSCIOUS / Signal Board
{headline}

➊ ready_pending_approval
{_fmt_items(ready)}

➋ watching
{_fmt_items(watching)}

➌ blocked_ready
{_fmt_items(blocked)}

➍ lifecycle
┈ approved={len(approved)} · cooling={len(cooling)} · archived={len(archived)}
┈ updated={updated}

Guardrail: SUBCONSCIOUS не билдит и не апрувит себя — максимум pending_approval."""
    return redact(msg)


def signature_for_board(summary: dict) -> str:
    """Stable signature for meaningful board changes.

    Scores can decay every walk, so the signature intentionally tracks lane membership
    instead of timestamp/score noise. The visible board still includes current scores.
    """
    lanes = summary.get('lanes') or {}
    payload = {}
    for lane in ['ready_pending_approval', 'blocked_ready', 'watching', 'approved', 'cooling', 'archived']:
        payload[lane] = sorted((item.get('id'), item.get('status')) for item in lanes.get(lane, []))
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]


def bot_api(token: str, method: str, data: dict) -> dict:
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/{method}',
        data=urllib.parse.urlencode(data).encode('utf-8'),
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode('utf-8'))


def publish_board(room: Path, message: str, target: dict, *, force: bool = False, dry_run: bool = False) -> dict:
    summary = load_json(room / 'summary.json', {})
    sig = signature_for_board(summary)
    state_path = room / BOARD_STATE
    state = load_json(state_path, {'last_signature': None, 'last_message_id': None})
    if state.get('last_signature') == sig and not force:
        return {'published_signal_board': 0, 'reason': 'unchanged', 'signature': sig, 'message_id': state.get('last_message_id')}
    if dry_run:
        return {'published_signal_board': 0, 'reason': 'dry_run', 'signature': sig, 'message': message, **target}
    token = env_token()
    if not token:
        return {'published_signal_board': 0, 'reason': 'telegram_token_unavailable', 'signature': sig, **target}
    if state.get('last_message_id'):
        res = bot_api(token, 'editMessageText', {
            'chat_id': target['chat_id'],
            'message_id': state['last_message_id'],
            'text': message[:3900],
        })
        message_id = state['last_message_id']
        action = 'edited'
    else:
        res = bot_api(token, 'sendMessage', {
            'chat_id': target['chat_id'],
            'message_thread_id': target['thread_id'],
            'text': message[:3900],
        })
        message_id = res.get('result', {}).get('message_id')
        action = 'sent'
    state.update({'last_signature': sig, 'last_message_id': message_id, 'updated_at': now_iso()})
    write_json(state_path, state)
    return {'published_signal_board': 1, 'action': action, 'signature': sig, 'message_id': message_id, 'ok': bool(res.get('ok'))}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--room', default='/home/hermes/.hermes/profiles/subc/room')
    ap.add_argument('--route', required=True, choices=ROUTES)
    ap.add_argument('--message')
    ap.add_argument('--summary', action='store_true', help='render message from room summary.json; currently intended for --route board')
    ap.add_argument('--send', action='store_true', help='actually send/edit Telegram projection')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args=ap.parse_args()
    room=Path(args.room)
    target=route_target(room, args.route)
    if args.summary:
        if args.route != 'board':
            raise SystemExit('--summary is only supported for --route board')
        summary = load_json(room / 'summary.json', {})
        message = format_signal_board(summary)
    elif args.message:
        message = redact(args.message)
    else:
        raise SystemExit('either --message or --summary is required')

    if args.route == 'board' and args.send:
        result = publish_board(room, message, target, force=args.force, dry_run=args.dry_run)
    else:
        result = {'target': target['target'], 'thread_id': target['thread_id'], 'message': message, 'dry_run': True}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
if __name__ == '__main__': raise SystemExit(main())
