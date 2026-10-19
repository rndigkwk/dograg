"""scripts/slo_report.py: service levels from the masked run records and model-call costs (2026-10-19)."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import slo_report


def chat(trace, route, seconds, abstained=False, error=None, **extra):
    record = {"route": route, "latency_ms": seconds * 1000, "abstained": abstained, "error": error, **extra}
    return {"traceId": trace, "output": json.dumps(record)}


class SloReportTests(unittest.TestCase):
    def test_summary_from_runs_and_costs(self):
        chats = [chat(f"t{i}", "rag", 10 + i, abstained=i < 3) for i in range(10)]
        chats += [chat("r1", "analysis", 30), chat("e1", "none", 1, error="Timeout")]
        generations = [{"traceId": "t0", "totalCost": 0.002}, {"traceId": "t0", "totalCost": 0.001},
                       {"traceId": "r1", "totalCost": 0.003}]
        summary = slo_report.summarize(chats, generations)
        self.assertEqual(summary["questions"], 12)
        self.assertEqual(summary["by_route"], {"rag": 10, "analysis": 1, "none": 1})
        self.assertAlmostEqual(summary["error_rate"], 1 / 12)
        self.assertEqual(summary["rag_p95_s"], 19)
        self.assertEqual(summary["report_p95_s"], 30)
        self.assertAlmostEqual(summary["rag_abstain_rate"], 0.3)
        self.assertAlmostEqual(summary["cost_per_question_usd"], 0.006 / 12)

    def test_guide_share_counts_answered_health_questions_that_record_it(self):
        chats = [chat("g1", "rag", 8, guide_count=1), chat("g2", "rag", 10, guide_count=2),
                 chat("n1", "rag", 6, guide_count=0), chat("a1", "rag", 3, abstained=True, guide_count=0),
                 chat("old", "rag", 5)]  # a record from before guide_count: left out
        generations = [{"traceId": "g1", "totalCost": 0.004}, {"traceId": "g2", "totalCost": 0.006},
                       {"traceId": "n1", "totalCost": 0.003}]
        summary = slo_report.summarize(chats, generations)
        self.assertEqual(summary["rag_answered_with_guide_count"], 3)
        self.assertAlmostEqual(summary["rag_guide_rate"], 2 / 3)
        self.assertAlmostEqual(summary["rag_cost_with_guide_usd"], 0.005)
        self.assertAlmostEqual(summary["rag_cost_without_guide_usd"], 0.003)
        self.assertEqual(summary["rag_p50_with_guide_s"], 8)
        self.assertEqual(summary["rag_p50_without_guide_s"], 6)

    def test_no_guide_records_give_no_share(self):
        summary = slo_report.summarize([chat("t1", "rag", 5)], [])
        self.assertIsNone(summary["rag_guide_rate"])

    def test_misses_are_judged_only_on_enough_questions(self):
        summary = {"questions": slo_report.MIN_QUESTIONS, "error_rate": 0.05, "rag_p95_s": 10.0,
                   "report_p95_s": None, "rag_abstain_rate": 0.1, "cost_per_question_usd": 0.001}
        self.assertEqual(slo_report.misses(summary), ["error_rate 0.05 > 0.02"])
        self.assertEqual(slo_report.misses({**summary, "questions": slo_report.MIN_QUESTIONS - 1}), [])

    def test_nearest_rank_percentile(self):
        self.assertEqual(slo_report.percentile([5, 1, 3, 2, 4], 0.5), 3)
        self.assertEqual(slo_report.percentile(list(range(1, 21)), 0.95), 19)
        self.assertIsNone(slo_report.percentile([], 0.95))


if __name__ == "__main__":
    unittest.main()
