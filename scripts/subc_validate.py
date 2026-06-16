#!/usr/bin/env python3
"""Validate SUBCONSCIOUS room skeleton without external dependencies.
Checks canonical files, schema_version presence, lane shape, topic IDs, and pending intent basics.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from subc_common import verify_shaw_run

REQUIRED_TOPICS = {
    'signal_board': 1550,
    'walk_logs': 1551,
    'pending_intents': 1552,
    'approved_builds': 1553,
    'archive': 1554,
}
SUMMARY_LANES = ['ready_pending_approval','blocked_ready','watching','cooling','approved','archived']
RESOLVED_DECISIONS = {'approved','rejected','cooled','archived'}

class ValidationError(Exception): pass

def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception as e:
        raise ValidationError(f'{path}: invalid JSON: {e}')

def require(cond, msg):
    if not cond:
        raise ValidationError(msg)

def validate_summary(room: Path):
    p = room / 'summary.json'
    require(p.exists(), f'missing {p}')
    data = load_json(p)
    require(data.get('schema_version') == '1.0', 'summary.json schema_version must be 1.0')
    require('lanes' in data and isinstance(data['lanes'], dict), 'summary.json lanes object required')
    for lane in SUMMARY_LANES:
        require(lane in data['lanes'], f'summary.json missing lane {lane}')
        require(isinstance(data['lanes'][lane], list), f'summary.json lane {lane} must be list')
    g = data.get('guardrails') or {}
    require(g.get('subconscious_max_state') == 'pending_approval', 'guardrail max state must be pending_approval')
    require(g.get('approval_required_for_build') is True, 'approval_required_for_build must be true')
    require(g.get('allowed_to_build') is False, 'allowed_to_build must be false')
    return data

def validate_topics(room: Path):
    p = room / 'telegram_topics.json'
    require(p.exists(), f'missing {p}')
    data = load_json(p)
    topics = data.get('topics') or {}
    for key, tid in REQUIRED_TOPICS.items():
        require(key in topics, f'telegram_topics missing {key}')
        try:
            actual = int(topics[key].get('message_thread_id'))
        except Exception as exc:
            raise ValidationError(f'{key} thread id invalid: {topics[key].get("message_thread_id")!r}') from exc
        require(actual == tid, f'{key} thread id expected {tid}, got {topics[key].get("message_thread_id")}')
    return data

def _yaml_scalar(text: str, key: str) -> str:
    import re
    m = re.search(rf'^{re.escape(key)}:\s*(.*?)\s*$', text, re.M)
    if not m:
        return ''
    value = m.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    return value


def validate_pending_intents(room: Path):
    d = room / 'pending_intents'
    require(d.exists() and d.is_dir(), f'missing dir {d}')
    # YAML parser intentionally avoided; for SUBC-001 only enforce no obviously invalid extension.
    bad = [p.name for p in d.iterdir() if p.is_file() and p.suffix not in ('.yaml','.yml','.json')]
    require(not bad, f'pending_intents contains unsupported files: {bad}')
    posted_path = room / 'posted_pending_intents.json'
    if posted_path.exists():
        posted = load_json(posted_path).get('posted') or {}
        stale = []
        for path in d.glob('*.yaml'):
            decision = (posted.get(path.stem) or {}).get('decision')
            if decision in RESOLVED_DECISIONS:
                stale.append(f'{path.name}:{decision}')
        require(not stale, f'pending_intents contains already-resolved files: {stale}')


def validate_approved_builds(room: Path):
    d = room / 'approved_builds'
    require(d.exists() and d.is_dir(), f'missing dir {d}')
    bad_status = []
    for path in d.glob('*.yaml'):
        status = _yaml_scalar(path.read_text(errors='replace'), 'status')
        if status and status != 'approved':
            bad_status.append(f'{path.name}:{status}')
    require(not bad_status, f'approved_builds contains non-approved artifacts: {bad_status}')


def validate_shaw_runs(room: Path):
    d = room / 'shaw_runs'
    require(d.exists() and d.is_dir(), f'missing dir {d}')
    bad_done = []
    malformed = []
    for path in d.glob('*.json'):
        try:
            data = load_json(path)
        except ValidationError as exc:
            malformed.append(f'{path.name}:{exc}')
            continue
        status = data.get('status')
        intent_id = data.get('intent_id') or path.stem
        if path.stem != intent_id:
            malformed.append(f'{path.name}:intent_id mismatch {intent_id}')
            continue
        if status == 'done':
            ok, reason, _details = verify_shaw_run(room, intent_id)
            if not ok:
                bad_done.append(f'{intent_id}:{reason}')
    require(not malformed, f'shaw_runs malformed: {malformed[:5]}')
    require(not bad_done, f'shaw_runs done without verification: {bad_done[:5]}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--room', required=True)
    args = ap.parse_args()
    room = Path(args.room)
    try:
        require(room.exists(), f'room not found: {room}')
        for rel in ['signal-board.md','pending_intents','walk_logs','approved_builds','archive']:
            require((room/rel).exists(), f'missing {room/rel}')
        validate_summary(room)
        validate_topics(room)
        validate_pending_intents(room)
        validate_approved_builds(room)
        validate_shaw_runs(room)
    except ValidationError as e:
        print(f'FAIL: {e}', file=sys.stderr)
        return 1
    print(f'OK: SUBCONSCIOUS room valid: {room}')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
