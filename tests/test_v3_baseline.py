import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


class V3BaselineTests(unittest.TestCase):
    def test_baseline_report_freezes_audit_and_source_boundary(self):
        report = json.loads((ROOT / "reports/v3/phase-1-baseline.json").read_text())
        self.assertEqual(report["schema_version"], "subc-v3-baseline/1")
        self.assertEqual(
            report["public_baseline"]["sha"],
            "4bc52a2e23c46b5dd660eb2a13c3ee0c244d58d4",
        )
        self.assertFalse(report["live_boundary"]["is_git"])
        self.assertEqual(report["audit_window"], ["2026-06-10", "2026-07-10"])
        self.assertEqual(report["audit_metrics"]["walk_reports"], 92)
        self.assertEqual(report["audit_metrics"]["empty_walk_reports"], 86)
        self.assertEqual(report["audit_metrics"]["observations"], 3472)
        self.assertEqual(report["audit_metrics"]["unique_evidence"], 51)
        self.assertEqual(report["audit_metrics"]["proactive_domain_recommendations"], 0)
        self.assertGreater(report["source_drift"]["live_only_count"], 0)
        self.assertNotIn("chat_id", json.dumps(report).lower())

    def test_privacy_scanner_detects_secret_private_id_and_home_path(self):
        from subc_privacy_scan import scan_path

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "bad.txt").write_text(
                "token=sk-" + "x" * 24 + "\n"
                "telegram=-100" + "1234567890" + "\n"
                "path=/home/" + "hermes/private-room\n"
            )
            findings = scan_path(root)
        kinds = {item["kind"] for item in findings}
        self.assertEqual(kinds, {"absolute_private_path", "private_id", "secret"})

    def test_public_checkout_passes_privacy_scan(self):
        from subc_privacy_scan import scan_path

        self.assertEqual(scan_path(ROOT, excludes={".git", ".supergoal"}), [])


if __name__ == "__main__":
    unittest.main()
