#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from subc_common import redact
from subc_common import verify_shaw_run
from subc_publish_pending import evidence_summaries, scalar

ROOM = Path('/home/hermes/.hermes/profiles/subc/room')


KNOWN_ACTIONS = {
    'intent_mem0g-health-issue': {
        'title': 'Проверить здоровье mem0g',
        'action': 'запустить read-only диагностику mem0g/inbox-adapter, показать причину inactive и дать один безопасный фикс-план',
        'risk': 'если память/инбокс деградируют, агенты продолжат терять события и контекст без явного алерта',
    },
    'intent_openclaw-session-corpus-unreachable': {
        'title': 'Починить доступ SUBCONSCIOUS к OpenClaw session corpus',
        'action': 'починить read-only доступ к корпусу сессий или явно заменить источник; без этого сканер слепнет по OpenClaw ошибкам',
        'risk': 'walks будут считать “sessions indexed/issue_hits” неполно и пропускать повторяющиеся сбои',
    },
}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _yaml_unquote(value: str) -> str:
    value = (value or '').strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    return value.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')


def _first_evidence(text: str) -> str:
    items = evidence_summaries(text, limit=1)
    return items[0] if items else 'есть сигнал в комнате SUBCONSCIOUS, деталей в pending intent'


def _risk(text: str, iid: str) -> str:
    known = KNOWN_ACTIONS.get(iid, {})
    raw = scalar(text, 'risk')
    # Some legacy intent templates used a generic “service may be inactive” risk
    # for unrelated signals. Prefer hand-written action risk for known recurrent
    # production signals so the digest tells Chip why the proposal matters.
    if known and (not raw or 'сервис выглядит неактивным' in raw):
        return known.get('risk') or raw
    return raw or known.get('risk') or 'сигнал будет повторяться, а walk продолжит шуметь без решения'


def _action(text: str, iid: str) -> str:
    known = KNOWN_ACTIONS.get(iid, {})
    return scalar(text, 'suggested_build') or known.get('action') or 'разобрать сигнал, подтвердить пользу и оформить задачу с проверками'


def _title(text: str, iid: str) -> str:
    known = KNOWN_ACTIONS.get(iid, {})
    title = scalar(text, 'title') or known.get('title') or iid
    if not re.search(r'[А-Яа-яЁё]', title):
        title = known.get('title') or f'Разобрать сигнал {iid}'
    return title


def _item_priority(item: dict[str, str]) -> tuple[int, str]:
    iid = item.get('id', '')
    if any(key in iid for key in ['subconscious-useful-walks-v2', 'promise-reality-gate', 'chip-correction-to-guard-eval', 'manual-repeat-automation-opportunity']):
        return (0, iid)
    if any(key in iid for key in ['mem0g-health-issue', 'openclaw-session-corpus-unreachable', 'openclaw-runtime-inactive']):
        return (50, iid)
    return (10, iid)


def pending_items(room: Path) -> list[dict[str, str]]:
    posted = (load_json(room / 'posted_pending_intents.json', {'posted': {}}).get('posted') or {})
    topics = load_json(room / 'telegram_topics.json', {})
    chat_id = str(topics.get('chat_id') or '')
    thread_id = str(((topics.get('topics') or {}).get('pending_intents') or {}).get('message_thread_id') or '')
    items: list[dict[str, str]] = []
    pending_dir = room / 'pending_intents'
    if not pending_dir.exists():
        return items
    for path in sorted(pending_dir.glob('*.yaml')):
        iid = path.stem
        entry = posted.get(iid) or {}
        if entry.get('decision') in {'approved', 'rejected', 'cooled', 'archived'}:
            continue
        text = path.read_text()
        items.append({
            'id': iid,
            'title': _title(text, iid),
            'evidence': _first_evidence(text),
            'action': _action(text, iid),
            'risk': _risk(text, iid),
            'message_id': str(entry.get('message_id') or ''),
            # A callback token in local state is not proof that Telegram still
            # shows an inline keyboard. Older publisher versions stored the
            # token even when the visible message had no buttons, so the digest
            # must only claim buttons when the Bot API send response confirmed
            # reply_markup on publish.
            'has_button': 'yes' if entry.get('reply_markup_sent') is True else 'no',
            'message_link': str(entry.get('message_link') or _message_link(chat_id, thread_id, entry.get('message_id'))),
        })
    return sorted(items, key=_item_priority)


def _message_link(chat_id: str, thread_id: str, message_id: Any) -> str:
    if not chat_id or not str(message_id or '').strip():
        return ''
    chat = chat_id.strip()
    if chat.startswith('-100'):
        internal = chat[4:]
    elif chat.startswith('100'):
        internal = chat[3:]
    else:
        return ''
    if thread_id:
        return f'https://t.me/c/{internal}/{thread_id}/{message_id}'
    return f'https://t.me/c/{internal}/{message_id}'


def _count_lane(summary: dict[str, Any], lane: str) -> int:
    return len((summary.get('lanes') or {}).get(lane) or [])


def stale_approved_builds(room: Path) -> list[str]:
    bad: list[str] = []
    approved = room / 'approved_builds'
    if not approved.exists():
        return bad
    for path in sorted(approved.glob('*.yaml')):
        text = path.read_text(errors='replace')
        status = scalar(text, 'status')
        if status and status != 'approved':
            bad.append(f'{path.stem}:{status}')
    return bad


