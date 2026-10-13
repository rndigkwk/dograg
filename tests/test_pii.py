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


if __name__ == "__main__":
    unittest.main()
