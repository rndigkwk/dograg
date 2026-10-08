"""Visit-prep team (team/): tool permissions, Send fan-out and reducer, review loop limit,
handoffs and saved files, with the models replaced by fakes."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from langgraph.types import Command, Send

from team.agents import workers
from team.core import config
from team.core.schemas import Clarification, Finding, KeyPoint, ReworkStep, VisitPlan, VisitTask
from team.graph import edges, nodes
from team.graph.builder import build_graph
from team.graph.state import merge_findings
from team.tools import handoff


class FakeLLM:
    """Structured outputs for the planner (VisitPlan) and supervisor (ReworkStep)."""

    def __init__(self, tasks, questions=()):
        self.tasks, self.questions = tasks, list(questions)

    def with_structured_output(self, schema):
        if schema is Clarification:
            return SimpleNamespace(invoke=lambda messages: Clarification(questions=self.questions))
        if schema is VisitPlan:
            return SimpleNamespace(invoke=lambda messages: VisitPlan(tasks=self.tasks))
        return SimpleNamespace(invoke=lambda messages: ReworkStep(next="writer", instruction="근거 없는 문장을 지우세요"))


class FakeResearcher:
    def __init__(self, kind):
        self.kind = kind

    def invoke(self, inputs):
        fact = KeyPoint(fact=f"{self.kind} 사실", evidence_id=f"{self.kind}-1")
        return {"structured_response": Finding(summary=f"{self.kind} 요약", key_points=[fact])}


class FakeWriter:
    def __init__(self, run_dir):
        self.run_dir, self.calls = run_dir, 0

    def invoke(self, inputs):
        self.calls += 1
        (self.run_dir / config.REPORT_FILE).write_text(f"# 방문 준비 보고서 {self.calls}", encoding="utf-8")
        return {"messages": []}  # no handoff: the writer node passes the report to the reviewer itself


def judge_with(unsupported):
    """A judge that flags the same claims in every review."""
    return judge_rounds([unsupported])


def judge_rounds(rounds):
    """A judge that flags rounds[i] in review i (the last entry repeats)."""
    calls = []

    def invoke(inputs):
        flagged = rounds[min(len(calls), len(rounds) - 1)]
        calls.append(flagged)
        claims = [SimpleNamespace(text=text, verdict="unsupported") for text in flagged]
        return SimpleNamespace(claims=[*claims, SimpleNamespace(text="증상 정리", verdict="supported")])

    return lambda model: SimpleNamespace(invoke=invoke)


class BrokenResearcher(FakeResearcher):
    """A researcher whose model call fails after the SDK's own retries (e.g. an API outage)."""

    def __init__(self, kind, broken_kinds):
        super().__init__(kind)
        self.broken = kind in broken_kinds

    def invoke(self, inputs):
        if self.broken:
            raise ConnectionError("API 연결 끊김")
        return super().invoke(inputs)


def initial_state(region="강남구"):
    return {"consultation": "말티즈가 설사와 구토를 해요", "region": region, "profile": "", "urgent": "",
            "plan": [], "findings": {}, "failures": {}, "outcome": "", "round": 0, "draft": "", "review": None,
            "feedback": "", "instruction": ""}


class ToolPermissionTests(unittest.TestCase):
    def test_each_role_gets_only_its_tools(self):
        names = {kind: [tool.name for tool in workers.researcher_tools(kind)] for kind in ("health", "place", "cost")}
        self.assertEqual(names, {"health": ["search_health_qa"], "place": ["find_hospitals"], "cost": ["search_report_stats"]})
        writer = [tool.name for tool in workers.writer_tools(Path("."))]
        self.assertEqual(writer, ["write_report", "request_review", "request_research"])
        searches = {name for tools in names.values() for name in tools}
        self.assertFalse(searches & set(writer))  # the writer cannot search

    def test_handoff_tools_move_control_in_the_parent_graph(self):
        review = handoff.request_review.func()
        research = handoff.request_research.func("체중 정보가 없습니다")
        self.assertEqual((review.goto, review.graph), ("reviewer", Command.PARENT))
        self.assertEqual((research.goto, research.update["feedback"]), ("supervisor", "체중 정보가 없습니다"))
        with tempfile.TemporaryDirectory() as directory:
            write = handoff.make_write_report(Path(directory))
            write.invoke({"markdown": "# 보고서"})
            self.assertEqual((Path(directory) / config.REPORT_FILE).read_text(encoding="utf-8"), "# 보고서")


