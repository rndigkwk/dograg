"""scripts/eval_history.py: recording never breaks a check, and the table is closed like the others."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_history  # noqa: E402

from src import supabase_store  # noqa: E402


class RecordTests(unittest.TestCase):
    def test_nothing_without_a_database(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(eval_history.record("deploy", "cloud-run", True, {}))

    def test_nothing_unless_the_workflow_asks(self):
        # The URL alone comes from .env on any machine (src/settings.py); only the workflows set the flag.
        with patch.dict("os.environ", {"SUPABASE_DB_URL": "postgresql://x"}, clear=True),                 patch("psycopg.connect") as connect:
            self.assertFalse(eval_history.record("regression", "crag", True, {}))
        connect.assert_not_called()

    def test_a_failing_database_does_not_raise(self):
        with patch.dict("os.environ", {"SUPABASE_DB_URL": "postgresql://x", "RAGDOG_EVAL_HISTORY": "1"}), \
                patch("psycopg.connect", side_effect=OSError("down")):
            self.assertFalse(eval_history.record("deploy", "cloud-run", True, {}))

    def test_a_row_in_a_locked_table(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        with patch.dict("os.environ", {"SUPABASE_DB_URL": "postgresql://x", "GITHUB_SHA": "abc1234",
                                       "RAGDOG_EVAL_HISTORY": "1"}), \
                patch("psycopg.connect", return_value=conn):
            self.assertTrue(eval_history.record("regression", "crag", False, {"accuracy": 0.8}, run="ci-1"))
        statements = [call.args[0] for call in conn.execute.call_args_list]
        self.assertIn("enable row level security", statements[1])
        insert = conn.execute.call_args_list[-1].args[1]
        self.assertEqual(insert[:5], ["regression", "crag", "ci-1", "abc1234", False])

    def test_the_lock_matches_the_app_tables(self):
        conn = MagicMock()
        supabase_store.lock_from_data_api(conn, eval_history.TABLE)
        self.assertEqual(tuple(call.args[0] for call in conn.execute.call_args_list), eval_history.LOCK)


if __name__ == "__main__":
    unittest.main()
