#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from subc_context_pack import _atomic_json
from subc_guardian import evaluate_fixture
from subc_privacy_scan import scan_path
from subc_reflexes import ReflexEngine, classify_complaint, load_events
from subc_scout import run_scout


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _corpus_fingerprint(corpus: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in corpus.rglob("*") if item.is_file()):
        digest.update(path.relative_to(corpus).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def run_backtest(corpus_path: str | Path) -> dict[str, Any]:
    corpus = Path(corpus_path)
    manifest = _load(corpus / "manifest.json")
    thresholds = manifest["thresholds"]
    findings = scan_path(corpus)
    base_report = {
        "schema_version": "subc-v3-backtest-report/1",
        "goal_id": manifest["goal_id"],
        "window": manifest["window"],
        "corpus_fingerprint": _corpus_fingerprint(corpus),
        "privacy_scan_pass": not findings,
        "privacy_finding_count": len(findings),
        "thresholds": thresholds,
        "v2": manifest["v2_frozen_baseline"],
    }
    if findings:
        return {
            **base_report,
            "v3": {},
            "separation": {},
            "failed_gates": ["privacy_scan"],
            "rollout_gate_pass": False,
        }

    rubric = _load(corpus / "rubric.json")
    reactive_events = load_events(corpus / "reactive_events.jsonl")
    guardian_snapshots = [
        json.loads(line)
        for line in (corpus / "guardian_snapshots.jsonl").read_text().splitlines()
        if line.strip()
    ]
    context_pack = _load(corpus / "context_pack.json")
    scout_model_output = _load(corpus / "scout_model_output.json")
    scout_config = _load(corpus / "scout_config.json")

    start = manifest["window"]["start"]
    end = manifest["window"]["end"]
    observed_times = [event["source"]["observed_at"] for event in reactive_events]
    observed_times += [snapshot["observed_at"] for snapshot in guardian_snapshots]
    observed_times += [event["source"]["observed_at"] for event in context_pack["events"]]
    window_integrity = all(start <= timestamp <= end for timestamp in observed_times)

    engine = ReflexEngine()
    reflex_result = engine.process(reactive_events)
    reflex_state = engine.state
    evidence_occurrences = Counter(
        fingerprint
        for instance in reflex_state.get("instances", {}).values()
        for fingerprint in instance.get("evidence_fingerprints", [])
    )
    evidence_score_inflation = sum(max(0, count - 1) for count in evidence_occurrences.values())

    event_by_id = {event["event_id"]: event for event in reactive_events}
    recall_counts = Counter()
    recovered_counts = Counter()
    for label in rubric["reactive_labels"]:
        kind = label["label_kind"]
        if kind == "duplicate_evidence":
            continue
        recall_counts[kind] += 1
        event = event_by_id[label["event_id"]]
        summary = event["evidence"][0]["safe_summary"]
        if classify_complaint(summary) == label["expected_class"]:
            recovered_counts[kind] += 1

    guardian_result = evaluate_fixture(corpus / "guardian_snapshots.jsonl", dry_run=True)
    scout_result = run_scout(context_pack, scout_model_output, scout_config, elapsed_ms=0)
    proposals = scout_result["proposals"] if scout_result["status"] == "selected" else []
    problem_counts = Counter(proposal["problem_fingerprint"] for proposal in proposals)
    duplicate_proposals = sum(max(0, count - 1) for count in problem_counts.values())
    duplicate_rate = _rate(duplicate_proposals, len(proposals))

    proposal_labels = {item["problem_fingerprint"]: item for item in rubric["proposal_labels"]}
    useful_approvable = 0
    domain_proposals = 0
    for proposal in proposals:
        label = proposal_labels.get(proposal["problem_fingerprint"])
        if proposal["domain"] in {"human20", "business", "product", "personal_ops", "team_ops", "travel", "finance", "health", "other_domain"}:
            domain_proposals += 1
        if label and label["useful"] and label["approvable"] and proposal["domain"] == label["expected_domain"]:
            useful_approvable += 1

    complaint_recall = _rate(recovered_counts["complaint"], recall_counts["complaint"])
    repeated_work_recall = _rate(recovered_counts["repeated_work"], recall_counts["repeated_work"])
    useful_rate = _rate(useful_approvable, len(proposals))
    scout_health_inputs = sum(
        1
        for event in context_pack["events"]
        if event.get("lane") == "scout" and event.get("event_type") in {"service_health", "config_health", "cron_health"}
    )

    metrics = {
        "reactive_label_count": sum(recall_counts.values()),
        "identical_evidence_replay_count": reflex_result["duplicate_count"],
        "identical_evidence_score_inflation": evidence_score_inflation,
        "complaint_recall": complaint_recall,
        "repeated_work_recall": repeated_work_recall,
        "visible_proposal_count": len(proposals),
        "duplicate_visible_output_rate": duplicate_rate,
        "useful_approvable_count": useful_approvable,
        "useful_approvable_rate": useful_rate,
        "proactive_domain_proposals": domain_proposals,
        "guardian_state_changes": guardian_result["change_count"],
        "telegram_deliveries": 0,
        "canonical_memory_writes": 0,
    }
    failed = []
    if not window_integrity:
        failed.append("window_integrity")
    if evidence_score_inflation > thresholds["max_identical_evidence_score_inflation"]:
        failed.append("identical_evidence_score_inflation")
    if duplicate_rate >= thresholds["max_duplicate_visible_output_rate"]:
        failed.append("duplicate_visible_output_rate")
    if complaint_recall < thresholds["min_complaint_recall"]:
        failed.append("complaint_recall")
    if repeated_work_recall < thresholds["min_repeated_work_recall"]:
        failed.append("repeated_work_recall")
    if useful_rate < thresholds["min_useful_approvable_rate"]:
        failed.append("useful_approvable_rate")
    if domain_proposals < thresholds["min_proactive_domain_proposals"]:
        failed.append("proactive_domain_proposals")
    if guardian_result["change_count"] != rubric["guardian_expected_changes"]:
        failed.append("guardian_state_changes")
    if scout_health_inputs:
        failed.append("scout_static_health_inputs")
    if scout_result["status"] not in {"selected", "empty"}:
        failed.append("scout_evaluator")

    return {
        **base_report,
        "corpus_label_counts": {
            "complaints": recall_counts["complaint"],
            "repeated_work": recall_counts["repeated_work"],
            "duplicate_evidence": sum(1 for item in rubric["reactive_labels"] if item["label_kind"] == "duplicate_evidence"),
            "guardian_snapshots": len(guardian_snapshots),
            "scout_context_events": len(context_pack["events"]),
        },
        "v3": metrics,
        "separation": {
            "scout_static_health_inputs": scout_health_inputs,
            "guardian_visible_proposals": 0,
            "reflex_telegram_deliveries": reflex_result["delivery_count"],
        },
        "failed_gates": failed,
        "rollout_gate_pass": not failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run privacy-safe SUBCONSCIOUS v3 historical backtest")
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = run_backtest(args.corpus)
    _atomic_json(Path(args.out), report)
    print(json.dumps({"rollout_gate_pass": report["rollout_gate_pass"], "failed_gates": report["failed_gates"]}, sort_keys=True))
    return 0 if report["rollout_gate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
