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


if __name__ == "__main__":
    unittest.main()
