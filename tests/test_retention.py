"""3-year retention of feedback and data-gap rows (scripts/sql/retention.sql): asked once a day, never fatal."""

import unittest
from unittest.mock import MagicMock, patch

from src import supabase_store


class ExpireOldRowsTests(unittest.TestCase):
    def setUp(self):
        supabase_store._expired_on = None
        self.addCleanup(setattr, supabase_store, "_expired_on", None)

    def test_once_a_day(self):
        conn = MagicMock()
        supabase_store.expire_old_rows(conn, today="2026-10-17")
        supabase_store.expire_old_rows(conn, today="2026-10-17")
        supabase_store.expire_old_rows(conn, today="2026-10-18")
        self.assertEqual(conn.execute.call_count, 2)
        conn.execute.assert_called_with("select public.ragdog_expire_old_rows()")

    def test_a_missing_function_does_not_break_the_write(self):
        conn = MagicMock()
        conn.execute.side_effect = RuntimeError("function public.ragdog_expire_old_rows() does not exist")
        with self.assertLogs("src.supabase_store", level="WARNING"):
            supabase_store.expire_old_rows(conn, today="2026-10-17")

    def test_data_gap_writes_ask_for_it(self):
        from src import data_gaps

        conn = MagicMock()
        connector = MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=conn), __exit__=MagicMock(return_value=False)))
        with patch("src.supabase_store.connector", return_value=connector), \
                patch("src.supabase_store.table_exists", return_value=True), \
                patch("src.supabase_store.expire_old_rows") as expire:
            data_gaps._insert([("rag", "missing", "자료에 없음")])
        expire.assert_called_once_with(conn)


if __name__ == "__main__":
    unittest.main()
