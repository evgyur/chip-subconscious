#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path
from subc_common import now_iso, write_json, redact, require_safe_intent_id, safe_child_path, latest_approval_event

def get_yaml_scalar(text, key):
    m=re.search(rf'^{re.escape(key)}:\s*"?(.*?)"?\s*$', text, re.M)
    return (m.group(1).replace('\\n','\n').replace('\\"','"') if m else '')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--room', default='/home/hermes/.hermes/profiles/subc/room'); ap.add_argument('--intent-id', required=True); ap.add_argument('--force', action='store_true')
    args=ap.parse_args(); room=Path(args.room)
    intent_id = require_safe_intent_id(args.intent_id)
    src=safe_child_path(room/'approved_builds', intent_id+'.yaml')
    if not src.exists(): raise SystemExit(f'approved intent not found: {src}')
    event = latest_approval_event(room, intent_id)
    if not event or event.get('decision') != 'approved':
        raise SystemExit(f'approved event not found for intent: {intent_id}')
    text=src.read_text()
    status=get_yaml_scalar(text,'status')
    if status != 'approved':
        raise SystemExit(f'approved intent artifact has non-approved status: {status or "missing"}')
    yaml_id=get_yaml_scalar(text,'id')
    if yaml_id and yaml_id != intent_id:
        raise SystemExit(f'approved intent id mismatch: {yaml_id} != {intent_id}')
    title=get_yaml_scalar(text,'title') or intent_id
    problem=get_yaml_scalar(text,'problem')
    suggested=get_yaml_scalar(text,'suggested_build')
    packet={
        'schema_version':'1.0',
        'intent_id':intent_id,
        'created_at':now_iso(),
        'executor':'shaw',
        'handoff':'Hermes/Main/Coder builds under Shaw after human approval; SUBCONSCIOUS remains read-only.',
        'approval': event,
        'goal':redact(suggested or title),
        'context':redact(problem),
        'non_goals':[
            'Do not mutate production without separate approval',
            'Do not restart/reload/start/stop services without separate approval',
            'Do not touch secrets/auth/grants unless explicitly scoped',
            'Do not skip Shaw verification gates',
        ],
        'file_targets':['Shaw selects concrete file targets during read-only preflight before editing'],
        'acceptance_criteria':[
            'Shaw preflight recorded: goal, assumptions, simplest path, verification target',
            'Implementation verified with tests/commands',
            'Evidence posted before done',
        ],
        'tests':['Shaw must record concrete verification commands/results in final_report before status=done'],
        'rollback':'Safe stop: no runtime mutation until implementation task defines rollback. Revert file changes or restore prior artifact if needed.',
        'source_evidence':[str(src)],
    }
    out_dir=room/'build_packets'; out_dir.mkdir(exist_ok=True)
    out=safe_child_path(out_dir, intent_id+'.json')
    if out.exists() and not args.force:
        raise SystemExit(f'build packet already exists, refusing overwrite: {out}')
    write_json(out, packet)
    print(json.dumps({'ok':True,'build_packet':str(out)}, ensure_ascii=False, indent=2)); return 0
if __name__ == '__main__': raise SystemExit(main())
