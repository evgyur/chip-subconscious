#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "subc-v3-delivery-state/1"
ACTIONS = {"save", "skip", "mute", "promote", "deep_dive", "accept", "reject"}
PROPOSAL_RE = re.compile(r"^prp_[a-f0-9]{16,64}$")
HASH_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def record_feedback(
    state_path: str | Path,
    *,
    proposal_instance_id: str,
    action: str,
    actor_ref_hash: str,
    recorded_at: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    path = Path(state_path)
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema_version") != SCHEMA:
        raise ValueError("unsupported delivery state; fail closed")
    if action not in ACTIONS:
        raise ValueError("unsupported feedback action")
    if not PROPOSAL_RE.fullmatch(proposal_instance_id):
        raise ValueError("invalid proposal instance id")
    if not HASH_RE.fullmatch(actor_ref_hash):
        raise ValueError("invalid actor reference hash")
    delivered = {item.get("proposal_instance_id") for item in state.get("deliveries", [])}
    if proposal_instance_id not in delivered:
        raise ValueError("proposal was not delivered; fail closed")
    feedback = state.setdefault("feedback", [])
    for item in feedback:
        if (
            item.get("proposal_instance_id") == proposal_instance_id
            and item.get("action") == action
            and item.get("actor_ref_hash") == actor_ref_hash
        ):
            return item
    timestamp = recorded_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    digest = hashlib.sha256(f"{proposal_instance_id}\0{action}\0{actor_ref_hash}".encode()).hexdigest()[:24]
    item: dict[str, Any] = {
        "schema_version": "subc-v3-feedback/1",
        "feedback_id": f"fbk_{digest}",
        "proposal_instance_id": proposal_instance_id,
        "action": action,
        "recorded_at": timestamp,
        "actor_ref_hash": actor_ref_hash,
        "creates_promotion_request": action == "promote",
        "writes_canonical_memory": False,
    }
    if reason:
        item["reason"] = reason[:500]
    feedback.append(item)
    _atomic_json(path, state)
    return item


def main() -> int:
    parser = argparse.ArgumentParser(description="Record bounded SUBCONSCIOUS v3 proposal feedback")
    parser.add_argument("--state", required=True)
    parser.add_argument("--proposal-id", required=True)
    parser.add_argument("--action", choices=sorted(ACTIONS), required=True)
    parser.add_argument("--actor-ref-hash", required=True)
    parser.add_argument("--reason", default="")
    args = parser.parse_args()
    item = record_feedback(
        args.state,
        proposal_instance_id=args.proposal_id,
        action=args.action,
        actor_ref_hash=args.actor_ref_hash,
        reason=args.reason,
    )
    print(json.dumps({
        "ok": True,
        "feedback_id": item["feedback_id"],
        "action": item["action"],
        "creates_promotion_request": item["creates_promotion_request"],
        "writes_canonical_memory": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
