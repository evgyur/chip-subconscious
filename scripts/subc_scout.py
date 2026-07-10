#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from subc_context_pack import _atomic_json
from subc_privacy_scan import PATTERNS

ROOT = Path(__file__).resolve().parents[1]
EVALUATION_SCHEMA = json.loads((ROOT / "schemas/v3_scout_evaluation.schema.json").read_text())
OUTPUT_SCHEMA = json.loads((ROOT / "schemas/v3_lane_output.schema.json").read_text())


def load_fixture(path: str | Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fixture = Path(path)
    return (
        json.loads((fixture / "context_pack.json").read_text()),
        json.loads((fixture / "model_output.json").read_text()),
        json.loads((fixture / "config.json").read_text()),
    )


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _privacy_unsafe(value: Any) -> bool:
    return any(pattern.search(text) for text in _strings(value) for _, pattern in PATTERNS)


def _prefilter(context_pack: dict[str, Any], config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    max_events = int(config["max_input_events"])
    max_chars = int(config["max_context_chars"])
    max_tokens = int(config["max_prompt_tokens"])
    eligible = []
    excluded_by_lane = 0
    excluded_by_policy = 0
    truncated = 0
    used_chars = 0

    events = sorted(
        context_pack.get("events", []),
        key=lambda event: (event.get("source", {}).get("observed_at", ""), event.get("event_id", "")),
    )
    for event in events:
        if event.get("lane") != "scout":
            excluded_by_lane += 1
            continue
        if event.get("raw_content_included") is not False:
            excluded_by_policy += 1
            continue
        if event.get("source", {}).get("privacy_class") not in {"green", "yellow"}:
            excluded_by_policy += 1
            continue
        summaries = [item.get("safe_summary", "") for item in event.get("evidence", [])]
        compact = event.get("event_id", "") + " " + " ".join(summaries)
        projected_chars = used_chars + len(compact)
        projected_tokens = math.ceil(projected_chars / 4)
        if len(eligible) >= max_events or projected_chars > max_chars or projected_tokens > max_tokens:
            truncated += 1
            continue
        eligible.append(event)
        used_chars = projected_chars

    return eligible, {
        "input_event_count": len(events),
        "eligible_event_count": len(eligible),
        "excluded_by_lane_count": excluded_by_lane,
        "excluded_by_policy_count": excluded_by_policy,
        "truncated_count": truncated,
        "context_chars": used_chars,
        "estimated_prompt_tokens": math.ceil(used_chars / 4),
        "max_prompt_tokens": max_tokens,
        "max_context_chars": max_chars,
        "max_input_events": max_events,
        "timeout_ms": int(config["timeout_ms"]),
        "max_proposals": int(config["max_proposals"]),
        "min_confidence": float(config["min_confidence"]),
    }


def _result(status: str, provider: str, prefilter: dict[str, Any], elapsed_ms: int, *, reason: str = "", proposals=None):
    selected = proposals or []
    return {
        "schema_version": "subc-v3-scout-run/1",
        "status": status,
        "provider": provider,
        "prefilter": prefilter,
        "elapsed_ms": elapsed_ms,
        "proposal_count": len(selected),
        "proposals": selected,
        "block_reason": reason,
        "delivery_count": 0,
        "canonical_memory_writes": 0,
    }


def run_scout(
    context_pack: dict[str, Any],
    model_output: dict[str, Any] | str,
    config: dict[str, Any],
    *,
    elapsed_ms: int,
) -> dict[str, Any]:
    provider = str(config.get("provider", ""))
    try:
        if config.get("schema_version") != "subc-v3-scout-config/1":
            raise ValueError("config_schema")
        if provider != "hermes-approved-route" or config.get("route") != "current-approved":
            raise ValueError("provider_route")
        if any(key in config for key in ("api_key", "token", "secret", "base_url")):
            raise ValueError("secret_or_provider_definition")
        if int(config["max_proposals"]) != 3:
            raise ValueError("proposal_cap")
        eligible, prefilter = _prefilter(context_pack, config)
    except (KeyError, TypeError, ValueError) as error:
        return _result("blocked", provider, {}, elapsed_ms, reason=f"invalid_config:{error}")

    if elapsed_ms > int(config["timeout_ms"]):
        return _result("blocked", provider, prefilter, elapsed_ms, reason="model_timeout")
    if not eligible:
        return _result("empty", provider, prefilter, elapsed_ms, reason="no_eligible_context")

    try:
        response = json.loads(model_output) if isinstance(model_output, str) else model_output
        Draft202012Validator(EVALUATION_SCHEMA).validate(response)
    except (json.JSONDecodeError, ValidationError, TypeError) as error:
        return _result("blocked", provider, prefilter, elapsed_ms, reason=f"malformed_model_output:{type(error).__name__}")

    if response["status"] == "empty":
        return _result("empty", provider, prefilter, elapsed_ms)
    if response["status"] != "ok":
        return _result("blocked", provider, prefilter, elapsed_ms, reason=f"model_status:{response['status']}")

    event_by_id = {event["event_id"]: event for event in eligible}
    selected = []
    problem_fingerprints = set()
    try:
        for item in response["proposals"]:
            event_ids = item["evidence_event_ids"]
            if any(event_id not in event_by_id for event_id in event_ids):
                raise ValueError("unknown_or_ineligible_evidence")
            if len(event_ids) < 2:
                allowed = bool(config.get("allow_single_source_exception"))
                reason = item.get("exception_reason", "")
                if not item.get("single_source_exception") or not allowed or len(reason) < 20:
                    raise ValueError("weak_single_source_evidence")
            proposal = item["proposal"]
            Draft202012Validator(OUTPUT_SCHEMA).validate(proposal)
            if proposal["output_type"] != "scout_proposal":
                raise ValueError("wrong_output_lane")
            if float(proposal["confidence"]) < float(config["min_confidence"]):
                raise ValueError("low_confidence")
            if _privacy_unsafe(proposal):
                raise ValueError("privacy_unsafe")
            expected_fingerprints = {
                evidence["fingerprint"]
                for event_id in event_ids
                for evidence in event_by_id[event_id].get("evidence", [])
            }
            actual_fingerprints = {evidence["fingerprint"] for evidence in proposal["evidence"]}
            actual_refs = {evidence["safe_ref"] for evidence in proposal["evidence"]}
            expected_refs = {f"event:{event_id}" for event_id in event_ids}
            if expected_fingerprints != actual_fingerprints or expected_refs != actual_refs:
                raise ValueError("evidence_mismatch")
            problem = proposal["problem_fingerprint"]
            if problem in problem_fingerprints:
                raise ValueError("duplicate_problem")
            problem_fingerprints.add(problem)
            selected.append(proposal)
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        return _result("blocked", provider, prefilter, elapsed_ms, reason=f"evaluator_gate:{error}")

    if not selected:
        return _result("empty", provider, prefilter, elapsed_ms)
    return _result("selected", provider, prefilter, elapsed_ms, proposals=selected)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate bounded semantic Scout output")
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    context, model_output, config = load_fixture(args.fixture)
    result = run_scout(context, model_output, config, elapsed_ms=0)
    _atomic_json(Path(args.output), result)
    print(json.dumps({"status": result["status"], "proposal_count": result["proposal_count"], "delivery_count": 0}, sort_keys=True))
    return 0 if result["status"] in {"selected", "empty"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
