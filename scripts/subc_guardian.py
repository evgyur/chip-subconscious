#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from subc_context_pack import _atomic_json

GUARDIAN_SCHEMA = "subc-v3-guardian-state/1"
FAIL_STATES = {"failed", "error", "inactive", "unreachable"}
WARN_STATES = {"degraded", "warning"}


def _load_snapshots(fixture: Path) -> list[dict[str, Any]]:
    path = fixture / "snapshots.jsonl" if fixture.is_dir() else fixture
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _severity(state: str) -> str:
    if state in FAIL_STATES:
        return "critical"
    if state in WARN_STATES:
        return "warning"
    return "info"


def evaluate_fixture(
    fixture: str | Path,
    *,
    state_path: str | Path | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    snapshots = _load_snapshots(Path(fixture))
    path = Path(state_path) if state_path else None
    if path and path.exists():
        state = json.loads(path.read_text())
    else:
        state = {"schema_version": GUARDIAN_SCHEMA, "components": {}, "seen_fingerprints": []}
    if state.get("schema_version") != GUARDIAN_SCHEMA:
        raise ValueError("unsupported guardian state; fail closed")

    components = dict(state["components"])
    seen = set(state["seen_fingerprints"])
    incidents: list[dict[str, Any]] = []
    baselines = 0
    duplicates = 0

    for snapshot in snapshots:
        fingerprint = snapshot["evidence_fingerprint"]
        if fingerprint in seen:
            duplicates += 1
            continue
        component = snapshot["component"]
        current = snapshot["state"]
        previous = components.get(component)
        if previous is None:
            baselines += 1
        elif previous != current:
            seed = f"{component}|{previous}|{current}|{fingerprint}"
            incident = {
                "schema_version": "subc-v3-lane-output/1",
                "output_type": "guardian_incident",
                "incident_id": "grd_" + hashlib.sha256(seed.encode()).hexdigest()[:24],
                "severity": _severity(current),
                "component": component,
                "safe_summary": snapshot["safe_summary"],
                "evidence_fingerprints": [fingerprint],
                "writes_canonical_memory": False,
            }
            incidents.append(incident)
        components[component] = current
        seen.add(fingerprint)

    next_state = {
        "schema_version": GUARDIAN_SCHEMA,
        "components": dict(sorted(components.items())),
        "seen_fingerprints": sorted(seen),
    }
    if path and not dry_run:
        _atomic_json(path, next_state)

    return {
        "schema_version": "subc-v3-guardian-run/1",
        "mode": "dry_run" if dry_run else "local_state",
        "snapshot_count": len(snapshots),
        "baseline_count": baselines,
        "duplicate_count": duplicates,
        "change_count": len(incidents),
        "incidents": incidents,
        "healthy_heartbeat_count": 0,
        "delivery_count": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit Guardian incidents only when observed state changes")
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--state")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = evaluate_fixture(args.fixture, state_path=args.state, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
