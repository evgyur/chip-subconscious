#!/usr/bin/env python3
from __future__ import annotations
import argparse, glob, json, re
from pathlib import Path
from subc_common import now_iso, write_json, load_json, redact

def slug(s):
    return re.sub(r'[^a-z0-9]+','-',s.lower()).strip('-')[:80] or 'signal'

def latest_walk(room: Path):
    files=sorted((room/'walk_logs').glob('walk_*.json'))
    if not files: raise SystemExit('no walk logs found')
    return files[-1]

def signal_from_obs(obs):
    summary=obs.get('summary','')
    ev={'evidence_uri':obs.get('evidence_uri',''), 'summary':summary, 'source_adapter':obs.get('source_adapter')}
    low=summary.lower()
    if 'inactive' in low or 'no response' in low or 'failed' in low:
        if obs.get('source') == 'openclaw':
            return 'openclaw-runtime-inactive', 'OpenClaw/GoClaw runtime inactive signals', ['blocker','friction'], 2.5, ev
        if obs.get('source') == 'mem0g':
            return 'mem0g-health-issue', 'mem0g health/service issue', ['blocker','friction'], 4.0, ev
    if obs.get('source') == 'mem0g' and 'health check' in low:
        return 'mem0g-health-baseline', 'mem0g health baseline observed', ['mention'], 1.0, ev
    if obs.get('source') == 'project-flow':
        return 'project-flow-state-surface', 'Project-flow states available for discovery', ['reuse','mention'], 1.0, ev
    if obs.get('source') == 'hermes' and 'skills directory' in low:
        return 'hermes-skills-surface', 'Hermes skills surface available for discovery', ['reuse'], 1.0, ev
    return None

def status_for(score):
    if score >= 6: return 'pending_intent'
    if score >= 4: return 'watching'
    return 'note'

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--room', default=None)
    ap.add_argument('--walk-json')
    ap.add_argument('--decay', type=float, default=0.9)
    args=ap.parse_args()
    from subc_paths import room_path
    room=Path(args.room) if args.room else room_path()
    walk_path=Path(args.walk_json) if args.walk_json else latest_walk(room)
    walk=json.loads(walk_path.read_text())
    existing=load_json(room/'signals.json', {'schema_version':'1.0','signals':{}})
    signals=existing.setdefault('signals', {})
    touched=[]
    # Decay existing first
    for sid,sig in signals.items():
        sig['score']=round(float(sig.get('score',0))*args.decay, 2)
        sig['status']=status_for(sig['score']) if sig.get('status') not in ('approved','rejected','archived','cooling') else sig.get('status')
    for obs in walk.get('observations',[]):
        item=signal_from_obs(obs)
        if not item: continue
        sid,title,types,delta,ev=item
        sig=signals.get(sid) or {'schema_version':'1.0','id':sid,'title':title,'signal_types':types,'score':0,'evidence':[], 'status':'note', 'created_at':now_iso(), 'duplicate_of':None, 'cooldown_until':None}
        if sig.get('status') in ('approved','rejected','archived','cooling'):
            # Terminal/cooldown decisions win over fresh observations until a human changes state.
            signals[sid] = sig
            continue
        seen={e.get('evidence_uri') for e in sig.get('evidence',[])}
        if ev['evidence_uri'] not in seen:
            sig.setdefault('evidence',[]).append(ev)
        sig['score']=min(10, round(float(sig.get('score',0))+delta, 2))
        sig['updated_at']=now_iso()
        sig['status']=status_for(sig['score'])
        sig['signal_types']=sorted(set(sig.get('signal_types',[])+types))
        signals[sid]=sig; touched.append(sid)
    write_json(room/'signals.json', existing)
    # Update summary lanes
    summary=load_json(room/'summary.json', {'schema_version':'1.0','status':'initialized','lanes':{},'guardrails':{}})
    lanes=summary.setdefault('lanes', {})
    for lane in ['ready_pending_approval','watching','cooling','approved','archived']:
        lanes[lane]=[]
    for sig in signals.values():
        ref={'id':sig['id'],'title':sig['title'],'score':sig['score'],'status':sig['status']}
        if sig['status']=='pending_intent': lanes['ready_pending_approval'].append(ref)
        elif sig['status']=='watching': lanes['watching'].append(ref)
        elif sig['status']=='cooling': lanes['cooling'].append(ref)
        elif sig['status']=='approved': lanes['approved'].append(ref)
        elif sig['status'] in ('archived','rejected'): lanes['archived'].append(ref)
    summary['updated_at']=now_iso()
    write_json(room/'summary.json', summary)
    print(json.dumps({'walk':str(walk_path),'touched':touched,'ready':lanes['ready_pending_approval'],'watching':lanes['watching']}, ensure_ascii=False, indent=2))
if __name__ == '__main__': raise SystemExit(main())
