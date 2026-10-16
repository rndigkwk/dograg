"""api/places.py: the place page's searches as JSON, on data/places.db (no model calls)."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import main
from src.places_data import KIND_LABELS

CITY_HALL = {"lat": 37.5665, "lon": 126.978}


class PlacesApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.create_app())

    def get(self, path, **params):
        return self.client.get(path, params=params)

    def test_kinds_say_which_can_be_searched_by_location(self):
        kinds = {row["kind"]: row for row in self.get("/places/kinds").json()}
        self.assertEqual(list(kinds), list(KIND_LABELS))
        self.assertTrue(kinds["hospital"]["has_location"])
        self.assertFalse(kinds["funeral"]["has_location"])
        self.assertGreater(kinds["hospital"]["source"]["rows"], 1000)

    def test_region_search_is_by_name_with_a_total(self):
        found = self.get("/places/search", kind="hospital", province="서울특별시", city="마포구", limit=5).json()
        self.assertGreater(found["total"], 5)
        self.assertEqual(len(found["places"]), 5)
        names = [place["name"] for place in found["places"]]
        self.assertEqual(names, sorted(names))
        self.assertTrue(all("마포구" in place["address"] for place in found["places"]))

    def test_nearby_is_by_distance(self):
        found = self.get("/places/nearby", kind="hospital", limit=5, **CITY_HALL).json()["places"]
        distances = [place["distance_km"] for place in found]
        self.assertEqual(len(found), 5)
        self.assertEqual(distances, sorted(distances))
        self.assertLess(distances[0], 3)

    def test_one_place_with_readable_details(self):
        found = self.get("/places/search", kind="pet_friendly", province="서울특별시", city="강남구", limit=1).json()
        place = self.get(f"/places/{found['places'][0]['id']}").json()
        self.assertEqual(place["name"], found["places"][0]["name"])
        self.assertIsInstance(place["info"], dict)
        self.assertTrue(all(":" in line for line in place["info_lines"]))

    def test_refusals(self):
        for path, params, status in (
            ("/places/search", {"kind": "zoo", "province": "서울특별시"}, 422),
            ("/places/search", {"kind": "hospital", "province": "서울시"}, 422),
            ("/places/search", {"kind": "hospital", "province": "서울특별시", "city": "해운대구"}, 422),
            ("/places/nearby", {"kind": "funeral", **CITY_HALL}, 422),  # no coordinates for this kind
            ("/places/nearby", {"kind": "hospital", "lat": 10, "lon": 10}, 422),  # outside Korea
            ("/places/nearby", {"kind": "hospital", "limit": 500, **CITY_HALL}, 422),
            ("/places/no-such-id", {}, 404),
        ):
            self.assertEqual(self.get(path, **params).status_code, status, (path, params))


if __name__ == "__main__":
    unittest.main()


class ApiDocsTests(unittest.TestCase):
    def test_the_docs_are_hidden_when_deployed(self):
        from api import main
        from src import settings

        with patch.object(settings, "deployed", return_value=True), patch.object(settings, "get_setting", return_value=None):
            client = TestClient(main.create_app())
            self.assertEqual(client.get("/docs").status_code, 404)
            self.assertEqual(client.get("/openapi.json").status_code, 404)
        with patch.object(settings, "deployed", return_value=False):
            self.assertEqual(TestClient(main.create_app()).get("/openapi.json").status_code, 200)
