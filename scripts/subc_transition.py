#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from subc_common import now_iso, write_json, load_json, redact, require_safe_intent_id, safe_child_path, patch_yaml_scalar

ALLOWED_APPROVERS = {'Chip','Evgeny "Chip"','hermes-main','Main'}
DECISIONS = {'approved':'approved_builds','rejected':'archive','cooled':'archive','archived':'archive'}

def require_allowed(approver, decision):
    if approver.lower() in {'subconscious','subc','bot'}:
        raise PermissionError('SUBCONSCIOUS cannot approve/reject/archive its own intents')
    if approver not in ALLOWED_APPROVERS:
        raise PermissionError(f'approver not allowed to decide SUBCONSCIOUS intents: {approver}')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--room', default='/home/hermes/.hermes/profiles/subc/room')
    ap.add_argument('--intent-id', required=True)
    ap.add_argument('--decision', required=True, choices=DECISIONS)
    ap.add_argument('--approver', required=True)
    ap.add_argument('--source-message-id')
    ap.add_argument('--note', default='')
    ap.add_argument('--dry-run', action='store_true')
    args=ap.parse_args(); room=Path(args.room)
    require_allowed(args.approver, args.decision)
    intent_id = require_safe_intent_id(args.intent_id)
    src=safe_child_path(room/'pending_intents', intent_id+'.yaml')
    if not src.exists(): raise SystemExit(f'intent not found: {src}')
    event={'schema_version':'1.0','intent_id':intent_id,'decision':args.decision,'approver':args.approver,'timestamp':now_iso(),'source_message_id':args.source_message_id,'note':redact(args.note)}
    dest_dir=room/DECISIONS[args.decision]; dest_dir.mkdir(exist_ok=True)
    dest=safe_child_path(dest_dir, intent_id+'.yaml')
    if dest.exists():
        raise SystemExit(f'destination already exists, refusing overwrite: {dest}')
    if args.dry_run:
        print(json.dumps({'event':event,'copy_to':str(dest)}, ensure_ascii=False, indent=2)); return 0
    text = src.read_text()
    terminal_status = 'approved' if args.decision == 'approved' else ('cooling' if args.decision == 'cooled' else 'archived')
    text = patch_yaml_scalar(text, 'status', terminal_status)
    text = patch_yaml_scalar(text, 'decided_by', args.approver)
    text = patch_yaml_scalar(text, 'decided_at', event['timestamp'])
    if args.source_message_id:
        text = patch_yaml_scalar(text, 'source_message_id', str(args.source_message_id))
    src.write_text(text)
    shutil.move(str(src), str(dest))
    posted_path = room / 'posted_pending_intents.json'
    posted_state = load_json(posted_path, {'posted': {}, 'tokens': {}})
    posted_entry = posted_state.setdefault('posted', {}).setdefault(intent_id, {})
    posted_entry['decision'] = args.decision
    posted_entry['decided_by'] = args.approver
    posted_entry['decided_at'] = event['timestamp']
    posted_entry['path'] = str(dest)
    if args.source_message_id:
        posted_entry['source_message_id'] = str(args.source_message_id)
    write_json(posted_path, posted_state)
    # Reflect terminal/cooling decisions back into signals.json when intent id follows intent_<signal_id>.
    signal_id = intent_id.removeprefix('intent_')
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
