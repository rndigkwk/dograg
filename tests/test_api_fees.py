"""api/fees.py: the fee page's table lookups (regional statistics, no model calls)."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import main
from src.tools import fees


class FeesApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.create_app())

    def test_the_items_are_listed_by_category_with_the_notice(self):
        body = self.client.get("/fees/items").json()
        self.assertEqual(len(body["items"]), 34)
        self.assertEqual(body["items"][0]["category"], "진찰료")
        self.assertIn({"category": "진찰료", "item": "초진 진찰료", "detail": "체중 5kg", "label": "초진 진찰료 (체중 5kg)"},
                      body["items"])
        self.assertIn("개별 병원의 가격이 아닙니다", body["notice"])

    def test_one_item_nationally_per_province_and_district(self):
        body = self.client.get("/fees", params={"item": "초진 진찰료", "detail": "체중 5kg"}).json()
        self.assertEqual(set(body["national"]), {"mean", "median", "min", "max"})
        self.assertEqual(len(body["sido"]), 17)
        self.assertGreater(len(body["sigungu"]), 100)
        seoul = [row for row in body["sigungu"] if row["sido"] == "서울특별시"]
        self.assertIn("강남구", [row["sigungu"] for row in seoul])
        row = body["sido"][0]
        self.assertLessEqual(row["min"], row["median"])
        self.assertLessEqual(row["median"], row["max"])
        self.assertEqual(len(body["collected"]), 10)

    def test_a_district_next_to_the_nation_for_the_hospital_list(self):
        body = self.client.get("/fees/region", params={"province": "서울특별시", "city": "강남구"}).json()
        self.assertEqual([row["item"] for row in body["items"]], list(fees.GENERAL_ITEMS))
        first = body["items"][0]
        self.assertEqual((first["label"], first["level"], first["region"]), ("초진 진찰료 (체중 5kg)", "sigungu", "강남구"))
        self.assertGreater(first["median"], 0)
        self.assertGreater(first["national_median"], 0)
        self.assertIn("개별 병원의 가격이 아닙니다", body["notice"])

    def test_a_district_without_a_figure_shows_its_province(self):
        """The survey leaves out districts with one clinic or none (연천군 has no figure)."""
        body = self.client.get("/fees/region", params={"province": "경기도", "city": "연천군"}).json()
        self.assertTrue(all(row["level"] in ("sido", None) for row in body["items"]))
        self.assertIn("경기도", {row["region"] for row in body["items"]})

    def test_the_merged_province_reads_the_two_surveyed_ones(self):
        self.assertEqual(fees.fee_region("전남광주통합특별시", "광산구"), ("광주광역시", "광산구"))
        self.assertEqual(fees.fee_region("전남광주통합특별시", "여수시"), ("전라남도", "여수시"))
        body = self.client.get("/fees/region", params={"province": "전남광주통합특별시", "city": "광산구"}).json()
        self.assertTrue(any(row["median"] for row in body["items"]))

    def test_an_unknown_region_is_not_found(self):
        self.assertEqual(self.client.get("/fees/region", params={"province": "없는도"}).status_code, 404)

    def test_a_province_without_a_figure_is_listed_not_shown_as_zero(self):
        body = self.client.get("/fees", params={"item": "자기공명영상검사(MRI)비와 판독료", "detail": "체중 5kg"}).json()
        self.assertIn("세종특별자치시", body["no_data"])
        self.assertNotIn("세종특별자치시", [row["sido"] for row in body["sido"]])
        self.assertTrue(all(row["median"] > 0 for row in body["sido"] + body["sigungu"]))
        self.assertEqual(len(body["sido"]) + len(body["no_data"]), 17)

    def test_an_unknown_item_is_a_404(self):
        response = self.client.get("/fees", params={"item": "슬개골 수술비"})
        self.assertEqual(response.status_code, 404)

    def test_a_missing_file_is_a_503(self):
        with patch.object(fees, "load_fee_rows", return_value=()):
            self.assertEqual(self.client.get("/fees/items").status_code, 503)


if __name__ == "__main__":
    unittest.main()