class FanOutTests(unittest.TestCase):
    def test_reducer_keeps_every_parallel_result(self):
        merged = {}
        for task_id in ("t2", "t1", "t3"):  # arrival order does not matter
            merged = merge_findings(merged, {task_id: {"summary": task_id}})
        self.assertEqual(sorted(merged), ["t1", "t2", "t3"])

    def test_dispatch_sends_only_unfinished_tasks(self):
        state = {**initial_state(), "plan": [{"task_id": "t1"}, {"task_id": "t2"}], "findings": {"t1": {}}}
        sends = edges.dispatch(state)
        self.assertEqual([(send.node, send.arg["task"]["task_id"]) for send in sends], [("researcher", "t2")])
        self.assertIsInstance(sends[0], Send)
        state["findings"]["t2"] = {}
        self.assertEqual(edges.dispatch(state), "supervisor")


class TeamGraphTests(unittest.TestCase):
    def run_team(self, unsupported=(), *, judge=None, broken_kinds=()):
        tasks = [VisitTask(kind="health", query="설사", angle="a"), VisitTask(kind="health", query="구토", angle="b"),
                 VisitTask(kind="cost", query="진료비", angle="c")]
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        run_dir = Path(directory.name)
        writer = FakeWriter(run_dir)
        # review_llm is replaced too: building a real ChatOpenAI needs an API key, which CI does not have.
        with patch.object(config, "llm", return_value=FakeLLM(tasks)), patch.object(config, "review_llm"), \
                patch.object(nodes, "create_researcher", side_effect=lambda kind: BrokenResearcher(kind, broken_kinds)), \
                patch.object(nodes, "build_judge", side_effect=judge or judge_with(list(unsupported))), \
                patch.object(nodes, "build_verifier"), patch.object(nodes, "recheck_unsupported", return_value=0):
            state = build_graph().invoke(initial_state(), context={"run_dir": run_dir, "writer": writer})
        result = json.loads((run_dir / config.RESULT_FILE).read_text(encoding="utf-8"))
        report = (run_dir / config.REPORT_FILE).read_text(encoding="utf-8")
        return state, result, report, writer

    def test_parallel_findings_are_all_merged_and_a_clean_report_passes(self):
        state, result, report, writer = self.run_team(unsupported=[])
        # 3 planned tasks + the place task added because a region was given, all researched in parallel
        self.assertEqual([task["kind"] for task in state["plan"]], ["health", "health", "cost", "place"])
        self.assertEqual(sorted(result["findings"]), ["t1", "t2", "t3", "t4"])
        self.assertEqual((result["status"], result["round"], writer.calls), (config.PASSED, 0, 1))
        self.assertTrue(report.startswith("# 방문 준비 보고서"))

    def test_rejections_stop_at_the_round_limit_for_a_person_to_check(self):
        # A different flagged sentence each time: real progress, so only the round limit stops it.
        judge = judge_rounds([["근거 없는 진단"], ["근거 없는 약 이름"], ["근거 없는 검사 비용"]])
        _, result, report, writer = self.run_team(judge=judge)
        self.assertEqual(result["status"], config.HUMAN_CHECK)
        self.assertEqual(result["round"], config.MAX_ROUNDS)
        self.assertEqual(writer.calls, config.MAX_ROUNDS + 1)  # first draft + one rewrite per round
        self.assertEqual(result["review"]["unsupported"], ["근거 없는 검사 비용"])
        self.assertIn(config.HUMAN_CHECK, report.splitlines()[0])  # the draft is marked, not published as checked

    def test_the_same_rejection_twice_stops_before_the_round_limit(self):
        # Ping-pong: the rewrite keeps the flagged sentence, so stop at the second review.
        _, result, report, writer = self.run_team(unsupported=["근거 없는 진단"])
        self.assertEqual(result["status"], config.REPEATED_CHECK)
        self.assertEqual((result["round"], writer.calls), (1, 2))  # one rewrite, not MAX_ROUNDS
        self.assertTrue(result["review"]["repeated"])
        self.assertIn(config.REPEATED_CHECK, report.splitlines()[0])


