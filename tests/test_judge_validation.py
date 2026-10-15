"""scripts/judge_validation.py: the scorecard arithmetic."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from judge_validation import card, kappa, two_way  # noqa: E402


class KappaTests(unittest.TestCase):
    def test_perfect_and_chance(self):
        self.assertEqual(kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]), 1.0)
        self.assertEqual(kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]), 0.0)

    def test_matches_scikit_learn_values(self):
        human = [0, 1, 2, 2, 1, 0, 2, 1, 0, 2]
        judge = [0, 2, 2, 1, 1, 0, 2, 2, 1, 2]
        # sklearn.metrics.cohen_kappa_score(human, judge) and (..., weights="quadratic")
        self.assertAlmostEqual(kappa(human, judge), 0.385, places=3)
        self.assertAlmostEqual(kappa(human, judge, "quadratic"), 0.701, places=3)


class CardTests(unittest.TestCase):
    def test_a_judge_that_always_passes_agrees_often_and_catches_nothing(self):
        human = ["pass"] * 8 + ["fail"] * 2
        result = card(human, ["pass"] * 10, "fail")
        self.assertEqual((result["agreement"], result["failure_caught"], result["pass_kept"]), (0.8, 0.0, 1.0))
        self.assertEqual(result["kappa"], 0.0)

    def test_misses_and_false_alarms(self):
        result = card(["fail", "fail", "pass", "pass"], ["fail", "pass", "fail", "pass"], "fail")
        self.assertEqual((result["failure_caught"], result["pass_kept"]), (0.5, 0.5))


class TwoWayTests(unittest.TestCase):
    def test_a_winner_only_when_both_orders_agree(self):
        self.assertEqual(two_way("original", "original"), "original")
        self.assertEqual(two_way("original", "variant"), "tie")
        self.assertEqual(two_way("tie", "tie"), "tie")


if __name__ == "__main__":
    unittest.main()
