"""scripts/check_deployed_app.py: what counts as a broken page."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_deployed_app import CHECK_AGENT, error_in, same_commit, summary_line  # noqa: E402

from src import data_gaps  # noqa: E402

# The chat page on 2026-10-09, redeployed without a reboot (Streamlit Cloud redacts the message).
DEPLOYED_IMPORT_ERROR = (
    "ImportError: This app has encountered an error. The original error message is redacted to "
    "prevent data leaks.\nTraceback:\nFile \"/mount/src/dograg/app_pages/rag.py\", line 12, in <module>"
)


class ErrorDetectionTests(unittest.TestCase):
    def test_the_redacted_cloud_error_is_found(self):
        self.assertIn("This app has encountered an error", error_in(["사이드바", DEPLOYED_IMPORT_ERROR]))

    def test_a_local_traceback_is_found(self):
        self.assertIsNotNone(error_in(["ImportError: cannot import name 'X'\nTraceback:\nFile ..."]))

    def test_an_error_box_counts_even_without_text(self):
        self.assertEqual(error_in([""], error_boxes=1), "Streamlit error box")

    def test_a_working_page_has_no_error(self):
        self.assertIsNone(error_in(["라그도그\n질병 문의\n오늘은 2026년 10월 9일입니다."]))


class SummaryTests(unittest.TestCase):
    def test_a_working_deployment_shows_its_times(self):
        self.assertEqual(summary_line("https://x.run.app", 12.4, 1.2, [], 9.6), "| https://x.run.app | 12s | 1s | 10s | ok |")

    def test_a_failed_deployment_shows_the_problem(self):
        self.assertEqual(summary_line("https://x", None, None, ["did not become ready"]),
                         "| https://x | - | - | - | did not become ready |")


class CommitTests(unittest.TestCase):
    def test_short_and_full_hashes_of_one_commit_match(self):
        self.assertTrue(same_commit("027492d", "027492d1a2b3c4d5e6f708192a3b4c5d6e7f8091"))
        self.assertTrue(same_commit("027492d1a2b3c4d5e6f708192a3b4c5d6e7f8091", "027492d1a2b3c4d5e6f708192a3b4c5d6e7f8091"))

    def test_another_or_missing_commit_does_not(self):
        self.assertFalse(same_commit("a9deab1", "027492d1a2b3c4d5e6f708192a3b4c5d6e7f8091"))
        self.assertFalse(same_commit(None, "027492d1"))
        self.assertFalse(same_commit("0274", "027492d1"))  # too short to trust


class FooterTests(unittest.TestCase):
    def test_footer_carries_the_commit_without_showing_it(self):
        from src.ui import footer_html

        self.assertIn('data-commit="027492d"', footer_html("027492d"))
        self.assertNotIn("data-commit", footer_html(None))



class CheckAgentTests(unittest.TestCase):
    def test_the_app_knows_the_check_browser(self):
        self.assertEqual(CHECK_AGENT, data_gaps.CHECK_AGENT)

if __name__ == "__main__":
    unittest.main()