class FailureTests(unittest.TestCase):
    run_team = TeamGraphTests.run_team
    def test_one_failed_researcher_does_not_cancel_the_others(self):
        # The cost researcher fails; both health findings and the place finding survive.
        _, result, report, _ = self.run_team(broken_kinds=("cost",))
        self.assertEqual(sorted(result["findings"]), ["t1", "t2", "t4"])
        self.assertEqual(list(result["failures"]), ["t3"])
        self.assertIn("ConnectionError", result["failures"]["t3"]["error"])
        from team.main import run_record
        record = run_record({**result, "failures": result["failures"]}, 1.0)
        self.assertEqual((record["failed_kinds"], record["failed_errors"]), (["cost"], ["ConnectionError"]))
        self.assertEqual((result["outcome"], result["status"]), ("degraded", config.PASSED))
        # The code, not the writer, states what is missing
        self.assertIn("수집하지 못한 자료: 진료비 통계", report)

    def test_failed_required_research_stops_before_writing(self):
        _, result, report, writer = self.run_team(broken_kinds=("health",))
        self.assertEqual((result["outcome"], result["status"]), ("held", config.RESEARCH_HELD))
        self.assertEqual(writer.calls, 0)  # nothing to write from
        self.assertIn("필수 조사(비슷한 상담 사례)가 오류로 실패", report)
        self.assertIn("말티즈가 설사와 구토를 해요", report)  # the person taking over sees the consultation

    def test_the_writer_and_reviewer_see_what_failed(self):
        state = {**initial_state(), "failures": {"t3": {"kind": "cost", "error": "x"}}}
        self.assertIn("[수집 실패] 진료비 통계", nodes.evidence_text(state))
        self.assertEqual(nodes.research_outcome({**state, "plan": [{"task_id": "t1", "kind": "health"}]}), "degraded")

    def test_model_retries_live_in_one_layer(self):
        # The SDK retries; the graph adds no RetryPolicy, so attempts are not multiplied.
        with patch.object(config.settings, "get_openai_api_key", return_value="sk-test"):
            config.llm.cache_clear()
            config.review_llm.cache_clear()
            config.writer_llm.cache_clear()
            try:
                models = [config.llm(), config.review_llm(), config.writer_llm()]
            finally:
                config.llm.cache_clear()
                config.review_llm.cache_clear()
                config.writer_llm.cache_clear()
        self.assertEqual({model.max_retries for model in models}, {config.MODEL_MAX_RETRIES})
        graph = build_graph()
        self.assertTrue(all(not node.retry_policy for node in graph.builder.nodes.values()))

    def test_run_reports_each_finished_node_and_returns_the_final_state(self):
        from team import main as team_main

        tasks = [VisitTask(kind="health", query="설사", angle="a")]
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        run_dir = Path(directory.name)
        steps = []
        with patch.object(config, "llm", return_value=FakeLLM(tasks)), patch.object(config, "review_llm"), \
                patch.object(nodes, "create_researcher", side_effect=FakeResearcher), \
                patch.object(nodes, "build_judge", side_effect=judge_with([])), \
                patch.object(nodes, "build_verifier"), patch.object(nodes, "recheck_unsupported", return_value=0), \
                patch.object(team_main, "create_writer", side_effect=FakeWriter), \
                patch.object(team_main.tracing, "client", return_value=None):
            state = team_main.run("말티즈가 설사를 해요", run_dir=run_dir, on_step=lambda node, update: steps.append(node))
        self.assertEqual(steps, ["clarify", "ask_guardian", "planner", "researcher", "supervisor", "writer", "reviewer",
                                 "publisher"])
        self.assertEqual(state["run_dir"], run_dir)
        self.assertTrue(state["review"]["passed"])
        self.assertEqual(sorted(path.name for path in run_dir.iterdir()), sorted([config.REPORT_FILE, config.RESULT_FILE]))


