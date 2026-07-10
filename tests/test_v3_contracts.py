import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"
DOC = ROOT / "docs/v3/architecture.md"


def load_schema(name):
    return json.loads((SCHEMAS / name).read_text())


class V3ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.event = load_schema("v3_event.schema.json")
        cls.output = load_schema("v3_lane_output.schema.json")
        cls.feedback = load_schema("v3_feedback.schema.json")
        for schema in (cls.event, cls.output, cls.feedback):
            Draft202012Validator.check_schema(schema)

    def valid_event(self, **overrides):
        event = {
            "schema_version": "subc-v3-event/1",
            "event_id": "evt_0123456789abcdef",
            "event_type": "repeated_work",
            "lane": "reflex",
            "source": {
                "source_class": "session_projection",
                "source_ref_hash": "sha256:" + "a" * 64,
                "observed_at": "2026-07-10T10:00:00Z",
                "authority": "projection",
                "privacy_class": "yellow",
            },
            "evidence": [{
                "fingerprint": "sha256:" + "b" * 64,
                "kind": "redacted_summary",
                "safe_summary": "Repeated operator correction detected",
            }],
            "raw_content_included": False,
            "model_egress": "local_redacted_only",
        }
        event.update(overrides)
        return event

    def test_health_signal_is_guardian_only(self):
        event = self.valid_event(event_type="service_health", lane="guardian")
        Draft202012Validator(self.event).validate(event)
        event["lane"] = "scout"
        with self.assertRaises(ValidationError):
            Draft202012Validator(self.event).validate(event)

    def test_raw_content_and_unknown_classification_fail_closed(self):
        event = self.valid_event(raw_content_included=True)
        with self.assertRaises(ValidationError):
            Draft202012Validator(self.event).validate(event)
        event = self.valid_event()
        del event["source"]["privacy_class"]
        with self.assertRaises(ValidationError):
            Draft202012Validator(self.event).validate(event)

    def test_lane_outputs_are_disjoint(self):
        validator = Draft202012Validator(self.output)
        outputs = [
            {
                "schema_version": "subc-v3-lane-output/1",
                "output_type": "reflex_candidate",
                "reflex_id": "rfx_0123456789abcdef",
                "candidate_kind": "eval",
                "evidence_fingerprints": ["sha256:" + "a" * 64],
                "safe_summary": "Regression fixture candidate",
                "writes_canonical_memory": False,
            },
            {
                "schema_version": "subc-v3-lane-output/1",
                "output_type": "scout_proposal",
                "proposal_instance_id": "prp_0123456789abcdef",
                "problem_fingerprint": "sha256:" + "b" * 64,
                "domain": "human20",
                "title": "Reduce repeated lesson publishing work",
                "why_now": "Two independent redacted events within the audit window",
                "expected_value": "Save operator time and reduce missed steps",
                "effort": "small",
                "risk": "low",
                "confidence": 0.85,
                "cheap_test": "Replay the last three redacted publishing outcomes locally",
                "evidence": [{"fingerprint": "sha256:" + "c" * 64, "safe_ref": "event:evt_example"}],
                "writes_canonical_memory": False,
            },
            {
                "schema_version": "subc-v3-lane-output/1",
                "output_type": "guardian_incident",
                "incident_id": "grd_0123456789abcdef",
                "severity": "warning",
                "component": "scheduler",
                "safe_summary": "Scheduled job delivery failed",
                "evidence_fingerprints": ["sha256:" + "d" * 64],
                "writes_canonical_memory": False,
            },
        ]
        for output in outputs:
            validator.validate(output)
        broken = dict(outputs[1])
        del broken["cheap_test"]
        with self.assertRaises(ValidationError):
            validator.validate(broken)

    def test_feedback_is_candidate_only_and_auditable(self):
        feedback = {
            "schema_version": "subc-v3-feedback/1",
            "feedback_id": "fbk_0123456789abcdef",
            "proposal_instance_id": "prp_0123456789abcdef",
            "action": "promote",
            "recorded_at": "2026-07-10T10:10:00Z",
            "actor_ref_hash": "sha256:" + "e" * 64,
            "creates_promotion_request": True,
            "writes_canonical_memory": False,
        }
        Draft202012Validator(self.feedback).validate(feedback)
        feedback["writes_canonical_memory"] = True
        with self.assertRaises(ValidationError):
            Draft202012Validator(self.feedback).validate(feedback)

    def test_architecture_documents_ownership_and_egress(self):
        text = DOC.read_text().lower()
        for phrase in (
            "reflexes owns",
            "subconscious scout owns",
            "guardian owns",
            "static health",
            "raw private content",
            "model egress",
            "no production runner",
            "mem0g",
        ):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
