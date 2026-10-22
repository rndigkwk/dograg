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

    def test_how_long_and_how_often_are_not_price_questions(self):
        # holdout (2026-10-10): "얼마나" asks for time or frequency as often as for money.
        for question in ("입원하면 보통 얼마나 입원해 있어야 해요?", "심장사상충 약 얼마나 자주 먹여야 돼요?",
                         "초음파 검사는 시간이 얼마나 걸려요?", "MRI 찍기 전에 얼마 동안 굶겨야 하나요?"):
            with self.subTest(question):
                self.assertFalse(fees.is_fee_question(question))
        for question in ("강릉 켄넬코프 접종 얼마나 해요?", "CT 촬영 비용 얼마나 나와요?", "초진 얼마 정도 해요",
                         "입원비 얼마예요", "엑스레이 얼마"):
            with self.subTest(question):
                self.assertTrue(fees.is_fee_question(question))

    def test_clinic_fees_as_a_topic_need_an_amount_asked(self):
        for question in ("동물병원 진료비 카드 할부 되나요?", "진료비가 너무 많이 나왔는데 어디에 신고해요?"):
            with self.subTest(question):
                self.assertFalse(fees.is_fee_question(question))
        for question in ("진료비 전국 평균 좀 알려줘", "춘천 동물병원 병원비 대충 얼마 나와요?"):
            with self.subTest(question):
                self.assertTrue(fees.is_fee_question(question))

    def test_everyday_words_for_price_items_and_weight(self):
        self.assertTrue(fees.is_fee_question("천안 초음파 몇만원 정도 해요?"))
        self.assertTrue(fees.is_fee_question("포항에서 엑스레이 찍으면 비싸요?"))
        self.assertTrue(fees.is_fee_question("제주도 동물병원 엑스레이 값"))
        self.assertEqual(fees.requested_items("평택 종합접종 비용"), ["종합백신 접종비"])
        self.assertEqual(fees.requested_items("충남 고양이 백신 가격"), ["종합백신 접종비"])
        self.assertEqual(fees.requested_items("광견병 백신 얼마"), ["광견병백신 접종비"])
        self.assertEqual(fees.requested_weight("10키로 강아지"), 10)

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

    def test_a_gu_name_holding_another_si_do_name(self):
        rows = (*ROWS, row("sigungu", "부산광역시", "해운대구", "초진 진찰료", "체중 5kg", 12000),
                row("sido", "대구광역시", "", "초진 진찰료", "체중 5kg", 9500))
        with (patch.object(fees, "load_fee_rows", return_value=rows),
              patch.object(fees.places, "extract_search_parameters", return_value=["해운대구"])):
            self.assertEqual(fees.resolve_regions("해운대구 초진 얼마야"), [("부산광역시", "해운대구")])
        # A si/do the extractor returns stays readable ("경기도 진료비 평균": 경기도, not nothing).
        with (patch.object(fees, "load_fee_rows", return_value=(*rows, row("sido", "경기도", "", "초진 진찰료", "체중 5kg", 9000))),
              patch.object(fees.places, "extract_search_parameters", return_value=["경기도"])):
            self.assertEqual(fees.resolve_regions("경기도 동물병원 진료비 평균 얼마야"), [("경기도", "")])

    def test_no_region_shows_the_nation_and_asks_for_one(self):
        answer = fees.fee_answer("초진 진찰료 얼마야?")
        self.assertIn("전국: 중간 10,000원", answer)
        self.assertIn("지역(예: 강남구, 수원)", answer)


class FeePointerTests(unittest.TestCase):
    """A health answer whose question also asks about money ends with where the fee figures are."""

    def test_a_long_consultation_asking_about_cost_gets_the_pointer(self):
        question = ("데려온 강아지가 심장사상충 2기 진단을 받아 보름간 혈관 확장제를 먹이고 성충을 죽이는 주사를 이틀에 걸쳐 "
                    "두 번 맞혔습니다. 한 달이 지났는데 목에 무엇이 걸린 듯 기침을 자주 하고 헥헥거려요. 치료가 제대로 안 된 "
                    "걸까요? 치료에 약 백만 원 정도의 비용이 들었는데 효과가 없으면 어떡하나요?")
        self.assertGreater(len(question), fees.MAX_FEE_QUESTION_CHARS)
        with patch.object(fees, "load_fee_rows", return_value=ROWS):  # the fee path is closed by length, not by data
            self.assertFalse(fees.is_fee_question(question))
        pointer = fees.fee_pointer(question)
        self.assertIn("지역별 진료비", pointer)
        self.assertIn("병원에 확인", pointer)

    def test_a_named_item_is_mentioned(self):
        pointer = fees.fee_pointer("강아지가 다리를 절어서 엑스레이를 찍었는데 보통 얼마 나와요? 그리고 뼈는 괜찮을까요?")
        self.assertIn("엑스선 촬영비와 판독료 같은 항목은", pointer)

    def test_no_money_no_pointer(self):
        for question in ["강아지가 이틀째 설사를 해요", "사료는 하루에 얼마나 자주 줘야 하나요?",
                         "약은 얼마 동안 먹여야 해요?", "펫보험 가입 비용 평균이 얼마예요?"]:
            self.assertEqual(fees.fee_pointer(question), "", question)


if __name__ == "__main__":
    unittest.main()
