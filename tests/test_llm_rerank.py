import unittest

from scripts.evaluate_llm_rerank import analyze, hit_at, llm_order, mcnemar_p


def record(ids, gold, useful5, useful12):
    return {
        "ids": ids, "gold": gold,
        "llm5": {"useful_ids": useful5, "error": None, "tokens": 10, "seconds": 1.0},
        "llm12": {"useful_ids": useful12, "error": None, "tokens": 20, "seconds": 2.0},
    }


class LlmRerankTests(unittest.TestCase):
    def test_selected_ids_come_first_and_unknown_ids_are_dropped(self):
        full, kept = llm_order(["a", "b", "c", "d"], ["[c]", "x", "a", "c"])
        self.assertEqual(kept, ["c", "a"])
        self.assertEqual(full, ["c", "a", "b", "d"])

    def test_hit_at_three(self):
        self.assertTrue(hit_at(["a", "b", "c", "d"], {"c"}))
        self.assertFalse(hit_at(["a", "b", "c", "d"], {"d"}))

    def test_mcnemar_is_symmetric_and_bounded(self):
        self.assertEqual(mcnemar_p(0, 0), 1.0)
        self.assertAlmostEqual(mcnemar_p(10, 0), 2 / 2**10)
        self.assertEqual(mcnemar_p(3, 5), mcnemar_p(5, 3))

    def test_analyze_counts_gains_losses_and_ceilings(self):
        ids = [str(i) for i in range(12)]
        records = [
            record(ids, ["4"], ["4"], ["4"]),      # gold at 5th: LLM pulls it up
            record(ids, ["0"], ["1", "2", "3"], ["0"]),  # @5 pushes gold out of top 3
            record(ids, ["9"], [], ["9"]),          # only the 12-pool can reach it
        ]
        summary = analyze(records)
        self.assertEqual(summary["hybrid"]["hits"], 1)
        self.assertEqual((summary["llm@5"]["gained"], summary["llm@5"]["lost"]), (1, 1))
        self.assertEqual((summary["llm@12"]["gained"], summary["llm@12"]["lost"]), (2, 0))
        self.assertEqual(summary["oracle@5"]["hits"], 2)
        self.assertEqual(summary["oracle@12"]["hits"], 3)
        self.assertEqual(summary["llm@5"]["empty_selection"], 1)


if __name__ == "__main__":
    unittest.main()
