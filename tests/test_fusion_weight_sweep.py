import unittest

from scripts.evaluate_fusion_weights import (
    analyze,
    first_gold_rank,
    fused_ids,
    split_indices,
    summarize_ranks,
)


def record(dense, bm25, gold, dense_pool=None):
    return {
        "dense_ids": dense,
        "dense_pool_ids": dense_pool or dense,
        "bm25_ids": bm25,
        "gold_ids": gold,
    }


class FusionWeightSweepTests(unittest.TestCase):
    def test_weight_extremes_follow_single_retriever_order(self):
        dense = ["a", "b", "c"]
        bm25 = ["c", "b", "a"]

        self.assertEqual(fused_ids(dense, bm25, bm25_weight=0.0), ["a", "b", "c"])
        self.assertEqual(fused_ids(dense, bm25, bm25_weight=1.0), ["c", "b", "a"])

    def test_rank_summary_counts_only_top_three(self):
        summary = summarize_ranks([1, 2, 4, None])

        self.assertEqual(summary["misses"], 2)
        self.assertAlmostEqual(summary["hit@3"], 0.5)
        self.assertAlmostEqual(summary["mrr@3"], (1 + 0.5) / 4)

    def test_first_gold_rank_is_none_without_gold(self):
        self.assertIsNone(first_gold_rank(["a", "b"], set()))
        self.assertEqual(first_gold_rank(["a", "b"], {"b"}), 2)

    def test_split_is_deterministic_and_disjoint(self):
        tune, holdout = split_indices(11)

        self.assertEqual((tune, holdout), split_indices(11))
        self.assertFalse(set(tune) & set(holdout))
        self.assertEqual(sorted(tune + holdout), list(range(11)))

    def test_pool_recall_counts_gold_outside_fused_top_three(self):
        dense = [f"d{i}" for i in range(12)]
        bm25 = [f"b{i}" for i in range(12)]
        records = [
            record(dense, bm25, ["d0"]),
            record(dense, bm25, ["b11"]),
            record(dense, bm25, ["nowhere"]),
        ]

        result = analyze(records)

        pool = result["candidate_pool_recall"]["dense12+bm2512"]
        self.assertEqual(pool["found"], 2)
        self.assertEqual(result["weight_sweep_bm25_weight"]["0.5"]["all"]["misses"], 2)


if __name__ == "__main__":
    unittest.main()
