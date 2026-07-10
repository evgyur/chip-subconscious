#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from subc_context_pack import _atomic_json

REFLEX_SCHEMA = "subc-v3-reflex-state/1"


def classify_complaint(text: str) -> str | None:
    normalized = " ".join((text or "").lower().split())
    if re.search(r"ничего.{0,24}(?:не найден|не наш)", normalized) or "ни одного предложения" in normalized:
        return "no_results"
    if re.search(r"(?:три|несколько) раз", normalized) and re.search(r"вопрос|спрос|задан", normalized):
        return "repeated_question"
    if re.search(r"ручн", normalized) and re.search(r"снова|несколько раз|повтор", normalized):
        return "repeated_manual_work"
    if re.search(r"reply|репла[йя]", normalized) and re.search(r"не видишь|не читаешь|контекст", normalized):
        return "reply_context_loss"
    if "при чём тут" in normalized or "при чем тут" in normalized:
        return "context_mismatch"
    if re.search(r"сразу\s+внос", normalized):
        return "immediate_recording"
    if "никогда не использовал" in normalized or re.search(r"залез.{0,30}стар", normalized):
        return "wrong_source_assumption"
    if "на будущее" in normalized or re.search(r"чтобы.{0,40}не (?:было|повтор)", normalized):
        return "prevention_request"
    if re.search(r"не приносит ценност|бесполез|туфта", normalized):
        return "no_value"
    if re.search(r"не так|исправ|ошиб", normalized):
        return "explicit_correction"
    return None


def load_events(path: str | Path) -> list[dict[str, Any]]:
    result = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            result.append(json.loads(line))
    return result


class ReflexEngine:
    def __init__(self, state_path: str | Path | None = None):
        self.state_path = Path(state_path) if state_path else None
        if self.state_path and self.state_path.exists():
            self.state = json.loads(self.state_path.read_text())
        else:
            self.state = {"schema_version": REFLEX_SCHEMA, "instances": {}, "seen_fingerprints": []}
        if self.state.get("schema_version") != REFLEX_SCHEMA:
            raise ValueError("unsupported reflex state; fail closed")

    def _save(self) -> None:
        if self.state_path:
            _atomic_json(self.state_path, self.state)

    def process(self, events: list[dict[str, Any]], *, persist: bool = False) -> dict[str, Any]:
        created: list[dict[str, Any]] = []
        enriched = 0
        duplicates = 0
        rejected = 0
        seen = set(self.state["seen_fingerprints"])
        instances = self.state["instances"]

        for event in events:
            if event.get("lane") != "reflex" or event.get("event_type") not in {"correction", "repeated_work"}:
                rejected += 1
                continue
            evidence = event.get("evidence") or []
            if not evidence or not evidence[0].get("fingerprint"):
                rejected += 1
                continue
            fingerprint = evidence[0]["fingerprint"]
            if fingerprint in seen:
                duplicates += 1
                continue
            summary = evidence[0].get("safe_summary", "")
            problem_key = classify_complaint(summary)
            if problem_key is None:
                rejected += 1
                seen.add(fingerprint)
                continue

            open_instance = next(
                (item for item in instances.values() if item["problem_key"] == problem_key and item["status"] == "open"),
                None,
            )
            if open_instance:
                open_instance["evidence_fingerprints"].append(fingerprint)
                open_instance["evidence_count"] = len(open_instance["evidence_fingerprints"])
                open_instance["last_event_id"] = event["event_id"]
                enriched += 1
            else:
                seed = f"{problem_key}|{fingerprint}"
                reflex_id = "rfx_" + hashlib.sha256(seed.encode()).hexdigest()[:24]
                candidate_kind = "workflow" if event["event_type"] == "repeated_work" else "eval"
                instance = {
                    "reflex_id": reflex_id,
                    "problem_key": problem_key,
                    "status": "open",
                    "candidate_kind": candidate_kind,
                    "evidence_fingerprints": [fingerprint],
                    "evidence_count": 1,
                    "last_event_id": event["event_id"],
                }
                instances[reflex_id] = instance
                candidate = {
                    "schema_version": "subc-v3-lane-output/1",
                    "output_type": "reflex_candidate",
                    "reflex_id": reflex_id,
                    "candidate_kind": candidate_kind,
                    "evidence_fingerprints": [fingerprint],
                    "safe_summary": f"Create {candidate_kind} candidate for {problem_key}",
                    "writes_canonical_memory": False,
                }
                created.append(candidate)
            seen.add(fingerprint)

        self.state["seen_fingerprints"] = sorted(seen)
        if persist:
            self._save()
        return {
            "schema_version": "subc-v3-reflex-run/1",
            "created_count": len(created),
            "enriched_count": enriched,
            "duplicate_count": duplicates,
            "rejected_count": rejected,
            "candidates": created,
            "delivery_count": 0,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Process explicit correction events into quiet reflex candidates")
    parser.add_argument("--events", required=True)
    parser.add_argument("--state")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    engine = ReflexEngine(args.state)
    result = engine.process(load_events(args.events), persist=not args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
