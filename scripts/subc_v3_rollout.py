#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from subc_validate_rollout_manifest import _manifest_json


def _jobs(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text())
    return data["jobs"] if isinstance(data, dict) else data


def _schedule(job: dict[str, Any]) -> str:
    schedule = job.get("schedule", {})
    if isinstance(schedule, dict):
        return str(schedule.get("expr") or schedule.get("display") or "")
    return str(schedule)


def verify_rollout_state(
    manifest_path: str | Path,
    *,
    jobs_path: str | Path | None = None,
    expected_stage: str = "canary",
) -> tuple[list[str], dict[str, Any]]:
    manifest = _manifest_json(Path(manifest_path))
    jobs = _jobs(jobs_path or Path.home() / ".hermes/cron/jobs.json")
    old = next((job for job in jobs if job.get("id") == manifest["old_job"]["id"]), None)
    replacements = [job for job in jobs if job.get("name") == manifest["replacement"]["name"]]
    errors: list[str] = []
    rollback_old = expected_stage == "rollback-old"
    if old is None:
        errors.append("old_job_missing")
    elif rollback_old:
        if old.get("enabled") is not True or old.get("state") != "scheduled":
            errors.append("old_job_not_restored")
    elif old.get("enabled") is not False or old.get("state") not in {"paused", "completed"}:
        errors.append("old_job_not_paused")
    if len(replacements) != 1:
        errors.append("replacement_count_invalid")
        new = replacements[0] if replacements else None
    else:
        new = replacements[0]
    expected_schedule = manifest["replacement"]["canary_schedule" if expected_stage == "canary" else "steady_schedule"]
    if new:
        if rollback_old:
            if new.get("enabled") is not False or new.get("state") != "paused":
                errors.append("replacement_not_paused_for_rollback")
        elif new.get("enabled") is not True:
            errors.append("replacement_not_enabled")
        if _schedule(new) != expected_schedule:
            errors.append("replacement_schedule_mismatch")
        if new.get("deliver") != manifest["replacement"].get("cron_delivery"):
            errors.append("replacement_cron_delivery_mismatch")
        if new.get("provider") != manifest["replacement"].get("provider"):
            errors.append("replacement_provider_mismatch")
        if new.get("model") != manifest["replacement"].get("model"):
            errors.append("replacement_model_mismatch")
    evidence = {
        "schema_version": "subc-v3-rollout-state/1",
        "stage": expected_stage,
        "old_job_paused": old is not None and old.get("enabled") is False,
        "old_job_enabled": old is not None and old.get("enabled") is True,
        "replacement_count": len(replacements),
        "new_job_id": new.get("id") if new else None,
        "new_job_enabled": new is not None and new.get("enabled") is True,
        "schedule": _schedule(new) if new else None,
        "cron_delivery": new.get("deliver") if new else None,
    }
    return errors, evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify rollout mutations performed by the standard Hermes executor")
    parser.add_argument("--manifest", default="reports/v3/rollout-manifest.md")
    parser.add_argument("--jobs")
    parser.add_argument("--stage", choices=["canary", "steady", "rollback-old"], default="canary")
    parser.add_argument("--pause-old", action="store_true")
    parser.add_argument("--activate-new", action="store_true")
    parser.add_argument("--output", default="reports/v3/rollout-state.json")
    args = parser.parse_args()
    if args.stage != "rollback-old" and not (args.pause_old and args.activate_new):
        print(json.dumps({"valid": False, "errors": ["bounded_flags_required"]}, sort_keys=True))
        return 2
    errors, evidence = verify_rollout_state(args.manifest, jobs_path=args.jobs, expected_stage=args.stage)
    Path(args.output).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"valid": not errors, "errors": errors, "stage": args.stage}, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
