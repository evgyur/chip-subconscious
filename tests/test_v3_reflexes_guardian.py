import copy
import json
import tempfile
import unittest
from pathlib import Path
import sys

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from subc_guardian import evaluate_fixture
from subc_reflexes import ReflexEngine, classify_complaint, load_events

REFLEX_FIXTURE = ROOT / "tests/fixtures/v3_reflexes/events.jsonl"
GUARDIAN_FIXTURE = ROOT / "tests/fixtures/v3_guardian"
OUTPUT_SCHEMA = json.loads((ROOT / "schemas/v3_lane_output.schema.json").read_text())


class V3ReflexesGuardianTests(unittest.TestCase):
    def test_complaint_regression_fixture_is_recovered(self):
        expected = {
            "ничего не найдено": "no_results",
            "за месяц ни одного предложения": "no_results",
            "один вопрос задан три раза": "repeated_question",
            "как сделать, чтобы этого не было на будущее": "prevention_request",
            "проект не приносит ценности": "no_value",
            "одна ручная проверка снова выполняется несколько раз": "repeated_manual_work",
            "я reply делаю, ты не видишь": "reply_context_loss",
            "ты снова не читаешь контекст того, на что я reply": "reply_context_loss",
            "при чём тут другой человек": "context_mismatch",
            "сразу вноси такие вещи": "immediate_recording",
            "я никогда не использовал этот сервис, ты залез в старые файлы": "wrong_source_assumption",
        }
        for text, label in expected.items():
            self.assertEqual(classify_complaint(text), label)

    def test_identical_evidence_is_idempotent(self):
        event = load_events(REFLEX_FIXTURE)[0]
        engine = ReflexEngine()
        first = engine.process([event])
        before = copy.deepcopy(engine.state)
        second = engine.process([event])
        self.assertEqual(first["created_count"], 1)
        self.assertEqual(second["created_count"], 0)
        self.assertEqual(second["duplicate_count"], 1)
        self.assertEqual(engine.state, before)

    def test_fresh_correction_enriches_open_or_creates_after_close(self):
        events = load_events(REFLEX_FIXTURE)
        engine = ReflexEngine()
        first = engine.process([events[0]])
        instance_id = first["candidates"][0]["reflex_id"]
        enriched = engine.process([events[1]])
        self.assertEqual(enriched["enriched_count"], 1)
        self.assertEqual(len(engine.state["instances"][instance_id]["evidence_fingerprints"]), 2)
        engine.state["instances"][instance_id]["status"] = "closed"
        fresh = copy.deepcopy(events[1])
        fresh["event_id"] = "evt_ffffffffffffffff"
        fresh["evidence"][0]["fingerprint"] = "sha256:" + "9" * 64
        created = engine.process([fresh])
        self.assertEqual(created["created_count"], 1)
        self.assertNotEqual(created["candidates"][0]["reflex_id"], instance_id)

    def test_reflex_outputs_validate_and_are_quiet_candidates(self):
        engine = ReflexEngine()
        result = engine.process(load_events(REFLEX_FIXTURE))
        self.assertEqual(result["created_count"], 4)
        self.assertEqual(result["enriched_count"], 1)
        self.assertNotIn("telegram", json.dumps(result).lower())
        for candidate in result["candidates"]:
            Draft202012Validator(OUTPUT_SCHEMA).validate(candidate)

    def test_guardian_emits_only_state_changes(self):
        result = evaluate_fixture(GUARDIAN_FIXTURE, dry_run=True)
        self.assertEqual(result["snapshot_count"], 5)
        self.assertEqual(result["change_count"], 2)
        self.assertEqual([item["severity"] for item in result["incidents"]], ["critical", "info"])
        self.assertEqual([item["safe_summary"] for item in result["incidents"]], [
            "Scheduled probe changed to failed",
            "Scheduled probe recovered",
        ])
        for incident in result["incidents"]:
            Draft202012Validator(OUTPUT_SCHEMA).validate(incident)

    def test_guardian_persisted_state_suppresses_heartbeat_across_runs(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "guardian.json"
            first = evaluate_fixture(GUARDIAN_FIXTURE, state_path=state, dry_run=False)
            second = evaluate_fixture(GUARDIAN_FIXTURE, state_path=state, dry_run=False)
            self.assertEqual(first["change_count"], 2)
            self.assertEqual(second["change_count"], 0)


if __name__ == "__main__":
    unittest.main()
