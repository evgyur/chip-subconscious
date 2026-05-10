import subprocess, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT

class TransitionTests(unittest.TestCase):
    def test_subconscious_cannot_approve(self):
        p=subprocess.run(['python3',str(BASE/'scripts/subc_transition.py'),'--intent-id','missing','--decision','approved','--approver','SUBCONSCIOUS','--dry-run'], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('cannot', (p.stderr+p.stdout).lower())
    def test_unconfigured_approver_cannot_approve(self):
        p=subprocess.run(['python3',str(BASE/'scripts/subc_transition.py'),'--intent-id','missing','--decision','approved','--approver','random-agent','--dry-run'], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('not allowed', (p.stderr+p.stdout).lower())
if __name__ == '__main__': unittest.main()
