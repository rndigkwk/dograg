"""src/citations.py and health.check_citations: sentence citations and invented numbers, no model."""

import unittest
from unittest.mock import patch

from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda

from src import citations
from src.tools import health

CASES = ["수의사 답변: 생후 6~8주부터 종합백신을 2~4주 간격으로 접종합니다.",
         "수의사 답변: 체중 1kg당 10mg을 하루 2번 줍니다."]
GUIDES = ["동물사랑배움터: 산책은 하루 1회 이상 30분"]


class CheckTests(unittest.TestCase):
    def test_numbers_from_the_cited_evidence_pass(self):
        answer = "종합백신은 생후 6~8주부터 2~4주 간격으로 맞힙니다 [사례 1]. 산책은 하루 30분 이상 하세요 [지침 1]."
        self.assertFalse(citations.check_answer(answer, CASES, GUIDES))

    def test_a_number_not_in_the_cited_case_is_unsupported(self):
        answer = "약은 체중 1kg당 15mg을 줍니다 [사례 2]. 증상이 계속되면 병원에 가세요."
        problems = citations.check_answer(answer, CASES, GUIDES)
        self.assertEqual(problems.unsupported, ["약은 체중 1kg당 15mg을 줍니다 [사례 2]."])
        self.assertEqual(problems.numbers[problems.unsupported[0]], ["15"])

    def test_a_number_from_another_case_than_the_cited_one_is_unsupported(self):
        problems = citations.check_answer("생후 6~8주부터 접종합니다 [사례 2].", CASES, GUIDES)
        self.assertEqual(len(problems.unsupported), 1)

    def test_without_a_citation_any_evidence_counts(self):
        self.assertFalse(citations.check_answer("하루 2번 주세요.", CASES, GUIDES))
        self.assertTrue(citations.check_answer("하루 5번 주세요.", CASES, GUIDES))

    def test_the_question_and_profile_numbers_may_be_repeated(self):
        self.assertFalse(citations.check_answer("3살 5kg 강아지라면 병원에 먼저 확인하세요.", CASES, GUIDES,
                                                context="3살 5kg 강아지가 기침해요"))

    def test_a_citation_to_missing_evidence_is_removed(self):
        answer = "백신은 2~4주 간격입니다 [사례 1]. 자세히는 [지침 3]을 보세요."
        problems = citations.check_answer(answer, CASES, GUIDES)
        self.assertEqual(problems.invalid, ["[지침 3]"])
        self.assertNotIn("[지침 3]", citations.remove_invalid(answer, problems.invalid))
        self.assertEqual(citations.cited("백신은 [사례 1, 3]"), [("사례", 1), ("사례", 3)])

    def test_list_markers_and_citation_numbers_are_not_claims(self):
        self.assertEqual(citations.claimed_numbers("1. 물을 자주 주세요 [사례 2]."), [])
        self.assertEqual(citations.claimed_numbers("- 하루 2~3번 [사례 1]"), ["2", "3"])

    def test_a_citation_after_the_full_stop_belongs_to_the_sentence_before(self):
        """The model wrote "…권했습니다. [사례 1] 다만 …"; split as is, [사례 1] cited the next sentence."""
        answer = "약은 체중 1kg당 15mg입니다. [사례 2] 다만 백신은 2~4주 간격입니다. [사례 1]\n병원에 가세요."
        self.assertEqual(citations.attach_citations(answer),
                         "약은 체중 1kg당 15mg입니다 [사례 2]. 다만 백신은 2~4주 간격입니다 [사례 1].\n병원에 가세요.")
        problems = citations.check_answer(answer, CASES, GUIDES)
        self.assertEqual(problems.unsupported, ["약은 체중 1kg당 15mg입니다 [사례 2]."])

    def test_drop_sentences(self):
        answer = "물을 주세요 [사례 1].\n약은 15mg입니다 [사례 2].\n병원에 가세요."
        self.assertEqual(citations.drop_sentences(answer, ["약은 15mg입니다 [사례 2]."]), "물을 주세요 [사례 1].\n\n병원에 가세요.")


def docs():
    return [Document(id="1", page_content="백신", metadata={"qa.output": CASES[0]}),
            Document(id="2", page_content="약", metadata={"qa.output": CASES[1]}),
            Document(id="g", page_content=GUIDES[0], metadata={"kind": "care_guide", "organization": "동물사랑배움터", "title": "산책"})]


class FixTests(unittest.TestCase):
    def test_a_clean_answer_is_left_as_is(self):
        with patch("src.resources.load_chat_model", side_effect=AssertionError("no rewrite")):
            answer, done = health.check_citations("백신?", docs(), "백신은 2~4주 간격입니다 [사례 1].")
        self.assertEqual((answer, done), ("백신은 2~4주 간격입니다 [사례 1].", []))

    def test_an_invented_number_is_rewritten_once(self):
        writer = RunnableLambda(lambda prompt: "약은 체중 1kg당 10mg을 줍니다 [사례 2].")
        with patch("src.resources.load_chat_model", return_value=writer):
            answer, done = health.check_citations("약 얼마나?", docs(), "약은 체중 1kg당 15mg을 줍니다 [사례 2].")
        self.assertEqual((answer, done), ("약은 체중 1kg당 10mg을 줍니다 [사례 2].", [health.CITATION_FIXED]))

    def test_still_invented_after_the_rewrite_the_sentence_is_dropped(self):
        writer = RunnableLambda(lambda prompt: "약은 20mg입니다 [사례 2]. 병원에 가세요.")
        with patch("src.resources.load_chat_model", return_value=writer):
            answer, done = health.check_citations("약?", docs(), "약은 15mg입니다 [사례 2]. 병원에 가세요.")
        self.assertEqual(answer, "병원에 가세요.")
        self.assertEqual(done, [health.CITATION_FIXED, health.CITATION_DROPPED])

    def test_the_output_guards_keep_the_citation_record(self):
        from src import guardrails

        result = guardrails.apply_output_guards("나도 죽고 싶어요", {"answer": "답", "guards": [health.CITATION_FIXED]})
        self.assertEqual(result["guards"], [health.CITATION_FIXED, guardrails.CRISIS])

    def test_the_rule_is_in_the_answer_prompt(self):
        prompt = health.RAG_PROMPT.messages[0].prompt.template
        self.assertIn("[사례 1], [지침 2]처럼 붙이세요", prompt)


if __name__ == "__main__":
    unittest.main()
