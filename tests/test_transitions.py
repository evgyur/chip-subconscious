import json, subprocess, sys, tempfile, unittest
from pathlib import Path
BASE = str(Path(__file__).resolve().parents[1])
class TransitionTests(unittest.TestCase):
    def test_subconscious_cannot_approve(self):
        p=subprocess.run(['python3',f'{BASE}/scripts/subc_transition.py','--intent-id','missing','--decision','approved','--approver','SUBCONSCIOUS','--dry-run'], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('cannot', (p.stderr+p.stdout).lower())
    def test_unconfigured_approver_cannot_approve(self):
        p=subprocess.run(['python3',f'{BASE}/scripts/subc_transition.py','--intent-id','missing','--decision','approved','--approver','random-agent','--dry-run'], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('not allowed', (p.stderr+p.stdout).lower())
    def test_transition_marks_posted_state_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            for d in ['pending_intents', 'approved_builds', 'archive']:
                (room / d).mkdir()
            intent = room / 'pending_intents' / 'intent_demo.yaml'
            intent.write_text('schema_version: "1.0"\nid: "intent_demo"\nstatus: "pending_approval"\n')
            (room / 'posted_pending_intents.json').write_text(json.dumps({'posted': {'intent_demo': {'message_id': 123}}, 'tokens': {}}))
            (room / 'signals.json').write_text(json.dumps({'schema_version': '1.0', 'signals': {'demo': {'id': 'demo', 'status': 'pending_intent'}}}))
            p=subprocess.run(['python3',f'{BASE}/scripts/subc_transition.py','--room',str(room),'--intent-id','intent_demo','--decision','approved','--approver','Chip','--source-message-id','123'], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr+p.stdout)
            posted=json.loads((room / 'posted_pending_intents.json').read_text())
            self.assertEqual(posted['posted']['intent_demo']['decision'], 'approved')
            self.assertEqual(posted['posted']['intent_demo']['path'], str(room / 'approved_builds' / 'intent_demo.yaml'))
            self.assertFalse(intent.exists())
            self.assertTrue((room / 'approved_builds' / 'intent_demo.yaml').exists())
if __name__ == '__main__': unittest.main()
