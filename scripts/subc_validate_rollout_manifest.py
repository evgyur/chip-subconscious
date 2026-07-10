#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

REQUIRED_STEPS = [
    "pause_old",
    "create_disabled",
    "enable_canary",
    "test_delivery",
    "readback",
    "second_scheduler_cycle",
    "set_steady_schedule",
]


def _manifest_json(path: Path) -> dict[str, Any]:
    match = re.search(r"```json\s*(\{.*?\})\s*```", path.read_text(), re.DOTALL)
    if not match:
        raise ValueError("manifest JSON block missing")
    return json.loads(match.group(1))


def validate_manifest(
    manifest_path: str | Path,
    *,
    cron_jobs: str | Path | None = None,
    repo_root: str | Path = ".",
    shadow_report: str | Path = "reports/v3/shadow-run.json",
    backtest_report: str | Path = "reports/v3/backtest.json",
) -> list[str]:
    manifest_path = Path(manifest_path)
    text = manifest_path.read_text()
    data = _manifest_json(manifest_path)
    root = Path(repo_root)
    cron_path = Path(cron_jobs) if cron_jobs else Path.home() / ".hermes/cron/jobs.json"
    jobs_data = json.loads(cron_path.read_text())
    jobs = jobs_data["jobs"] if isinstance(jobs_data, dict) else jobs_data
    errors = []

    if data.get("schema_version") != "subc-v3-rollout-manifest/1":
        errors.append("schema_version_invalid")
    old = data.get("old_job", {})
    if old.get("action") != "pause":
        errors.append("old_job_action_must_be_pause")
    if old.get("delete") is not False:
        errors.append("old_job_delete_must_be_false")
    target = next((job for job in jobs if job.get("id") == old.get("id")), None)
    if target is None:
        errors.append("old_job_not_found")
    else:
        if bool(target.get("enabled")) is not bool(old.get("expected_enabled")):
            errors.append("old_job_enabled_state_mismatch")
        actual_target_hash = "sha256:" + hashlib.sha256(str(target.get("deliver")).encode()).hexdigest()
        replacement = data.get("replacement", {})
        if actual_target_hash != replacement.get("delivery_target_sha256"):
            errors.append("delivery_target_hash_mismatch")

    replacement = data.get("replacement", {})
    if replacement.get("weekly_proposal_cap") != 3:
        errors.append("weekly_proposal_cap_must_be_three")
    if replacement.get("canary_schedule") != "every 5m":
        errors.append("canary_schedule_invalid")
    if replacement.get("steady_schedule") != "17 6 * * *":
        errors.append("steady_schedule_invalid")
    if replacement.get("cron_delivery") != "local":
        errors.append("cron_delivery_must_be_local")
    if replacement.get("delivery_mode") != "verified_self_send":
        errors.append("delivery_mode_must_be_verified_self_send")
    if not str(replacement.get("workdir", "")).startswith("${HOME}/"):
        errors.append("workdir_must_use_home_alias")
    prompt_file = replacement.get("prompt_file")
    if not prompt_file or not (root / prompt_file).is_file():
        errors.append("prompt_file_missing")
    for script in replacement.get("scripts", []):
        if not (root / script).is_file():
            errors.append(f"script_missing:{script}")
    if data.get("activation_steps") != REQUIRED_STEPS:
        errors.append("activation_steps_invalid")
    rollback = data.get("rollback_commands", [])
    if rollback != [f"hermes cron pause ${{NEW_JOB_ID}}", f"hermes cron resume {old.get('id')}"]:
        errors.append("rollback_commands_invalid")
    if any(re.search(r"\b(?:remove|delete|rm)\b", command) for command in rollback):
        errors.append("rollback_is_destructive")
    if data.get("approval_scope") != "pause-old/activate-new/test-readback/rollback only":
        errors.append("approval_scope_invalid")
    if not data.get("recovery_owner"):
        errors.append("recovery_owner_missing")
    if re.search(r"-100\d{10,}", text):
        errors.append("raw_private_target_present")
    if not json.loads(Path(shadow_report).read_text()).get("shadow_gate_pass"):
        errors.append("shadow_gate_not_green")
    if not json.loads(Path(backtest_report).read_text()).get("rollout_gate_pass"):
        errors.append("backtest_gate_not_green")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate bounded SUBCONSCIOUS v3 rollout manifest")
    parser.add_argument("manifest")
    parser.add_argument("--cron-jobs")
    parser.add_argument("--shadow", default="reports/v3/shadow-run.json")
    parser.add_argument("--backtest", default="reports/v3/backtest.json")
    args = parser.parse_args()
    errors = validate_manifest(
        args.manifest,
        cron_jobs=args.cron_jobs,
        repo_root=Path.cwd(),
        shadow_report=args.shadow,
        backtest_report=args.backtest,
    )
    print(json.dumps({"valid": not errors, "errors": errors}, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
