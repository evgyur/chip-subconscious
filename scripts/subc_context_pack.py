#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

CURSOR_SCHEMA = "subc-v3-cursor/1"
REPORT_SCHEMA = "subc-v3-context-pack/1"
LANE_BY_EVENT = {
    "correction": "reflex",
    "repeated_work": "reflex",
    "commitment": "scout",
    "unfinished_work": "scout",
    "project_risk": "scout",
    "memory_signal": "scout",
    "service_health": "guardian",
    "config_health": "guardian",
    "cron_health": "guardian",
}
FORBIDDEN_RECORD_FIELDS = {"raw_content", "message_body", "content", "transcript"}


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


class CursorStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._legacy_original: dict[str, Any] | None = None

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": CURSOR_SCHEMA, "watermarks": {}, "evidence_fingerprints": []}
        raw = json.loads(self.path.read_text())
        if raw.get("schema_version") == CURSOR_SCHEMA:
            watermarks = raw.get("watermarks")
            fingerprints = raw.get("evidence_fingerprints")
            if not isinstance(watermarks, dict) or not isinstance(fingerprints, list):
                raise ValueError("invalid v3 cursor state")
            return raw
        if raw and all(isinstance(key, str) and isinstance(value, int) for key, value in raw.items()):
            self._legacy_original = raw
            return {"schema_version": CURSOR_SCHEMA, "watermarks": dict(raw), "evidence_fingerprints": []}
        raise ValueError("unsupported cursor schema; fail closed")

    def save(self, state: dict[str, Any]) -> None:
        if state.get("schema_version") != CURSOR_SCHEMA:
            raise ValueError("refusing to write unknown cursor schema")
        if self._legacy_original is not None:
            backup = self.path.with_suffix(self.path.suffix + ".bak")
            if not backup.exists():
                _atomic_json(backup, self._legacy_original)
        _atomic_json(self.path, state)


def _load_registry(fixture: Path) -> dict[str, Any]:
    registry = json.loads((fixture / "source_registry.json").read_text())
    if registry.get("schema_version") != "subc-v3-source-registry/1":
        raise ValueError("unsupported source registry; fail closed")
    if not registry.get("owner_identity_hash") or not isinstance(registry.get("sources"), list):
        raise ValueError("incomplete source registry; fail closed")
    return registry


def _records(fixture: Path) -> list[dict[str, Any]]:
    result = []
    for line in (fixture / "records.jsonl").read_text().splitlines():
        if line.strip():
            result.append(json.loads(line))
    return result


def _event(record: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    event_type = record["event_type"]
    seed = "|".join((record["source_ref_hash"], record["evidence_fingerprint"], event_type))
    event_id = "evt_" + hashlib.sha256(seed.encode()).hexdigest()[:24]
    return {
        "schema_version": "subc-v3-event/1",
        "event_id": event_id,
        "event_type": event_type,
        "lane": LANE_BY_EVENT[event_type],
        "source": {
            "source_class": source["source_class"],
            "source_ref_hash": record["source_ref_hash"],
            "observed_at": record["observed_at"],
            "authority": source["authority"],
            "privacy_class": source["privacy_class"],
        },
        "evidence": [{
            "fingerprint": record["evidence_fingerprint"],
            "kind": "redacted_summary",
            "safe_summary": record["safe_summary"],
        }],
        "raw_content_included": False,
        "model_egress": "disabled",
    }


def build_context_pack(
    fixture: str | Path,
    *,
    cursor_path: str | Path | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    fixture_path = Path(fixture)
    registry = _load_registry(fixture_path)
    records = _records(fixture_path)
    source_by_id = {source["source_id"]: source for source in registry["sources"]}
    denied_origins = set(registry.get("rejected_origin_kinds", []))
    owner_identity = registry["owner_identity_hash"]

    store = CursorStore(cursor_path or fixture_path / "cursor.json")
    state = store.load()
    before = dict(state["watermarks"])
    watermarks = dict(before)
    seen = set(state["evidence_fingerprints"])

    events: list[dict[str, Any]] = []
    rejected = Counter()
    per_source = defaultdict(lambda: Counter(scanned=0, eligible=0, rejected=0))
    observed_times: list[str] = []

    for record in records:
        source_id = str(record.get("source_id", ""))
        sequence = record.get("sequence")
        per_source[source_id]["scanned"] += 1
        if isinstance(record.get("observed_at"), str):
            observed_times.append(record["observed_at"])

        current = int(watermarks.get(source_id, 0))
        if isinstance(sequence, int) and sequence <= current:
            rejected["already_seen"] += 1
            per_source[source_id]["rejected"] += 1
            continue

        source = source_by_id.get(source_id)
        reason = None
        if source is None:
            reason = "source_unconfigured"
        elif not source.get("enabled", False):
            reason = "source_disabled"
        elif not source.get("available", False):
            reason = "source_unavailable"
        elif record.get("identity_hash") != owner_identity:
            reason = "wrong_identity"
        elif record.get("origin_kind") in denied_origins:
            reason = "origin_denied"
        elif FORBIDDEN_RECORD_FIELDS.intersection(record):
            reason = "unsafe_payload"
        elif record.get("event_type") not in LANE_BY_EVENT:
            reason = "event_type_unknown"
        elif not all(record.get(key) for key in ("source_ref_hash", "evidence_fingerprint", "observed_at", "safe_summary")):
            reason = "record_incomplete"
        elif record["evidence_fingerprint"] in seen:
            reason = "duplicate_evidence"

        if source is not None and isinstance(sequence, int):
            watermarks[source_id] = max(current, sequence)

        if reason:
            rejected[reason] += 1
            per_source[source_id]["rejected"] += 1
            continue

        assert source is not None  # All unconfigured sources failed closed above.
        event = _event(record, source)
        events.append(event)
        seen.add(record["evidence_fingerprint"])
        per_source[source_id]["eligible"] += 1

    sources = {}
    for source_id, source in sorted(source_by_id.items()):
        if not source.get("enabled"):
            status = "disabled"
        elif not source.get("available"):
            status = "unavailable"
        else:
            status = "available"
        counts = per_source[source_id]
        sources[source_id] = {
            "status": status,
            "source_class": source["source_class"],
            "scanned_count": counts["scanned"],
            "eligible_count": counts["eligible"],
            "rejected_count": counts["rejected"],
        }

    state = {
        "schema_version": CURSOR_SCHEMA,
        "watermarks": dict(sorted(watermarks.items())),
        "evidence_fingerprints": sorted(seen)[-10000:],
    }
    if not dry_run:
        store.save(state)

    report = {
        "schema_version": REPORT_SCHEMA,
        "mode": "dry_run" if dry_run else "local_state",
        "sources": sources,
        "coverage": {
            "time_range": [min(observed_times), max(observed_times)] if observed_times else [None, None],
            "scanned_count": len(records),
            "eligible_count": len(events),
            "rejected_count": sum(rejected.values()),
            "rejected_reasons": dict(sorted(rejected.items())),
        },
        "cursor": {"before": before, "after": state["watermarks"], "persisted": not dry_run},
        "events": events,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a redacted, cursor-based v3 context pack")
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--cursor")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    report = build_context_pack(args.fixture, cursor_path=args.cursor, dry_run=args.dry_run)
    _atomic_json(Path(args.report), report)
    print(json.dumps({"ok": True, "mode": report["mode"], "coverage": report["coverage"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
