import json
import shutil
import tempfile
import unittest
from pathlib import Path
import sys

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from subc_context_pack import CursorStore, build_context_pack

FIXTURE = ROOT / "tests/fixtures/v3_ingestion"


class V3IngestionTests(unittest.TestCase):
    def test_dry_run_is_identity_scoped_redacted_and_complete(self):
        report = build_context_pack(FIXTURE, dry_run=True)
        coverage = report["coverage"]
        self.assertEqual(coverage["scanned_count"], 11)
        self.assertEqual(coverage["eligible_count"], 6)
        self.assertEqual(coverage["rejected_count"], 5)
        self.assertEqual(
            coverage["rejected_reasons"],
            {"duplicate_evidence": 1, "origin_denied": 3, "wrong_identity": 1},
        )
        self.assertEqual(coverage["time_range"], ["2026-06-10T09:00:00Z", "2026-07-01T17:05:00Z"])
        self.assertEqual({event["lane"] for event in report["events"]}, {"reflex", "scout", "guardian"})
        event_schema = json.loads((ROOT / "schemas/v3_event.schema.json").read_text())
        for event in report["events"]:
            Draft202012Validator(event_schema).validate(event)
        serialized = json.dumps(report).lower()
        self.assertNotIn("message_body", serialized)
        self.assertNotIn('"content"', serialized)
        self.assertTrue(all(event["raw_content_included"] is False for event in report["events"]))
        self.assertFalse((FIXTURE / "cursor.json").exists())
        unavailable = report["sources"]["project_archive"]
        self.assertEqual(unavailable["status"], "unavailable")

    def test_cursor_prevents_rescan_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = Path(td) / "fixture"
            shutil.copytree(FIXTURE, fixture)
            cursor_path = fixture / "cursor.json"
            first = build_context_pack(fixture, cursor_path=cursor_path, dry_run=False)
            self.assertEqual(first["coverage"]["eligible_count"], 6)
            self.assertTrue(cursor_path.exists())
            second = build_context_pack(fixture, cursor_path=cursor_path, dry_run=False)
            self.assertEqual(second["coverage"]["eligible_count"], 0)
            self.assertEqual(second["coverage"]["rejected_reasons"], {"already_seen": 11})
            reloaded = CursorStore(cursor_path).load()
            self.assertEqual(reloaded["watermarks"]["hermes_sessions"], 11)

    def test_legacy_cursor_migration_keeps_backup(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cursor.json"
            path.write_text(json.dumps({"hermes_sessions": 7, "commitments": 3}))
            store = CursorStore(path)
            state = store.load()
            self.assertEqual(state["schema_version"], "subc-v3-cursor/1")
            self.assertEqual(state["watermarks"]["hermes_sessions"], 7)
            store.save(state)
            self.assertTrue(path.with_suffix(".json.bak").exists())
            self.assertEqual(json.loads(path.with_suffix(".json.bak").read_text())["hermes_sessions"], 7)

    def test_record_with_unconfigured_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = Path(td)
            shutil.copy(FIXTURE / "source_registry.json", fixture / "source_registry.json")
            record = {
                "sequence": 1,
                "source_id": "unknown",
                "identity_hash": "sha256:" + "1" * 64,
                "origin_kind": "user_event",
                "observed_at": "2026-07-01T00:00:00Z",
                "event_type": "correction",
                "source_ref_hash": "sha256:" + "2" * 64,
                "evidence_fingerprint": "sha256:" + "3" * 64,
                "safe_summary": "Unknown source",
            }
            (fixture / "records.jsonl").write_text(json.dumps(record) + "\n")
            report = build_context_pack(fixture, dry_run=True)
            self.assertEqual(report["coverage"]["rejected_reasons"], {"source_unconfigured": 1})


if __name__ == "__main__":
    unittest.main()
