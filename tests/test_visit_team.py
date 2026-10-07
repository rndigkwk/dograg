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
from team.core.schemas import Finding, KeyPoint, ReworkStep, VisitPlan, VisitTask
from team.graph import edges, nodes
from team.graph.builder import build_graph
from team.graph.state import merge_findings
from team.tools import handoff


class FakeLLM:
    """Structured outputs for the planner (VisitPlan) and supervisor (ReworkStep)."""

    def __init__(self, tasks):
        self.tasks = tasks

    def with_structured_output(self, schema):
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
    claims = [SimpleNamespace(text=text, verdict="unsupported") for text in unsupported]
    claims.append(SimpleNamespace(text="증상 정리", verdict="supported"))
    return lambda model: SimpleNamespace(invoke=lambda inputs: SimpleNamespace(claims=claims))


def initial_state(region="강남구"):
    return {"consultation": "말티즈가 설사와 구토를 해요", "region": region, "profile": "", "urgent": "",
            "plan": [], "findings": {}, "round": 0, "draft": "", "review": None, "feedback": "", "instruction": ""}


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
    def run_team(self, unsupported):
        tasks = [VisitTask(kind="health", query="설사", angle="a"), VisitTask(kind="health", query="구토", angle="b"),
                 VisitTask(kind="cost", query="진료비", angle="c")]
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        run_dir = Path(directory.name)
        writer = FakeWriter(run_dir)
        with patch.object(config, "llm", return_value=FakeLLM(tasks)), \
                patch.object(nodes, "create_researcher", side_effect=FakeResearcher), \
                patch.object(nodes, "build_judge", side_effect=judge_with(unsupported)), \
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
        _, result, report, writer = self.run_team(unsupported=["근거 없는 진단"])
        self.assertEqual(result["status"], config.HUMAN_CHECK)
        self.assertEqual(result["round"], config.MAX_ROUNDS)
        self.assertEqual(writer.calls, config.MAX_ROUNDS + 1)  # first draft + one rewrite per round
        self.assertEqual(result["review"]["unsupported"], ["근거 없는 진단"])
        self.assertIn(config.HUMAN_CHECK, report.splitlines()[0])  # the draft is marked, not published as checked

    def test_run_reports_each_finished_node_and_returns_the_final_state(self):
        from team import main as team_main

        tasks = [VisitTask(kind="health", query="설사", angle="a")]
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        run_dir = Path(directory.name)
        steps = []
        with patch.object(config, "llm", return_value=FakeLLM(tasks)),                 patch.object(nodes, "create_researcher", side_effect=FakeResearcher),                 patch.object(nodes, "build_judge", side_effect=judge_with([])),                 patch.object(nodes, "build_verifier"), patch.object(nodes, "recheck_unsupported", return_value=0),                 patch.object(team_main, "create_writer", side_effect=FakeWriter),                 patch.object(team_main.tracing, "client", return_value=None):
            state = team_main.run("말티즈가 설사를 해요", run_dir=run_dir, on_step=lambda node, update: steps.append(node))
        self.assertEqual(steps, ["planner", "researcher", "supervisor", "writer", "reviewer", "publisher"])
        self.assertEqual(state["run_dir"], run_dir)
        self.assertTrue(state["review"]["passed"])
        self.assertEqual(sorted(path.name for path in run_dir.iterdir()), sorted([config.REPORT_FILE, config.RESULT_FILE]))


if __name__ == "__main__":
    unittest.main()
