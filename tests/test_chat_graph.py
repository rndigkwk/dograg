import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from langchain_core.documents import Document
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import StrOutputParser

from app_pages import rag
from src import chatbot as app
from src import resources, settings
from src.chat_graph import HEALTH_ABSTAIN, REPORT_ABSTAIN, run_chat
from src.crag import (
    RetrievalReview,
    clean_sub_queries,
    grade_documents,
    merge_documents,
)
from src.run_log import log_chat_run
from src.tools import health, router
from src.tools import review as review_tools


def doc(doc_id, text="본문", **metadata):
    return Document(id=doc_id, page_content=text, metadata={"qa.output": f"답변 {doc_id}", **metadata})


def review(useful_ids, sufficient, feedback="확인함"):
    return RetrievalReview(feedback=feedback, useful_ids=useful_ids, sufficient=sufficient)


def make_tools(route="rag", **overrides):
    tools = SimpleNamespace(
        is_date_question=lambda question: False,
        is_fee_question=lambda question: False,
        fee_answer=Mock(return_value="진료비 표"),
        current_date_answer=lambda: "오늘",
        classify_question=lambda question, chat_history=None: route,
        build_rag_search_query=lambda question, history=None: question,
        memory_search_query=lambda question, history=None: question,
        infer_rag_filters=lambda question, profile=None: {},
        ask_rag=Mock(return_value={"answer": "기존 답변", "evidence_rows": [{"qa.output": "x"}], "safety_notice": None}),
        analyze_report=Mock(return_value={"answer": "기존 분석", "evidence_rows": []}),
        run_sql_search=Mock(return_value=("병원 목록", [{"ids": 1}])),
        is_symptom_and_place_request=lambda question: "토" in question and "병원" in question,
        symptom_part=lambda question: question.split(" 강남구")[0],
        answer_without_tool=Mock(return_value="안녕하세요"),
        retrieve_health=Mock(return_value=[doc("a"), doc("b"), doc("c")]),
        review_evidence=Mock(return_value=review(["b", "a"], True)),
        rewrite_search_query=Mock(return_value="다시 쓴 검색어"),
        generate_health_answer=Mock(return_value="생성 답변"),
        review_health_answer=Mock(return_value=("고친 답변", {"claims": 3, "unsupported": 1, "revised": True})),
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

    def run_chat(self, tools, question="강아지가 구토해요", crag=True, top_k=2, crag_reports=False):
        return run_chat(tools, question, top_k=top_k, crag=crag, crag_reports=crag_reports)

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

    def test_every_route_the_graph_returns_can_be_saved_as_a_turn(self):
        # The fee route reached the deployed app before the stored-turn model accepted it, and
        # saving the conversation failed (2026-10-10).
        from src.storage.models import Turn

        cases = [make_tools(route) for route in ("rag", "analysis", "sql", "none")]
        cases += [make_tools(is_date_question=lambda question: True), make_tools(is_fee_question=lambda question: True)]
        for tools in cases:
            for crag in (False, True):
                result = self.run_chat(tools, crag=crag)
                with self.subTest(route=result["route"], crag=crag):
                    Turn(question="질문", answer=result["answer"], route=result["route"])

    def test_date_question_is_answered_without_tools(self):
        tools = make_tools(is_date_question=lambda question: True)
        result = self.run_chat(tools, crag=True)
        self.assertEqual((result["route"], result["answer"]), ("none", "오늘"))

    def test_fee_question_is_answered_from_the_table_without_a_model(self):
        tools = make_tools(is_fee_question=lambda question: True)
        tools.classify_question = Mock(side_effect=AssertionError("no router call for fee questions"))
        result = self.run_chat(tools, question="강남구 초진 진찰료 얼마야?", crag=True)
        self.assertEqual((result["route"], result["answer"]), ("fee", "진료비 표"))
        tools.retrieve_health.assert_not_called()
        tools.run_sql_search.assert_not_called()


class SelfRagTests(ChatGraphTestCase):
    """Day53 Self-RAG review of health answers: measured and off by default (CHAT_SELF_RAG)."""

    def test_off_by_default(self):
        tools = make_tools()
        result = self.run_chat(tools)
        tools.review_health_answer.assert_not_called()
        self.assertEqual(result["answer"], "생성 답변")

    def test_on_the_answer_is_checked_against_the_same_evidence_and_replaced(self):
        tools = make_tools()
        result = run_chat(tools, "강아지가 구토해요", top_k=2, crag=True, self_rag=True)
        question, docs, answer = tools.review_health_answer.call_args.args
        self.assertEqual((question, [d.id for d in docs], answer), ("강아지가 구토해요", ["b", "a"], "생성 답변"))
        self.assertEqual(result["answer"], "고친 답변")

    def test_abstentions_are_not_reviewed(self):
        tools = make_tools(review_evidence=Mock(return_value=review([], False)))
        run_chat(tools, "강아지가 구토해요", top_k=2, crag=True, self_rag=True)
        tools.review_health_answer.assert_not_called()


class CompoundQuestionTests(ChatGraphTestCase):
    """Day54 Adaptive: a facility request that also describes a symptom gets both answers."""

    def test_places_first_then_the_health_answer_with_its_evidence(self):
        tools = make_tools(route="sql")
        result = self.run_chat(tools, question="토하는데 강남구 동물병원 알려줘")
        self.assertEqual(result["route"], "sql")
        self.assertEqual(result["hospital_rows"], [{"ids": 1}])
        self.assertTrue(result["answer"].startswith("병원 목록"))
        self.assertIn("**증상에 대해**", result["answer"])
        self.assertTrue(result["answer"].endswith("생성 답변"))
        self.assertEqual(len(result["evidence_rows"]), 2)
        self.assertEqual(tools.generate_health_answer.call_args.args[0], "토하는데")  # only the symptom half

    def test_no_health_evidence_keeps_the_places_and_says_so(self):
        tools = make_tools(route="sql", review_evidence=Mock(return_value=review([], False)))
        result = self.run_chat(tools, question="토하는데 강남구 동물병원 알려줘")
        self.assertTrue(result["answer"].startswith("병원 목록"))
        self.assertIn(HEALTH_ABSTAIN, result["answer"])  # the health abstention, not the report one
        self.assertEqual(result["hospital_rows"], [{"ids": 1}])

    def test_the_same_question_routed_to_health_also_gets_the_places(self):
        # The router sends about half of these to rag; the places must not be lost there.
        tools = make_tools(route="rag")
        result = self.run_chat(tools, question="토하는데 강남구 동물병원 알려줘")
        tools.run_sql_search.assert_called_once()
        self.assertEqual(result["route"], "rag")
        self.assertEqual(result["hospital_rows"], [{"ids": 1}])
        self.assertTrue(result["answer"].startswith("병원 목록"))
        self.assertTrue(result["answer"].endswith("생성 답변"))
        plain = make_tools(route="rag")
        self.assertEqual(self.run_chat(plain, question="강아지가 토해요")["answer"], "생성 답변")
        plain.run_sql_search.assert_not_called()

    def test_the_place_list_can_be_shown_before_the_health_path_runs(self):
        tools = make_tools(route="sql")
        steps = []
        result = run_chat(tools, "토하는데 강남구 동물병원 알려줘", top_k=2, crag=True,
                          on_step=lambda node, update: steps.append((node, update)))
        early = [(i, rag.places_first(node, update)) for i, (node, update) in enumerate(steps)
                 if rag.places_first(node, update)]
        self.assertEqual(len(early), 1)
        index, places = early[0]
        self.assertEqual(steps[index][0], "hospital")
        self.assertTrue(all(node.startswith("health_") for node, _ in steps[index + 1:]))
        self.assertTrue(result["answer"].startswith(places))  # the final answer only adds below it
        self.assertIn("상담 자료", rag.progress_message(*steps[index]))
        plain = []
        run_chat(make_tools(route="sql"), "강남구 동물병원 알려줘", top_k=2, crag=True,
                 on_step=lambda node, update: plain.append(rag.places_first(node, update)))
        self.assertEqual(plain, [None, None])  # a plain list is the whole answer: nothing early

    def test_plain_facility_questions_and_crag_off_stay_one_path(self):
        tools = make_tools(route="sql")
        result = self.run_chat(tools, question="강남구 동물병원 알려줘")
        self.assertEqual(result["answer"], "병원 목록")
        tools.retrieve_health.assert_not_called()
        result = self.run_chat(tools, question="토하는데 강남구 동물병원 알려줘", crag=False)
        self.assertEqual(result["answer"], "병원 목록")
        tools.retrieve_health.assert_not_called()


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
        self.assertTrue(result["answer"].startswith(HEALTH_ABSTAIN))
        self.assertIn("- **찾아본 것:** 반려견 건강 상담 사례", result["answer"])
        self.assertIn("- **다시 물어볼 때:**", result["answer"])
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

    def test_rewrite_searches_again_without_the_department_filter(self):
        tools = make_tools(
            infer_rag_filters=lambda question, profile=None: {"life_cycle": "성견", "department": "피부과"},
            review_evidence=Mock(side_effect=[review([], False), review(["c"], True)]),
        )
        self.run_chat(tools)
        first, second = (call.kwargs["filters"] for call in tools.retrieve_health.call_args_list)
        self.assertEqual(first, {"life_cycle": "성견", "department": "피부과"})
        self.assertEqual(second, {"life_cycle": "성견"})  # the user-stated age stays

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
    def run_chat(self, tools, question="보고서 질문", crag=True, top_k=2, crag_reports=True):
        return super().run_chat(tools, question, crag=crag, top_k=top_k, crag_reports=crag_reports)

    def test_health_crag_alone_keeps_reports_on_the_plain_path(self):
        tools = make_tools("analysis")
        result = self.run_chat(tools, question="입양비와 생활비를 비교해줘", crag=True, crag_reports=False)
        tools.analyze_report.assert_called_once()
        tools.review_evidence.assert_not_called()
        tools.decompose_question.assert_not_called()
        self.assertEqual(result["answer"], "기존 분석")

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
        self.assertTrue(result["answer"].startswith(REPORT_ABSTAIN))
        self.assertIn("반려동물 보고서 5종", result["answer"])
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
        with patch.object(settings, "get_setting", return_value="true"):
            self.assertTrue(settings.crag_enabled())
        with patch.object(settings, "get_setting", return_value=None):
            self.assertFalse(settings.crag_enabled())

    def test_chatbot_reads_report_flag_separately(self):
        values = {"ENABLE_CRAG": "true", "ENABLE_CRAG_REPORTS": None}
        with (
            patch.object(settings, "get_setting", side_effect=values.get),
            patch.object(resources, "load_chat_model", return_value=object()),
            patch.object(app, "run_chat", return_value={}) as run,
        ):
            app.chatbot("질문")
        self.assertTrue(run.call_args.kwargs["crag"])
        self.assertFalse(run.call_args.kwargs["crag_reports"])

    def test_chatbot_without_model_never_uses_crag(self):
        with patch.object(resources, "load_chat_model", return_value=None), \
                patch.object(router, "classify_question", return_value="rag"), \
                patch.object(health, "ask_rag", return_value={"answer": "기존", "evidence_rows": []}) as ask, \
                patch.object(health, "retrieve_health") as retrieve:
            result = app.chatbot("강아지가 구토해요", crag=True)
        ask.assert_called_once()
        retrieve.assert_not_called()
        self.assertEqual(result["answer"], "기존")

    def test_chatbot_routes_through_page_functions_with_crag(self):
        with patch.object(resources, "load_chat_model", return_value=object()), \
                patch.object(router, "classify_question", return_value="rag"), \
                patch.object(health, "retrieve_health", return_value=[doc("7")]), \
                patch.object(review_tools, "review_evidence", return_value=review(["7"], True)), \
                patch.object(health, "generate_health_answer", return_value="CRAG 답변"):
            result = app.chatbot("강아지가 구토해요", crag=True)
        self.assertEqual(result["answer"], "CRAG 답변")


class RouterKeywordTests(unittest.TestCase):
    def test_unrelated_question_mentioning_sangwan_is_not_a_report_question(self):
        with patch.object(resources, "load_chat_model", return_value=None):
            self.assertNotEqual(router.classify_question("강아지와 상관없는 파이썬 리스트 정렬 방법을 알려줘"), "analysis")

    def test_new_report_topics_route_to_analysis(self):
        with patch.object(resources, "load_chat_model", return_value=None):
            for question in ("반려동물 장묘 서비스 이용 실태", "펫보험 가입 현황", "반려동물 산업 시장 규모"):
                with self.subTest(question=question):
                    self.assertEqual(router.classify_question(question), "analysis")


def fake_llm_text(text):
    """Run a fake chat model the way the app does (model | StrOutputParser), streaming word by word."""
    model = GenericFakeChatModel(messages=iter([AIMessage(content=text)]))
    return (model | StrOutputParser()).invoke("질문")


class StreamingTests(ChatGraphTestCase):
    def stream(self, tools, **kwargs):
        tokens, steps = [], []
        result = run_chat(
            tools, "강아지가 구토해요", top_k=2, crag=kwargs.pop("crag", True),
            on_token=tokens.append, on_step=lambda node, update: steps.append(node), **kwargs,
        )
        return result, tokens, steps

    def test_streams_only_the_answer_tokens(self):
        def reviewer(*args, **kwargs):
            fake_llm_text("평가 결과는 비공개")  # grader output must not reach the screen
            return review(["a"], True)

        tools = make_tools(
            review_evidence=Mock(side_effect=reviewer),
            generate_health_answer=Mock(side_effect=lambda *a, **k: fake_llm_text("수분을 보충해 주세요")),
        )
        result, tokens, steps = self.stream(tools)
        self.assertGreater(len(tokens), 1)
        self.assertEqual("".join(tokens), "수분을 보충해 주세요")
        self.assertEqual(result["answer"], "수분을 보충해 주세요")
        self.assertEqual(steps, ["classify", "health_retrieve", "health_grade", "health_generate"])

    def test_streamed_result_matches_the_blocking_result(self):
        for route in ("rag", "analysis", "sql", "none"):
            with self.subTest(route=route):
                blocking = self.run_chat(make_tools(route), crag=False)
                streamed, tokens, _ = self.stream(make_tools(route), crag=False)
                self.assertEqual(streamed, blocking)
                self.assertEqual(tokens, [])  # mocked tools produce no model tokens

    def test_abstain_streams_nothing_and_still_logs(self):
        tools = make_tools(review_evidence=Mock(return_value=review([], False)))
        result, tokens, steps = self.stream(tools)
        self.assertTrue(result["abstained"])
        self.assertEqual(tokens, [])
        self.assertIn("health_rewrite", steps)
        self.assertEqual(steps[-1], "abstain")
        self.assertTrue(self.log_records()[-1]["abstained"])

    def test_progress_messages_follow_the_graph(self):
        self.assertIn("건강 상담", rag.progress_message("classify", {"route": "rag"}))
        self.assertIn("확인", rag.progress_message("health_retrieve", {}))
        self.assertIn("답변", rag.progress_message("health_grade", {"documents": [doc("a")]}))
        self.assertIn("다시 찾고", rag.progress_message("health_grade", {"documents": []}))
        self.assertIsNone(rag.progress_message("report_grade", {"documents": []}))
        self.assertIsNone(rag.progress_message("health_generate", {"answer": "x"}))

    def test_chatbot_passes_streaming_callbacks(self):
        with patch.object(resources, "load_chat_model", return_value=None),                 patch.object(app, "run_chat", return_value={}) as run:
            app.chatbot("질문", on_token=print, on_step=len)
        self.assertIs(run.call_args.kwargs["on_token"], print)
        self.assertIs(run.call_args.kwargs["on_step"], len)


if __name__ == "__main__":
    unittest.main()
