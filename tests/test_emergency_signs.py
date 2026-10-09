import json
import unittest
from pathlib import Path

from src.health_safety import detect_urgent_sign

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


if __name__ == "__main__":
    unittest.main()
