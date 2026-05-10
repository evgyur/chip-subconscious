import json, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT

class BuildPacketTests(unittest.TestCase):
    def test_build_packet_from_approved_intent(self):
        with tempfile.TemporaryDirectory() as td:
            room=Path(td)
            (room/'approved_builds').mkdir()
            intent=room/'approved_builds'/'intent_fixture.yaml'
            intent.write_text('''schema_version: "1.0"\nid: "intent_fixture"\ntitle: "Fixture"\nproblem: "Need verify fixture"\nsuggested_build: "Build fixture packet"\n''')
            p=subprocess.run(['python3',str(BASE/'scripts/subc_build_packet.py'),'--room',str(room),'--intent-id','intent_fixture'], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr+p.stdout)
            out=json.loads((room/'build_packets'/'intent_fixture.json').read_text())
            self.assertEqual(out['schema_version'], '1.0')
            self.assertEqual(out['intent_id'], 'intent_fixture')
            self.assertIn('acceptance_criteria', out)

if __name__ == '__main__': unittest.main()
