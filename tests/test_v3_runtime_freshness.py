from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from subc_v3_prepare_runtime import _invalidate_model_output


class RuntimeFreshnessTests(unittest.TestCase):
    def test_prepare_invalidates_stale_model_output_before_evaluation(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            stale = runtime / "model_output.json"
            stale.write_text('{"status":"ok","proposals":[{"stale":true}]}')

            _invalidate_model_output(runtime)

            self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
