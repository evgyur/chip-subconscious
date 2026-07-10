#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _baseline_values(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in {"old_job_id", "baseline_public_sha"}:
            values[key] = value.strip().strip("`")
    return values


def assert_no_live_mutation(baseline_path: str | Path, shadow_path: str | Path = "reports/v3/shadow-run.json") -> list[str]:
    baseline = _baseline_values(Path(baseline_path))
    report = json.loads(Path(shadow_path).read_text())
    errors = []
    if not baseline.get("old_job_id") or not baseline.get("baseline_public_sha"):
        errors.append("baseline_markers_missing")
    if report.get("live_mutation_detected"):
        errors.append("live_mutation_detected")
    for key, value in report.get("mutation_checks", {}).items():
        if not value:
            errors.append(f"mutation_check_failed:{key}")
    for key in ("telegram_deliveries", "cron_changes", "provider_config_changes", "state_writes", "canonical_memory_writes"):
        if report.get(key) != 0:
            errors.append(f"{key}_nonzero")
    passes = report.get("passes") or []
    if not passes:
        errors.append("shadow_passes_missing")
    else:
        target = passes[0].get("snapshot", {}).get("cron_target", {})
        if target.get("id") != baseline.get("old_job_id"):
            errors.append("old_job_identity_changed")
        if target.get("enabled") is not True:
            errors.append("old_job_was_not_enabled_during_shadow")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert that read-only shadow did not mutate live surfaces")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--shadow", default="reports/v3/shadow-run.json")
    args = parser.parse_args()
    errors = assert_no_live_mutation(args.baseline, args.shadow)
    print(json.dumps({"pass": not errors, "errors": errors}, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
