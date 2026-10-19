"""scripts/release_check.py: a stale Supabase chunk is caught, and every failing check has a fix (2026-10-19)."""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import release_check


class ReleaseCheckTests(unittest.TestCase):
    def test_a_chunk_whose_text_differs_fails_the_report_table(self):
        with TemporaryDirectory() as directory:
            store = Path(directory)
            for name, rows in (("report", [("a", "39.2%"), ("b", "본문")]), ("health", [("h", "x")])):
                (store / name).mkdir()
                (store / name / "documents.jsonl").write_text(
                    "".join(json.dumps({"id": i, "text": t}, ensure_ascii=False) + "\n" for i, t in rows), encoding="utf-8")
            conn = MagicMock()
            conn.__enter__.return_value = conn
            conn.execute.side_effect = lambda sql: MagicMock(
                fetchall=lambda: [("a", "59.2%"), ("b", "본문")], fetchone=lambda: (1,))
            with patch.object(release_check, "STORE", store), \
                    patch("src.supabase_store.connector", return_value=lambda: conn), \
                    patch("src.settings.get_setting", return_value="postgresql://example"):
                (report_name, report_ok, detail), (_, health_ok, _) = release_check.check_tables()
        self.assertEqual(report_name, "report table")
        self.assertFalse(report_ok)
        self.assertIn("different text 1 (e.g. a)", detail)
        self.assertTrue(health_ok)

    def test_every_check_has_a_fix(self):
        self.assertEqual(set(release_check.FIX),
                         {"git", "revision", "local data", "report table", "health table", "api"})


if __name__ == "__main__":
    unittest.main()
