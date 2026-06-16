import json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from subc_score import main as score_main, status_for, signal_from_obs
from subc_publish import ROUTES, format_signal_board, signature_for_board
from subc_common import intent_eligibility, verify_shaw_run
from subc_intents import main as intents_main
from subc_adapters import Mem0gAdapter

class ScoringTests(unittest.TestCase):
    def test_status_lanes(self):
        self.assertEqual(status_for(2), 'note')
        self.assertEqual(status_for(4), 'watching')
        self.assertEqual(status_for(6), 'pending_intent')
    def test_routes(self):
        self.assertEqual(ROUTES['board'], 'signal_board')
        self.assertEqual(ROUTES['walk'], 'walk_logs')
        self.assertEqual(ROUTES['intent'], 'pending_intents')
        self.assertEqual(ROUTES['build'], 'approved_builds')
        self.assertEqual(ROUTES['archive'], 'archive')
    def test_signal_board_renders_mature_lanes(self):
        summary = {
            'updated_at': '2026-05-14T03:00:24Z',
            'lanes': {
                'ready_pending_approval': [{'id': 'sig-a', 'title': 'Signal A', 'score': 6.2, 'status': 'pending_intent'}],
                'watching': [{'id': 'sig-b', 'title': 'Signal B', 'score': 4.1, 'status': 'watching'}],
                'approved': [],
                'cooling': [],
                'archived': [],
            },
        }
        msg = format_signal_board(summary)
        self.assertIn('зрелые сигналы: ready=1, blocked=0, watching=1', msg)
        self.assertIn('Signal A', msg)
        self.assertIn('`sig-b`', msg)
    def test_signal_board_signature_ignores_score_decay_and_timestamp(self):
        base = {
            'updated_at': 't1',
            'lanes': {'ready_pending_approval': [{'id': 'sig-a', 'status': 'pending_intent', 'score': 6.0}]},
        }
        decayed = {
            'updated_at': 't2',
            'lanes': {'ready_pending_approval': [{'id': 'sig-a', 'status': 'pending_intent', 'score': 5.4}]},
        }
        changed = {
            'updated_at': 't2',
            'lanes': {'ready_pending_approval': [{'id': 'sig-c', 'status': 'pending_intent', 'score': 6.0}]},
        }
        self.assertEqual(signature_for_board(base), signature_for_board(decayed))
        self.assertNotEqual(signature_for_board(base), signature_for_board(changed))
    def test_trusted_single_evidence_health_signal_is_approval_eligible(self):
        sig = {
            'id': 'mem0g-health-issue',
            'status': 'pending_intent',
            'score': 10,
            'evidence': [{'evidence_uri': 'service:mem0g-inbox-adapter.service'}],
        }
        self.assertEqual(intent_eligibility(sig), (True, 'trusted_single_evidence'))
    def test_generic_single_evidence_signal_is_blocked_not_ready(self):
        sig = {
            'id': 'generic-repeat',
            'status': 'pending_intent',
            'score': 10,
            'evidence': [{'evidence_uri': 'session:1'}],
        }
        eligible, reason = intent_eligibility(sig)
        self.assertFalse(eligible)
        self.assertEqual(reason, 'needs_more_evidence:1/2')
    def test_mem0g_adapter_treats_disabled_legacy_inbox_adapter_as_non_canonical(self):
        class FakeRunner:
            def run(self, cmd, timeout=5):
                key = tuple(cmd)
                responses = {
                    ('curl','-fsS','http://127.0.0.1:8081/health'): (0, '{"status":"ok"}'),
                    ('curl','-fsS','http://127.0.0.1:8081/ready'): (0, '{"status":"ready"}'),
                    ('curl','-fsS','http://127.0.0.1:18792/health'): (0, '{"status":"ok","protocol":3}'),
                    ('systemctl','is-active','mem0g-api'): (0, 'active'),
                    ('systemctl','is-active','goclaw-inbox-media-worker.timer'): (0, 'active'),
                    ('systemctl','is-active','mem0g-inbox-adapter'): (3, 'inactive'),
                }
                return responses[key]

        adapter = Mem0gAdapter()
        adapter.runner = FakeRunner()
        observations = adapter.collect(limit=10)
        legacy = next(obs for obs in observations if obs['id'].endswith('legacy-service-mem0g-inbox-adapter'))
        self.assertIn('legacy mem0g-inbox-adapter not part of HEL1 canonical health', legacy['summary'])
        self.assertEqual(legacy['metadata']['legacy_state'], 'inactive')
        self.assertIsNone(signal_from_obs(legacy))
        self.assertTrue(any('GoClaw Inbox health check' in obs['summary'] for obs in observations))
    def test_intents_creates_card_for_trusted_single_evidence_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            (room / 'pending_intents').mkdir()
            (room / 'signals.json').write_text(json.dumps({
                'schema_version': '1.0',
                'signals': {
                    'openclaw-session-corpus-unreachable': {
                        'schema_version': '1.0',
                        'id': 'openclaw-session-corpus-unreachable',
                        'title': 'OpenClaw session corpus unreachable from SUBCONSCIOUS',
                        'status': 'pending_intent',
                        'score': 10,
                        'evidence': [{
                            'evidence_uri': 'ssh:chipdev@example:/home/chipdev/.openclaw',
                            'summary': 'Permission denied (publickey).',
                            'source_adapter': 'OpenClawSessionAdapter',
                        }],
                    },
                },
            }))
            (room / 'summary.json').write_text(json.dumps({'schema_version': '1.0', 'lanes': {}}))
            with patch.object(sys, 'argv', ['subc_intents.py', '--room', str(room), '--max', '3']):
                intents_main()
            path = room / 'pending_intents' / 'intent_openclaw-session-corpus-unreachable.yaml'
            self.assertTrue(path.exists())
            self.assertIn('Починить доступ SUBCONSCIOUS', path.read_text())
    def test_closed_bucket_does_not_swallow_fresh_chip_value_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            (room / 'walk_logs').mkdir()
            (room / 'signals.json').write_text(json.dumps({
                'schema_version': '1.0',
                'signals': {
                    'manual-repeat-automation-opportunity': {
                        'schema_version': '1.0',
                        'id': 'manual-repeat-automation-opportunity',
                        'title': 'Автоматизировать повторяющиеся ручные операции',
                        'signal_types': ['reuse', 'repeat'],
                        'score': 0.16,
                        'status': 'approved',
                        'evidence': [{'evidence_uri': 'session:old#msg:1'}],
                    },
                },
            }))
            (room / 'summary.json').write_text(json.dumps({'schema_version': '1.0', 'lanes': {}}))
            walk_path = room / 'walk_logs' / 'walk_20260610T150018Z.json'
            walk_path.write_text(json.dumps({
                'schema_version': '1.0',
                'observations': [{
                    'schema_version': '1.0',
                    'id': 'HermesSessionAdapter:manual-repeat-automation-opportunity',
                    'source': 'hermes-sessions',
                    'source_adapter': 'HermesSessionAdapter',
                    'evidence_uri': 'session:fresh#msg:42',
                    'observed_at': '2026-06-10T15:00:13Z',
                    'confidence': 0.9,
                    'redacted': True,
                    'summary': 'Chip correction pattern: manual repeat / automation opportunity',
                    'metadata': {
                        'pattern_type': 'manual_repeat',
                        'proposal_id': 'manual-repeat-automation-opportunity',
                        'title': 'Автоматизировать повторяющиеся ручные операции',
                        'proposed_action': 'Собрать повторяющуюся ручную операцию в automation candidate.',
                        'risk': 'Chip продолжит платить вниманием за ручной повтор',
                        'score_delta': 6.8,
                        'chip_value_signal': True,
                    },
                }],
            }))

            with patch.object(sys, 'argv', ['subc_score.py', '--room', str(room), '--walk-json', str(walk_path), '--decay', '1']):
                score_main()

            scored = json.loads((room / 'signals.json').read_text())['signals']
            self.assertEqual(scored['manual-repeat-automation-opportunity']['status'], 'approved')
            instance_ids = [sid for sid in scored if sid.startswith('manual-repeat-automation-opportunity-')]
            self.assertEqual(len(instance_ids), 1)
            instance = scored[instance_ids[0]]
            self.assertEqual(instance['status'], 'pending_intent')
            self.assertEqual(instance['evidence'][0]['bucket_signal_id'], 'manual-repeat-automation-opportunity')
            summary = json.loads((room / 'summary.json').read_text())
            self.assertEqual(summary['lanes']['ready_pending_approval'][0]['id'], instance_ids[0])

    def test_non_reopening_system_fix_bucket_suppresses_duplicate_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            (room / 'walk_logs').mkdir()
            (room / 'signals.json').write_text(json.dumps({
                'schema_version': '1.0',
                'signals': {
                    'chip-correction-mining-loop': {
                        'schema_version': '1.0',
                        'id': 'chip-correction-mining-loop',
                        'title': 'Превращать повторяющиеся правки Chip в guards/evals/skills',
                        'signal_types': ['reuse', 'repeat'],
                        'score': 0.5,
                        'status': 'approved',
                        'evidence': [{'evidence_uri': 'session:old#msg:1'}],
                    },
                    'chip-correction-mining-loop-oldrun': {
                        'schema_version': '1.0',
                        'id': 'chip-correction-mining-loop-oldrun',
                        'title': 'Превращать повторяющиеся правки Chip в guards/evals/skills',
                        'signal_types': ['reuse', 'repeat'],
                        'score': 8,
                        'status': 'approved',
                        'evidence': [{'evidence_uri': 'session:old#msg:2'}],
                    },
                },
            }))
            (room / 'summary.json').write_text(json.dumps({'schema_version': '1.0', 'lanes': {}}))
            walk_path = room / 'walk_logs' / 'walk_20260616T050000Z.json'
            walk_path.write_text(json.dumps({
                'schema_version': '1.0',
                'observations': [{
                    'schema_version': '1.0',
                    'id': 'CorrectionMiningAdapter:chip-correction-mining-loop',
                    'source': 'correction-mining',
                    'source_adapter': 'CorrectionMiningAdapter',
                    'evidence_uri': 'session:fresh#msg:99',
                    'confidence': 0.92,
                    'redacted': True,
                    'summary': 'Chip correction mining grouped 1 clean recent correction(s).',
                    'metadata': {
                        'pattern_type': 'correction_mining',
                        'proposal_id': 'chip-correction-mining-loop',
                        'title': 'Превращать повторяющиеся правки Chip в guards/evals/skills',
                        'proposed_action': 'Создать candidate guard/eval/skill patch из повторяющейся правки Chip и привязать его к redacted evidence.',
                        'risk': 'без correction mining Chip будет снова руками повторять одни и те же правки агенту',
                        'score_delta': 8.0,
                        'chip_value_signal': True,
                    },
                }],
            }))

            with patch.object(sys, 'argv', ['subc_score.py', '--room', str(room), '--walk-json', str(walk_path), '--decay', '1']):
                score_main()

            scored = json.loads((room / 'signals.json').read_text())['signals']
            fresh_instances = [sid for sid in scored if sid.startswith('chip-correction-mining-loop-') and sid != 'chip-correction-mining-loop-oldrun']
            self.assertEqual(fresh_instances, [])
            summary = json.loads((room / 'summary.json').read_text())
            self.assertNotIn('ready_pending_approval', {k for k, v in summary['lanes'].items() if v})

    def test_approved_signal_without_verified_shaw_run_stays_blocked_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            (room / 'walk_logs').mkdir()
            (room / 'signals.json').write_text(json.dumps({
                'schema_version': '1.0',
                'signals': {
                    'promise-reality-gate': {
                        'schema_version': '1.0',
                        'id': 'promise-reality-gate',
                        'title': 'Проверять approved/done через verified Shaw run',
                        'signal_types': ['friction', 'blocker'],
                        'score': 10,
                        'status': 'approved',
                        'evidence': [{'evidence_uri': 'session:old#msg:1'}],
                    },
                },
            }))
            (room / 'summary.json').write_text(json.dumps({'schema_version': '1.0', 'lanes': {}}))
            walk_path = room / 'walk_logs' / 'walk_empty.json'
            walk_path.write_text(json.dumps({'schema_version': '1.0', 'observations': []}))

            with patch.object(sys, 'argv', ['subc_score.py', '--room', str(room), '--walk-json', str(walk_path), '--decay', '1']):
                score_main()

            summary = json.loads((room / 'summary.json').read_text())
            self.assertEqual(summary['lanes']['approved'], [])
            self.assertEqual(summary['lanes']['blocked_ready'][0]['id'], 'promise-reality-gate')
            self.assertEqual(summary['lanes']['blocked_ready'][0]['reason'], 'missing_shaw_run')

    def test_approved_signal_with_done_run_final_and_acceptance_stays_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            (room / 'walk_logs').mkdir()
            (room / 'shaw_runs').mkdir()
            (room / 'build_packets').mkdir()
            (room / 'signals.json').write_text(json.dumps({
                'schema_version': '1.0',
                'signals': {
                    'promise-reality-gate': {
                        'schema_version': '1.0',
                        'id': 'promise-reality-gate',
                        'title': 'Проверять approved/done через verified Shaw run',
                        'signal_types': ['friction', 'blocker'],
                        'score': 10,
                        'status': 'approved',
                        'evidence': [{'evidence_uri': 'session:fresh#msg:1'}],
                    },
                },
            }))
            (room / 'summary.json').write_text(json.dumps({'schema_version': '1.0', 'lanes': {}}))
            (room / 'approval_events.jsonl').write_text(json.dumps({
                'intent_id': 'intent_promise-reality-gate',
                'decision': 'approved',
                'timestamp': '2026-06-10T15:00:00Z',
            }) + '\n')
            packet_path = room / 'build_packets' / 'intent_promise-reality-gate.json'
            packet_path.write_text(json.dumps({
                'schema_version': '1.0',
                'intent_id': 'intent_promise-reality-gate',
                'acceptance_criteria': ['Implementation verified with tests/commands'],
            }))
            final_path = room / 'shaw_runs' / 'intent_promise-reality-gate.final.md'
            final_path.write_text('## Что изменено\n\nGate added.\n\n## Как проверено\n\nunit tests pass.\n')
            (room / 'shaw_runs' / 'intent_promise-reality-gate.json').write_text(json.dumps({
                'schema_version': '1.0',
                'intent_id': 'intent_promise-reality-gate',
                'status': 'done',
                'finished_at': '2026-06-10T15:10:00Z',
                'final_report': str(final_path),
                'build_packet': str(packet_path),
            }))
            walk_path = room / 'walk_logs' / 'walk_empty.json'
            walk_path.write_text(json.dumps({'schema_version': '1.0', 'observations': []}))

            ok, reason, details = verify_shaw_run(room, 'intent_promise-reality-gate')
            self.assertTrue(ok, details)
            self.assertEqual(reason, 'verified_shaw_run')

            with patch.object(sys, 'argv', ['subc_score.py', '--room', str(room), '--walk-json', str(walk_path), '--decay', '1']):
                score_main()

            summary = json.loads((room / 'summary.json').read_text())
            self.assertEqual(summary['lanes']['blocked_ready'], [])
            self.assertEqual(summary['lanes']['approved'][0]['id'], 'promise-reality-gate')

if __name__ == '__main__': unittest.main()
