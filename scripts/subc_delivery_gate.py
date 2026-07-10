#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from subc_context_pack import _atomic_json

STATE_SCHEMA = "subc-v3-delivery-state/1"


def empty_state() -> dict[str, Any]:
    return {"schema_version": STATE_SCHEMA, "deliveries": [], "feedback": []}


def load_state(path: str | Path) -> dict[str, Any]:
    state_path = Path(path)
    if not state_path.exists():
        return empty_state()
    state = json.loads(state_path.read_text())
    if state.get("schema_version") != STATE_SCHEMA:
        raise ValueError("unsupported delivery state; fail closed")
    return state


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    _atomic_json(Path(path), state)


def apply_delivery_gate(
    scout_report: dict[str, Any],
    state: dict[str, Any],
    *,
    now: datetime | None = None,
    max_per_week: int = 3,
) -> dict[str, Any]:
    if state.get("schema_version") != STATE_SCHEMA:
        raise ValueError("unsupported delivery state; fail closed")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current - timedelta(days=7)
    recent = [
        item for item in state["deliveries"]
        if datetime.fromisoformat(item["delivered_at"].replace("Z", "+00:00")) >= cutoff
    ]
    delivered_fingerprints = {item["problem_fingerprint"] for item in state["deliveries"]}
    proposals = scout_report.get("proposals", []) if scout_report.get("status") == "selected" else []
    novel = [item for item in proposals if item["problem_fingerprint"] not in delivered_fingerprints]
    blocked_duplicates = len(proposals) - len(novel)
    slots = max(0, int(max_per_week) - len(recent))
    allowed = novel[:slots]
    blocked_budget = max(0, len(novel) - len(allowed))
    next_state = deepcopy(state)
    timestamp = current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    for proposal in allowed:
        next_state["deliveries"].append({
            "proposal_instance_id": proposal["proposal_instance_id"],
            "problem_fingerprint": proposal["problem_fingerprint"],
            "delivered_at": timestamp,
            "status": "delivery_selected",
        })
    return {
        "schema_version": "subc-v3-delivery-gate/1",
        "allowed_proposals": allowed,
        "blocked_as_duplicate": blocked_duplicates,
        "blocked_by_budget": blocked_budget,
        "weekly_delivered_before": len(recent),
        "weekly_slots_before": slots,
        "silent": not allowed,
        "next_state": next_state,
    }


def record_feedback(state: dict[str, Any], feedback: dict[str, Any]) -> dict[str, Any]:
    schema_path = Path(__file__).resolve().parents[1] / "schemas/v3_feedback.schema.json"
    Draft202012Validator(json.loads(schema_path.read_text())).validate(feedback)
    if feedback["writes_canonical_memory"]:
        raise ValueError("feedback cannot write canonical memory")
    updated = deepcopy(state)
    if any(item["feedback_id"] == feedback["feedback_id"] for item in updated["feedback"]):
        return updated
    updated["feedback"].append(feedback)
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply hard weekly and duplicate delivery gates")
    parser.add_argument("--scout-report", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-per-week", type=int, default=3)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    scout_report = json.loads(Path(args.scout_report).read_text())
    state = load_state(args.state)
    result = apply_delivery_gate(scout_report, state, max_per_week=args.max_per_week)
    if args.commit:
        save_state(args.state, result["next_state"])
    public_result = {key: value for key, value in result.items() if key != "next_state"}
    _atomic_json(Path(args.output), public_result)
    print(json.dumps({"allowed": len(result["allowed_proposals"]), "silent": result["silent"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
