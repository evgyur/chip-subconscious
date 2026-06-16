import json, subprocess, tempfile, unittest
from pathlib import Path
BASE = str(Path(__file__).resolve().parents[1])

class BuildPacketTests(unittest.TestCase):
    def test_build_packet_from_approved_intent(self):
        with tempfile.TemporaryDirectory() as td:
            room=Path(td)
            (room/'approved_builds').mkdir()
            intent=room/'approved_builds'/'intent_fixture.yaml'
            intent.write_text('''schema_version: "1.0"\nid: "intent_fixture"\ntitle: "Fixture"\nproblem: "Need verify fixture"\nsuggested_build: "Build fixture packet"\nstatus: "approved"\n''')
            (room/'approval_events.jsonl').write_text(json.dumps({'schema_version':'1.0','intent_id':'intent_fixture','decision':'approved','approver':'Chip'})+'\n')
            p=subprocess.run(['python3',f'{BASE}/scripts/subc_build_packet.py','--room',str(room),'--intent-id','intent_fixture'], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr+p.stdout)
            out=json.loads((room/'build_packets'/'intent_fixture.json').read_text())
            self.assertEqual(out['schema_version'], '1.0')
            self.assertEqual(out['intent_id'], 'intent_fixture')
            self.assertIn('acceptance_criteria', out)
            self.assertEqual(out['executor'], 'shaw')
            self.assertIn('Shaw', out['handoff'])
            self.assertNotIn('TBD', ' '.join(out.get('tests') or []))

    def test_build_packet_refuses_non_approved_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            room=Path(td)
            (room/'approved_builds').mkdir()
            intent=room/'approved_builds'/'intent_fixture.yaml'
            intent.write_text('''schema_version: "1.0"\nid: "intent_fixture"\nstatus: "pending_approval"\n''')
            (room/'approval_events.jsonl').write_text(json.dumps({'schema_version':'1.0','intent_id':'intent_fixture','decision':'approved','approver':'Chip'})+'\n')
            p=subprocess.run(['python3',f'{BASE}/scripts/subc_build_packet.py','--room',str(room),'--intent-id','intent_fixture'], capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('non-approved status', p.stderr+p.stdout)

    def test_build_packet_refuses_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as td:
            room=Path(td)
            (room/'approved_builds').mkdir(); (room/'build_packets').mkdir()
            intent=room/'approved_builds'/'intent_fixture.yaml'
            intent.write_text('''schema_version: "1.0"\nid: "intent_fixture"\ntitle: "Fixture"\nstatus: "approved"\n''')
            (room/'approval_events.jsonl').write_text(json.dumps({'schema_version':'1.0','intent_id':'intent_fixture','decision':'approved','approver':'Chip'})+'\n')
            (room/'build_packets'/'intent_fixture.json').write_text('{}')
            p=subprocess.run(['python3',f'{BASE}/scripts/subc_build_packet.py','--room',str(room),'--intent-id','intent_fixture'], capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('refusing overwrite', p.stderr+p.stdout)

if __name__ == '__main__': unittest.main()
