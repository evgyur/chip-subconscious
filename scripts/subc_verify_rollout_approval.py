#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

EXPECTED_GOAL = "sg-20260710-subconscious-v3-product-reset"


def verify_approval(state_path: str | Path, expected_goal: str = EXPECTED_GOAL) -> list[str]:
    text = Path(state_path).read_text()
    errors: list[str] = []
    if f"Goal identity: `{expected_goal}`" not in text:
        errors.append("goal_identity_mismatch")
    if "Current phase: 8" not in text and "Current phase: AUDIT" not in text:
        errors.append("phase_08_not_active")
    approval_line = next((line for line in text.splitlines() if "P08 approval source:" in line), "")
    if not approval_line:
        errors.append("rollout_approval_event_missing")
    bounded = "bounded reversible cron/test lane" in approval_line and "covered" in approval_line
    if "Chip explicitly instructed" not in approval_line or not bounded:
        errors.append("bounded_rollout_approval_missing")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify bounded SUBCONSCIOUS v3 rollout approval")
    parser.add_argument("state")
    parser.add_argument("--goal-id", default=EXPECTED_GOAL)
    args = parser.parse_args()
    errors = verify_approval(args.state, args.goal_id)
    print(json.dumps({"approved": not errors, "errors": errors}, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
