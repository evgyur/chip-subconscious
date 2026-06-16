import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from subc_common import verify_shaw_run


def write_run_fixture(room: Path, *, with_approval: bool = True, report_text: str | None = None):
    intent_id = 'intent_fixture'
    for d in ['shaw_runs', 'build_packets', 'approved_builds']:
        (room / d).mkdir(parents=True, exist_ok=True)
    (room / 'approved_builds' / f'{intent_id}.yaml').write_text('schema_version: "1.0"\nid: "intent_fixture"\nstatus: "approved"\n')
    if with_approval:
        (room / 'approval_events.jsonl').write_text(json.dumps({
            'schema_version': '1.0',
            'intent_id': intent_id,
            'decision': 'approved',
            'approver': 'Chip',
            'timestamp': '2026-06-16T00:00:00Z',
        }) + '\n')
    (room / 'build_packets' / f'{intent_id}.json').write_text(json.dumps({
        'schema_version': '1.0',
        'intent_id': intent_id,
        'acceptance_criteria': ['Implementation verified with tests/commands'],
        'tests': ['python3 -m unittest discover -s tests -v'],
    }))
    (room / 'shaw_runs' / f'{intent_id}.json').write_text(json.dumps({
        'schema_version': '1.0',
        'intent_id': intent_id,
        'status': 'done',
        'started_at': '2026-06-16T00:01:00Z',
        'finished_at': '2026-06-16T00:02:00Z',
        'build_packet': str(room / 'build_packets' / f'{intent_id}.json'),
        'final_report': str(room / 'shaw_runs' / f'{intent_id}.final.md'),
    }))
    (room / 'shaw_runs' / f'{intent_id}.final.md').write_text(report_text or '## Как проверено\n\npython3 -m unittest discover -s tests -v -> OK\n')
    return intent_id


class VerifyShawRunTests(unittest.TestCase):
    def test_verify_requires_approved_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            intent_id = write_run_fixture(room, with_approval=False)
            ok, reason, _details = verify_shaw_run(room, intent_id)
            self.assertFalse(ok)
            self.assertEqual(reason, 'missing_approved_event')

    def test_verify_rejects_negative_verification_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            intent_id = write_run_fixture(room, report_text='## Как проверено\n\nГотово без проверки, тесты не запускал.\n')
            ok, reason, _details = verify_shaw_run(room, intent_id)
            self.assertFalse(ok)
            self.assertEqual(reason, 'negative_verification_evidence')

    def test_verify_accepts_naive_timestamps_as_utc(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            intent_id = write_run_fixture(room)
            run_path = room / 'shaw_runs' / f'{intent_id}.json'
            state = json.loads(run_path.read_text())
            state['finished_at'] = '2026-06-16T00:02:00'
            run_path.write_text(json.dumps(state))
            ok, reason, _details = verify_shaw_run(room, intent_id)
            self.assertTrue(ok, reason)


if __name__ == '__main__':
    unittest.main()
