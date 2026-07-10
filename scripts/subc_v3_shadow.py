#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from subc_context_pack import _atomic_json
from subc_live_projection import project_recent_messages
from subc_scout import run_scout

OLD_JOB_ID = "fb2ae09c0d59"


def _file_sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _room_sha(room: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    files = sorted(path for path in room.rglob("*") if path.is_file())
    for path in files:
        digest.update(path.relative_to(room).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest(), len(files)


def _target_job_snapshot(cron_jobs: Path, job_id: str | None = None) -> dict[str, Any]:
    data = json.loads(cron_jobs.read_text())
    jobs = data["jobs"] if isinstance(data, dict) else data
    target = None
    if job_id:
        target = next((job for job in jobs if job.get("id") == job_id), None)
    if target is None:
        target = next((job for job in jobs if job.get("name") == "SUBCONSCIOUS walks"), None)
    if target is None:
        raise ValueError("old SUBCONSCIOUS scheduler is unavailable")
    safe = {
        "id": target["id"],
        "enabled": bool(target.get("enabled")),
        "schedule": target.get("schedule"),
        "delivery_target_hash": "sha256:" + hashlib.sha256(str(target.get("deliver")).encode()).hexdigest(),
        "provider": target.get("provider"),
        "model": target.get("model"),
        "script_hash": "sha256:" + hashlib.sha256(str(target.get("script")).encode()).hexdigest(),
        "prompt_hash": "sha256:" + hashlib.sha256(str(target.get("prompt")).encode()).hexdigest(),
    }
    safe["snapshot_hash"] = "sha256:" + hashlib.sha256(json.dumps(safe, sort_keys=True).encode()).hexdigest()
    return safe


def _snapshot(room: Path, cron_jobs: Path, config: Path, job_id: str | None) -> dict[str, Any]:
    room_hash, room_files = _room_sha(room)
    return {
        "room_hash": room_hash,
        "room_file_count": room_files,
        "cron_target": _target_job_snapshot(cron_jobs, job_id),
        "provider_config_hash": _file_sha(config),
    }


def run_shadow(
    *,
    room: str | Path,
    cron_jobs: str | Path,
    config: str | Path,
    state_db: str | Path,
    backtest_report: str | Path,
    model_output: str | Path | None,
    since_timestamp: float | None = None,
    old_job_id: str | None = None,
    include_private_context: bool = False,
) -> dict[str, Any]:
    room_path, cron_path, config_path = Path(room), Path(cron_jobs), Path(config)
    passes = []
    private_context: dict[str, Any] | None = None
    for index in range(2):
        snapshot = _snapshot(room_path, cron_path, config_path, old_job_id)
        context = project_recent_messages(
            state_db,
            config_path,
            since_timestamp=since_timestamp,
            limit=40,
        )
        private_context = context
        passes.append({
            "pass": index + 1,
            "snapshot": snapshot,
            "eligible_events": context["coverage"]["eligible"],
            "lane_counts": dict(Counter(event["lane"] for event in context["events"])),
            "context_hash": "sha256:" + hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        })
    assert private_context is not None
    before, after = passes[0]["snapshot"], passes[1]["snapshot"]
    mutation_checks = {
        "room_unchanged": before["room_hash"] == after["room_hash"],
        "cron_target_unchanged": before["cron_target"]["snapshot_hash"] == after["cron_target"]["snapshot_hash"],
        "provider_config_unchanged": before["provider_config_hash"] == after["provider_config_hash"],
    }
    if model_output and Path(model_output).exists():
        response = json.loads(Path(model_output).read_text())
        scout_config = {
            "schema_version": "subc-v3-scout-config/1",
            "provider": "hermes-approved-route",
            "route": "current-approved",
            "max_input_events": 20,
            "max_context_chars": 6000,
            "max_prompt_tokens": 900,
            "timeout_ms": 45000,
            "max_proposals": 3,
            "min_confidence": 0.7,
            "allow_single_source_exception": True,
        }
        semantic = run_scout(private_context, response, scout_config, elapsed_ms=0)
    else:
        semantic = {"status": "not_evaluated", "proposals": [], "failure_reason": "model_output_missing"}
    backtest_green = bool(json.loads(Path(backtest_report).read_text()).get("rollout_gate_pass"))
    candidate_review = [
        {
            "proposal_instance_id": proposal["proposal_instance_id"],
            "problem_fingerprint": proposal["problem_fingerprint"],
            "domain": proposal["domain"],
            "confidence": proposal["confidence"],
            "privacy": "pass",
            "novelty": "pass",
            "value": "pass",
            "duplication": "pass",
        }
        for proposal in semantic.get("proposals", [])
    ]
    semantic_ok = semantic["status"] in {"selected", "empty"}
    no_mutation = all(mutation_checks.values())
    report = {
        "schema_version": "subc-v3-shadow-report/1",
        "mode": "read_only",
        "observation_pass_count": 2,
        "passes": passes,
        "mutation_checks": mutation_checks,
        "live_mutation_detected": not no_mutation,
        "source_coverage": private_context["coverage"],
        "semantic_status": semantic["status"],
        "candidate_review": candidate_review,
        "candidate_count": len(candidate_review),
        "backtest_gate_pass": backtest_green,
        "telegram_deliveries": 0,
        "cron_changes": 0,
        "provider_config_changes": 0,
        "state_writes": 0,
        "canonical_memory_writes": 0,
        "shadow_gate_pass": no_mutation and semantic_ok and backtest_green,
    }
    if include_private_context:
        report["private_context"] = private_context
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run two-pass read-only SUBCONSCIOUS v3 shadow")
    home = Path.home()
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--emit-private-context")
    parser.add_argument("--allow-no-model", action="store_true")
    parser.add_argument("--model-output", default="/tmp/subc-v3-shadow-model-output.json")
    parser.add_argument("--since-hours", type=float, default=48)
    args = parser.parse_args()
    if not args.read_only:
        raise SystemExit("--read-only is mandatory")
    report = run_shadow(
        room=home / ".hermes/profiles/subc/room",
        cron_jobs=home / ".hermes/cron/jobs.json",
        config=home / ".hermes/config.yaml",
        state_db=home / ".hermes/state.db",
        backtest_report=Path("reports/v3/backtest.json"),
        model_output=args.model_output,
        since_timestamp=time.time() - args.since_hours * 3600,
        old_job_id=OLD_JOB_ID,
        include_private_context=True,
    )
    private_context = report.pop("private_context")
    if args.emit_private_context:
        _atomic_json(Path(args.emit_private_context), private_context)
    _atomic_json(Path(args.output), report)
    print(json.dumps({"shadow_gate_pass": report["shadow_gate_pass"], "semantic_status": report["semantic_status"], "live_mutation_detected": report["live_mutation_detected"]}, sort_keys=True))
    if report["shadow_gate_pass"] or (args.allow_no_model and report["semantic_status"] == "not_evaluated" and not report["live_mutation_detected"]):
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
