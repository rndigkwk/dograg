import json
import unittest
from pathlib import Path

from src.pii import mask_history, mask_pii

QUESTIONS = Path(__file__).resolve().parent / "data" / "guardrail_questions.json"


class MaskPiiTests(unittest.TestCase):
    """Personal data is masked before a model call (the guardrail dev items); dog questions are not."""

    def test_dev_items_lose_their_personal_string(self):
        items = [i for i in json.loads(QUESTIONS.read_text(encoding="utf-8"))["items"]
                 if i["category"] == "pii" and i["split"] == "dev"]
        self.assertEqual(len(items), 4)
        for item in items:
            masked = mask_pii(item["question"])
            self.assertNotIn(item["pii"], masked, item["id"])
            self.assertIn("강아지", masked, item["id"])

    def test_shapes(self):
        self.assertEqual(mask_pii("연락처 010.2222.3333 이요"), "연락처 [전화번호] 이요")
        self.assertEqual(mask_pii("집 전화 02-123-4567"), "집 전화 [전화번호]")
        self.assertEqual(mask_pii("서울 강남구 테헤란로 12길 34 근처 병원"), "서울 강남구 [주소] 근처 병원")
        self.assertEqual(mask_pii("마포구 동물병원 알려줘"), "마포구 동물병원 알려줘")

    def test_dog_questions_keep_their_numbers(self):
        for question in ("3살 5kg 말티즈가 하루 2번 토해요", "체온이 39.5도예요", "2024-10-13부터 설사해요",
                         "생후 10-12주에 접종하나요", "운동 30분 하고 다리를 절어요", "강남구 동물병원 3곳 알려줘",
                         "체중 12.5kg, 사료 150g 먹어요", "1588-0000 같은 대표번호는요"):
            self.assertEqual(mask_pii(question), question)

    def test_history_masks_only_the_guardian(self):
        history = [{"role": "user", "content": "제 번호 01012345678"}, {"role": "assistant", "content": "01012345678"}]
        self.assertEqual(mask_history(history), [{"role": "user", "content": "제 번호 [전화번호]"},
                                                 {"role": "assistant", "content": "01012345678"}])



class NamesAndAddressesTests(unittest.TestCase):
    """tests/data/pii_cases.json (2026-10-15), and the consultation shapes the first rules caught wrongly."""

    def test_the_case_set(self):
        cases = json.loads((Path(__file__).parent / "data" / "pii_cases.json").read_text(encoding="utf-8"))["items"]
        for case in cases:
            masked = mask_pii(case["text"])
            if "mask" in case:
                self.assertNotIn(case["mask"], masked, case["id"])
            if "keep" in case:
                self.assertIn(case["keep"], masked, case["id"])

    def test_quantities_after_a_particle_are_not_addresses(self):
        for text in ("심장 질환을 앓고 있는 것으로 11세 노령견", "결과적으로 10월 20일이", "수술비로 165만 원을",
                     "정도로 5~10알 정도의 사료", "간격으로 20~30분 정도씩", "올해로 5세가 되는", "체중이 3.5kg으로"):
            self.assertEqual(mask_pii(text), text)

    def test_lab_values_lists_and_ranges_are_not_addresses(self):
        # The shapes the 2026-10-23 scan of the 19,206 consultations masked wrongly (none was an address).
        for text in ("현재 적혈구 농축도가 40이 정상인 상황에서", "백혈구 수치가 22,000으로 평균보다", "백혈구 수치가 6으로 정상범위",
                     "슬개골 탈구 단계가 1기에서 4기까지", "탈구 상태가 2기에서 3기 정도로", "슬개골탈구 정도가 3기라면",
                     "그런데 이번에 실수로 5에서 10kg에 해당하는", "외출 등의 문제로 2, 3일 대소변을", "주로 1) 안과 질환, 2) 귀 질환",
                     "마취 비용으로 20,000원, 그리고", "평균적으로 1에서 5년의", "심장 크기가 일반적으로 8에서 10 사이"):
            self.assertEqual(mask_pii(text), text)

    def test_real_addresses_still_go(self):
        for text, gone in (("마포구 월드컵로 123에 살아요", "123"), ("중구 을지로3가 5 근처", "을지로3가 5"),
                           ("역삼동 123-4 근처예요", "123-4"), ("테헤란로 12길 34, 2층", "12길 34")):
            self.assertNotIn(gone, mask_pii(text), text)

    def test_a_dogs_name_is_not_the_guardians(self):
        text = "반려견의 이름은 양감자입니다"
        self.assertEqual(mask_pii(text), text)

if __name__ == "__main__":
    unittest.main()
