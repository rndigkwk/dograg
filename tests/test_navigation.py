"""Page files live in app_pages/, not pages/.

With a `pages/` folder next to main.py, Streamlit keeps its old multipage mode until
main.py has run once in the server process (PagesManager.uses_pages_directory). After a
restart, a first visit to a deep link such as /rag then ran the page file without
main.py: no st.navigation menu, no conversation sidebar.
"""

import unittest
from pathlib import Path

from src.ui import NAVIGATION_GROUPS

PROJECT_DIR = Path(__file__).resolve().parents[1]


class NavigationTests(unittest.TestCase):
    def test_no_auto_discovered_pages_folder(self):
        self.assertFalse((PROJECT_DIR / "pages").exists())

    def test_every_navigation_page_exists(self):
        paths = [item["path"] for group in NAVIGATION_GROUPS for item in group["items"]]
        self.assertEqual([path for path in paths if not (PROJECT_DIR / path).is_file()], [])
        self.assertTrue(all(path.startswith("app_pages/") for path in paths))


if __name__ == "__main__":
    unittest.main()
