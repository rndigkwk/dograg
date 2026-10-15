import unittest
from unittest.mock import MagicMock, patch

from src import feedback_store


def db_conn(table_exists: bool):
    """A connection whose to_regclass answers whether the table exists; every statement is recorded."""
    conn = MagicMock()
    conn.__enter__.return_value = conn

    def execute(sql, *args):
        result = MagicMock()
        result.fetchone.return_value = ("public.t" if table_exists else None,)
        return result

    conn.execute.side_effect = execute
    return conn


DDL = ("create table", "create index", "enable row level security", "revoke all")


class FeedbackStoreTests(unittest.TestCase):
    def test_nothing_is_stored_without_a_database(self):
        with patch.object(feedback_store.settings, "get_setting", return_value=None):
            self.assertFalse(feedback_store.enabled())
            self.assertFalse(feedback_store.save_review(question="q", answer="a", reason=None, route="rag", trace_id="t"))

    def test_the_question_is_stored_masked_and_the_table_closed_to_the_public_api(self):
        conn = db_conn(table_exists=False)
        feedback_store._ready.clear()
        with patch.object(feedback_store.settings, "get_setting", return_value="postgresql://x"),                 patch("src.supabase_store.connector", return_value=lambda: conn):
            self.assertTrue(feedback_store.save_review(question="기침해요 010-1234-5678", answer="답", reason="틀린 정보",
                                                       route="rag", trace_id="t", evidence=["사례 1"]))
        statements = [call.args[0] for call in conn.execute.call_args_list]
        self.assertTrue(any("enable row level security" in sql for sql in statements))
        self.assertTrue(any("revoke all" in sql for sql in statements))
        insert = conn.execute.call_args_list[-1].args[1]
        self.assertEqual(insert[3], "기침해요 [전화번호]")
        self.assertNotIn("010", insert[3])

    def test_an_existing_table_is_not_created_or_locked_again(self):
        conn = db_conn(table_exists=True)
        feedback_store._ready.clear()
        with patch.object(feedback_store.settings, "get_setting", return_value="postgresql://x"),                 patch("src.supabase_store.connector", return_value=lambda: conn):
            self.assertTrue(feedback_store.save_review(question="q", answer="a", reason=None, route="rag", trace_id="t"))
        statements = [call.args[0] for call in conn.execute.call_args_list]
        self.assertFalse([sql for sql in statements if any(word in sql for word in DDL)])

    def test_a_database_error_does_not_break_the_page(self):
        with patch.object(feedback_store.settings, "get_setting", return_value="postgresql://x"),                 patch("src.supabase_store.connector", side_effect=OSError("down")),                 self.assertLogs("src.feedback_store", level="WARNING"):
            self.assertFalse(feedback_store.save_review(question="q", answer="a", reason=None, route=None, trace_id=None))

    def test_evidence_keeps_labels_not_long_texts(self):
        row = {"meta.lifeCycle": "성견", "page": 3, "qa.output": "수의사 답변 " * 40}
        self.assertEqual(feedback_store.evidence_summary(row), {"meta.lifeCycle": "성견", "page": 3})


if __name__ == "__main__":
    unittest.main()
