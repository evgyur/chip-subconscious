import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from subc_shaw_enqueue import stale_run_reason

BASE = str(Path(__file__).resolve().parents[1])


class ShawEnqueueTests(unittest.TestCase):
    def test_enqueue_dry_run_does_not_create_shaw_run_state(self):
        with tempfile.TemporaryDirectory() as td:
            room = Path(td)
            (room / 'build_packets').mkdir()
            (room / 'approved_builds').mkdir()
            approved = room / 'approved_builds' / 'intent_fixture.yaml'
            approved.write_text('schema_version: "1.0"\nid: "intent_fixture"\nstatus: "approved"\n')
            (room / 'approval_events.jsonl').write_text(json.dumps({'schema_version': '1.0', 'intent_id': 'intent_fixture', 'decision': 'approved', 'approver': 'Chip'}) + '\n')
            packet = room / 'build_packets' / 'intent_fixture.json'
            packet.write_text(json.dumps({
                'schema_version': '1.0',
                'intent_id': 'intent_fixture',
                'goal': 'Build fixture safely',
                'context': 'Need a dry run',
                'non_goals': [],
                'file_targets': [],
                'acceptance_criteria': [],
                'tests': [],
                'rollback': 'Revert',
                'source_evidence': [str(approved)],
            }))
            p = subprocess.run([
                'python3', f'{BASE}/scripts/subc_shaw_enqueue.py',
                '--room', str(room),
                '--project', BASE,
                '--intent-id', 'intent_fixture',
                '--hermes-bin', '/bin/true',
                '--dry-run',
            ], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
            payload = json.loads(p.stdout)
            self.assertTrue(payload['dry_run'])
            self.assertFalse(payload['state_written'])
            self.assertFalse((room / 'shaw_runs' / 'intent_fixture.json').exists())
            self.assertIn('subc_shaw_worker.py', ' '.join(payload['command']))

    def test_stale_queued_run_without_pid_is_not_silent(self):
        now = datetime(2026, 5, 16, 8, 0, tzinfo=timezone.utc)
        state = {'status': 'queued', 'queued_at': '2026-05-16T07:00:00Z'}
        self.assertEqual(stale_run_reason(state, now=now, stale_after_seconds=900), 'queued_without_pid')

    def test_fresh_queued_run_is_not_marked_stale(self):
        now = datetime(2026, 5, 16, 8, 0, tzinfo=timezone.utc)
        state = {'status': 'queued', 'queued_at': '2026-05-16T07:59:00Z'}
        self.assertIsNone(stale_run_reason(state, now=now, stale_after_seconds=900))

    def test_running_dead_pid_is_not_silent(self):
        now = datetime(2026, 5, 16, 8, 0, tzinfo=timezone.utc)
        state = {'status': 'running', 'worker_started_at': '2026-05-16T07:00:00Z', 'worker_pid': 999999999}
        self.assertEqual(stale_run_reason(state, now=now, stale_after_seconds=900), 'running_without_live_worker')


if __name__ == '__main__':
    unittest.main()
