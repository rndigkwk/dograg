"""scripts/langfuse_experiments.py: dataset items and evaluators, without Langfuse calls."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

import langfuse_experiments as experiments


def scores(evaluator, **kwargs):
    result = evaluator(**kwargs)
    return {e.name: e.value for e in (result if isinstance(result, list) else [result])}


class DatasetItemTests(unittest.TestCase):
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
        passed, urgent, scope, hospitals, numbers = experiments.visit_evaluators()
        output = {"status": "human_check", "urgent": True, "says_no_evidence": False, "hospitals": 0,
                  "round": 2, "latency_s": 53.0}
        self.assertEqual(scores(passed, output=output), {"passed": 0.0})
        self.assertEqual(scores(urgent, output=output, expected_output={"urgent": False}), {"urgent_correct": 0.0})
        self.assertEqual(scores(scope, output=output, expected_output={"scope": "dog"}), {"scope_handled": 0.0})
        self.assertEqual(scores(scope, output=output, expected_output={"scope": "other_species"}), {"scope_handled": 1.0})
        passed_report = {**output, "status": "passed", "says_no_evidence": True}
        self.assertEqual(scores(scope, output=passed_report, expected_output={"scope": "other_species"}), {"scope_handled": 1.0})
        self.assertEqual(scores(hospitals, input={"region": ""}, output=output), {})
        self.assertEqual(scores(hospitals, input={"region": "강남구"}, output=output), {"hospitals_listed": 0.0})
        self.assertEqual(scores(numbers, output=output), {"rounds": 2, "latency_s": 53.0})

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
