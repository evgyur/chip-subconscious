#!/usr/bin/env python3
from __future__ import annotations
import argparse, glob, json, hashlib, re
from pathlib import Path
from subc_common import now_iso, write_json, load_json, redact, intent_eligibility, verify_shaw_run

CLOSED_SIGNAL_STATUSES = {'approved', 'rejected', 'archived'}
REOPENABLE_PATTERN_TYPES = {
    'style_guard',
    'manual_repeat',
    'correction_mining',
    'openclaw_semantic_cluster',
    'promise_gap',
    'promise_reality_gap',
}

def slug(s):
    return re.sub(r'[^a-z0-9]+','-',s.lower()).strip('-')[:80] or 'signal'

def latest_walk(room: Path):
    files=sorted((room/'walk_logs').glob('walk_*.json'))
    if not files: raise SystemExit('no walk logs found')
    return files[-1]

def opportunity_score(sig: dict) -> float:
    """Rank by Chip value first, infra severity second."""
    score = float(sig.get('score') or 0)
    evidence = sig.get('evidence') or []
    chip_value = any((e or {}).get('chip_value_signal') for e in evidence)
    types = set(sig.get('signal_types') or [])
    value = score
    if chip_value:
        value += 10
    if 'repeat' in types:
        value += 2
    if 'reuse' in types:
        value += 1
    if 'blocker' in types and not chip_value:
        value += 1
    return round(value, 2)


def signal_from_obs(obs):
    summary=obs.get('summary','')
    ev={'evidence_uri':obs.get('evidence_uri',''), 'summary':summary, 'source_adapter':obs.get('source_adapter')}
    low=summary.lower()
    if 'inactive' in low or 'no response' in low or 'failed' in low:
        if obs.get('source') == 'openclaw':
            return 'openclaw-runtime-inactive', 'OpenClaw/GoClaw runtime inactive signals', ['blocker','friction'], 2.5, ev
        if obs.get('source') == 'mem0g':
            return 'mem0g-health-issue', 'mem0g health/service issue', ['blocker','friction'], 4.0, ev
    if obs.get('source') == 'openclaw-sessions':
        meta=obs.get('metadata') or {}
        if meta.get('target_status') == 'unreachable':
            return 'openclaw-session-corpus-unreachable', 'OpenClaw session corpus unreachable from SUBCONSCIOUS', ['blocker','friction'], 4.0, ev
        if meta.get('agent') and int(meta.get('issue_count') or 0) > 0:
            return 'openclaw-session-error-pattern', 'OpenClaw session error/friction patterns observed', ['friction','repeat'], 3.0, ev
        if 'session corpus reachable' in low:
            return 'openclaw-session-corpus-baseline', 'OpenClaw session corpus baseline observed', ['reuse','mention'], 1.0, ev
    if obs.get('source') in {'hermes-sessions', 'correction-mining', 'openclaw-semantic', 'promise-reality'}:
        meta = obs.get('metadata') or {}
        sid = meta.get('proposal_id') or slug(meta.get('title') or summary)
        title = meta.get('title') or 'SUBCONSCIOUS improvement opportunity'
        types = ['friction', 'repeat']
        if meta.get('pattern_type') in {'promise_gap', 'promise_reality_gap'}:
            types = ['friction', 'blocker']
        elif meta.get('pattern_type') in {'style_guard', 'manual_repeat', 'correction_mining'}:
            types = ['reuse', 'repeat']
        elif meta.get('pattern_type') == 'openclaw_semantic_cluster':
            types = ['friction', 'repeat']
        delta = float(meta.get('score_delta') or 6.5)
        ev.update({
            'pattern_type': meta.get('pattern_type'),
            'proposed_action': meta.get('proposed_action'),
            'risk': meta.get('risk'),
            'chip_value_signal': bool(meta.get('chip_value_signal')),
        })
        for key in ('suggested_patch_type', 'candidate_patch', 'correction_buckets', 'evidence_items', 'automation_candidate'):
            if key in meta:
                ev[key] = meta.get(key)
        return sid, title, types, delta, ev
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


NON_REOPENING_APPROVAL_BUCKETS = {
    # These are system-improvement work items, not per-evidence tasks. Once an
    # instance is approved/running, new evidence should enrich the existing work
    # or wait for verification — not ask Chip to approve the same generic card.
    'correction_mining',
    'promise_gap',
    'promise_reality_gap',
}


