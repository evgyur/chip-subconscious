import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from subc_shaw_worker import CANONICAL_SHAW_SKILL, build_prompt, main as worker_main, report_declares_blocked


class ShawWorkerPromptTests(unittest.TestCase):
    def test_prompt_prevents_repeated_clarification_loop(self):
        with tempfile.TemporaryDirectory() as td:
            room = Path(td)
            packet_path = room / 'build_packets' / 'intent_fixture.json'
            final_report_path = room / 'shaw_runs' / 'intent_fixture.final.md'
            packet = {
                'schema_version': '1.0',
                'intent_id': 'intent_fixture',
                'executor': 'shaw',
                'goal': 'Fix repeated clarification loop',
            }

            prompt = build_prompt('intent_fixture', room, packet_path, packet, final_report_path)

            self.assertIn('Не задавай пользователю повторных уточнений', prompt)
            self.assertIn('выбери минимальный безопасный путь сам', prompt)
            self.assertIn('blocked handoff с одним конкретным недостающим фактом', prompt)
            self.assertNotIn('уточни минимальный путь', prompt)

    def test_shaw_skill_is_pinned_by_exact_path(self):
        self.assertEqual(CANONICAL_SHAW_SKILL, Path('/home/hermes/.hermes/skills/shaw/SKILL.md'))
        self.assertNotEqual(str(CANONICAL_SHAW_SKILL), 'shaw')
    def test_blocked_detection_requires_explicit_blocked_handoff(self):
        successful_report = '''## Что изменено

Worker now writes `blocked` state only when the promise/reality gate fails.

## Как проверено

unit tests pass.

## Остаточные риски / блокеры

- If gate fails, state is blocked with gate_reason.
'''
        self.assertFalse(report_declares_blocked(successful_report))
        self.assertTrue(report_declares_blocked('blocked:\n┈ где остановился: missing approval'))
        self.assertTrue(report_declares_blocked('Статус: blocked\nнет данных'))

    def test_done_worker_output_without_verification_is_blocked_by_promise_reality_gate(self):
        with tempfile.TemporaryDirectory() as td:
            room = Path(td)
            (room / 'build_packets').mkdir()
            (room / 'shaw_runs').mkdir()
            intent_id = 'intent_worker-gate'
            (room / 'build_packets' / f'{intent_id}.json').write_text(json.dumps({
                'schema_version': '1.0',
                'intent_id': intent_id,
                'acceptance_criteria': ['Implementation verified with tests/commands'],
                'goal': 'Do not report done without verification evidence',
            }))
            (room / 'approval_events.jsonl').write_text(json.dumps({
                'intent_id': intent_id,
                'decision': 'approved',
                'timestamp': '2026-06-10T15:00:00Z',
            }) + '\n')

            fake_proc = SimpleNamespace(returncode=0, stdout='готово без evidence', stderr='')
            with patch.object(sys, 'argv', ['subc_shaw_worker.py', '--room', str(room), '--intent-id', intent_id, '--hermes-bin', '/bin/true']), \
                 patch('subc_shaw_worker.subprocess.run', return_value=fake_proc), \
                 patch('subc_shaw_worker.send_telegram', return_value=True):
                rc = worker_main()

            self.assertEqual(rc, 2)
            state = json.loads((room / 'shaw_runs' / f'{intent_id}.json').read_text())
            self.assertEqual(state['status'], 'blocked')
            self.assertEqual(state['promise_reality_gate'], 'failed')
            self.assertEqual(state['gate_reason'], 'missing_verification_evidence')

    def test_done_worker_records_successful_promise_reality_gate_before_done_handoff(self):
        with tempfile.TemporaryDirectory() as td:
            room = Path(td)
            (room / 'build_packets').mkdir()
            (room / 'shaw_runs').mkdir()
            intent_id = 'intent_worker-gate-pass'
            packet_path = room / 'build_packets' / f'{intent_id}.json'
            packet_path.write_text(json.dumps({
                'schema_version': '1.0',
                'intent_id': intent_id,
                'acceptance_criteria': ['Implementation verified with tests/commands'],
                'goal': 'Record proof before reporting done',
            }))
            (room / 'approval_events.jsonl').write_text(json.dumps({
                'intent_id': intent_id,
                'decision': 'approved',
                'timestamp': '2026-06-10T15:00:00Z',
            }) + '\n')
            def fake_run(*args, **kwargs):
                (room / 'shaw_runs' / f'{intent_id}.final.md').write_text(
                    '## Что изменено\n\nGate proof saved.\n\n## Как проверено\n\nunit tests pass.\n'
                )
                return SimpleNamespace(returncode=0, stdout='готово с проверкой', stderr='')

            with patch.object(sys, 'argv', ['subc_shaw_worker.py', '--room', str(room), '--intent-id', intent_id, '--hermes-bin', '/bin/true']), \
                 patch('subc_shaw_worker.subprocess.run', side_effect=fake_run), \
                 patch('subc_shaw_worker.send_telegram', return_value=True):
                rc = worker_main()

            self.assertEqual(rc, 0)
            state = json.loads((room / 'shaw_runs' / f'{intent_id}.json').read_text())
            self.assertEqual(state['status'], 'done')
            self.assertEqual(state['promise_reality_gate'], 'passed')
            self.assertEqual(state['gate_reason'], 'verified_shaw_run')
            self.assertEqual(state['gate_details']['acceptance_criteria_count'], 1)
            self.assertEqual(state['gate_details']['build_packet'], str(packet_path))
            self.assertIn('promise_reality_gate_verified_at', state)


if __name__ == '__main__':
    unittest.main()
