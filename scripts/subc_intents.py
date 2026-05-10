#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
from subc_common import load_json, redact
from subc_paths import room_path


def yaml_quote(s):
    return '"' + str(s).replace('\\','\\\\').replace('"','\\"').replace('\n','\\n') + '"'


def write_intent_yaml(path: Path, intent: dict):
    lines=[]
    for k in ['schema_version','id','title','problem','suggested_build','risk','confidence','approval_required','status']:
        v=intent[k]
        if isinstance(v,bool): val='true' if v else 'false'
        elif isinstance(v,(int,float)): val=str(v)
        else: val=yaml_quote(v)
        lines.append(f'{k}: {val}')
    for k in ['source_adapters','non_goals','acceptance_criteria','related_intents']:
        lines.append(f'{k}:')
        for item in intent.get(k,[]): lines.append(f'  - {yaml_quote(item)}')
    lines.append('duplicate_of: null')
    lines.append('evidence:')
    for ev in intent['evidence']:
        lines.append(f'  - evidence_uri: {yaml_quote(ev.get("evidence_uri",""))}')
        lines.append(f'    summary: {yaml_quote(ev.get("summary",""))}')
        if ev.get('source_adapter'): lines.append(f'    source_adapter: {yaml_quote(ev.get("source_adapter"))}')
    path.write_text('\n'.join(lines)+'\n')


def build_intent(sig):
    sid=sig['id']
    if sid == 'openclaw-runtime-inactive':
        title='Investigate inactive OpenClaw/GoClaw runtime signals'
        problem='Read-only discovery observed OpenClaw/GoClaw services that appear inactive. A human should decide whether this is expected topology or a real blocker.'
        suggested='Create a read-only topology audit: expected services, actual active/inactive state, evidence, and recommended next step. Do not restart anything from SUBCONSCIOUS.'
        risk='False positive if an inactive service is expected in this deployment.'
    elif sid == 'mem0g-health-issue':
        title='Investigate mem0g health or service issue'
        problem='Read-only discovery observed a mem0g health or service issue.'
        suggested='Run read-only mem0g diagnostics and propose a recovery task if confirmed.'
        risk='False positive if the health endpoint is intentionally disabled or bound elsewhere.'
    elif sid == 'project-flow-state-surface':
        title='Review project-flow state surfaces for reusable work signals'
        problem='Project-flow STATE.yaml files are present and may contain durable open work, blockers, or reusable workflows.'
        suggested='Summarize active project-flow states and decide whether any should become build or cleanup tasks.'
        risk='False positive if the state files are historical or archived.'
    else:
        title=sig.get('title') or f'Review signal: {sid}'
        problem=f'Signal crossed threshold: {title}'
        suggested='Review the signal and decide whether to create a build task.'
        risk='False positive if evidence is stale or weak.'
    return {
        'schema_version':'1.0',
        'id':'intent_'+sid,
        'title':redact(title),
        'problem':redact(problem),
        'evidence':sig.get('evidence',[]),
        'source_adapters':sorted({e.get('source_adapter','ManualAdapter') for e in sig.get('evidence',[])}),
        'suggested_build':redact(suggested),
        'non_goals':['No production mutation from SUBCONSCIOUS','No service restart','No secrets/grants/auth changes'],
        'acceptance_criteria':['Read-only evidence reviewed','Decision recorded as approved/rejected/cooled','If approved, handoff packet includes tests and rollback'],
        'risk':redact(risk),
        'confidence':min(1.0, round(sig.get('score',0)/10,2)),
        'duplicate_of':None,
        'related_intents':[],
        'approval_required':True,
        'status':'pending_approval'
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--room', default=None)
    ap.add_argument('--max', type=int, default=3)
    ap.add_argument('--force', action='store_true')
    args=ap.parse_args()
    room=Path(args.room) if args.room else room_path()
    data=load_json(room/'signals.json', {'signals':{}})
    out=[]
    d=room/'pending_intents'; d.mkdir(exist_ok=True)
    for sig in sorted(data.get('signals',{}).values(), key=lambda s:s.get('score',0), reverse=True):
        if len(out)>=args.max: break
        if sig.get('status')!='pending_intent' and not args.force: continue
        if len(sig.get('evidence',[])) < 2 and not args.force: continue
        intent=build_intent(sig); path=d/(intent['id']+'.yaml')
        if path.exists(): continue
        write_intent_yaml(path, intent); out.append(str(path))
    print(json.dumps({'created':out}, ensure_ascii=False, indent=2))
if __name__ == '__main__': raise SystemExit(main())
