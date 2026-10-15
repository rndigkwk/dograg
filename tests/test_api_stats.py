"""api/stats.py: the data page's numbers, counts only (no consultation text, no model calls)."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import main
from src import data_stats
from src.places_data import KIND_LABELS


class StatsApiTests(unittest.TestCase):
    def test_the_overview_has_the_four_charts(self):
        stats = TestClient(main.create_app()).get("/stats/overview").json()
        diseases = [row["label"] for row in stats["diseases"]]
        self.assertEqual(len(diseases), 10)
        self.assertNotIn("기타", diseases)
        counts = [row["count"] for row in stats["diseases"]]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertEqual({row["label"] for row in stats["departments"]} >= {"내과", "외과", "피부과", "안과", "치과"}, True)
        self.assertEqual(stats["hospitals_by_province"][0]["label"], "경기도")
        self.assertEqual([row["kind"] for row in stats["place_sources"]], list(KIND_LABELS))
        self.assertNotIn("file", stats["place_sources"][0])
        self.assertIsInstance(stats["place_sources"][0]["notes"], list)

    def test_only_counts_leave(self):
        stats = TestClient(main.create_app()).get("/stats/overview").json()
        for chart in ("diseases", "departments", "hospitals_by_province"):
            for row in stats[chart]:
                self.assertEqual(set(row), {"label", "count"})
                self.assertLess(len(row["label"]), 20)

    def test_a_missing_file_is_a_503_not_a_crash(self):
        with patch.object(data_stats, "disease_counts", side_effect=data_stats.StatsUnavailable("비어 있음")):
            response = TestClient(main.create_app()).get("/stats/overview")
        self.assertEqual((response.status_code, response.json()["detail"]), (503, "비어 있음"))


if __name__ == "__main__":
    unittest.main()
