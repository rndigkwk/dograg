import json
import unittest
from pathlib import Path

from src.health_safety import detect_urgent_sign, first_aid_steps

DATA = Path(__file__).parent / "data" / "emergency_signs.json"


class EmergencySignSetTests(unittest.TestCase):
    """tests/data/emergency_signs.json: the rules were written from the dev half."""

    def setUp(self):
        self.items = json.loads(DATA.read_text(encoding="utf-8"))["items"]

    def test_every_dev_question_is_judged_right(self):
        for item in self.items:
            if item["split"] == "dev":
                with self.subTest(item["id"]):
                    self.assertEqual(bool(detect_urgent_sign(item["question"])), item["urgent"], item["question"])

    def test_no_false_alarm_on_holdout(self):
        # Holdout misses are known (scripts/evaluate_emergency.py); a warning on an ordinary,
        # negated, past or "what if" question would be new.
        for item in self.items:
            if item["split"] == "holdout" and not item["urgent"]:
                with self.subTest(item["id"]):
                    self.assertIsNone(detect_urgent_sign(item["question"]), item["question"])

    def test_the_sign_itself_can_contain_a_negative_verb(self):
        self.assertIsNotNone(detect_urgent_sign("피가 멈추지 않아요"))
        self.assertIsNotNone(detect_urgent_sign("숨을 못 쉬고 구토는 없어요"))
        self.assertIsNone(detect_urgent_sign("처방받은 약물을 먹었는데 토했어요"))


class FirstAidTests(unittest.TestCase):
    def test_steps_follow_the_kind_of_sign(self):
        self.assertIn("억지로 토하게 하지 마세요", " ".join(first_aid_steps("자일리톨 껌을 두 개 삼켰어요")))
        self.assertIn("입에 손이나 물건을 넣지 마세요.", first_aid_steps("갑자기 경련을 해요"))

    def test_none_without_an_urgent_sign(self):
        self.assertEqual(first_aid_steps("귀를 자주 긁고 냄새가 나요"), [])
        self.assertEqual(first_aid_steps("오줌 색이 조금 진해요"), [])

    def test_a_poison_asked_about_still_says_go_if_eaten(self):
        self.assertIsNone(detect_urgent_sign("포도를 먹여도 되나요?"))
        self.assertIn("증상이 없어도", first_aid_steps("포도를 먹여도 되나요?")[0])

    def test_the_second_check_brings_steps_the_rules_missed(self):
        question = "밥 먹고 뛰어논 뒤 배가 불룩해지고 헛구역질만 계속해요"
        self.assertEqual(first_aid_steps(question), [])
        self.assertIn("물과 음식을 주지 마세요.", first_aid_steps(question, urgent=True))

    def test_no_numbers(self):
        # Fixed text that skips the citation check: a dose or a time here would go unchecked.
        from src.health_safety import FIRST_AID

        for _, steps in FIRST_AID:
            for step in steps:
                self.assertNotRegex(step, r"\d", step)


if __name__ == "__main__":
    unittest.main()
