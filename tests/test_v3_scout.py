import copy
import json
import tempfile
import unittest
from pathlib import Path
import sys

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from subc_scout import load_fixture, run_scout

FIXTURE = ROOT / "tests/fixtures/v3_scout"
OUTPUT_SCHEMA = json.loads((ROOT / "schemas/v3_lane_output.schema.json").read_text())


class V3ScoutTests(unittest.TestCase):
    def setUp(self):
        self.context, self.model_output, self.config = load_fixture(FIXTURE)

    def test_good_evaluation_joins_sources_and_is_bounded(self):
        result = run_scout(self.context, self.model_output, self.config, elapsed_ms=20)
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["proposal_count"], 2)
        self.assertLessEqual(result["proposal_count"], 3)
        self.assertEqual(result["delivery_count"], 0)
        self.assertEqual(result["provider"], "hermes-approved-route")
        self.assertEqual(result["prefilter"]["eligible_event_count"], 4)
        self.assertEqual(result["prefilter"]["excluded_by_lane_count"], 1)
        for proposal in result["proposals"]:
            Draft202012Validator(OUTPUT_SCHEMA).validate(proposal)
            self.assertGreaterEqual(proposal["confidence"], 0.7)

    def test_malformed_timeout_low_confidence_and_privacy_unsafe_fail_closed(self):
        cases = []
        cases.append(("{not-json", 10))
        cases.append((self.model_output, self.config["timeout_ms"] + 1))
        low = copy.deepcopy(self.model_output)
        low["proposals"][0]["proposal"]["confidence"] = 0.2
        cases.append((low, 10))
        unsafe = copy.deepcopy(self.model_output)
        unsafe["proposals"][0]["proposal"]["title"] = "Leak /home/" + "hermes/private"
        cases.append((unsafe, 10))
        for model_output, elapsed in cases:
            result = run_scout(self.context, model_output, self.config, elapsed_ms=elapsed)
            self.assertEqual(result["proposal_count"], 0)
            self.assertEqual(result["delivery_count"], 0)
            self.assertEqual(result["status"], "blocked")

    def test_unknown_or_guardian_evidence_fails_closed(self):
        bad = copy.deepcopy(self.model_output)
        bad["proposals"][0]["evidence_event_ids"] = ["evt_1111111111111111", "evt_5555555555555555"]
        result = run_scout(self.context, bad, self.config, elapsed_ms=10)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["proposal_count"], 0)

        wrong_ref = copy.deepcopy(self.model_output)
        wrong_ref["proposals"][0]["proposal"]["evidence"][0]["safe_ref"] = "event:evt_9999999999999999"
        result = run_scout(self.context, wrong_ref, self.config, elapsed_ms=10)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["proposal_count"], 0)

    def test_single_source_requires_exception_reason(self):
        one = copy.deepcopy(self.model_output)
        one["proposals"] = [one["proposals"][0]]
        one["proposals"][0]["evidence_event_ids"] = ["evt_1111111111111111"]
        one["proposals"][0]["proposal"]["evidence"] = [one["proposals"][0]["proposal"]["evidence"][0]]
        result = run_scout(self.context, one, self.config, elapsed_ms=10)
        self.assertEqual(result["status"], "blocked")
        one["proposals"][0]["single_source_exception"] = True
        one["proposals"][0]["exception_reason"] = "One canonical project state contains an explicit measured bottleneck"
        result = run_scout(self.context, one, self.config, elapsed_ms=10)
        self.assertEqual(result["status"], "selected")
        self.assertEqual(result["proposal_count"], 1)

    def test_empty_high_quality_result_stays_silent(self):
        empty = {"schema_version": "subc-v3-scout-evaluation/1", "status": "empty", "proposals": []}
        result = run_scout(self.context, empty, self.config, elapsed_ms=10)
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["proposal_count"], 0)
        self.assertEqual(result["delivery_count"], 0)

    def test_more_than_three_is_rejected_not_truncated(self):
        over = copy.deepcopy(self.model_output)
        over["proposals"] = [copy.deepcopy(over["proposals"][0]) for _ in range(4)]
        for index, item in enumerate(over["proposals"]):
            item["proposal"]["proposal_instance_id"] = f"prp_{index + 1:016x}"
            item["proposal"]["problem_fingerprint"] = "sha256:" + f"{index + 1:064x}"
        result = run_scout(self.context, over, self.config, elapsed_ms=10)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["proposal_count"], 0)

    def test_fixture_config_contains_no_secret_or_new_provider_definition(self):
        serialized = json.dumps(self.config).lower()
        self.assertNotIn("api_key", serialized)
        self.assertNotIn("base_url", serialized)
        self.assertEqual(self.config["provider"], "hermes-approved-route")


if __name__ == "__main__":
    unittest.main()
