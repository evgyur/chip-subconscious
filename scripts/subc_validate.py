#!/usr/bin/env python3
"""Validate a SUBCONSCIOUS room skeleton without external dependencies."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from subc_paths import room_path

REQUIRED_TOPIC_KEYS = ['signal_board','walk_logs','pending_intents','approved_builds','archive']
SUMMARY_LANES = ['ready_pending_approval','watching','cooling','approved','archived']

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
    require(data.get('chat_id'), 'telegram_topics.json must include chat_id')
    topics = data.get('topics') or {}
    for key in REQUIRED_TOPIC_KEYS:
        require(key in topics, f'telegram_topics missing {key}')
        tid = topics[key].get('message_thread_id')
        require(tid is not None, f'{key} missing message_thread_id')
        require(str(tid).isdigit() or (isinstance(tid, int) and tid > 0), f'{key} invalid message_thread_id: {tid}')
    return data

def validate_pending_intents(room: Path):
    d = room / 'pending_intents'
    require(d.exists() and d.is_dir(), f'missing dir {d}')
    bad = [p.name for p in d.iterdir() if p.is_file() and p.suffix not in ('.yaml','.yml','.json')]
    require(not bad, f'pending_intents contains unsupported files: {bad}')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--room', default=None)
    args = ap.parse_args()
    room = Path(args.room) if args.room else room_path()
    try:
        require(room.exists(), f'room not found: {room}')
        for rel in ['signal-board.md','pending_intents','walk_logs','approved_builds','archive','build_packets']:
            require((room/rel).exists(), f'missing {room/rel}')
        validate_summary(room)
        validate_topics(room)
        validate_pending_intents(room)
    except ValidationError as e:
        print(f'FAIL: {e}', file=sys.stderr)
        return 1
    print(f'OK: SUBCONSCIOUS room valid: {room}')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