class AskGuardianTests(unittest.TestCase):
    """Day51 interrupt: the team stops before planning to ask the guardian, then resumes."""

    def run_app(self, consultation, answer, questions=("언제부터 설사했나요?", "하루에 몇 번인가요?")):
        from langgraph.checkpoint.memory import InMemorySaver

        from team import main as team_main

        checkpointer, thread_id = InMemorySaver(), "visit-test"
        tasks = [VisitTask(kind="health", query="설사", angle="a")]
        llm = FakeLLM(tasks, questions)
        planned = []
        original_planner_input = nodes.PLANNER_INPUT
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        runs = []
        with patch.object(config, "llm", return_value=llm), patch.object(config, "review_llm"),                 patch.object(nodes, "create_researcher", side_effect=FakeResearcher),                 patch.object(nodes, "build_judge", side_effect=judge_with([])),                 patch.object(nodes, "build_verifier"), patch.object(nodes, "recheck_unsupported", return_value=0),                 patch.object(nodes, "PLANNER_INPUT", _Recorder(original_planner_input, planned)),                 patch.object(team_main, "create_writer", side_effect=FakeWriter),                 patch.object(team_main.tracing, "client", return_value=None):
            common = {"checkpointer": checkpointer, "thread_id": thread_id}
            for number in (1, 2):
                run_dir = Path(directory.name) / str(number)
                run_dir.mkdir()
                if number == 1:
                    runs.append(team_main.run(consultation, run_dir=run_dir, ask=True, **common))
                    if not runs[0]["paused"]:
                        break
                else:
                    runs.append(team_main.run(consultation, run_dir=run_dir, resume=answer, **common))
        return runs, planned

    def test_the_run_pauses_with_questions_and_resumes_with_the_answer(self):
        runs, planned = self.run_app("말티즈가 설사를 해요", "어제 저녁부터, 하루 세 번")
        first, second = runs
        self.assertTrue(first["paused"])
        self.assertEqual(first["questions"], ["언제부터 설사했나요?", "하루에 몇 번인가요?"])
        self.assertEqual(first["plan"], [])  # nothing planned or researched before the answer
        self.assertFalse(second["paused"])
        self.assertTrue(second["review"]["passed"])
        # The answer became part of the consultation the planner read and the report may cite
        self.assertIn("(보호자 추가 답변) 어제 저녁부터, 하루 세 번", second["consultation"])
        self.assertEqual(len(planned), 1)
        self.assertIn("어제 저녁부터", planned[0])

    def test_an_empty_answer_skips_and_the_consultation_stays_as_written(self):
        runs, _ = self.run_app("말티즈가 설사를 해요", "")
        self.assertEqual(runs[1]["consultation"], "말티즈가 설사를 해요")
        self.assertTrue(runs[1]["review"]["passed"])

    def test_no_questions_means_no_pause(self):
        runs, _ = self.run_app("말티즈가 설사를 해요", "무시됨", questions=())
        self.assertEqual(len(runs), 1)
        self.assertFalse(runs[0]["paused"])

    def test_urgent_consultations_and_runs_without_asking_never_call_the_model(self):
        llm = SimpleNamespace(with_structured_output=lambda schema: self.fail("clarify called the model"))
        with patch.object(config, "llm", return_value=llm):
            self.assertEqual(nodes.clarify({**initial_state(), "ask": False}), {"questions": []})
            self.assertEqual(nodes.clarify({**initial_state(), "ask": True, "urgent": "경련"}), {"questions": []})


class _Recorder(str):
    """PLANNER_INPUT stand-in that records each formatted planner message."""

    def __new__(cls, template, sink):
        value = super().__new__(cls, template)
        value.sink = sink
        return value

    def format(self, *args, **kwargs):
        text = str.format(self, *args, **kwargs)
        self.sink.append(text)
        return text


class ReworkRuleTests(unittest.TestCase):
    def test_a_second_research_request_goes_back_to_the_writer(self):
        state = {**initial_state(), "review": {"passed": False, "by": "writer"}, "feedback": "영업 여부가 없습니다",
                 "plan": [{"task_id": "t1", "kind": "health"}, {"task_id": "t2", "kind": "health", "extra": True}]}
        with patch.object(config, "llm") as llm:
            step = nodes.supervisor(state)
        llm.assert_not_called()  # decided in code, no model call
        self.assertEqual((step.goto, step.update["round"]), ("writer", 1))
        self.assertEqual(step.update["instruction"], nodes.WRITE_WITH_WHAT_EXISTS)

    def test_the_first_research_request_still_reaches_the_planner(self):
        state = {**initial_state(), "review": {"passed": False, "by": "writer"}, "feedback": "비용 자료가 없습니다",
                 "plan": [{"task_id": "t1", "kind": "health"}]}
        with patch.object(config, "llm", return_value=FakeLLM([])):
            with patch.object(FakeLLM, "with_structured_output",
                              return_value=SimpleNamespace(invoke=lambda m: ReworkStep(next="planner", instruction="비용"))):
                step = nodes.supervisor(state)
        self.assertEqual(step.goto, "planner")

    def test_planner_adds_no_second_place_task_and_marks_extra_tasks(self):
        extra = [VisitTask(kind="place", query="강남구 24시", angle="a"), VisitTask(kind="cost", query="비용", angle="b")]
        state = {**initial_state(), "plan": [{"task_id": "t1", "kind": "place", "query": "강남구"}], "findings": {"t1": {}}}
        with patch.object(config, "llm", return_value=FakeLLM(extra)):
            update = nodes.planner(state)
        added = update["plan"][1:]
        self.assertEqual([(task["task_id"], task["kind"], task["extra"]) for task in added], [("t2", "cost", True)])

    def test_evidence_includes_the_urgency_decision_and_the_region(self):
        state = {**initial_state(), "urgent": "응급 징후가 의심됩니다."}
        text = nodes.evidence_text(state)
        self.assertIn("[응급 판정]", text)
        self.assertIn("보호자가 입력한 지역: 강남구", text)


if __name__ == "__main__":
    unittest.main()
