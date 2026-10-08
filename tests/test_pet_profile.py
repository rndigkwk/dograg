import json
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda

from src import resources
from src.chat_graph import run_chat
from src.storage.models import PetProfile
from src.tools import health
from src.tools import profile as pet_profile

TODAY = date(2026, 10, 6)
QUESTIONS = Path(__file__).resolve().parent / "data" / "crag_eval_questions.json"


def born(months_ago: int) -> date:
    total = TODAY.year * 12 + TODAY.month - 1 - months_ago
    return date(total // 12, total % 12 + 1, 1)


class LifeStageTests(unittest.TestCase):
    def test_boundaries_match_the_question_rules(self):
        cases = {0: "자견", 12: "자견", 13: "성견", 6 * 12 + 11: "성견", 7 * 12: "노령견"}
        for months, stage in cases.items():
            profile = PetProfile(birth_month=born(months))
            self.assertEqual(pet_profile.life_stage(profile, TODAY), stage, months)
        self.assertIsNone(pet_profile.life_stage(PetProfile(name="초코"), TODAY))
        self.assertIsNone(pet_profile.life_stage(None, TODAY))

    def test_context_lists_only_known_fields(self):
        self.assertEqual(pet_profile.profile_context(None), "등록된 정보 없음")
        profile = PetProfile(name="초코", breed="말티즈", weight_kg=3.2, neutered=False, conditions=["슬개골 탈구"])
        text = pet_profile.profile_context(profile)
        self.assertEqual(text, "이름: 초코\n견종: 말티즈\n체중: 3.2kg\n중성화: 안 함\n지병: 슬개골 탈구")
        self.assertEqual(pet_profile.profile_summary(profile), text.replace("\n", " · "))


class DetectionTests(unittest.TestCase):
    def test_age_becomes_a_birth_month(self):
        detected = pet_profile.DetectedProfile(breed="말티즈", age_months=36, conditions=["슬개골 탈구"])
        profile = pet_profile.to_profile(detected, on=TODAY)
        self.assertEqual(profile.birth_month, date(2023, 10, 1))
        self.assertEqual(profile.conditions, ["슬개골 탈구"])

    def test_other_dogs_and_empty_results_are_ignored(self):
        self.assertIsNone(pet_profile.to_profile(pet_profile.DetectedProfile(about_own_dog=False, age_months=60)))
        self.assertIsNone(pet_profile.to_profile(pet_profile.DetectedProfile()))
        self.assertIsNone(pet_profile.to_profile(pet_profile.DetectedProfile(weight_kg=-2)))

    def test_detect_uses_structured_output_and_needs_a_model(self):
        model = Mock()
        model.with_structured_output.return_value = RunnableLambda(
            lambda _: pet_profile.DetectedProfile(name="초코", age_months=5)
        )
        with patch.object(resources, "load_chat_model", return_value=model):
            self.assertEqual(pet_profile.detect_profile("우리 초코가 5개월인데 설사해요").name, "초코")
        with patch.object(resources, "load_chat_model", return_value=None):
            self.assertIsNone(pet_profile.detect_profile("우리 초코가 5개월이에요"))


class ProfileInRetrievalTests(unittest.TestCase):
    def test_profile_fills_the_life_stage_and_the_question_wins(self):
        senior = PetProfile(birth_month=born(9 * 12))
        with patch.object(pet_profile, "today", return_value=TODAY):
            self.assertEqual(health.infer_rag_filters("기침을 해요", profile=senior)["life_cycle"], "노령견")
            self.assertEqual(health.infer_rag_filters("5개월인데 기침을 해요", profile=senior)["life_cycle"], "자견")
            self.assertNotIn("life_cycle", health.infer_rag_filters("기침을 해요"))

    def test_twenty_health_questions_without_an_age_get_the_profile_stage(self):
        """Design doc phase 4 criterion: age-less health questions follow the profile."""
        items = json.loads(QUESTIONS.read_text(encoding="utf-8"))["items"]
        questions = [i["question"] for i in items if i["group"].startswith("health") and health.infer_life_cycle_filter(i["question"]) is None][:20]
        self.assertEqual(len(questions), 20)
        with patch.object(pet_profile, "today", return_value=TODAY):
            for months, stage in ((5, "자견"), (36, "성견"), (120, "노령견")):
                profile = PetProfile(birth_month=born(months))
                stages = {health.infer_rag_filters(q, profile=profile).get("life_cycle") for q in questions}
                self.assertEqual(stages, {stage})

    def test_profile_reaches_the_answer_prompt(self):
        chain = Mock()
        chain.invoke.return_value = "답"
        with patch.object(health, "initialize_rag", return_value=(object(), chain)):
            health.generate_health_answer("기침해요", [Document(page_content="q", metadata={"qa.output": "a"})],
                                          profile=PetProfile(name="초코", allergies=["닭고기"]))
        prompt_input = chain.invoke.call_args.args[0]
        self.assertIn("알레르기: 닭고기", prompt_input["profile"])
        self.assertIn("[반려견 정보]", health.RAG_PROMPT.messages[0].prompt.template)

    def test_graph_passes_the_profile_to_filters_and_generation(self):
        profile = PetProfile(name="초코")
        tools = SimpleNamespace(
            is_date_question=lambda q: False, classify_question=lambda q, chat_history=None: "rag",
            build_rag_search_query=lambda q, h=None: q, memory_search_query=lambda q, h=None: q,
            is_symptom_and_place_request=lambda q: False,
            infer_rag_filters=Mock(return_value={}),
            retrieve_health=Mock(return_value=[Document(id="1", page_content="q", metadata={})]),
            review_evidence=Mock(return_value=SimpleNamespace(feedback="", useful_ids=["1"], sufficient=True)),
            generate_health_answer=Mock(return_value="답"),
            detect_urgent_sign=lambda q: None,
        )
        run_chat(tools, "기침해요", top_k=1, crag=True, pet_profile=profile)
        self.assertIs(tools.infer_rag_filters.call_args.kwargs["profile"], profile)
        self.assertIs(tools.generate_health_answer.call_args.kwargs["profile"], profile)


if __name__ == "__main__":
    unittest.main()
