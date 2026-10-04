import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from langchain_core.documents import Document

from pages import rag
from src.chat_graph import HEALTH_ABSTAIN, REPORT_ABSTAIN, run_chat
from src.crag import (
    RetrievalReview,
    clean_sub_queries,
    grade_documents,
    merge_documents,
)
from src.run_log import log_chat_run


def doc(doc_id, text="본문", **metadata):
    return Document(id=doc_id, page_content=text, metadata={"qa.output": f"답변 {doc_id}", **metadata})


def review(useful_ids, sufficient, feedback="확인함"):
    return RetrievalReview(feedback=feedback, useful_ids=useful_ids, sufficient=sufficient)


def make_tools(route="rag", **overrides):
    tools = SimpleNamespace(
        is_date_question=lambda question: False,
        current_date_answer=lambda: "오늘",
        classify_question=lambda question, chat_history=None: route,
        build_rag_search_query=lambda question, history=None: question,
        infer_rag_filters=lambda question: {},
        ask_rag=Mock(return_value={"answer": "기존 답변", "evidence_rows": [{"qa.output": "x"}], "safety_notice": None}),
        analyze_report=Mock(return_value={"answer": "기존 분석", "evidence_rows": []}),
        run_sql_search=Mock(return_value=("병원 목록", [{"ids": 1}])),
        answer_without_tool=Mock(return_value="안녕하세요"),
        retrieve_health=Mock(return_value=[doc("a"), doc("b"), doc("c")]),
        review_evidence=Mock(return_value=review(["b", "a"], True)),
        rewrite_search_query=Mock(return_value="다시 쓴 검색어"),
        generate_health_answer=Mock(return_value="생성 답변"),
        detect_urgent_sign=lambda question: "응급" if "숨" in question else None,
        decompose_question=Mock(return_value=["입양비", "생활비"]),
        search_reports=Mock(return_value=[doc("r1"), doc("r2")]),
        generate_report_answer=Mock(return_value="보고서 답변"),
        report_evidence_from_docs=lambda docs: [{"page": 1, "excerpt": d.page_content} for d in docs],
    )
    for name, value in overrides.items():
        setattr(tools, name, value)
    return tools


class ChatGraphTestCase(unittest.TestCase):
    def setUp(self):
        self.log_dir = tempfile.TemporaryDirectory()
        self.log_path = os.path.join(self.log_dir.name, "runs.jsonl")
        patcher = patch.dict(os.environ, {"CHAT_RUN_LOG": self.log_path})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.log_dir.cleanup)

    def run_chat(self, tools, question="강아지가 구토해요", crag=True, top_k=2):
        return run_chat(tools, question, top_k=top_k, crag=crag)

    def log_records(self):
        with open(self.log_path, encoding="utf-8") as file:
            return [json.loads(line) for line in file]


class CragOffTests(ChatGraphTestCase):
    def test_each_route_uses_the_existing_function(self):
        cases = {
            "rag": ("ask_rag", "기존 답변"),
            "analysis": ("analyze_report", "기존 분석"),
            "sql": ("run_sql_search", "병원 목록"),
            "none": ("answer_without_tool", "안녕하세요"),
        }
        for route, (function, answer) in cases.items():
            with self.subTest(route=route):
                tools = make_tools(route)
                result = self.run_chat(tools, crag=False)
                getattr(tools, function).assert_called_once()
                tools.retrieve_health.assert_not_called()
                tools.review_evidence.assert_not_called()
                self.assertEqual((result["route"], result["answer"]), (route, answer))

    def test_date_question_is_answered_without_tools(self):
        tools = make_tools(is_date_question=lambda question: True)
        result = self.run_chat(tools, crag=True)
        self.assertEqual((result["route"], result["answer"]), ("none", "오늘"))


class HealthCragTests(ChatGraphTestCase):
    def test_correct_grade_answers_with_reviewer_ordered_evidence(self):
        tools = make_tools()
        result = self.run_chat(tools)
        docs = tools.generate_health_answer.call_args.args[1]
        self.assertEqual([d.id for d in docs], ["b", "a"])
        self.assertEqual(result["answer"], "생성 답변")
        self.assertEqual(len(result["evidence_rows"]), 2)
        tools.rewrite_search_query.assert_not_called()

    def test_no_evidence_rewrites_once_then_abstains_with_safety_notice(self):
        tools = make_tools(review_evidence=Mock(return_value=review([], False)))
        result = self.run_chat(tools, question="강아지가 숨을 못 쉬어요")
        self.assertEqual(tools.rewrite_search_query.call_count, 1)
        self.assertEqual(tools.retrieve_health.call_count, 2)
        self.assertEqual(tools.retrieve_health.call_args_list[1].args[0], "다시 쓴 검색어")
        tools.generate_health_answer.assert_not_called()
        self.assertTrue(result["abstained"])
        self.assertEqual(result["answer"], HEALTH_ABSTAIN)
        self.assertEqual(result["evidence_rows"], [])
        self.assertEqual(result["safety_notice"], "응급")

    def test_partial_evidence_answers_without_rewrite_or_note(self):
        tools = make_tools(review_evidence=Mock(return_value=review(["a"], False)))
        result = self.run_chat(tools)
        tools.rewrite_search_query.assert_not_called()
        self.assertEqual(result["answer"], "생성 답변")
        self.assertFalse(result["abstained"])
        self.assertEqual(self.log_records()[-1]["decision"], "ambiguous")

    def test_rewrite_that_finds_evidence_answers(self):
        tools = make_tools(review_evidence=Mock(side_effect=[review([], False), review(["c"], True)]))
        result = self.run_chat(tools)
        self.assertEqual(tools.rewrite_search_query.call_count, 1)
        self.assertEqual([d.id for d in tools.generate_health_answer.call_args.args[1]], ["c"])
        self.assertFalse(result["abstained"])

    def test_grader_failure_falls_back_to_top_documents(self):
        tools = make_tools(review_evidence=Mock(side_effect=RuntimeError("down")))
        result = self.run_chat(tools)
        self.assertEqual([d.id for d in tools.generate_health_answer.call_args.args[1]], ["a", "b"])
        self.assertEqual(result["answer"], "생성 답변")

    def test_run_is_logged_without_question_text(self):
        tools = make_tools()
        self.run_chat(tools, question="우리 강아지 초코가 구토해요")
        record = self.log_records()[-1]
        self.assertNotIn("초코", json.dumps(record, ensure_ascii=False))
        self.assertEqual(record["route"], "rag")
        self.assertEqual(record["decision"], "correct")
        self.assertEqual(record["trace"][0]["kept_ids"], ["b", "a"])
        self.assertIn("token_usage", record)


