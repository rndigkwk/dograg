"""src/model_outage.py: an exhausted model quota shows the search, without an answer."""

import unittest
from unittest.mock import patch

from langchain_core.documents import Document

from src import model_outage
from src.tools import care_guides, health


class RateLimitError(Exception):
    pass


GUIDE = Document(id="g", page_content="2~3주", metadata={"kind": "care_guide", "title": "윤리 가이드라인", "page": 39})
CASE = Document(id="c", page_content="발톱", metadata={"qa.output": "자주 깎아 주세요"})


class QuotaErrorTests(unittest.TestCase):
    def test_a_quota_error_is_found_even_when_wrapped(self):
        quota = RateLimitError("Error code: 429 - {'code': 'project_spend_limit_exceeded', 'type': 'insufficient_quota'}")
        try:
            try:
                raise quota
            except RateLimitError as inner:
                raise RuntimeError("graph failed") from inner
        except RuntimeError as outer:
            self.assertTrue(model_outage.is_quota_error(outer))

    def test_a_plain_rate_limit_or_other_error_is_not_a_quota_error(self):
        self.assertFalse(model_outage.is_quota_error(RateLimitError("Rate limit reached for requests per min")))
        self.assertFalse(model_outage.is_quota_error(RuntimeError("insufficient_quota")))
        self.assertFalse(model_outage.is_quota_error(None))


class SearchOnlyTests(unittest.TestCase):
    def search(self, similarity, guides=(GUIDE,), species=None):
        with patch.object(health, "other_species", return_value=species),                 patch.object(health, "health_top_similarity", return_value=similarity),                 patch.object(health, "retrieve_health", return_value=[CASE]) as cases,                 patch.object(care_guides, "retrieve_care_guides", return_value=list(guides)):
            return model_outage.search_only_result("강아지 발톱은 얼마 만에 깎아요?", 3), cases

    def test_near_the_material_the_guides_and_cases_are_shown_with_the_notice(self):
        result, cases = self.search(0.7)
        self.assertEqual(result["evidence_rows"], [GUIDE.metadata, CASE.metadata])
        self.assertEqual(result["route"], "rag")
        self.assertTrue(result["answer"].startswith(model_outage.PAUSED))
        self.assertIn(model_outage.FOUND, result["answer"])
        cases.assert_called_once_with("강아지 발톱은 얼마 만에 깎아요?", k=3)

    def test_each_screen_names_only_what_it_has(self):
        with patch.object(health, "other_species", return_value=None), \
                patch.object(health, "health_top_similarity", return_value=0.1), \
                patch.object(care_guides, "retrieve_care_guides", return_value=[]):
            web = model_outage.search_only_result("기침해요", 3)["answer"]
            backup = model_outage.search_only_result("기침해요", 3, screen="streamlit")["answer"]
        self.assertIn("관리 일정", web)
        self.assertNotIn("관리 일정", backup)
        self.assertNotIn("진료비", backup)

    def test_far_from_every_consultation_only_the_guides_show(self):
        result, cases = self.search(0.2)
        self.assertEqual(result["evidence_rows"], [GUIDE.metadata])
        cases.assert_not_called()

    def test_nothing_near_gives_the_notice_alone(self):
        result, _ = self.search(0.2, guides=())
        self.assertEqual((result["answer"], result["route"], result["evidence_rows"]), (model_outage.PAUSED, "none", []))

    def test_another_animal_gets_the_notice_alone(self):
        result, _ = self.search(0.9, species="고양이")
        self.assertEqual(result["evidence_rows"], [])

    def test_a_failing_search_still_gives_the_notice(self):
        with patch.object(health, "other_species", side_effect=RuntimeError("db")),                 self.assertLogs("src.model_outage", level="WARNING"):
            result = model_outage.search_only_result("기침해요", 3)
        self.assertEqual(result["answer"], model_outage.PAUSED)

    def test_the_urgent_check_still_runs(self):
        result, _ = self.search(0.2, guides=())
        self.assertIsNone(result["safety_notice"])
        with patch.object(health, "other_species", return_value=None),                 patch.object(health, "health_top_similarity", return_value=0.1),                 patch.object(care_guides, "retrieve_care_guides", return_value=[]):
            urgent = model_outage.search_only_result("강아지가 숨을 못 쉬어요", 3)
        self.assertTrue(urgent["safety_notice"])


if __name__ == "__main__":
    unittest.main()
