"""src/tools/fees.py: regional clinic fee answers straight from the survey table."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.tools import fees


def row(level, sido, sigungu, item, detail, median, mean=None, low=1000, high=90000):
    return {"level": level, "sido_cd": "", "sido": sido, "sigungu": sigungu, "category": "", "item": item,
            "detail": detail, "medi_type_cd": "", "animal_type_cd": "", "mean": str(mean or median),
            "median": str(median), "min": str(low), "max": str(high), "collected_utc": "", "source": ""}


ROWS = (
    row("national", "전국", "", "초진 진찰료", "체중 5kg", 10000),
    row("national", "전국", "", "초진 진찰료", "체중 10kg", 10500),
    row("sido", "서울특별시", "", "초진 진찰료", "체중 5kg", 10800),
    row("sigungu", "서울특별시", "강남구", "초진 진찰료", "체중 5kg", 11000),
    row("sigungu", "서울특별시", "강남구", "초진 진찰료", "체중 10kg", 11400),
    row("sigungu", "서울특별시", "중구", "초진 진찰료", "체중 5kg", 9000),
    row("sigungu", "부산광역시", "중구", "초진 진찰료", "체중 5kg", 8000),
    row("national", "전국", "", "입원비", "고양이", 50000),
    row("national", "전국", "", "입원비", "개 체중 5kg", 45000),
    row("sido", "서울특별시", "", "광범위 구충비", "", 3000),
)


class FeeTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(fees, "load_fee_rows", return_value=ROWS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fee_questions_and_other_questions(self):
        for question in ("강남구 초진 진찰료 얼마야?", "강남구 동물병원 진료비 얼마 나와?", "MRI 찍으면 얼마 들어요?",
                         "구충제 가격"):
            with self.subTest(question):
                self.assertTrue(fees.is_fee_question(question))
        for question in ("강남구 동물병원 알려줘", "중성화 비용 얼마야", "펫보험 들면 진료비 얼마나 돌려받아?",
                         "반려동물 월평균 양육비", "엑스레이 찍어야 하나요?", "elect 비용"):
            with self.subTest(question):
                self.assertFalse(fees.is_fee_question(question))

    def test_no_table_means_no_fee_route(self):
        with patch.object(fees, "load_fee_rows", return_value=()):
            self.assertFalse(fees.is_fee_question("강남구 초진 진찰료 얼마야?"))

    def test_weight_maps_to_the_surveys_reference_weights(self):
        self.assertEqual(fees.requested_weight("7kg 강아지"), 5)
        self.assertEqual(fees.requested_weight("12 킬로 강아지"), 10)
        self.assertEqual(fees.requested_weight("30kg"), 20)
        self.assertEqual(fees.requested_weight("강아지", SimpleNamespace(weight_kg=9.0)), 10)
        self.assertIsNone(fees.requested_weight("강아지"))

    def test_answer_quotes_the_table_with_the_nation_and_the_notice(self):
        answer = fees.fee_answer("7kg 강아지 강남구 초진 얼마야?")
        self.assertIn("서울특별시 강남구: 중간 11,000원", answer)
        self.assertIn("전국: 중간 10,000원", answer)
        self.assertNotIn("11,400원", answer)  # 10kg row: the dog weighs 7 kg
        self.assertIn("개별 병원의 가격이 아닙니다", answer)

    def test_species_picks_the_row(self):
        self.assertIn("입원비 (고양이)", fees.fee_answer("고양이 입원비 얼마야?"))
        self.assertIn("입원비 (개 체중 5kg)", fees.fee_answer("강아지 5kg 입원비 얼마야?"))

    def test_the_named_si_do_decides_which_jung_gu(self):
        answer = fees.fee_answer("부산 중구 초진 얼마야?")
        self.assertIn("부산광역시 중구: 중간 8,000원", answer)
        self.assertNotIn("서울특별시 중구", answer)
        both = fees.fee_answer("중구 초진 얼마야?")
        self.assertIn("서울특별시 중구", both)
        self.assertIn("시·도를 함께 말씀하시면", both)

    def test_no_region_shows_the_nation_and_asks_for_one(self):
        answer = fees.fee_answer("초진 진찰료 얼마야?")
        self.assertIn("전국: 중간 10,000원", answer)
        self.assertIn("지역(예: 강남구, 수원)", answer)


if __name__ == "__main__":
    unittest.main()
