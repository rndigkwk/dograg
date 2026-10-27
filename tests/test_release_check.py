"""scripts/release_check.py: a stale Supabase chunk is caught, and every failing check has a fix (2026-10-19)."""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import release_check


class ReleaseCheckTests(unittest.TestCase):
    def check(self, remote_report, remote_health_text, remote_vectors):
        """check_tables() on a local store of two report chunks and one health row (vector [0.6, 0.8])."""
        with TemporaryDirectory() as directory:
            store = Path(directory)
            for name, rows in (("report", [("a", "39.2%"), ("b", "본문")]), ("health", [("h", "x")])):
                (store / name).mkdir()
                (store / name / "documents.jsonl").write_text(
                    "".join(json.dumps({"id": i, "text": t}, ensure_ascii=False) + "\n" for i, t in rows), encoding="utf-8")
            np.save(store / "health" / "vectors.npy", np.array([[0.6, 0.8]], dtype=np.float32))

            def execute(sql, params=None):
                rows = remote_vectors if "embedding" in sql else remote_health_text if "sha256" in sql else remote_report
                return MagicMock(fetchall=lambda: rows)

            conn = MagicMock()
            conn.__enter__.return_value = conn
            conn.execute.side_effect = execute
            with patch.object(release_check, "STORE", store), \
                    patch("src.supabase_store.connector", return_value=lambda: conn), \
                    patch("src.settings.get_setting", return_value="postgresql://example"):
                return release_check.check_tables()

    def test_a_chunk_whose_text_differs_fails_the_report_table(self):
        (report_name, report_ok, detail), (_, health_ok, _) = self.check(
            [("a", "59.2%"), ("b", "본문")], [("h", release_check.text_hash("x"))], [("h", "[0.6,0.8]")])
        self.assertEqual(report_name, "report table")
        self.assertFalse(report_ok)
        self.assertIn("different text 1 (e.g. a)", detail)
        self.assertTrue(health_ok)

    def test_the_health_table_fails_on_other_text_or_other_vectors_with_the_same_row_count(self):
        report = [("a", "39.2%"), ("b", "본문")]
        _, (_, ok, detail) = self.check(report, [("h", release_check.text_hash("y"))], [("h", "[0.6,0.8]")])
        self.assertFalse(ok)
        self.assertIn("different text 1", detail)
        _, (_, ok, detail) = self.check(report, [("h", release_check.text_hash("x"))], [("h", "[0.8,0.6]")])
        self.assertFalse(ok)
        self.assertIn("vectors differ 1/1 (e.g. h)", detail)
        _, (_, ok, _) = self.check(report, [("h", release_check.text_hash("x"))], [("h", "[0.6001,0.7998]")])
        self.assertTrue(ok)  # float16 rounding in halfvec

    def test_every_check_has_a_fix(self):
        self.assertEqual(set(release_check.FIX),
                         {"git", "revision", "local data", "report table", "health table", "api"})


if __name__ == "__main__":
    unittest.main()
