#!/usr/bin/env bash
set -euo pipefail
BASE="${SUBC_BASE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
ROOM="${SUBC_ROOM:-$HOME/.hermes/profiles/subc/room}"
cd "$BASE"

walk_out=$(python3 scripts/subc_walk.py --room "$ROOM" --no-publish --source all --limit "${SUBC_WALK_LIMIT:-25}")
score_out=$(python3 scripts/subc_score.py --room "$ROOM")
intent_out=$(python3 scripts/subc_intents.py --room "$ROOM" --max "${SUBC_MAX_INTENTS:-3}")
publish_pending_out=$(python3 scripts/subc_publish_pending.py || true)
validate_out=$(python3 scripts/subc_validate.py --room "$ROOM")

timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
ready_count=$(python3 - <<PY
import json
p='$ROOM/summary.json'
d=json.load(open(p))
print(len(d.get('lanes',{}).get('ready_pending_approval',[])))
PY
)
watching_count=$(python3 - <<PY
import json
p='$ROOM/summary.json'
d=json.load(open(p))
print(len(d.get('lanes',{}).get('watching',[])))
PY
)

cat <<EOF
🚶 SUBCONSCIOUS walk
updated: $timestamp
ready_pending_approval: $ready_count
watching: $watching_count
validate: $validate_out
pending_publish: $publish_pending_out

$walk_out
EOF
