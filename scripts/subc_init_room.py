#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from subc_common import now_iso, write_json
from subc_paths import room_path

LANES = ['ready_pending_approval','watching','cooling','approved','archived']
TOPICS = ['signal_board','walk_logs','pending_intents','approved_builds','archive']

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--room', default=None)
    ap.add_argument('--chat-id', default='REPLACE_WITH_TELEGRAM_CHAT_ID')
    ap.add_argument('--topic-ids', default='1,2,3,4,5', help='signal_board,walk_logs,pending_intents,approved_builds,archive')
    args = ap.parse_args()
    room = Path(args.room) if args.room else room_path()
    for rel in ['pending_intents','walk_logs','approved_builds','archive','build_packets']:
        (room/rel).mkdir(parents=True, exist_ok=True)
    if not (room/'signal-board.md').exists():
        (room/'signal-board.md').write_text('# SUBCONSCIOUS Signal Board\n')
    topic_ids = [x.strip() for x in args.topic_ids.split(',')]
    if len(topic_ids) != 5:
        raise SystemExit('--topic-ids must contain 5 comma-separated ids')
    write_json(room/'telegram_topics.json', {'schema_version':'1.0','chat_id':args.chat_id,'topics':{k:{'message_thread_id': int(v) if v.isdigit() else v} for k,v in zip(TOPICS, topic_ids)}})
    write_json(room/'summary.json', {'schema_version':'1.0','status':'initialized','lanes':{lane:[] for lane in LANES},'guardrails':{'subconscious_max_state':'pending_approval','approval_required_for_build':True,'allowed_to_build':False},'updated_at':now_iso()})
    write_json(room/'signals.json', {'schema_version':'1.0','signals':{}})
    write_json(room/'posted_pending_intents.json', {'posted':{},'tokens':{}})
    (room/'approval_events.jsonl').touch()
    print(f'OK: initialized room {room}')

if __name__ == '__main__':
    raise SystemExit(main())
