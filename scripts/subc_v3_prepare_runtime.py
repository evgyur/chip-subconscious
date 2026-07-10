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
from subc_guardian import evaluate_fixture
from subc_live_projection import project_recent_messages
from subc_reflexes import ReflexEngine

SCOUT_CONFIG = {
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


def _fingerprint(component: str, state: str, observed_at: str) -> str:
    return "sha256:" + hashlib.sha256(f"{component}|{state}|{observed_at}".encode()).hexdigest()


def _invalidate_model_output(runtime: Path) -> None:
    """Require every cycle to produce a fresh evaluator response."""
    (runtime / "model_output.json").unlink(missing_ok=True)


def prepare_runtime(
    runtime_dir: str | Path,
    *,
    state_db: str | Path,
    config: str | Path,
    cron_jobs: str | Path,
    room: str | Path,
    since_timestamp: float | None = None,
) -> dict[str, Any]:
    runtime = Path(runtime_dir)
    runtime.mkdir(parents=True, exist_ok=True)
    _invalidate_model_output(runtime)
    context = project_recent_messages(state_db, config, since_timestamp=since_timestamp, limit=60)
    reflex_events = [event for event in context["events"] if event["lane"] == "reflex"]
    scout_events = [event for event in context["events"] if event["lane"] == "scout"]
    reflex = ReflexEngine(runtime / "reflex-state.json").process(reflex_events, persist=True)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    jobs_data = json.loads(Path(cron_jobs).read_text())
    jobs = jobs_data["jobs"] if isinstance(jobs_data, dict) else jobs_data
    replacement = next((job for job in jobs if job.get("name") == "SUBCONSCIOUS v3 Scout"), None)
    scheduler_state = "healthy" if replacement and replacement.get("enabled") else "failed"
    room_state = "healthy"
    try:
        json.loads((Path(room) / "summary.json").read_text())
    except Exception:
        room_state = "failed"
    snapshots = [
        {
            "observed_at": now,
            "component": "v3_scheduler",
            "probe_type": "cron",
            "state": scheduler_state,
            "evidence_fingerprint": _fingerprint("v3_scheduler", scheduler_state, now),
            "safe_summary": f"SUBCONSCIOUS v3 scheduler changed to {scheduler_state}",
        },
        {
            "observed_at": now,
            "component": "subconscious_room",
            "probe_type": "room_summary",
            "state": room_state,
            "evidence_fingerprint": _fingerprint("subconscious_room", room_state, now),
            "safe_summary": f"SUBCONSCIOUS room changed to {room_state}",
        },
    ]
    snapshot_path = runtime / "guardian-snapshots.jsonl"
    snapshot_path.write_text("\n".join(json.dumps(item, sort_keys=True) for item in snapshots) + "\n")
    guardian = evaluate_fixture(snapshot_path, state_path=runtime / "guardian-state.json", dry_run=False)

    scout_context = {
        "schema_version": "subc-v3-context-pack/1",
        "coverage": context["coverage"],
        "events": scout_events,
    }
    _atomic_json(runtime / "context_pack.json", scout_context)
    _atomic_json(runtime / "config.json", SCOUT_CONFIG)
    return {
        "schema_version": "subc-v3-runtime-prepare/1",
        "source_coverage": context["coverage"],
        "lane_counts": dict(Counter(event["lane"] for event in context["events"])),
        "reflex_created": reflex["created_count"],
        "reflex_enriched": reflex["enriched_count"],
        "reflex_duplicates": reflex["duplicate_count"],
        "guardian_change_count": guardian["change_count"],
        "guardian_incidents": guardian["incidents"],
        "scout_event_count": len(scout_events),
        "telegram_deliveries": 0,
        "canonical_memory_writes": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare private v3 runtime context, Reflex state and Guardian transitions")
    home = Path.home()
    parser.add_argument("--runtime-dir", default=str(home / ".hermes/profiles/subc/v3"))
    parser.add_argument("--since-hours", type=float, default=48)
    args = parser.parse_args()
    report = prepare_runtime(
        args.runtime_dir,
        state_db=home / ".hermes/state.db",
        config=home / ".hermes/config.yaml",
        cron_jobs=home / ".hermes/cron/jobs.json",
        room=home / ".hermes/profiles/subc/room",
        since_timestamp=time.time() - args.since_hours * 3600,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
