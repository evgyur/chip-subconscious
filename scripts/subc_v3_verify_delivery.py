#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from subc_validate_rollout_manifest import _manifest_json


def verify_delivery_receipt(receipt_path: str | Path, manifest_path: str | Path) -> list[str]:
    receipt_text = Path(receipt_path).read_text()
    receipt = json.loads(receipt_text)
    manifest = _manifest_json(Path(manifest_path))
    replacement = manifest["replacement"]
    errors: list[str] = []
    if receipt.get("schema_version") != "subc-v3-rollout-receipt/1":
        errors.append("receipt_schema_invalid")
    if receipt.get("target_alias") != replacement.get("delivery_target_alias"):
        errors.append("target_alias_mismatch")
    if receipt.get("target_sha256") != replacement.get("delivery_target_sha256"):
        errors.append("target_hash_mismatch")
    if receipt.get("sender_transport") != "hermes-bot":
        errors.append("sender_transport_invalid")
    if not isinstance(receipt.get("test_message_id"), int) or receipt.get("test_message_id", 0) <= 0:
        errors.append("test_message_id_invalid")
    if receipt.get("fetched_back") is not True:
        errors.append("delivery_not_fetched_back")
    if not str(receipt.get("content_sha256", "")).startswith("sha256:"):
        errors.append("content_hash_missing")
    second = receipt.get("second_cycle", {})
    if second.get("status") != "ok" or second.get("telegram_delivery_count") != 0:
        errors.append("second_cycle_not_silent")
    rollback = receipt.get("rollback_drill", {})
    if not all(rollback.get(key) is True for key in ("old_resumed", "new_paused", "restored_to_v3_steady")):
        errors.append("rollback_drill_incomplete")
    if "-100" in receipt_text or "telegram:" in receipt_text:
        errors.append("raw_private_target_present")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify SUBCONSCIOUS v3 Telegram readback receipt")
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--manifest", default="reports/v3/rollout-manifest.md")
    args = parser.parse_args()
    errors = verify_delivery_receipt(args.receipt, args.manifest)
    print(json.dumps({"valid": not errors, "errors": errors}, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
