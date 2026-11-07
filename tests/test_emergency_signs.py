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


class GeneralQuestionTests(unittest.TestCase):
    """A question about a danger in general gets no warning from the rules (2026-11-07); one that
    says it is happening keeps it."""

    def test_asked_in_general(self):
        for question in ("여름철 강아지 열사병 예방은 어떻게 해요?", "열사병 증상이 뭐예요?", "발작의 원인이 뭔가요?",
                         "강아지 열사병 예방법 알려주세요", "단두종은 호흡곤란이 잘 생기나요?"):
            with self.subTest(question):
                self.assertIsNone(detect_urgent_sign(question))

    def test_happening_now(self):
        for question in ("경련을 하는데 원인이 뭐예요?", "발작 증상이 10분째 계속돼요", "열사병 같아요 몸이 뜨거운데 증상이 뭐예요?",
                         "숨을 못 쉬어요 왜 이런 거예요?", "갑작스러운 경련 증상과 함께 숨을 헐떡여요",
                         "숨이 가빠 보이고, 때때로 헥헥거려요", "초콜릿을 섭취하였을 때 증상이 없을 수도 있나요? 어제 먹었어요"):
            with self.subTest(question):
                self.assertIsNotNone(detect_urgent_sign(question))


class BleedingTests(unittest.TestCase):
    """Bleeding that does not stop, continues or is heavy gets the warning (2026-11-07)."""

    def test_continuing_bleeding(self):
        for question in ("코피가 줄줄 나는데 그치지를 않아요", "중성화 수술한 자리에서 피가 계속 배어 나와요",
                         "피를 토했어요", "발을 베였는데 피가 멈추지 않아요"):
            with self.subTest(question):
                self.assertIsNotNone(detect_urgent_sign(question))

    def test_a_little_or_stopped_or_asked(self):
        for question in ("피가 계속 조금씩 묻어나요", "소변에서 피가 계속 묻어나와요", "피가 많이 나지는 않아요",
                         "피는 멈췄어요", "피가 멈추지 않으면 어떻게 해요?", "변에 피가 조금 묻었어요"):
            with self.subTest(question):
                self.assertIsNone(detect_urgent_sign(question))

    def test_vomited_blood_gets_its_own_steps(self):
        steps = first_aid_steps("피를 토했어요")
        self.assertIn("물과 음식을 주지 마세요.", steps)
        self.assertNotIn("피가 나는 곳을 깨끗한 천으로 꾹 눌러 주세요.", steps)
        self.assertIn("피가 나는 곳을 깨끗한 천으로 꾹 눌러 주세요.", first_aid_steps("발을 베였는데 피가 멈추지 않아요"))


class UrgencyHoldoutSetTests(unittest.TestCase):
    """tests/data/urgency_holdout_questions.json is only measured: no question may come from the
    sets a change to the urgency check is tuned on."""

    def test_new_wording_only(self):
        # bleeding_holdout_questions (2026-11-07) may not repeat the first holdout either.
        data = Path(__file__).parent / "data"
        seen = {"여름철 강아지 열사병 예방은 어떻게 해요?", "기침을 며칠째 해요"}
        for name in ("emergency_signs", "care_level_questions", "basic_care_questions", "care_guide_questions"):
            seen |= {item["question"] for item in json.loads((data / f"{name}.json").read_text(encoding="utf-8"))["items"]}
        for name in ("urgency_holdout_questions", "bleeding_holdout_questions"):
            items = json.loads((data / f"{name}.json").read_text(encoding="utf-8"))["items"]
            self.assertEqual(len({item["id"] for item in items}), len(items))
            self.assertEqual({item["kind"] for item in items}, {"emergency", "vet_soon", "info_danger", "mild"})
            for item in items:
                with self.subTest(name=name, id=item["id"]):
                    self.assertNotIn(item["question"], seen)
            seen |= {item["question"] for item in items}


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
