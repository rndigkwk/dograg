"""main.py (P5, 2026-10-23): the old Streamlit address shows where the web app is, on every old page."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

MAIN = str(Path(__file__).resolve().parents[1] / "main.py")


class MovedNoticeTests(unittest.TestCase):
    def test_the_notice_links_to_the_web_app_and_loads_no_data(self):
        with patch.dict(os.environ, {"STREAMLIT_FULL_APP": ""}),                 patch("src.private_data.ensure", side_effect=AssertionError("no data download")):
            app = AppTest.from_file(MAIN, default_timeout=30).run()
        self.assertEqual([error.message for error in app.exception], [])
        self.assertIn("새 주소로 옮겼어요", app.title[0].value)
        self.assertTrue(any("ragdog-rndigkwks-projects.vercel.app" in caption.value for caption in app.caption))


if __name__ == "__main__":
    unittest.main()
