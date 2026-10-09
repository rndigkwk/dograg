"""scripts/check_deployed_app.py: what counts as a broken page."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_deployed_app import error_in  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
