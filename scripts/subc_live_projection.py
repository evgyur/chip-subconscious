#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import yaml

from subc_context_pack import _atomic_json
from subc_reflexes import classify_complaint

COMPACTION_MARKERS = (
    "[CONTEXT COMPACTION",
    "[IMPORTANT: The user has invoked",
    "<system-reminder>",
)
SYSTEM_INJECTION_MARKERS = (
    "[Continuing toward your standing goal]",
    "You've reached the maximum number of tool-calling iterations",
    "[The user sent an image~",
)
ONE_SHOT_PATTERN = re.compile(
    r"^(?:\[Evgeny \"Chip\"\]\s*)?(?:слушай[,]?\s*)?(?:stop\b|удали\b|почисти git\b|сделай git\b|найди\b)",
    re.IGNORECASE,
)
SCOUT_SIGNAL_PATTERN = re.compile(
    r"период|регуляр|кажд|автомат|повтор|снова|постоян|заранее|на будущее|fresh|stale|выборк|обнов|монитор",
    re.IGNORECASE,
)


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _redact(text: str) -> str:
    value = " ".join((text or "").split())
    voice = re.match(
        r'^\[The user sent a voice message~ Here\'s what they said: ["“](.*?)["”]\](?:\s*\[Transcript.*)?$',
        value,
        re.IGNORECASE,
    )
    if voice:
        value = voice.group(1)
    substitutions = (
        (r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[email]", re.IGNORECASE),
        (r"https?://\S+", "[url]", 0),
        (r"/home/" + r"[A-Za-z0-9._-]+(?:/\S*)?", "[private-path]", 0),
        (r"-100\d{10,}", "[private-topic]", 0),
        (r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b", "[secret]", 0),
        (r"\b(?:sk|gsk|pplx|gh[pousr])-[A-Za-z0-9_-]{16,}\b", "[secret]", re.IGNORECASE),
        (r"\+?\d[\d\s().-]{9,}\d", "[phone]", 0),
    )
    for pattern, replacement, flags in substitutions:
        value = re.sub(pattern, replacement, value, flags=flags)
    return value[:600]


def _event_type(summary: str) -> tuple[str, str]:
    complaint = classify_complaint(summary)
    if complaint in {"repeated_question", "repeated_manual_work"}:
        return "repeated_work", "reflex"
    if complaint:
        return "correction", "reflex"
    return "memory_signal", "scout"


def project_recent_messages(
    state_db: str | Path,
    config_path: str | Path,
    *,
    since_timestamp: float | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    config = yaml.safe_load(Path(config_path).read_text()) or {}
    try:
        owner_id = str(config["telegram"]["chip_history_recovery"]["chip_user_id"])
    except (KeyError, TypeError) as exc:
        raise ValueError("owner identity is unavailable; live projection fails closed") from exc
    since = float(since_timestamp if since_timestamp is not None else time.time() - 48 * 3600)
    connection = sqlite3.connect(f"file:{Path(state_db)}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT m.id, m.session_id, m.content, m.timestamp
            FROM messages AS m
            JOIN sessions AS s ON s.id = m.session_id
            WHERE s.source = 'telegram'
              AND s.user_id = ?
              AND s.parent_session_id IS NULL
              AND COALESCE(s.archived, 0) = 0
              AND m.role = 'user'
              AND COALESCE(m.active, 1) = 1
              AND COALESCE(m.compacted, 0) = 0
              AND m.timestamp >= ?
            ORDER BY m.timestamp DESC, m.id DESC
            LIMIT ?
            """,
            (owner_id, since, int(limit)),
        ).fetchall()
    finally:
        connection.close()

    events: list[dict[str, Any]] = []
    excluded_compaction = 0
    excluded_system = 0
    excluded_duplicate = 0
    excluded_one_shot = 0
    excluded_no_scout_signal = 0
    excluded_short = 0
    seen_summaries: set[str] = set()
    for row in reversed(rows):
        content = str(row["content"] or "")
        if len(content) > 8000 or any(marker in content for marker in COMPACTION_MARKERS):
            excluded_compaction += 1
            continue
        if any(marker in content for marker in SYSTEM_INJECTION_MARKERS):
            excluded_system += 1
            continue
        lowered = content.casefold()
        if "supergoal" in lowered and ("делай" in lowered or "goal:" in lowered):
            excluded_system += 1
            continue
        summary = _redact(content)
        if ONE_SHOT_PATTERN.search(summary):
            excluded_one_shot += 1
            continue
        if len(summary) < 20 or summary.startswith("/"):
            excluded_short += 1
            continue
        dedupe_key = summary.casefold()
        if dedupe_key in seen_summaries:
            excluded_duplicate += 1
            continue
        seen_summaries.add(dedupe_key)
        event_type, lane = _event_type(summary)
        if lane == "scout" and not SCOUT_SIGNAL_PATTERN.search(summary):
            excluded_no_scout_signal += 1
            continue
        evidence_fingerprint = _sha(f"{row['session_id']}|{row['id']}|{content}")
        event_id = "evt_" + hashlib.sha256(evidence_fingerprint.encode()).hexdigest()[:24]
        events.append({
            "schema_version": "subc-v3-event/1",
            "event_id": event_id,
            "event_type": event_type,
            "lane": lane,
            "source": {
                "source_class": "session_projection",
                "source_ref_hash": _sha(str(row["session_id"])),
                "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(row["timestamp"]))),
                "authority": "operator",
                "privacy_class": "yellow",
            },
            "evidence": [{
                "fingerprint": evidence_fingerprint,
                "kind": "redacted_summary",
                "safe_summary": summary,
            }],
            "raw_content_included": False,
            "model_egress": "approved_governed_api" if lane == "scout" else "disabled",
        })

    return {
        "schema_version": "subc-v3-context-pack/1",
        "owner_identity_hash": _sha(owner_id),
        "coverage": {
            "queried_owner_messages": len(rows),
            "eligible": len(events),
            "excluded_compaction": excluded_compaction,
            "excluded_system_injection": excluded_system,
            "excluded_duplicate": excluded_duplicate,
            "excluded_one_shot_command": excluded_one_shot,
            "excluded_no_scout_signal": excluded_no_scout_signal,
            "excluded_short_or_command": excluded_short,
            "source_status": "available",
        },
        "events": events,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an identity-scoped redacted live projection")
    home = Path.home()
    parser.add_argument("--state-db", default=str(home / ".hermes/state.db"))
    parser.add_argument("--config", default=str(home / ".hermes/config.yaml"))
    parser.add_argument("--since-hours", type=float, default=48)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    context = project_recent_messages(
        args.state_db,
        args.config,
        since_timestamp=time.time() - args.since_hours * 3600,
        limit=args.limit,
    )
    _atomic_json(Path(args.output), context)
    print(json.dumps({"eligible": context["coverage"]["eligible"], "source_status": "available"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
