#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path
from subc_common import now_iso, write_json, load_json, redact
from subc_adapters import collect_sources

LATEST_BLOCK_RE = re.compile(r'(^|\n)## Latest read-only discovery\n.*?(?=\n## |\Z)', re.S)

def render_md(observations):
    lines=['# SUBCONSCIOUS Walk Log', '', f'Observed: {now_iso()}', '', f'Observations: {len(observations)}', '']
    for o in observations:
        lines += [f"## {o['id']}", f"source: {o['source']} / {o['source_adapter']}", f"evidence: `{o['evidence_uri']}`", f"confidence: {o['confidence']}", '', redact(o['summary']), '']
    return '\n'.join(lines).strip()+'\n'

def update_board(room: Path, observations):
    board=room/'signal-board.md'
    existing=board.read_text() if board.exists() else '# SUBCONSCIOUS Signal Board\n'
    block=['', '## Latest read-only discovery', '', f'Updated: {now_iso()}', '']
    for o in observations[:10]:
        block.append(f"- `{o['source']}` {redact(o['summary'])} — {redact(o['evidence_uri'])}")
    new_block = '\n'.join(block) + '\n'
    cleaned = LATEST_BLOCK_RE.sub('', existing.rstrip())
    board.write_text(cleaned.rstrip() + '\n' + new_block)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--room', default='/home/hermes/.hermes/profiles/subc/room')
    ap.add_argument('--source', default='all', choices=['all','hermes','hermes-sessions','correction-mining','openclaw','openclaw-sessions','openclaw-semantic','promise-reality','mem0g','project-flow'])
    ap.add_argument('--limit', type=int, default=20)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--no-publish', action='store_true')
    args=ap.parse_args()
    room=Path(args.room); room.mkdir(parents=True, exist_ok=True)
    observations=collect_sources(args.source, args.limit)
    payload={'schema_version':'1.0','walk_id':'walk_'+now_iso().replace(':','').replace('-',''), 'observed_at':now_iso(), 'source':args.source, 'observations':observations, 'publish': not args.no_publish and not args.dry_run}
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    stem=payload['walk_id']
    write_json(room/'walk_logs'/f'{stem}.json', payload)
    (room/'walk_logs'/f'{stem}.md').write_text(render_md(observations))
    update_board(room, observations)
    print(f'OK: wrote walk {stem} observations={len(observations)} publish={payload["publish"]}')
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
