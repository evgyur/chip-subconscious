import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from subc_score import status_for
from subc_publish import ROUTES

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

if __name__ == '__main__': unittest.main()
