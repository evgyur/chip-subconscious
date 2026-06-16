import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from subc_walk import update_board


class WalkBoardTests(unittest.TestCase):
    def test_update_board_replaces_latest_discovery_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = Path(tmp)
            obs1 = [{'source': 'hermes', 'summary': 'first', 'evidence_uri': 'file:/home/hermes/secret.txt'}]
            obs2 = [{'source': 'mem0g', 'summary': 'second', 'evidence_uri': 'session:s2'}]

            update_board(room, obs1)
            update_board(room, obs2)
            text = (room / 'signal-board.md').read_text()

            self.assertEqual(text.count('## Latest read-only discovery'), 1)
            self.assertIn('second', text)
            self.assertNotIn('first', text)
            self.assertNotIn('/home/hermes/secret.txt', text)


if __name__ == '__main__':
    unittest.main()
