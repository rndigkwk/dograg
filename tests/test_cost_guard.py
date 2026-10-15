"""scripts/cost_guard.py: large evaluation runs stop unless asked to go on."""

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import cost_guard  # noqa: E402


class CostGuardTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for item in (patch.object(cost_guard, "LOG", Path(directory.name) / "calls.jsonl"),
                     patch.dict("os.environ", {"CI": "", "RAGDOG_EVAL_YES": ""}),
                     patch("sys.stdout", io.StringIO())):
            item.start()
            self.addCleanup(item.stop)

    def test_small_runs_go_on_and_are_counted(self):
        self.assertTrue(cost_guard.confirm("a", 50))
        self.assertTrue(cost_guard.confirm("b", 150))
        self.assertEqual(cost_guard.today_total(), 200)

    def test_large_runs_stop_without_someone_saying_yes(self):
        with patch("sys.stdin", io.StringIO("")):
            self.assertFalse(cost_guard.confirm("big", 360))
        self.assertEqual(cost_guard.today_total(), 0)
        self.assertTrue(cost_guard.confirm("big", 360, yes=True))
        with patch.dict("os.environ", {"CI": "true"}):
            self.assertTrue(cost_guard.confirm("big", 360))
        self.assertEqual(cost_guard.today_total(), 720)

    def test_a_terminal_without_input_stops(self):
        terminal = io.StringIO("")
        terminal.isatty = lambda: True
        with patch("sys.stdin", terminal):
            self.assertFalse(cost_guard.confirm("big", 360))


if __name__ == "__main__":
    unittest.main()
