import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from subc_common import ReadOnlyCommandRunner, redact
from subc_adapters import collect_sources

class SafetyTests(unittest.TestCase):
    def test_forbidden_command_rejected(self):
        r=ReadOnlyCommandRunner()
        with self.assertRaises(PermissionError):
            r.assert_allowed(['systemctl','restart','mem0g-api'])
    def test_secret_redaction(self):
        token = 'sk-' + 'abcdefghijklmnopqrstuvwxyz'
        self.assertIn('<REDACTED>', redact(f'API_KEY={token}'))

class AdapterTests(unittest.TestCase):
    def test_collect_project_flow(self):
        obs=collect_sources('project-flow', 3)
        self.assertTrue(isinstance(obs, list))
        if obs:
            self.assertIn('evidence_uri', obs[0])
            self.assertIn('source_adapter', obs[0])

if __name__ == '__main__': unittest.main()