def shaw_run_status(room: Path) -> tuple[int, int, int, int, list[str]]:
    done_verified = done_unverified = running = blocked = 0
    unverified_reasons: list[str] = []
    runs = room / 'shaw_runs'
    if not runs.exists():
        return (0, 0, 0, 0, [])
    for path in runs.glob('*.json'):
        data = load_json(path, {})
        status = data.get('status')
        intent_id = data.get('intent_id') or path.stem
        if status == 'done':
            ok, reason, _details = verify_shaw_run(room, str(intent_id))
            if ok:
                done_verified += 1
            else:
                done_unverified += 1
                unverified_reasons.append(f'{intent_id}:{reason}')
        elif status in {'queued', 'running'}:
            running += 1
        elif status in {'blocked', 'failed', 'error'}:
            blocked += 1
    return done_verified, done_unverified, running, blocked, unverified_reasons


def latest_walk_source_counts(room: Path) -> dict[str, int]:
    logs = sorted((room / 'walk_logs').glob('walk_*.json')) if (room / 'walk_logs').exists() else []
    if not logs:
        return {}
    data = load_json(logs[-1], {})
    counts: dict[str, int] = {}
    for obs in data.get('observations') or []:
        source = obs.get('source') or 'unknown'
        counts[source] = counts.get(source, 0) + 1
    return counts


def build_digest(room: Path = ROOM, timestamp: str | None = None) -> str:
    timestamp = timestamp or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    summary = load_json(room / 'summary.json', {'lanes': {}})
    items = pending_items(room)
    stale = stale_approved_builds(room)
    done_verified, done_unverified, running, blocked, unverified_reasons = shaw_run_status(room)
    source_counts = latest_walk_source_counts(room)

    lines: list[str] = [f'🚶 subc walk · {timestamp}']
    if items:
        lines.append('')
        lines.append('➊ предлагаю')
        for idx, item in enumerate(items[:3], 1):
            button = 'кнопка в Pending Intents, не в этом walk-log' if item['has_button'] == 'yes' else 'кнопки не подтверждены — надо перепостить'
            if item.get('message_link'):
                msg = f"{item['message_link']}"
            else:
                msg = f"msg {item['message_id']}" if item['message_id'] else 'msg не найден'
            lines.extend([
                f'┈ {idx}. {item["title"]}',
                f'  proposal_id: {item["id"]}',
                f'  evidence: {item["evidence"]}',
                f'  предлагаю: {item["action"]}',
                f'  риск: {item["risk"]}',
                f'  approval: {msg} ({button})',
            ])
    else:
        lines.extend([
            '',
            '➊ новых предложений нет',
            f'┈ watching: {_count_lane(summary, "watching")}',
            f'┈ blocked_ready: {_count_lane(summary, "blocked_ready")}',
        ])

    lines.extend([
        '',
        '➋ где гулял',
    ])
    if source_counts:
        for source, count in sorted(source_counts.items()):
            lines.append(f'┈ {source}: {count}')
    else:
        lines.append('┈ walk log не найден')

    lines.extend([
        '',
        '➌ hygiene',
        f'┈ pending_intents_unresolved: {len(items)}',
        f'┈ approved_builds_stale_status: {len(stale)}' + (f' ({", ".join(stale[:3])})' if stale else ''),
        f'┈ shaw_runs: done_verified={done_verified}, done_unverified={done_unverified}, running_or_queued={running}, blocked_or_failed={blocked}',
    ])

    if done_unverified:
        lines.append(f'┈ unverified_done: {", ".join(unverified_reasons[:3])}')

    if stale:
        lines.extend([
            '',
            '➌ надо почистить',
            '┈ approved_builds со status!=approved больше не считаю нормой; validate должен падать, пока это не исправлено',
        ])

    return redact('\n'.join(lines).strip())


def build_weekly_digest(room: Path = ROOM, days: int = 3, timestamp: str | None = None) -> str:
    """Compact multi-day pattern view; still no LLM rewrite."""
    timestamp = timestamp or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    logs = sorted((room / 'walk_logs').glob('walk_*.json')) if (room / 'walk_logs').exists() else []
    source_counts: dict[str, int] = {}
    proposal_counts: dict[str, int] = {}
    for path in logs[-max(1, days * 8):]:
        data = load_json(path, {})
        for obs in data.get('observations') or []:
            source = obs.get('source') or 'unknown'
            source_counts[source] = source_counts.get(source, 0) + 1
            proposal_id = ((obs.get('metadata') or {}).get('proposal_id'))
            if proposal_id:
                proposal_counts[proposal_id] = proposal_counts.get(proposal_id, 0) + 1
    items = pending_items(room)[:3]
    lines = [f'🧠 subc weekly · {timestamp}', '', f'➊ окно: {days}d']
    if proposal_counts:
        lines.append('┈ повторяющиеся proposals: ' + ', '.join(f'{k}×{v}' for k, v in sorted(proposal_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]))
    else:
        lines.append('┈ повторяющихся proposals нет')
    lines.append('')
    lines.append('➋ top actions')
    if items:
        for idx, item in enumerate(items, 1):
            lines.append(f'┈ {idx}. {item["id"]}: {item["title"]}')
    else:
        lines.append('┈ новых approval actions нет')
    lines.append('')
    lines.append('➌ coverage')
    if source_counts:
        for source, count in sorted(source_counts.items()):
            lines.append(f'┈ {source}: {count}')
    else:
        lines.append('┈ walk logs не найдены')
    return redact('\n'.join(lines).strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--room', default=str(ROOM))
    ap.add_argument('--weekly', action='store_true')
    ap.add_argument('--days', type=int, default=3)
    args = ap.parse_args()
    if args.weekly:
        print(build_weekly_digest(Path(args.room), days=args.days))
    else:
        print(build_digest(Path(args.room)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
