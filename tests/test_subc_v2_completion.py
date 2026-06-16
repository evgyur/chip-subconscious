import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from subc_adapters import CorrectionMiningAdapter, PromiseRealityAdapter, OpenClawSemanticAdapter
from subc_cron_digest import build_digest
from subc_intents import build_intent, write_intent_yaml
from subc_score import opportunity_score, signal_from_obs


def make_state_db(path: Path, messages):
    con = sqlite3.connect(path)
    con.execute('create table sessions (id text primary key, source text, title text, started_at real)')
    con.execute('create table messages (id integer primary key, session_id text, role text, content text, timestamp real)')
    con.execute('insert into sessions values (?,?,?,?)', ('s1', 'telegram', 'chip corrections', 1000.0))
    con.executemany('insert into messages (session_id, role, content, timestamp) values (?,?,?,?)', messages)
    con.commit(); con.close()


class SubconsciousV2CompletionTests(unittest.TestCase):
    def test_correction_mining_adapter_emits_clean_chip_corrections_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'state.db'
            make_state_db(db, [
                ('s1', 'user', '[IMPORTANT: fake skill blob фуфел не пиши так]', 1001),
                ('s1', 'user', '[Replying to: assistant quote фуфел]\nnot chip speaking', 1002),
                ('s1', 'user', '[Evgeny "Chip"] это фуфел, где результат и почему ты не проверил?', 1003),
            ])
            old = os.environ.get('SUBC_HERMES_STATE_DB')
            os.environ['SUBC_HERMES_STATE_DB'] = str(db)
            try:
                obs = CorrectionMiningAdapter().collect(limit=10)
            finally:
                if old is None:
                    os.environ.pop('SUBC_HERMES_STATE_DB', None)
                else:
                    os.environ['SUBC_HERMES_STATE_DB'] = old
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]['source'], 'correction-mining')
        self.assertEqual(obs[0]['metadata']['proposal_id'], 'chip-correction-mining-loop')
        self.assertTrue(obs[0]['metadata']['chip_value_signal'])
        self.assertEqual(obs[0]['metadata']['correction_count'], 1)
        self.assertEqual(obs[0]['metadata']['primary_bucket'], 'promise_reality_guard')
        self.assertEqual(obs[0]['metadata']['suggested_patch_type'], 'guard')
        self.assertEqual(obs[0]['metadata']['candidate_patch']['status'], 'candidate')
        self.assertEqual(obs[0]['metadata']['candidate_patch']['patch_type'], 'guard')
        self.assertEqual(obs[0]['metadata']['candidate_patch']['privacy'], 'redacted_session_pointers_only')
        self.assertEqual(len(obs[0]['metadata']['evidence_items']), 1)
        self.assertIn('Proposed patch type: guard', obs[0]['summary'])
        self.assertNotIn('IMPORTANT', obs[0]['summary'])
        self.assertNotIn('Replying to', obs[0]['summary'])
        self.assertNotIn('ху', obs[0]['summary'].lower())
        self.assertNotIn('фуфел', obs[0]['metadata']['evidence_items'][0]['summary'].lower())
        self.assertIn('session:s1#msg:', obs[0]['metadata']['evidence_items'][0]['evidence_uri'])

    def test_correction_mining_does_not_promote_generic_transcript_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'state.db'
            make_state_db(db, [
                ('s1', 'user', '[The user sent a voice message~ Here\'s what they said: "Привет всем. Это не то чтобы вопрос, просто транскрипт вебинара. Надо было заранее сказать участникам про запись." ]', 1001),
                ('s1', 'user', '[Evgeny "Chip"] не то сделал, исправь ответ и покажи проверку', 1002),
            ])
            old = os.environ.get('SUBC_HERMES_STATE_DB')
            os.environ['SUBC_HERMES_STATE_DB'] = str(db)
            try:
                obs = CorrectionMiningAdapter().collect(limit=10)
            finally:
                if old is None:
                    os.environ.pop('SUBC_HERMES_STATE_DB', None)
                else:
                    os.environ['SUBC_HERMES_STATE_DB'] = old
        self.assertEqual(len(obs), 1)
        evidence = obs[0]['metadata']['evidence_items']
        self.assertEqual(len(evidence), 1)
        self.assertIn('msg:2', evidence[0]['evidence_uri'])
        self.assertNotIn('вебинара', evidence[0]['summary'].lower())

    def test_correction_mining_classifies_model_provider_failure_as_skill_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'state.db'
            make_state_db(db, [
                ('s1', 'user', '[Replying to: "⚠️ The model provider failed after retries."]\n[Evgeny "Chip"] почему ты не мог отработать на h20-fusion? чини эту модель', 1001),
            ])
            old = os.environ.get('SUBC_HERMES_STATE_DB')
            os.environ['SUBC_HERMES_STATE_DB'] = str(db)
            try:
                obs = CorrectionMiningAdapter().collect(limit=10)
            finally:
                if old is None:
                    os.environ.pop('SUBC_HERMES_STATE_DB', None)
                else:
                    os.environ['SUBC_HERMES_STATE_DB'] = old
        self.assertEqual(len(obs), 1)
        meta = obs[0]['metadata']
        self.assertEqual(meta['primary_bucket'], 'model_provider_routing_skill')
        self.assertEqual(meta['suggested_patch_type'], 'skill')
        candidate = meta['candidate_patch']
        self.assertEqual(candidate['patch_type'], 'skill')
        self.assertEqual(candidate['target'], 'project/human20-keys references/h20-fusion-hermes-profile-routing.md')
        self.assertIn('profile home', candidate['action'])
        summaries = ' '.join(item['summary'] for item in candidate['evidence_items'])
        self.assertIn('profile/env/streaming/smoke', summaries)
        self.assertNotIn('чини эту модель', summaries.lower())

    def test_correction_mining_groups_multiple_clean_corrections_into_one_patch_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'state.db'
            make_state_db(db, [
                ('s1', 'user', '[Evgeny "Chip"] опять руками повторяю, автоматизируй это командой', 1001),
                ('s1', 'user', '[Evgeny "Chip"] не пиши так, это slop, поправь guard', 1002),
                ('s1', 'user', '[Evgeny "Chip"] где результат, почему ты не проверил?', 1003),
            ])
            old = os.environ.get('SUBC_HERMES_STATE_DB')
            os.environ['SUBC_HERMES_STATE_DB'] = str(db)
            try:
                obs = CorrectionMiningAdapter().collect(limit=10)
            finally:
                if old is None:
                    os.environ.pop('SUBC_HERMES_STATE_DB', None)
                else:
                    os.environ['SUBC_HERMES_STATE_DB'] = old
        self.assertEqual(len(obs), 1)
        meta = obs[0]['metadata']
        self.assertEqual(meta['proposal_id'], 'chip-correction-mining-loop')
        self.assertEqual(meta['correction_count'], 3)
        self.assertEqual(meta['correction_buckets']['promise_reality_guard'], 1)
        self.assertEqual(meta['correction_buckets']['style_slop_eval'], 1)
        self.assertEqual(meta['correction_buckets']['manual_repeat_skill'], 1)
        self.assertEqual(meta['primary_bucket'], 'promise_reality_guard')
        self.assertEqual(meta['suggested_patch_type'], 'guard')
        self.assertEqual(len(meta['evidence_items']), 3)
        self.assertTrue(all(item['evidence_uri'].startswith('session:s1#msg:') for item in meta['evidence_items']))
        self.assertIn('guard', meta['proposed_action'])

    def test_correction_mining_redacts_candidate_patch_evidence_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'state.db'
            make_state_db(db, [
                ('s1', 'user', '[Evgeny "Chip"] я не понимаю, какого хера ты остановился. Transcript text file was written to: /home/hermes/.hermes/audio_cache/raw.txt', 1001),
                ('s1', 'user', '[Evgeny "Chip"] Я не разрешал тебе это делать, надо было сначала спросить перед тем как такое делать. Как это откатить?', 1002),
            ])
            old = os.environ.get('SUBC_HERMES_STATE_DB')
            os.environ['SUBC_HERMES_STATE_DB'] = str(db)
            try:
                obs = CorrectionMiningAdapter().collect(limit=10)
            finally:
                if old is None:
                    os.environ.pop('SUBC_HERMES_STATE_DB', None)
                else:
                    os.environ['SUBC_HERMES_STATE_DB'] = old
        self.assertEqual(len(obs), 1)
        candidate = obs[0]['metadata']['candidate_patch']
        summaries = ' '.join(item['summary'] for item in candidate['evidence_items'])
        self.assertIn('session:s1#msg:', candidate['evidence_items'][0]['evidence_uri'])
        for forbidden in ['какого', 'хера', 'Transcript text file', '/home/hermes', 'Я не разрешал']:
            self.assertNotIn(forbidden.lower(), summaries.lower())
        self.assertIn('сырой текст скрыт', summaries)

    def test_openclaw_semantic_adapter_clusters_repeated_failures_into_one_proposal(self):
        adapter = OpenClawSemanticAdapter()
        adapter._scan_target = lambda target, limit: {
            'ok': True,
            'agents': [
                {'agent': 'main', 'exists': True, 'issue_count': 3, 'recent_sessions': [
                    {'issue_terms': {'failed': 2, 'timeout': 1}, 'snippets': ['ssh timeout 100.69.179.41:22']},
                ]},
                {'agent': 'chiptask', 'exists': True, 'issue_count': 2, 'recent_sessions': [
                    {'issue_terms': {'failed': 1, 'timeout': 1}, 'snippets': ['NO_REPLY after handoff']},
                ]},
            ],
        }
        obs = adapter.collect(limit=10)
        self.assertEqual(len(obs), 1)
        meta = obs[0]['metadata']
        self.assertEqual(meta['proposal_id'], 'openclaw-semantic-session-failures')
        self.assertEqual(meta['affected_agents'], ['main', 'chiptask'])
        self.assertGreaterEqual(meta['issue_count'], 5)
        self.assertIn('cluster', meta)
        self.assertIn('OpenClaw handoff/session failures', obs[0]['summary'])

    def test_promise_reality_adapter_flags_approved_build_without_verified_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            (room / 'approved_builds').mkdir()
            (room / 'shaw_runs').mkdir()
            (room / 'approved_builds' / 'intent_demo.yaml').write_text('''schema_version: "1.0"\nid: "intent_demo"\ntitle: "Demo Build"\nstatus: "approved"\n''')
            old = os.environ.get('SUBC_ROOM')
            os.environ['SUBC_ROOM'] = str(room)
            try:
                obs = PromiseRealityAdapter().collect(limit=10)
            finally:
                if old is None:
                    os.environ.pop('SUBC_ROOM', None)
                else:
                    os.environ['SUBC_ROOM'] = old
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]['source'], 'promise-reality')
        self.assertEqual(obs[0]['metadata']['proposal_id'], 'promise-reality-gate')
        self.assertIn('approved build has no verified Shaw run', obs[0]['summary'])

    def test_opportunity_score_orders_chip_value_above_infra(self):
        chip = {'id': 'chip-correction-mining-loop', 'signal_types': ['repeat'], 'evidence': [{'chip_value_signal': True}], 'score': 7}
        infra = {'id': 'mem0g-health-issue', 'signal_types': ['blocker'], 'evidence': [{}], 'score': 10}
        self.assertGreater(opportunity_score(chip), opportunity_score(infra))

    def test_digest_v2_limits_to_three_and_renders_proposal_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            for d in ['pending_intents', 'walk_logs', 'approved_builds', 'shaw_runs']:
                (room / d).mkdir()
            (room / 'summary.json').write_text(json.dumps({'lanes': {}}, ensure_ascii=False))
            posted = {'posted': {}, 'tokens': {}}
            for idx in range(4):
                iid = f'intent_chip-value-{idx}'
                posted['posted'][iid] = {'message_id': 100 + idx, 'callback_token': f't{idx}'}
                (room / 'pending_intents' / f'{iid}.yaml').write_text(f'''schema_version: "1.0"\nid: "{iid}"\ntitle: "Chip value {idx}"\nsuggested_build: "Action {idx}"\nrisk: "Risk {idx}"\nstatus: "pending_approval"\nevidence:\n  - evidence_uri: "session:s#msg:{idx}"\n    summary: "Evidence {idx}"\n''')
            (room / 'posted_pending_intents.json').write_text(json.dumps(posted, ensure_ascii=False))
            text = build_digest(room, timestamp='2026-05-29T09:00:00Z')
        self.assertIn('proposal_id: intent_chip-value-0', text)
        self.assertIn('proposal_id: intent_chip-value-2', text)
        self.assertNotIn('Chip value 3', text)

    def test_signal_from_semantic_observation_carries_action_and_risk(self):
        obs = {
            'source': 'openclaw-semantic',
            'source_adapter': 'OpenClawSemanticAdapter',
            'evidence_uri': 'ssh:demo',
            'summary': 'OpenClaw handoff/session failures cluster: timeout/no_reply',
            'metadata': {
                'proposal_id': 'openclaw-semantic-session-failures',
                'title': 'Cluster OpenClaw NO_REPLY/timeouts',
                'proposed_action': 'Group failed handoffs and fix one root cause.',
                'risk': 'Handoffs keep failing silently.',
                'chip_value_signal': True,
                'score_delta': 8.2,
            },
        }
        sid, title, types, delta, ev = signal_from_obs(obs)
        self.assertEqual(sid, 'openclaw-semantic-session-failures')
        self.assertIn('repeat', types)
        self.assertGreater(delta, 8)
        self.assertEqual(ev['proposed_action'], 'Group failed handoffs and fix one root cause.')
        self.assertTrue(ev['chip_value_signal'])

    def test_correction_candidate_survives_signal_and_intent_yaml(self):
        obs = {
            'source': 'correction-mining',
            'source_adapter': 'CorrectionMiningAdapter',
            'evidence_uri': 'session:s1#msg:7',
            'summary': 'Chip correction mining grouped 1 clean recent correction(s). Proposed patch type: eval.',
            'metadata': {
                'proposal_id': 'chip-correction-mining-loop',
                'title': 'Превращать повторяющиеся правки Chip в guards/evals/skills',
                'proposed_action': 'Добавить eval/skill patch на повторяющуюся стилевую правку Chip.',
                'risk': 'ручные правки повторятся',
                'chip_value_signal': True,
                'score_delta': 8.0,
                'pattern_type': 'correction_mining',
                'suggested_patch_type': 'eval',
                'candidate_patch': {
                    'schema_version': '1.0',
                    'status': 'candidate',
                    'patch_type': 'eval',
                    'title': 'Candidate eval from Chip correction',
                    'target': 'TBD by Shaw/Hermes after approval',
                    'action': 'Добавить eval/skill patch на повторяющуюся стилевую правку Chip.',
                    'source': 'chip-explicit-correction',
                    'privacy': 'redacted_session_pointers_only',
                    'evidence_items': [{'evidence_uri': 'session:s1#msg:7', 'bucket': 'style_slop_eval', 'summary': 'не пиши так'}],
                },
            },
        }
        sid, title, types, delta, ev = signal_from_obs(obs)
        sig = {'id': sid, 'title': title, 'signal_types': types, 'score': delta, 'status': 'pending_intent', 'evidence': [ev]}
        intent = build_intent(sig)
        self.assertEqual(intent['candidate_patch']['patch_type'], 'eval')
        self.assertIn('candidate eval', intent['problem'])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'intent.yaml'
            write_intent_yaml(path, intent)
            text = path.read_text()
        self.assertIn('candidate_patch:', text)
        self.assertIn('patch_type: "eval"', text)
        self.assertIn('privacy: "redacted_session_pointers_only"', text)


if __name__ == '__main__':
    unittest.main()
