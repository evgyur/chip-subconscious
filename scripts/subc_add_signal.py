#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path
from subc_common import now_iso, write_json, load_json, redact

VALID_TYPES = {'friction','repeat','excitement','reuse','mention','return','cooling','blocker'}

def slug(s: str) -> str:
    return re.sub(r'[^a-z0-9]+','-',s.lower()).strip('-')[:80] or 'manual-signal'

def status_for(score: float) -> str:
    if score >= 6: return 'pending_intent'
    if score >= 4: return 'watching'
    return 'note'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--room', default='/home/hermes/.hermes/profiles/subc/room')
    ap.add_argument('--id')
    ap.add_argument('--title', required=True)
    ap.add_argument('--summary', required=True)
    ap.add_argument('--evidence-uri', required=True)
    ap.add_argument('--source', default='manual')
    ap.add_argument('--adapter', default='ManualAdapter')
    ap.add_argument('--types', default='mention')
    ap.add_argument('--score-delta', type=float, default=1.0)
    args = ap.parse_args()

    room = Path(args.room)
    signals_path = room / 'signals.json'
    data = load_json(signals_path, {'schema_version': '1.0', 'signals': {}})
    sid = args.id or slug(args.title)
    types = [t.strip() for t in args.types.split(',') if t.strip()]
    bad = [t for t in types if t not in VALID_TYPES]
    if bad:
        raise SystemExit(f'invalid signal types: {bad}')

    signals = data.setdefault('signals', {})
    sig = signals.get(sid) or {
        'schema_version': '1.0',
        'id': sid,
        'title': redact(args.title),
        'signal_types': [],
        'score': 0,
        'evidence': [],
        'status': 'note',
        'created_at': now_iso(),
        'duplicate_of': None,
        'cooldown_until': None,
    }
    if sig.get('status') in ('approved','rejected','archived','cooling'):
        print(json.dumps({'ok': False, 'reason': f'signal is {sig.get("status")}', 'id': sid}, ensure_ascii=False))
        return 0
    ev = {
        'evidence_uri': args.evidence_uri,
        'summary': redact(args.summary),
        'source_adapter': args.adapter,
        'source': args.source,
        'observed_at': now_iso(),
    }
    seen = {e.get('evidence_uri') for e in sig.get('evidence', [])}
    if ev['evidence_uri'] not in seen:
        sig.setdefault('evidence', []).append(ev)
    sig['signal_types'] = sorted(set(sig.get('signal_types', []) + types))
    sig['score'] = min(10, round(float(sig.get('score', 0)) + args.score_delta, 2))
    sig['status'] = status_for(sig['score'])
    sig['updated_at'] = now_iso()
    signals[sid] = sig
    write_json(signals_path, data)
    print(json.dumps({'ok': True, 'id': sid, 'score': sig['score'], 'status': sig['status']}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    raise SystemExit(main())
