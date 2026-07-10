import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from subc_delivery_gate import apply_delivery_gate, record_feedback

SCOUT_REPORT = {
    "schema_version": "subc-v3-scout-run/1",
    "status": "selected",
    "proposals": [
        {"proposal_instance_id": f"prp_{index:024x}", "problem_fingerprint": "sha256:" + str(index) * 64}
        for index in range(1, 5)
    ],
}


class V3DeliveryGateTests(unittest.TestCase):
    def test_weekly_budget_is_hard_and_duplicates_are_suppressed(self):
        now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        state = {"schema_version": "subc-v3-delivery-state/1", "deliveries": [], "feedback": []}
        first = apply_delivery_gate(SCOUT_REPORT, state, now=now, max_per_week=3)
        self.assertEqual(len(first["allowed_proposals"]), 3)
        self.assertEqual(first["blocked_by_budget"], 1)
        second = apply_delivery_gate(SCOUT_REPORT, first["next_state"], now=now, max_per_week=3)
        self.assertEqual(second["allowed_proposals"], [])
        self.assertEqual(second["blocked_as_duplicate"], 3)
        self.assertEqual(second["blocked_by_budget"], 1)

    def test_dry_run_does_not_write_and_commit_is_atomic_state(self):
        now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "delivery.json"
            state = {"schema_version": "subc-v3-delivery-state/1", "deliveries": [], "feedback": []}
            result = apply_delivery_gate({**SCOUT_REPORT, "proposals": SCOUT_REPORT["proposals"][:1]}, state, now=now)
            self.assertFalse(state_path.exists())
            from subc_delivery_gate import save_state
            save_state(state_path, result["next_state"])
            self.assertTrue(state_path.exists())
            saved = json.loads(state_path.read_text())
            self.assertEqual(len(saved["deliveries"]), 1)

    def test_feedback_is_auditable_and_never_writes_canonical_memory(self):
        state = {"schema_version": "subc-v3-delivery-state/1", "deliveries": [], "feedback": []}
        updated = record_feedback(
            state,
            {"schema_version": "subc-v3-feedback/1", "feedback_id": "fbk_1234567890abcdef", "proposal_instance_id": "prp_000000000000000000000001", "action": "save", "recorded_at": "2026-07-10T12:00:00Z", "actor_ref_hash": "sha256:" + "1" * 64, "creates_promotion_request": False, "writes_canonical_memory": False},
        )
        self.assertEqual(len(updated["feedback"]), 1)
        self.assertFalse(updated["feedback"][0]["writes_canonical_memory"])


if __name__ == "__main__":
    unittest.main()