class ReportCragTests(ChatGraphTestCase):
    def test_comparison_question_is_decomposed_and_graded(self):
        tools = make_tools("analysis", review_evidence=Mock(return_value=review(["r2"], True)))
        result = self.run_chat(tools, question="입양비와 생활비를 비교해줘")
        tools.decompose_question.assert_called_once()
        self.assertEqual(tools.search_reports.call_args.args[1], ["입양비", "생활비"])
        self.assertEqual([d.id for d in tools.generate_report_answer.call_args.args[1]], ["r2"])
        self.assertEqual(result["answer"], "보고서 답변")

    def test_simple_question_is_not_decomposed(self):
        tools = make_tools("analysis")
        self.run_chat(tools, question="반려견 비만 비율")
        tools.decompose_question.assert_not_called()

    def test_report_without_evidence_abstains(self):
        tools = make_tools("analysis", review_evidence=Mock(return_value=review([], False)))
        result = self.run_chat(tools, question="반려동물 장묘 비용")
        tools.generate_report_answer.assert_not_called()
        tools.rewrite_search_query.assert_not_called()
        self.assertEqual(result["answer"], REPORT_ABSTAIN)
        self.assertIsNone(result["safety_notice"])


class CragHelperTests(unittest.TestCase):
    def test_unknown_ids_block_a_correct_decision(self):
        docs = [doc("a"), doc("b")]
        kept, decision, _ = grade_documents(lambda q, c: review(["a", "zzz"], True), "q", docs, str)
        self.assertEqual(([d.id for d in kept], decision), (["a"], "ambiguous"))

    def test_bracketed_ids_are_accepted(self):
        kept, decision, _ = grade_documents(lambda q, c: review(["[b]"], True), "q", [doc("b")], str)
        self.assertEqual(([d.id for d in kept], decision), (["b"], "correct"))

    def test_no_documents_skips_the_reviewer(self):
        reviewer = Mock()
        self.assertEqual(grade_documents(reviewer, "q", [], str)[1], "incorrect")
        reviewer.assert_not_called()

    def test_merge_keeps_previous_evidence_first(self):
        merged = merge_documents([doc("a")], [doc("b"), doc("a")])
        self.assertEqual([d.id for d in merged], ["a", "b"])

    def test_sub_queries_are_capped_and_fall_back_to_question(self):
        self.assertEqual(clean_sub_queries("q", ["a", "a", " ", "b", "c", "d"]), ["a", "b", "c"])
        self.assertEqual(clean_sub_queries("q", []), ["q"])

    def test_log_failure_does_not_raise(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(log_chat_run({"x": 1}, path=directory))


class PageWiringTests(ChatGraphTestCase):
    def test_crag_flag_reads_settings(self):
        with patch.object(rag, "get_setting", return_value="true"):
            self.assertTrue(rag.crag_enabled())
        with patch.object(rag, "get_setting", return_value=None):
            self.assertFalse(rag.crag_enabled())

    def test_chatbot_without_model_never_uses_crag(self):
        with patch.object(rag, "load_chat_model", return_value=None), \
                patch.object(rag, "classify_question", return_value="rag"), \
                patch.object(rag, "ask_rag", return_value={"answer": "기존", "evidence_rows": []}) as ask, \
                patch.object(rag, "retrieve_health") as retrieve:
            result = rag.chatbot("강아지가 구토해요", crag=True)
        ask.assert_called_once()
        retrieve.assert_not_called()
        self.assertEqual(result["answer"], "기존")

    def test_chatbot_routes_through_page_functions_with_crag(self):
        with patch.object(rag, "load_chat_model", return_value=object()), \
                patch.object(rag, "classify_question", return_value="rag"), \
                patch.object(rag, "retrieve_health", return_value=[doc("7")]), \
                patch.object(rag, "review_evidence", return_value=review(["7"], True)), \
                patch.object(rag, "generate_health_answer", return_value="CRAG 답변"):
            result = rag.chatbot("강아지가 구토해요", crag=True)
        self.assertEqual(result["answer"], "CRAG 답변")


class RouterKeywordTests(unittest.TestCase):
    def test_unrelated_question_mentioning_sangwan_is_not_a_report_question(self):
        with patch.object(rag, "load_chat_model", return_value=None):
            self.assertNotEqual(rag.classify_question("강아지와 상관없는 파이썬 리스트 정렬 방법을 알려줘"), "analysis")

    def test_new_report_topics_route_to_analysis(self):
        with patch.object(rag, "load_chat_model", return_value=None):
            for question in ("반려동물 장묘 서비스 이용 실태", "펫보험 가입 현황", "반려동물 산업 시장 규모"):
                with self.subTest(question=question):
                    self.assertEqual(rag.classify_question(question), "analysis")


if __name__ == "__main__":
    unittest.main()
