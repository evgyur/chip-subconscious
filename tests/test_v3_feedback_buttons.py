import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from subc_v3_feedback import record_feedback
from subc_v3_telegram import _api_call, apply_markup, callback_markup, parse_target, validate_single_suggestion


class V3FeedbackTests(unittest.TestCase):
    def test_feedback_is_idempotent_and_never_writes_canonical_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "delivery-state.json"
            state.write_text(json.dumps({
                "schema_version": "subc-v3-delivery-state/1",
                "deliveries": [{
                    "proposal_instance_id": "prp_a900471f04148fb763f9c2f15f2c62cd",
                    "problem_fingerprint": "sha256:" + "7" * 64,
                    "status": "delivery_selected",
                }],
                "feedback": [],
            }))
            actor = "sha256:" + "1" * 64
            first = record_feedback(
                state,
                proposal_instance_id="prp_a900471f04148fb763f9c2f15f2c62cd",
                action="accept",
                actor_ref_hash=actor,
                recorded_at="2026-07-10T12:00:00Z",
            )
            second = record_feedback(
                state,
                proposal_instance_id="prp_a900471f04148fb763f9c2f15f2c62cd",
                action="accept",
                actor_ref_hash=actor,
                recorded_at="2026-07-10T12:00:01Z",
            )
            payload = json.loads(state.read_text())
            self.assertEqual(len(payload["feedback"]), 1)
            self.assertEqual(first["feedback_id"], second["feedback_id"])
            self.assertFalse(first["creates_promotion_request"])
            self.assertFalse(first["writes_canonical_memory"])

    def test_unknown_proposal_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "delivery-state.json"
            state.write_text(json.dumps({"schema_version": "subc-v3-delivery-state/1", "deliveries": [], "feedback": []}))
            with self.assertRaises(ValueError):
                record_feedback(
                    state,
                    proposal_instance_id="prp_a900471f04148fb763f9c2f15f2c62cd",
                    action="save",
                    actor_ref_hash="sha256:" + "1" * 64,
                    recorded_at="2026-07-10T12:00:00Z",
                )


class V3ButtonTests(unittest.TestCase):
    def test_six_actions_are_real_inline_buttons(self):
        proposal = "prp_a900471f04148fb763f9c2f15f2c62cd"
        markup = callback_markup(proposal)
        buttons = [button for row in markup["inline_keyboard"] for button in row]
        self.assertEqual([button["text"] for button in buttons], [
            "✅ Accept", "❌ Reject", "⏭ Skip", "💾 Save", "🔕 Mute", "🔎 Deep dive"
        ])
        self.assertEqual([button["callback_data"].split(":", 2)[1] for button in buttons], ["a", "r", "k", "s", "m", "d"])
        self.assertTrue(all(button["callback_data"].endswith(proposal) for button in buttons))
        self.assertTrue(all(len(button["callback_data"].encode()) <= 64 for button in buttons))

    def test_private_target_is_parsed_without_persisting_it(self):
        self.assertEqual(parse_target("telegram:-100123:1551"), ("-100123", 1551))
        with self.assertRaises(ValueError):
            parse_target("local")

    def test_telegram_message_contains_exactly_one_suggestion(self):
        one = """🧠 SUBCONSCIOUS v3

➊ Одна идея
┈ почему сейчас: сигнал
┈ ценность: результат
┈ effort / risk / confidence: small / low / 0.8
┈ дешёвый тест: проверить
┈ выбери действие кнопкой ниже
"""
        self.assertIsNone(validate_single_suggestion(one))
        with self.assertRaisesRegex(ValueError, "exactly one suggestion"):
            validate_single_suggestion(one + "\n➋ Другая идея\n┈ почему сейчас: другой сигнал\n")

    def test_telegram_message_rejects_multiple_why_now_blocks_without_numbered_marker(self):
        text = """🧠 SUBCONSCIOUS v3

➊ Одна идея
┈ почему сейчас: сигнал
┈ почему сейчас: скрытая вторая идея
┈ ценность: результат
┈ effort / risk / confidence: small / low / 0.8
┈ дешёвый тест: проверить
┈ выбери действие кнопкой ниже
"""
        with self.assertRaisesRegex(ValueError, "exactly one suggestion"):
            validate_single_suggestion(text)

    def test_reapplying_identical_markup_is_idempotent(self):
        body = io.BytesIO(json.dumps({
            "ok": False,
            "error_code": 400,
            "description": "Bad Request: message is not modified",
        }).encode())

        def opener(request, timeout=20):
            raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", {}, body)

        result = _api_call(
            "test-token",
            "editMessageReplyMarkup",
            {"chat_id": "-100123", "message_id": 23054, "reply_markup": callback_markup("prp_a900471f04148fb763f9c2f15f2c62cd")},
            opener=opener,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["unchanged"])
        self.assertEqual(result["result"]["message_id"], 23054)


if __name__ == "__main__":
    unittest.main()
