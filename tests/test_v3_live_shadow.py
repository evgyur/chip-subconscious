import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from subc_live_projection import project_recent_messages
from subc_v3_shadow import run_shadow


class V3LiveProjectionShadowTests(unittest.TestCase):
    def _fixture(self, root: Path):
        config = root / "config.yaml"
        config.write_text("telegram:\n  chip_history_recovery:\n    chip_user_id: 42\n")
        db = root / "state.db"
        connection = sqlite3.connect(db)
        connection.executescript(
            """
            CREATE TABLE sessions (
              id TEXT PRIMARY KEY, source TEXT, user_id TEXT, parent_session_id TEXT,
              started_at REAL, archived INTEGER, chat_id TEXT, thread_id TEXT
            );
            CREATE TABLE messages (
              id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT,
              timestamp REAL, active INTEGER, compacted INTEGER
            );
            """
        )
        sessions = [
            ("s1", "telegram", "42", None, 1000, 0, "private", None),
            ("s2", "telegram", "99", None, 1000, 0, "other", None),
            ("s3", "cron", "42", None, 1000, 0, "private", None),
            ("s4", "telegram", "42", "parent", 1000, 0, "private", None),
        ]
        connection.executemany("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)", sessions)
        messages = [
            (1, "s1", "user", "Нужно снова автоматизировать ручную проверку уроков; owner@example.com; /home/" + "hermes/private", 1010, 1, 0),
            (2, "s1", "user", "[CONTEXT COMPACTION — REFERENCE ONLY] blob", 1020, 1, 0),
            (3, "s1", "tool", "tool output", 1030, 1, 0),
            (4, "s2", "user", "unrelated user", 1040, 1, 0),
            (5, "s3", "user", "cron prompt", 1050, 1, 0),
            (6, "s4", "user", "subagent projection", 1060, 1, 0),
            (7, "s1", "user", "Нужно снова автоматизировать ручную проверку уроков; owner@example.com; /home/" + "hermes/private", 1070, 1, 0),
            (8, "s1", "user", "[Evgeny \"Chip\"] [Continuing toward your standing goal] Goal: execute package", 1080, 1, 0),
            (9, "s1", "user", "Как правильно смешать напиток со льдом?", 1090, 1, 0),
        ]
        connection.executemany("INSERT INTO messages VALUES (?,?,?,?,?,?,?)", messages)
        connection.commit()
        connection.close()

        room = root / "room"
        room.mkdir()
        (room / "summary.json").write_text('{"counts":{"pending":0}}')
        cron = root / "jobs.json"
        cron.write_text(json.dumps({"jobs": [{
            "id": "oldjob", "name": "SUBCONSCIOUS walks", "enabled": True,
            "schedule": {"kind": "cron", "expr": "0 6,12,18 * * *", "display": "0 6,12,18 * * *"},
            "deliver": "private-target", "provider": "approved", "model": "current",
            "script": "run-old", "prompt": "",
        }]}))
        backtest = root / "backtest.json"
        backtest.write_text(json.dumps({"rollout_gate_pass": True}))
        model_output = root / "model-output.json"
        model_output.write_text(json.dumps({
            "schema_version": "subc-v3-scout-evaluation/1", "status": "empty", "proposals": []
        }))
        return config, db, room, cron, backtest, model_output

    def test_live_projection_is_owner_scoped_and_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, db, *_ = self._fixture(Path(tmp))
            context = project_recent_messages(db, config, since_timestamp=900, limit=20)
            self.assertEqual(context["coverage"]["eligible"], 1)
            self.assertEqual(context["coverage"]["excluded_compaction"], 1)
            self.assertEqual(context["coverage"]["excluded_system_injection"], 1)
            self.assertEqual(context["coverage"]["excluded_duplicate"], 1)
            self.assertEqual(context["coverage"]["excluded_no_scout_signal"], 1)
            self.assertEqual(len(context["events"]), 1)
            event = context["events"][0]
            self.assertEqual(event["lane"], "reflex")
            self.assertFalse(event["raw_content_included"])
            serialized = json.dumps(context, ensure_ascii=False)
            self.assertNotIn("owner@example.com", serialized)
            self.assertNotIn("/home/" + "hermes", serialized)
            self.assertNotIn("unrelated user", serialized)
            self.assertIn("[email]", serialized)
            self.assertIn("[private-path]", serialized)

    def test_shadow_runs_two_fresh_passes_without_live_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, db, room, cron, backtest, model_output = self._fixture(Path(tmp))
            report = run_shadow(
                room=room,
                cron_jobs=cron,
                config=config,
                state_db=db,
                backtest_report=backtest,
                model_output=model_output,
                since_timestamp=900,
            )
            self.assertTrue(report["shadow_gate_pass"])
            self.assertEqual(report["observation_pass_count"], 2)
            self.assertFalse(report["live_mutation_detected"])
            self.assertTrue(report["mutation_checks"]["room_unchanged"])
            self.assertTrue(report["mutation_checks"]["cron_target_unchanged"])
            self.assertEqual(report["telegram_deliveries"], 0)
            self.assertEqual(report["state_writes"], 0)
            self.assertEqual(report["semantic_status"], "empty")
            self.assertNotIn("safe_summary", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