def _family_has_active_or_closed(signals: dict, base_id: str) -> bool:
    prefix = f'{base_id}-'
    for sid, sig in signals.items():
        if sid != base_id and not str(sid).startswith(prefix):
            continue
        if sig.get('status') in {'pending_intent', 'approved', 'cooling'}:
            return True
    return False


def should_instance_closed_bucket(sig: dict, ev: dict, signals: dict | None = None) -> bool:
    """Closed buckets should not swallow fresh concrete Chip-value evidence.

    Base proposal ids such as manual-repeat-automation-opportunity are buckets:
    once approved/archived, new session evidence for the same pattern can become
    a separately approvable proposal instance. Same evidence_uri maps to the same
    instance id so repeated walks do not spam duplicates.

    Exception: some buckets describe one system fix, not one item per evidence
    URI. For those, an approved/running family member suppresses new instances.
    """
    if sig.get('status') not in CLOSED_SIGNAL_STATUSES:
        return False
    if ev.get('pattern_type') in NON_REOPENING_APPROVAL_BUCKETS and signals is not None:
        if _family_has_active_or_closed(signals, str(sig.get('id') or '')):
            return False
    if ev.get('chip_value_signal'):
        return True
    if ev.get('pattern_type') in REOPENABLE_PATTERN_TYPES:
        return True
    return False


def instance_signal_id(base_id: str, ev: dict) -> str:
    seed = ev.get('evidence_uri') or ev.get('summary') or now_iso()
    digest = hashlib.sha1(str(seed).encode('utf-8')).hexdigest()[:10]
    return f'{base_id[:68]}-{digest}'

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--room', default='/home/hermes/.hermes/profiles/subc/room')
    ap.add_argument('--walk-json')
    ap.add_argument('--decay', type=float, default=0.9)
    args=ap.parse_args()
    room=Path(args.room)
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
        bucket_sig = signals.get(sid)
        if bucket_sig and should_instance_closed_bucket(bucket_sig, ev, signals):
            bucket_id = sid
            sid = instance_signal_id(bucket_id, ev)
            ev = dict(ev)
            ev['bucket_signal_id'] = bucket_id
            ev['bucket_status'] = bucket_sig.get('status')
        sig=signals.get(sid) or {'schema_version':'1.0','id':sid,'title':title,'signal_types':types,'score':0,'evidence':[], 'status':'note', 'created_at':now_iso(), 'duplicate_of':None, 'cooldown_until':None}
        if sig.get('status') in ('approved','rejected','archived','cooling'):
            # Human decisions and cooldowns win for this exact signal instance.
            # New evidence for a closed bucket was already split above into a
            # deterministic instance id, so terminal buckets no longer hide it.
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
    for lane in ['ready_pending_approval','blocked_ready','watching','cooling','approved','archived']:
        lanes[lane]=[]
    for sig in sorted(signals.values(), key=opportunity_score, reverse=True):
        ref={'id':sig['id'],'title':sig['title'],'score':sig['score'],'opportunity_score':opportunity_score(sig),'status':sig['status']}
        if sig['status']=='pending_intent':
            eligible, reason = intent_eligibility(sig)
            if eligible:
                lanes['ready_pending_approval'].append(ref)
            else:
                ref['status']='blocked_ready'
                ref['reason']=reason
                lanes['blocked_ready'].append(ref)
        elif sig['status']=='watching': lanes['watching'].append(ref)
        elif sig['status']=='cooling': lanes['cooling'].append(ref)
        elif sig['status']=='approved':
            intent_id = sig['id'] if str(sig['id']).startswith('intent_') else 'intent_' + str(sig['id'])
            verified, reason, _details = verify_shaw_run(room, intent_id)
            if verified:
                lanes['approved'].append(ref)
            else:
                ref['status']='blocked_ready'
                ref['reason']=reason
                lanes['blocked_ready'].append(ref)
        elif sig['status'] in ('archived','rejected'): lanes['archived'].append(ref)
    summary['updated_at']=now_iso()
    write_json(room/'summary.json', summary)
    print(json.dumps({'walk':str(walk_path),'touched':touched,'ready':lanes['ready_pending_approval'],'watching':lanes['watching']}, ensure_ascii=False, indent=2))
if __name__ == '__main__': raise SystemExit(main())
