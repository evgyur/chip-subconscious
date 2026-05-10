#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from subc_common import now_iso, write_json, load_json, redact

ALLOWED_APPROVERS = {'Chip','Evgeny "Chip"','hermes-main','Main'}
DECISIONS = {'approved':'approved_builds','rejected':'archive','cooled':'archive','archived':'archive'}

def require_allowed(approver, decision):
    if approver.lower() in {'subconscious','subc','bot'}:
        raise PermissionError('SUBCONSCIOUS cannot approve/reject/archive its own intents')
    if decision == 'approved' and approver not in ALLOWED_APPROVERS:
        raise PermissionError(f'approver not allowed to approve: {approver}')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--room', default=None)
    ap.add_argument('--intent-id', required=True)
    ap.add_argument('--decision', required=True, choices=DECISIONS)
    ap.add_argument('--approver', required=True)
    ap.add_argument('--source-message-id')
    ap.add_argument('--note', default='')
    ap.add_argument('--dry-run', action='store_true')
    args=ap.parse_args();
    from subc_paths import room_path
    from subc_paths import room_path
    room=Path(args.room) if args.room else room_path() if args.room else room_path()
    require_allowed(args.approver, args.decision)
    src=room/'pending_intents'/(args.intent_id+'.yaml')
    if not src.exists(): raise SystemExit(f'intent not found: {src}')
    event={'schema_version':'1.0','intent_id':args.intent_id,'decision':args.decision,'approver':args.approver,'timestamp':now_iso(),'source_message_id':args.source_message_id,'note':redact(args.note)}
    dest_dir=room/DECISIONS[args.decision]; dest_dir.mkdir(exist_ok=True)
    dest=dest_dir/(args.intent_id+'.yaml')
    if args.dry_run:
        print(json.dumps({'event':event,'copy_to':str(dest)}, ensure_ascii=False, indent=2)); return 0
    shutil.move(str(src), str(dest))
    # Reflect terminal/cooling decisions back into signals.json when intent id follows intent_<signal_id>.
    signal_id = args.intent_id.removeprefix('intent_')
    signals_path = room / 'signals.json'
    signals_data = load_json(signals_path, {'schema_version':'1.0','signals':{}})
    sig = signals_data.get('signals', {}).get(signal_id)
    if sig:
        if args.decision == 'approved':
            sig['status'] = 'approved'
        elif args.decision == 'cooled':
            sig['status'] = 'cooling'
            sig['cooldown_until'] = (datetime.now(timezone.utc) + timedelta(days=7)).replace(microsecond=0).isoformat().replace('+00:00','Z')
        elif args.decision in ('rejected','archived'):
            sig['status'] = 'archived'
            sig['cooldown_until'] = (datetime.now(timezone.utc) + timedelta(days=14)).replace(microsecond=0).isoformat().replace('+00:00','Z')
        sig['updated_at'] = now_iso()
        write_json(signals_path, signals_data)
    with (room/'approval_events.jsonl').open('a') as f: f.write(json.dumps(event, ensure_ascii=False)+'\n')
    print(json.dumps({'ok':True,'event':event,'artifact':str(dest)}, ensure_ascii=False, indent=2)); return 0
if __name__ == '__main__': raise SystemExit(main())
