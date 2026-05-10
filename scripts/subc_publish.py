#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from subc_paths import room_path

ROUTES={'board':'signal_board','walk':'walk_logs','intent':'pending_intents','build':'approved_builds','archive':'archive'}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--room', default=None)
    ap.add_argument('--route', required=True, choices=ROUTES)
    ap.add_argument('--message', required=True)
    ap.add_argument('--dry-run', action='store_true')
    args=ap.parse_args()
    room=Path(args.room) if args.room else room_path()
    topic_doc=json.loads((room/'telegram_topics.json').read_text())
    topics=topic_doc['topics']
    topic=topics[ROUTES[args.route]]
    target=f"telegram:{topic_doc['chat_id']}:{topic['message_thread_id']}"
    print(json.dumps({'target':target,'thread_id':topic['message_thread_id'],'message':args.message,'dry_run':args.dry_run}, ensure_ascii=False, indent=2))
    return 0
if __name__ == '__main__': raise SystemExit(main())
