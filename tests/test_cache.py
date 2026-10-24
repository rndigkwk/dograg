"""src/cache.py and the API's imports: the API process loads no Streamlit or chart library."""

import subprocess
import sys
import threading
import time
import unittest

from src.cache import cache_resource
from src.settings import PROJECT_DIR


class CacheResourceTests(unittest.TestCase):
    def test_loads_once_until_cleared(self):
        calls = []

        @cache_resource
        def load():
            calls.append(1)
            return object()

        first = load()
        self.assertIs(load(), first)
        load.clear()
        self.assertIsNot(load(), first)
        self.assertEqual(len(calls), 2)

    def test_concurrent_first_calls_load_once(self):
        calls = []

        @cache_resource
        def load():
            calls.append(1)
            time.sleep(0.05)
            return len(calls)

        threads = [threading.Thread(target=load) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(calls, [1])


class ApiImportTests(unittest.TestCase):
    def test_api_imports_no_ui_library(self):
        code = ("import sys, api.main; "
                "print(sorted(m for m in ('streamlit', 'plotly', 'matplotlib', 'pandas') if m in sys.modules))")
        out = subprocess.run([sys.executable, "-c", code], cwd=PROJECT_DIR, capture_output=True, text=True,
                             timeout=300, check=True).stdout
        self.assertEqual(out.strip().splitlines()[-1], "[]")


if __name__ == "__main__":
    unittest.main()
