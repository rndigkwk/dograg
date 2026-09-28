import subprocess
import sys
import unittest
from pathlib import Path


class LiveSmokeContractTest(unittest.TestCase):
    def test_refuses_without_explicit_opt_in(self):
        script = Path(__file__).with_name("live_model_smoke.py")
        result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--allow-external-corpus", result.stderr)


if __name__ == "__main__":
    unittest.main()
