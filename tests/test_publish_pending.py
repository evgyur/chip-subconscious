import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from subc_publish_pending import format_plain_ru_message, reconcile_resolved_pending_files, reply_markup_for, should_publish_pending


SAMPLE_INTENT = '''schema_version: "1.0"
id: "intent_demo"
title: "Проверить демо"
problem: "Простыми словами: что-то повторяется и мешает Чипу."
suggested_build: "Собрать read-only отчёт и предложить следующий шаг."
risk: "Ложная тревога."
confidence: 0.72
approval_required: true
status: "pending_approval"
source_adapters:
  - "ManualAdapter"
non_goals:
  - "SUBCONSCIOUS не меняет прод"
  - "Без рестартов сервисов"
acceptance_criteria:
  - "Факты read-only проверены"
  - "Решение записано"
related_intents:
duplicate_of: null
evidence:
  - evidence_uri: "session:demo"
    summary: "В двух сессиях повторился один и тот же сбой."
    source_adapter: "ManualAdapter"
'''


class PublishPendingTests(unittest.TestCase):
    def test_plain_ru_message_is_russian_and_actionable(self):
        msg = format_plain_ru_message('intent_demo', SAMPLE_INTENT, Path('/tmp/intent_demo.yaml'))
        self.assertIn('Идея на решение', msg)
        forbidden_label = 'EL' + 'I5'
        self.assertNotIn(forbidden_label, msg)
        self.assertIn('В чём дело:', msg)
        self.assertIn('Почему это всплыло:', msg)
        self.assertIn('Что предлагаю сделать:', msg)
        self.assertIn('Чего не делаем:', msg)
        self.assertIn('Готово, если:', msg)
        self.assertIn('Нажми ✅ Да', msg)
        self.assertIn('❌ Нет', msg)
        self.assertIn('В двух сессиях повторился', msg)
        self.assertNotIn('source:', msg)

    def test_known_english_intent_is_rendered_in_russian(self):
        yaml_text = '''schema_version: "1.0"
id: "intent_hermes-cross-session-recall-gap"
title: "Build automatic cross-session recall preflight for Hermes Telegram"
problem: "Repeated memory review shows Hermes Telegram sessions still rely on manual session_search."
suggested_build: "Create a read-only preflight that summarizes recent relevant sessions."
confidence: 0.66
non_goals:
  - "No production mutation from SUBCONSCIOUS"
  - "No service restart"
  - "No secrets/grants/auth changes"
acceptance_criteria:
  - "Read-only evidence reviewed"
  - "Decision recorded as approved/rejected/cooled"
  - "If approved, handoff packet includes tests and rollback"
evidence:
  - evidence_uri: "session:demo"
    summary: "Repeated sessions show Chip's main pain is lost context across Telegram sessions."
'''
        msg = format_plain_ru_message('intent_hermes-cross-session-recall-gap', yaml_text, Path('/tmp/intent.yaml'))
        self.assertIn('Автоматически вспоминать важный контекст', msg)
        self.assertIn('В нескольких прошлых сессиях', msg)
        self.assertIn('Не меняем прод из слоя наблюдения', msg)
        self.assertIn('пакет задачи с проверками и откатом', msg)
        self.assertNotIn('Build automatic', msg)
        self.assertNotIn('Repeated memory review', msg)
        self.assertNotIn('Create a read-only', msg)
        self.assertNotIn('read-only', msg)
        self.assertNotIn('preflight', msg)
        self.assertNotIn('Hermes/Main', msg)
        self.assertNotIn('source:', msg)

    def test_reply_markup_has_yes_no_callback_tokens(self):
        state = {'posted': {}, 'tokens': {}}
        markup = reply_markup_for('intent_demo', state)
        row = markup['inline_keyboard'][0]
        self.assertEqual(row[0]['text'], '✅ Да')
        self.assertEqual(row[1]['text'], '❌ Нет')
        self.assertRegex(row[0]['callback_data'], r'^subc:y:[0-9a-f]{24}$')
        self.assertRegex(row[1]['callback_data'], r'^subc:n:[0-9a-f]{24}$')
        token = row[0]['callback_data'].rsplit(':', 1)[-1]
        self.assertEqual(state['tokens'][token], 'intent_demo')

    def test_should_republish_when_buttons_not_confirmed(self):
        self.assertTrue(should_publish_pending('intent_demo', {}))
        self.assertFalse(should_publish_pending('intent_demo', {'intent_demo': {'message_id': 123, 'reply_markup_sent': True}}))
        self.assertTrue(should_publish_pending('intent_demo', {'intent_demo': {'message_id': 123, 'callback_token': 'abc'}}))
        self.assertTrue(should_publish_pending('intent_demo', {'intent_demo': {'message_id': 123, 'reply_markup_sent': False}}))
        self.assertFalse(should_publish_pending('intent_demo', {'intent_demo': {'message_id': 123, 'decision': 'approved'}}))

    def test_reconcile_moves_resolved_pending_file_out_of_pending_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            pending = room / 'pending_intents'
            approved = room / 'approved_builds'
            pending.mkdir()
            approved.mkdir()
            path = pending / 'intent_demo.yaml'
            path.write_text(SAMPLE_INTENT)
            (room / 'approval_events.jsonl').write_text(json.dumps({'intent_id': 'intent_demo', 'decision': 'approved', 'timestamp': '2026-06-16T00:00:00Z'}) + '\n')
            state = {'posted': {'intent_demo': {'decision': 'approved', 'path': str(path)}}}

            moved = reconcile_resolved_pending_files(room, state)

            self.assertEqual(len(moved), 1)
            self.assertFalse(path.exists())
            self.assertTrue((approved / 'intent_demo.yaml').exists())
            self.assertEqual(moved[0]['mode'], 'canonical_transition')
            self.assertEqual(state['posted']['intent_demo']['path'], str(approved / 'intent_demo.yaml'))

    def test_reconcile_quarantines_duplicate_when_destination_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            pending = room / 'pending_intents'
            approved = room / 'approved_builds'
            archive = room / 'archive'
            pending.mkdir()
            approved.mkdir()
            archive.mkdir()
            path = pending / 'intent_demo.yaml'
            path.write_text(SAMPLE_INTENT)
            (approved / 'intent_demo.yaml').write_text('already transitioned')
            (room / 'approval_events.jsonl').write_text(json.dumps({'intent_id': 'intent_demo', 'decision': 'approved', 'timestamp': '2026-06-16T00:00:00Z'}) + '\n')
            state = {'posted': {'intent_demo': {'decision': 'approved', 'path': str(path)}}}

            moved = reconcile_resolved_pending_files(room, state)

            self.assertEqual(len(moved), 1)
            self.assertFalse(path.exists())
            self.assertEqual(moved[0]['mode'], 'quarantine_duplicate')
            self.assertTrue(Path(moved[0]['to']).exists())
            self.assertIn('/archive/resolved_pending_intents/', moved[0]['to'])
    def test_reconcile_quarantines_approved_decision_without_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            pending = room / 'pending_intents'
            archive = room / 'archive'
            pending.mkdir()
            archive.mkdir()
            path = pending / 'intent_demo.yaml'
            path.write_text(SAMPLE_INTENT)
            state = {'posted': {'intent_demo': {'decision': 'approved', 'path': str(path)}}}

            moved = reconcile_resolved_pending_files(room, state)

            self.assertEqual(len(moved), 1)
            self.assertFalse(path.exists())
            self.assertEqual(moved[0]['mode'], 'quarantine_unverified_decision')
            self.assertTrue(Path(moved[0]['to']).exists())
            self.assertIn('/archive/resolved_pending_intents/', moved[0]['to'])


if __name__ == '__main__':
    unittest.main()
