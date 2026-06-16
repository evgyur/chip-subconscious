import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from subc_cron_digest import build_digest
from subc_validate import validate_approved_builds, ValidationError


SUMMARY = {
    'schema_version': '1.0',
    'lanes': {
        'ready_pending_approval': [
            {'id': 'mem0g-health-issue', 'title': 'mem0g health/service issue', 'score': 10},
        ],
        'blocked_ready': [],
        'watching': [{'id': 'foo', 'title': 'Foo', 'score': 4.1}],
        'cooling': [],
        'approved': [],
        'archived': [],
    },
    'guardrails': {'subconscious_max_state': 'pending_approval', 'approval_required_for_build': True, 'allowed_to_build': False},
}


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


class CronDigestTests(unittest.TestCase):
    def test_build_digest_surfaces_actionable_pending_intents_not_counters(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            for d in ['pending_intents', 'walk_logs', 'approved_builds', 'archive', 'shaw_runs']:
                (room / d).mkdir()
            write_json(room / 'summary.json', SUMMARY)
            write_json(room / 'posted_pending_intents.json', {
                'posted': {
                    'intent_mem0g-health-issue': {
                        'message_id': 123,
                        'callback_token': 'abc',
                        'reply_markup_sent': True,
                    }
                },
                'tokens': {'abc': 'intent_mem0g-health-issue'},
            })
            write_json(room / 'walk_logs' / 'walk_20260529T090000Z.json', {
                'observations': [
                    {'source': 'hermes-sessions'},
                    {'source': 'openclaw-sessions'},
                    {'source': 'openclaw-sessions'},
                ]
            })
            (room / 'pending_intents' / 'intent_mem0g-health-issue.yaml').write_text('''schema_version: "1.0"
id: "intent_mem0g-health-issue"
title: "Проверить здоровье mem0g"
problem: "mem0g может быть нездоров."
suggested_build: "Сделать read-only диагностику mem0g и предложить конкретный фикс."
risk: "Слой памяти деградирует незаметно."
status: "pending_approval"
evidence:
  - evidence_uri: "service:mem0g"
    summary: "mem0g-inbox-adapter.service active check: inactive"
''')

            text = build_digest(room, timestamp='2026-05-29T09:00:00Z')

            self.assertIn('предлагаю', text.lower())
            self.assertIn('Проверить здоровье mem0g', text)
            self.assertIn('mem0g-inbox-adapter.service active check: inactive', text)
            self.assertIn('риск', text.lower())
            self.assertIn('Pending Intents', text)
            self.assertIn('кнопка в Pending Intents, не в этом walk-log', text)
            self.assertIn('➋ где гулял', text)
            self.assertIn('hermes-sessions: 1', text)
            self.assertIn('openclaw-sessions: 2', text)
            self.assertNotIn('наблюдений:', text)
            self.assertNotIn('ready approval:', text)

    def test_callback_token_alone_does_not_claim_visible_buttons(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            for d in ['pending_intents', 'walk_logs', 'approved_builds', 'archive', 'shaw_runs']:
                (room / d).mkdir()
            write_json(room / 'summary.json', SUMMARY)
            write_json(room / 'posted_pending_intents.json', {
                'posted': {'intent_mem0g-health-issue': {'message_id': 123, 'callback_token': 'abc'}},
                'tokens': {'abc': 'intent_mem0g-health-issue'},
            })
            (room / 'pending_intents' / 'intent_mem0g-health-issue.yaml').write_text('''schema_version: "1.0"
id: "intent_mem0g-health-issue"
title: "Проверить здоровье mem0g"
risk: "Слой памяти деградирует незаметно."
evidence:
  - summary: "mem0g-inbox-adapter.service active check: inactive"
''')

            text = build_digest(room, timestamp='2026-05-29T09:00:00Z')

            self.assertIn('кнопки не подтверждены — надо перепостить', text)
            self.assertNotIn('кнопка есть', text)

    def test_build_digest_is_honest_healthcheck_when_no_actionable_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            for d in ['pending_intents', 'walk_logs', 'approved_builds', 'archive', 'shaw_runs']:
                (room / d).mkdir()
            empty_summary = dict(SUMMARY)
            empty_summary['lanes'] = {k: [] for k in SUMMARY['lanes']}
            empty_summary['lanes']['watching'] = [{'id': 'foo', 'title': 'Foo', 'score': 4.1}]
            write_json(room / 'summary.json', empty_summary)
            write_json(room / 'posted_pending_intents.json', {'posted': {}, 'tokens': {}})

            text = build_digest(room, timestamp='2026-05-29T09:00:00Z')

            self.assertIn('новых предложений нет', text.lower())
            self.assertIn('watching: 1', text)
            self.assertIn('done_verified=0, done_unverified=0', text)
            self.assertNotIn('ready approval', text.lower())

    def test_validate_rejects_approved_build_with_pending_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            approved = room / 'approved_builds'
            approved.mkdir()
            (approved / 'intent_demo.yaml').write_text('''schema_version: "1.0"
id: "intent_demo"
status: "pending_approval"
''')

            with self.assertRaises(ValidationError):
                validate_approved_builds(room)


if __name__ == '__main__':
    unittest.main()
