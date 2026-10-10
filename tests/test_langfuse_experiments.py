"""scripts/langfuse_experiments.py: dataset items and evaluators, without Langfuse calls."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

import langfuse_experiments as experiments

from src.private_data import needs_private_data


def scores(evaluator, **kwargs):
    result = evaluator(**kwargs)
    return {e.name: e.value for e in (result if isinstance(result, list) else [result])}


class DatasetItemTests(unittest.TestCase):
    @needs_private_data
    def test_items_have_fixed_ids_and_expected_outputs(self):
        crag = experiments.dataset_items("crag")
        routing = experiments.dataset_items("routing")
        self.assertEqual((len(crag), len(routing)), (60, 36))
        self.assertEqual(len({item["id"] for item in crag + routing}), 96)
        report = next(item for item in crag if item["metadata"]["id"] == "r06")
        self.assertEqual(report["expected_output"]["behavior"], "answer")
        self.assertTrue(report["expected_output"]["gold_pages"])
        self.assertEqual(routing[0]["expected_output"], {"route": "sql", "kind": "hospital"})

    def test_visit_items_carry_the_team_inputs(self):
        visit = experiments.dataset_items("visit")
        self.assertEqual(len(visit), 12)
        self.assertEqual(set(visit[0]["input"]), {"consultation", "region", "profile"})
        self.assertEqual(sum(item["expected_output"]["urgent"] for item in visit), 4)
        self.assertEqual(sum(item["expected_output"]["scope"] != "dog" for item in visit), 2)


class EvaluatorTests(unittest.TestCase):
    def test_crag_item_scores(self):
        correct, gold, latency = experiments.crag_evaluators()
        output = {"outcome": "partial", "latency_s": 6.2, "evidence_pages": [["a.pdf", 3]]}
        self.assertEqual(scores(correct, output=output, expected_output={"behavior": "answer"}), {"correct_behavior": 1.0})
        self.assertEqual(scores(correct, output=output, expected_output={"behavior": "abstain"}), {"correct_behavior": 0.0})
        self.assertEqual(scores(gold, output=output, expected_output={"gold_pages": [["a.pdf", 3]]}), {"gold_page_hit": 1.0})
        self.assertEqual(scores(gold, output=output, expected_output={"gold_pages": []}), {})
        self.assertEqual(scores(latency, output=output), {"latency_s": 6.2})

    def test_crag_run_scores(self):
        [summary] = experiments.crag_run_evaluators()
        results = [
            SimpleNamespace(item=SimpleNamespace(expected_output={"behavior": expected}),
                            output={"outcome": outcome, "latency_s": latency},
                            evaluations=[SimpleNamespace(name="correct_behavior", value=value)])
            for expected, outcome, latency, value in (
                ("answer", "answer", 4.0, 1.0), ("answer", "abstain", 2.0, 0.0),
                ("abstain", "abstain", 1.0, 1.0), ("abstain", "partial", 9.0, 0.0),
            )
        ]
        values = scores(summary, item_results=results)
        self.assertEqual(values["accuracy"], 0.5)
        self.assertEqual((values["over_abstain"], values["missed_abstain"]), (0.5, 0.5))
        self.assertEqual(values["latency_p90_s"], 4.0)

    def test_routing_scores_skip_kind_for_non_searches(self):
        route, kind = experiments.routing_evaluators()
        self.assertEqual(scores(kind, output={"route": "rag", "kind": None}, expected_output={"route": "rag", "kind": None}), {})
        self.assertEqual(scores(route, output={"route": "rag", "kind": None}, expected_output={"route": "sql", "kind": "hospital"}),
                         {"route_correct": 0.0})

    def test_visit_scores(self):
        passed, urgent, scope, hospitals, numbers, repeat, _, _ = experiments.visit_evaluators()
        output = {"status": "human_check", "urgent": True, "says_no_evidence": False, "hospitals": 0,
                  "round": 2, "latency_s": 53.0, "visits": {"planner": 1, "writer": 3, "reviewer": 3},
                  "repeated_nodes": ["reviewer", "writer"]}
        self.assertEqual(scores(passed, output=output), {"passed": 0.0})
        self.assertEqual(scores(urgent, output=output, expected_output={"urgent": False}), {"urgent_correct": 0.0})
        self.assertEqual(scores(scope, output=output, expected_output={"scope": "dog"}), {"scope_handled": 0.0})
        self.assertEqual(scores(scope, output=output, expected_output={"scope": "other_species"}), {"scope_handled": 1.0})
        passed_report = {**output, "status": "passed", "says_no_evidence": True}
        self.assertEqual(scores(scope, output=passed_report, expected_output={"scope": "other_species"}), {"scope_handled": 1.0})
        self.assertEqual(scores(hospitals, input={"region": ""}, output=output), {})
        self.assertEqual(scores(hospitals, input={"region": "강남구"}, output=output), {"hospitals_listed": 0.0})
        self.assertEqual(scores(numbers, output=output), {"rounds": 2, "latency_s": 53.0, "node_visits": 7})
        self.assertEqual(scores(repeat, output=output), {"repeat_suspect": 1.0})
        self.assertEqual(scores(repeat, output={**output, "repeated_nodes": []}), {"repeat_suspect": 0.0})

    def test_fee_citations_are_checked_against_the_survey_and_the_region(self):
        rows = [{"level": "sigungu", "sido": "서울특별시", "sigungu": "강남구", "item": "엑스선 촬영비와 판독료",
                 "median": "50000", "mean": "51099", "min": "15000", "max": "110000"},
                {"level": "sido", "sido": "대구광역시", "sigungu": "", "item": "엑스선 촬영비와 판독료",
                 "median": "40000", "mean": "42000", "min": "10000", "max": "90000"}]
        gangnam, daegu = "fee-서울특별시-강남구-엑스선-촬영비와-판독료-(체중-5kg)", "fee-대구광역시-엑스선-촬영비와-판독료-(체중-5kg)"
        report = (f"중간 50,000원, 평균 51,099원, 범위 15,000~110,000원입니다. [{gangnam}]\n"
                  "비용이 걱정되면 미리 전화하세요. [상담 내용]")
        with patch.object(experiments, "_fee_rows", return_value=rows):
            self.assertEqual(experiments.fee_citations(report), {"fee_ids": [gangnam], "fee_amounts": 4, "fee_amounts_wrong": []})
            self.assertEqual(experiments.fee_citations(report.replace("51,099원", "52,000원"))["fee_amounts_wrong"], ["52,000"])
        *_, regional, region = experiments.visit_evaluators()
        asked = {"region": "강남구", "consultation": "엑스레이 비용이 걱정돼요"}
        output = {"fee_ids": [gangnam], "fee_amounts": 4, "fee_amounts_wrong": []}
        self.assertEqual(scores(regional, input=asked, output=output), {"regional_fee_cited": 1.0, "fee_amounts_exact": 1.0})
        self.assertEqual(scores(regional, input={**asked, "consultation": "다리를 절어요"}, output=output), {})
        self.assertEqual(scores(region, input={"region": "해운대구"}, output={"fee_ids": [daegu]}), {"fee_region_ok": 0.0})
        self.assertEqual(scores(region, input={"region": "강남구"}, output=output), {"fee_region_ok": 1.0})

    def test_visit_run_scores_count_dog_cases_for_the_pass_rate(self):
        [summary] = experiments.visit_run_evaluators()
        results = [
            SimpleNamespace(item=SimpleNamespace(expected_output={"scope": scope}),
                            output={"status": status, "latency_s": latency},
                            evaluations=[SimpleNamespace(name="passed", value=float(status == "passed"))])
            for scope, status, latency in (("dog", "passed", 60.0), ("dog", "human_check", 100.0),
                                           ("other_species", "human_check", 40.0))
        ]
        values = scores(summary, item_results=results)
        self.assertEqual(values["dog_pass_rate"], 0.5)
        self.assertAlmostEqual(values["human_check_rate"], 2 / 3)
        self.assertEqual(values["latency_p50_s"], 60.0)


if __name__ == "__main__":
    unittest.main()
