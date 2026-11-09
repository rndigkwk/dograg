"""scripts/answer_top_k_experiment.py: the summary and the decision set before measuring."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import answer_top_k_experiment as experiment


def row(recall3, recall5, verdict3, verdict5, seconds3=4.0, seconds5=4.5):
    arm = lambda recall, verdict, seconds: {"context_recall": recall, "verdict": verdict, "seconds": seconds,
                                            "context_chars": 1000, "answer": "", "cases": []}
    return {"k3": arm(recall3, verdict3, seconds3), "k5": arm(recall5, verdict5, seconds5)}


class TopKDecisionTests(unittest.TestCase):
    def summary(self, rows):
        return experiment.summarize(rows, count_unsupported=lambda r, arm: 0)

    def test_five_is_kept_only_when_every_check_passes(self):
        rows = [row(0.3, 0.5, "fail", "pass") for _ in range(4)] + [row(0.5, 0.5, "pass", "pass") for _ in range(6)]
        out = self.summary(rows)
        self.assertEqual((out["k3"]["fail"], out["k5"]["fail"], out["fail_to_pass"]), (4, 0, 4))
        self.assertTrue(experiment.decide(out)["change"])

    def test_three_fewer_fails_or_a_slower_answer_keeps_three(self):
        rows = [row(0.3, 0.4, "fail", "pass") for _ in range(3)] + [row(0.5, 0.6, "pass", "pass") for _ in range(7)]
        decision = experiment.decide(self.summary(rows))
        self.assertFalse(decision["fails_fall_by_4"])
        self.assertFalse(decision["change"])
        rows = [row(0.3, 0.4, "fail", "pass", 4.0, 5.5) for _ in range(5)]
        self.assertFalse(experiment.decide(self.summary(rows))["median_seconds_up_at_most_1"])

    def test_no_decision_until_every_row_is_scored(self):
        rows = [row(0.3, 0.4, "fail", "pass"), row(0.3, 0.4, "fail", "pass")]
        del rows[1]["k5"]["context_recall"]
        self.assertIsNone(experiment.decide(self.summary(rows)))


class HoldoutTwoTests(unittest.TestCase):
    def test_the_committed_rows_are_new_and_rebuild_the_same(self):
        import json

        built = experiment.build_holdout2()
        saved = json.loads(experiment.HOLDOUT2.read_text(encoding="utf-8"))
        self.assertEqual(built["rows"], saved["rows"])
        self.assertEqual(len(set(saved["rows"])), experiment.HOLDOUT2_SIZE)
        data = experiment.PROJECT_DIR / "tests" / "data"
        read = [int(item["row"]) for name in ("health_relevance_100.json", "health_relevance_dental.json", "crag_grader_labels.json")
                for item in json.loads((data / name).read_text(encoding="utf-8"))["items"]]
        same = json.loads((data / "eval_overlap_labels.json").read_text(encoding="utf-8"))["same"]
        self.assertFalse(set(saved["rows"]) & (set(read) | set(same)))
        self.assertEqual(saved["excluded"]["crag_eval_questions"], 20)

    def test_holdout2_compares_the_app_with_both_changes(self):
        self.assertEqual(experiment.arms("holdout2"), {"k3": (3, False), "k5_rules": (5, True)})
        self.assertEqual(experiment.arms("holdout"), {"k3": (3, False), "k5": (5, False)})


if __name__ == "__main__":
    unittest.main()
