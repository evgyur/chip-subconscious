import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from subc_verify_rollout_approval import verify_approval
from subc_v3_rollout import verify_rollout_state
from subc_v3_verify_cron import verify_cron_state
from subc_v3_verify_delivery import verify_delivery_receipt
from subc_final_audit import audit_artifacts


def write_manifest(root: Path, target: str = "telegram:private:topic") -> Path:
    data = {
        "schema_version": "subc-v3-rollout-manifest/1",
        "old_job": {
            "id": "oldjob",
            "action": "pause",
            "delete": False,
            "expected_enabled": True,
        },
        "replacement": {
            "name": "SUBCONSCIOUS v3 Scout",
            "provider": "minimax",
            "model": "MiniMax-M2.7-highspeed",
            "provider_change": False,
            "canary_schedule": "every 5m",
            "steady_schedule": "17 6 * * *",
            "cron_delivery": "local",
            "delivery_mode": "verified_self_send",
            "delivery_target_alias": "subconscious-supervisor-topic",
            "delivery_target_sha256": "sha256:" + hashlib.sha256(target.encode()).hexdigest(),
            "workdir": "${HOME}/workspace/chip-subconscious-v3",
            "prompt_file": "docs/v3/cron-prompt.md",
            "scripts": ["scripts/subc_delivery_gate.py"],
            "weekly_proposal_cap": 3,
        },
        "activation_steps": [
            "pause_old",
            "create_disabled",
            "enable_canary",
            "test_delivery",
            "readback",
            "second_scheduler_cycle",
            "set_steady_schedule",
        ],
        "rollback_commands": [
            "hermes cron pause ${NEW_JOB_ID}",
            "hermes cron resume oldjob",
        ],
        "recovery_owner": "Chip/Hermes operator lane",
        "approval_scope": "pause-old/activate-new/test-readback/rollback only",
    }
    path = root / "manifest.md"
    path.write_text("# manifest\n\n```json\n" + json.dumps(data) + "\n```\n")
    return path


def write_jobs(root: Path, *, old_enabled: bool, new_enabled: bool, schedule: str) -> Path:
    path = root / "jobs.json"
    path.write_text(json.dumps({
        "jobs": [
            {
                "id": "oldjob",
                "name": "SUBCONSCIOUS walks",
                "enabled": old_enabled,
                "state": "scheduled" if old_enabled else "paused",
                "deliver": "telegram:private:topic",
                "schedule": {"kind": "cron", "expr": "0 6,12,18 * * *", "display": "0 6,12,18 * * *"},
            },
            {
                "id": "newjob",
                "name": "SUBCONSCIOUS v3 Scout",
                "enabled": new_enabled,
                "state": "scheduled" if new_enabled else "paused",
                "deliver": "local",
                "provider": "minimax",
                "model": "MiniMax-M2.7-highspeed",
                "workdir": str(root),
                "schedule": {"kind": "cron", "expr": schedule, "display": schedule},
            },
        ]
    }))
    return path


class ApprovalTests(unittest.TestCase):
    def test_exact_goal_and_bounded_approval_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "STATE.md"
            state.write_text(
                "Goal identity: `sg-20260710-subconscious-v3-product-reset`\n"
                "Current phase: 8\n"
                "Goal complete: no\n"
                "EVT-000009 P08 approval source: Chip explicitly instructed the standard Hermes `/goal` executor to continue; bounded reversible cron/test lane is also covered by the standing operator lane.\n"
            )
            self.assertEqual(verify_approval(state, "sg-20260710-subconscious-v3-product-reset"), [])
            state.write_text(state.read_text().replace("bounded reversible cron/test lane is also covered", "approval pending"))
            self.assertIn("bounded_rollout_approval_missing", verify_approval(state, "sg-20260710-subconscious-v3-product-reset"))


class RolloutStateTests(unittest.TestCase):
    def test_rollout_requires_old_paused_new_enabled_and_local_cron_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = write_manifest(root)
            jobs = write_jobs(root, old_enabled=False, new_enabled=True, schedule="every 5m")
            errors, evidence = verify_rollout_state(manifest, jobs_path=jobs, expected_stage="canary")
            self.assertEqual(errors, [])
            self.assertEqual(evidence["new_job_id"], "newjob")

    def test_rollout_rejects_old_job_still_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = write_manifest(root)
            jobs = write_jobs(root, old_enabled=True, new_enabled=True, schedule="every 5m")
            errors, _ = verify_rollout_state(manifest, jobs_path=jobs, expected_stage="canary")
            self.assertIn("old_job_not_paused", errors)

    def test_rollback_old_stage_requires_old_enabled_and_new_paused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = write_manifest(root)
            jobs = write_jobs(root, old_enabled=True, new_enabled=False, schedule="17 6 * * *")
            errors, evidence = verify_rollout_state(manifest, jobs_path=jobs, expected_stage="rollback-old")
            self.assertEqual(errors, [])
            self.assertTrue(evidence["old_job_enabled"])
            self.assertFalse(evidence["new_job_enabled"])


class CronVerificationTests(unittest.TestCase):
    def test_final_cron_is_weekly_local_and_not_duplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = write_manifest(root)
            jobs = write_jobs(root, old_enabled=False, new_enabled=True, schedule="17 6 * * *")
            errors, evidence = verify_cron_state(manifest, jobs_path=jobs)
            self.assertEqual(errors, [])
            self.assertEqual(evidence["replacement_count"], 1)
            self.assertEqual(evidence["schedule"], "17 6 * * *")


class DeliveryReceiptTests(unittest.TestCase):
    def test_receipt_requires_send_and_exact_fetch_back_without_raw_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = write_manifest(root)
            receipt = root / "receipt.json"
            receipt.write_text(json.dumps({
                "schema_version": "subc-v3-rollout-receipt/1",
                "target_alias": "subconscious-supervisor-topic",
                "target_sha256": "sha256:" + hashlib.sha256("telegram:private:topic".encode()).hexdigest(),
                "sender_transport": "hermes-bot",
                "test_message_id": 321,
                "fetched_back": True,
                "content_sha256": "sha256:" + "a" * 64,
                "second_cycle": {"status": "ok", "telegram_delivery_count": 0},
                "rollback_drill": {"old_resumed": True, "new_paused": True, "restored_to_v3_steady": True},
            }))
            self.assertEqual(verify_delivery_receipt(receipt, manifest), [])
            receipt.write_text(receipt.read_text().replace('"fetched_back": true', '"fetched_back": false'))
            self.assertIn("delivery_not_fetched_back", verify_delivery_receipt(receipt, manifest))


class FinalArtifactAuditTests(unittest.TestCase):
    def test_artifact_audit_requires_all_phase_reports_and_green_rollout_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "reports/v3"
            reports.mkdir(parents=True)
            for number in range(1, 9):
                (reports / f"phase-{number:02d}.md").write_text("Status: PASS\n")
            (reports / "backtest.json").write_text(json.dumps({"rollout_gate_pass": True}))
            (reports / "shadow-run.json").write_text(json.dumps({"shadow_gate_pass": True, "live_mutation_detected": False}))
            (reports / "rollout-receipt.json").write_text(json.dumps({"fetched_back": True, "second_cycle": {"telegram_delivery_count": 0}, "rollback_drill": {"restored_to_v3_steady": True}}))
            errors, evidence = audit_artifacts(root)
            self.assertEqual(errors, [])
            self.assertEqual(evidence["phase_reports_passed"], 8)


if __name__ == "__main__":
    unittest.main()
