import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from subc_v3_backtest import run_backtest

CORPUS = ROOT / "evals/v3"


class V3BacktestTests(unittest.TestCase):
    def test_frozen_window_passes_all_product_gates(self):
        report = run_backtest(CORPUS)
        self.assertTrue(report["rollout_gate_pass"])
        self.assertEqual(report["window"]["start"], "2026-06-10T00:00:00Z")
        metrics = report["v3"]
        self.assertEqual(metrics["identical_evidence_replay_count"], 1)
        self.assertEqual(metrics["identical_evidence_score_inflation"], 0)
        self.assertLess(metrics["duplicate_visible_output_rate"], 0.2)
        self.assertEqual(metrics["complaint_recall"], 1.0)
        self.assertEqual(metrics["repeated_work_recall"], 1.0)
        self.assertGreaterEqual(metrics["useful_approvable_rate"], 0.5)
        self.assertGreaterEqual(metrics["proactive_domain_proposals"], 1)
        self.assertEqual(metrics["guardian_state_changes"], 2)
        self.assertEqual(metrics["telegram_deliveries"], 0)

    def test_v2_fails_duplicate_and_domain_value_gates(self):
        report = run_backtest(CORPUS)
        self.assertFalse(report["v2"]["rollout_gate_pass"])
        self.assertGreaterEqual(report["v2"]["duplicate_visible_output_rate"], 0.2)
        self.assertEqual(report["v2"]["proactive_domain_proposals"], 0)

    def test_usefulness_failure_blocks_rollout_without_weakening_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "corpus"
            shutil.copytree(CORPUS, copied)
            rubric_path = copied / "rubric.json"
            rubric = json.loads(rubric_path.read_text())
            for label in rubric["proposal_labels"]:
                label["useful"] = False
            rubric_path.write_text(json.dumps(rubric))
            report = run_backtest(copied)
            self.assertFalse(report["rollout_gate_pass"])
            self.assertIn("useful_approvable_rate", report["failed_gates"])
            self.assertEqual(report["thresholds"]["min_useful_approvable_rate"], 0.5)

    def test_private_corpus_marker_fails_closed_and_report_does_not_echo_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "corpus"
            shutil.copytree(CORPUS, copied)
            context_path = copied / "context_pack.json"
            context = json.loads(context_path.read_text())
            context["events"][0]["evidence"][0]["safe_summary"] = "/home/" + "hermes/private"
            context_path.write_text(json.dumps(context))
            report = run_backtest(copied)
            self.assertFalse(report["rollout_gate_pass"])
            self.assertIn("privacy_scan", report["failed_gates"])
            serialized = json.dumps(report)
            self.assertNotIn("/home/" + "hermes", serialized)

    def test_report_is_aggregate_and_privacy_safe(self):
        report = run_backtest(CORPUS)
        serialized = json.dumps(report).lower()
        self.assertNotIn("safe_summary", serialized)
        self.assertNotIn("message_body", serialized)
        self.assertNotIn("chat_id", serialized)
        self.assertTrue(report["privacy_scan_pass"])
        self.assertEqual(report["separation"]["scout_static_health_inputs"], 0)
        self.assertEqual(report["separation"]["guardian_visible_proposals"], 0)


if __name__ == "__main__":
    unittest.main()
