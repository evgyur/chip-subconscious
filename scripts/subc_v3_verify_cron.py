#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from subc_v3_rollout import verify_rollout_state


def verify_cron_state(
    manifest_path: str | Path,
    *,
    jobs_path: str | Path | None = None,
) -> tuple[list[str], dict[str, Any]]:
    errors, evidence = verify_rollout_state(manifest_path, jobs_path=jobs_path, expected_stage="steady")
    if evidence.get("cron_delivery") != "local":
        errors.append("cron_must_deliver_local")
    return list(dict.fromkeys(errors)), evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify final SUBCONSCIOUS v3 cron state")
    parser.add_argument("--manifest", default="reports/v3/rollout-manifest.md")
    parser.add_argument("--jobs")
    args = parser.parse_args()
    errors, evidence = verify_cron_state(args.manifest, jobs_path=args.jobs)
    print(json.dumps({"valid": not errors, "errors": errors, "evidence": evidence}, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
