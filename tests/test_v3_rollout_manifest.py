import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from subc_assert_no_live_mutation import assert_no_live_mutation
from subc_validate_rollout_manifest import validate_manifest


class V3RolloutManifestTests(unittest.TestCase):
    def _files(self, root: Path):
        cron = root / "jobs.json"
        cron.write_text(json.dumps({"jobs": [{
            "id": "oldjob", "enabled": True,
            "schedule": {"kind": "cron", "expr": "0 6,12,18 * * *", "display": "0 6,12,18 * * *"},
            "deliver": "private-target"
        }]}))
        shadow = root / "shadow.json"
        shadow.write_text(json.dumps({
            "shadow_gate_pass": True, "live_mutation_detected": False,
            "mutation_checks": {"room_unchanged": True, "cron_target_unchanged": True, "provider_config_unchanged": True},
            "telegram_deliveries": 0, "cron_changes": 0, "provider_config_changes": 0,
            "state_writes": 0, "canonical_memory_writes": 0,
            "passes": [{"snapshot": {"cron_target": {"id": "oldjob", "enabled": True}}}],
        }))
        backtest = root / "backtest.json"
        backtest.write_text(json.dumps({"rollout_gate_pass": True}))
        baseline = root / "baseline.md"
        baseline.write_text("old_job_id: oldjob\nbaseline_public_sha: abcdef\n")
        scripts = root / "scripts"
        scripts.mkdir()
        for name in (
            "subc_live_projection.py", "subc_scout.py", "subc_delivery_gate.py",
            "subc_v3_telegram.py", "subc_v3_feedback.py",
        ):
            (scripts / name).write_text("# test\n")
        docs = root / "docs/v3"
        docs.mkdir(parents=True)
        (docs / "cron-prompt.md").write_text("test prompt")
        return cron, shadow, backtest, baseline

    def _manifest(self, root: Path, delete_old: bool = False):
        data = {
            "schema_version": "subc-v3-rollout-manifest/1",
            "old_job": {"id": "oldjob", "action": "pause", "delete": delete_old, "expected_enabled": True},
            "replacement": {
                "name": "SUBCONSCIOUS v3 Scout", "canary_schedule": "every 5m", "steady_schedule": "17 6 * * *",
                "cron_delivery": "local", "delivery_mode": "verified_self_send",
                "delivery_target_alias": "subconscious-supervisor-topic",
                "delivery_target_sha256": "sha256:b44d0cd8336a21e52ace1d2c1ea8b30db8ab7febec342c0751663a7d4aebed29",
                "workdir": "${HOME}/workspace/chip-subconscious-v3", "prompt_file": "docs/v3/cron-prompt.md",
                "scripts": [
                    "scripts/subc_live_projection.py", "scripts/subc_scout.py", "scripts/subc_delivery_gate.py",
                    "scripts/subc_v3_telegram.py", "scripts/subc_v3_feedback.py",
                ],
                "weekly_proposal_cap": 3,
            },
            "activation_steps": ["pause_old", "create_disabled", "enable_canary", "test_delivery", "readback", "second_scheduler_cycle", "set_steady_schedule"],
            "rollback_commands": ["hermes cron pause ${NEW_JOB_ID}", "hermes cron resume oldjob"],
            "recovery_owner": "Chip/Hermes operator lane",
            "approval_scope": "pause-old/activate-new/test-readback/rollback only"
        }
        path = root / "manifest.md"
        path.write_text("# Rollout\n\n```json\n" + json.dumps(data) + "\n```\n")
        return path

    def test_valid_manifest_is_bounded_and_live_target_hash_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cron, shadow, backtest, _ = self._files(root)
            errors = validate_manifest(self._manifest(root), cron_jobs=cron, repo_root=root, shadow_report=shadow, backtest_report=backtest)
            self.assertEqual(errors, [])

    def test_manifest_remains_valid_after_verified_steady_rollout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cron, shadow, backtest, _ = self._files(root)
            jobs = json.loads(cron.read_text())
            jobs["jobs"][0]["enabled"] = False
            jobs["jobs"][0]["state"] = "paused"
            jobs["jobs"].append({
                "id": "newjob",
                "name": "SUBCONSCIOUS v3 Scout",
                "enabled": True,
                "state": "scheduled",
                "schedule": {"kind": "cron", "expr": "17 6 * * *", "display": "17 6 * * *"},
                "deliver": "local",
            })
            cron.write_text(json.dumps(jobs))
            errors = validate_manifest(self._manifest(root), cron_jobs=cron, repo_root=root, shadow_report=shadow, backtest_report=backtest)
            self.assertEqual(errors, [])

    def test_delete_old_or_destructive_rollback_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cron, shadow, backtest, _ = self._files(root)
            errors = validate_manifest(self._manifest(root, delete_old=True), cron_jobs=cron, repo_root=root, shadow_report=shadow, backtest_report=backtest)
            self.assertIn("old_job_delete_must_be_false", errors)

    def test_direct_cron_delivery_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cron, shadow, backtest, _ = self._files(root)
            manifest = self._manifest(root)
            manifest.write_text(manifest.read_text().replace('"cron_delivery": "local"', '"cron_delivery": "private-target"'))
            errors = validate_manifest(manifest, cron_jobs=cron, repo_root=root, shadow_report=shadow, backtest_report=backtest)
            self.assertIn("cron_delivery_must_be_local", errors)

    def test_no_live_mutation_assertion_checks_every_surface(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, shadow, _, baseline = self._files(root)
            errors = assert_no_live_mutation(baseline, shadow)
            self.assertEqual(errors, [])
            report = json.loads(shadow.read_text())
            report["telegram_deliveries"] = 1
            shadow.write_text(json.dumps(report))
            self.assertIn("telegram_deliveries_nonzero", assert_no_live_mutation(baseline, shadow))

    def test_cron_contract_sends_six_buttons_before_committing_delivery_state(self):
        prompt = (ROOT / "docs/v3/cron-prompt.md").read_text()
        send_command = "subc_v3_telegram.py send"
        self.assertIn(send_command, prompt)
        self.assertIn("allowed_proposals", prompt)
        self.assertIn("button_count", prompt)
        self.assertIn("fetch back", prompt.lower())
        self.assertLess(prompt.index(send_command), prompt.rindex("--commit"))

    def test_cron_contract_forbids_bundled_suggestions(self):
        prompt = (ROOT / "docs/v3/cron-prompt.md").read_text()
        self.assertIn("one proposal per Telegram message", prompt)
        self.assertIn("Never bundle", prompt)
        self.assertIn("outbound-$PROPOSAL_ID.md", prompt)
        self.assertIn("send-result-$PROPOSAL_ID.json", prompt)
        self.assertIn("cron delivery is `local`", prompt.lower())
        self.assertIn("never propose deliberate re-exposure", prompt.lower())


if __name__ == "__main__":
    unittest.main()
