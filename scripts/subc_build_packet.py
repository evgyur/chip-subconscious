#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path
from subc_common import now_iso, write_json, redact

def get_yaml_scalar(text, key):
    m=re.search(rf'^{re.escape(key)}:\s*"?(.*?)"?\s*$', text, re.M)
    return (m.group(1).replace('\\n','\n').replace('\\"','"') if m else '')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--room', default=None); ap.add_argument('--intent-id', required=True)
    args=ap.parse_args();
    from subc_paths import room_path
    from subc_paths import room_path
    room=Path(args.room) if args.room else room_path() if args.room else room_path()
    src=room/'approved_builds'/(args.intent_id+'.yaml')
    if not src.exists(): raise SystemExit(f'approved intent not found: {src}')
    text=src.read_text()
    title=get_yaml_scalar(text,'title') or args.intent_id
    problem=get_yaml_scalar(text,'problem')
    suggested=get_yaml_scalar(text,'suggested_build')
    packet={'schema_version':'1.0','intent_id':args.intent_id,'created_at':now_iso(),'goal':redact(suggested or title),'context':redact(problem),'non_goals':['Do not mutate production without separate approval','Do not touch secrets/auth/grants unless explicitly scoped','Do not skip verification'],'file_targets':['TBD by Main/Coder after codebase inspection'],'acceptance_criteria':['Plan reviewed','Implementation verified with tests/commands','Evidence posted before done'],'tests':['TBD: implementation-specific verification command required before build starts'],'rollback':'Safe stop: no runtime mutation until implementation task defines rollback. Revert file changes or restore prior artifact if needed.','source_evidence':[str(src)]}
    out_dir=room/'build_packets'; out_dir.mkdir(exist_ok=True)
    out=out_dir/(args.intent_id+'.json')
    write_json(out, packet)
    print(json.dumps({'ok':True,'build_packet':str(out)}, ensure_ascii=False, indent=2)); return 0
if __name__ == '__main__': raise SystemExit(main())
