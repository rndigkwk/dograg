"""scripts/relevance_set.py: the saved relevance set and its metrics, without model calls."""

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

import relevance_set


def item(grades, ranking, labels=None, gold=None):
    return {"grades": grades, "rankings": {"hybrid": ranking}, "doc_labels": labels or {}, "gold_labels": gold or {}}


class MetricTests(unittest.TestCase):
    def test_top_three_only_and_each_metric(self):
        items = [
            item({"a": 0, "b": 1, "c": 2, "d": 2}, ["a", "b", "c", "d"],
                 labels={"a": {"x": "1"}}, gold={"x": "1"}),           # useful in the top 3, label hit
            item({"a": 1, "b": 0, "c": 0, "d": 2}, ["a", "b", "c", "d"]),  # the grade-2 doc is 4th
        ]
        result = relevance_set.metrics(items, lambda it: it["rankings"]["hybrid"])
        self.assertEqual(result["useful@3"], 0.5)
        self.assertEqual(result["relevant@3"], 1.0)
        self.assertEqual(result["precision@3"], round((2 / 3 + 1 / 3) / 2, 3))
        self.assertEqual(result["label_hit@3"], 0.5)
        self.assertEqual(result["judged_share"], 1.0)

    def test_unjudged_documents_count_as_not_useful_and_lower_coverage(self):
        result = relevance_set.metrics([item({"a": 2}, ["x", "y", "a"])], lambda it: it["rankings"]["hybrid"])
        self.assertEqual((result["useful@3"], result["judged_share"]), (1.0, round(1 / 3, 3)))


class SavedSetTests(unittest.TestCase):
    def test_saved_set_has_a_graded_pool_per_question(self):
        items = relevance_set.load_items()
        self.assertEqual(len(items), relevance_set.SAMPLE_SIZE)
        self.assertEqual(len({it["row"] for it in items}), relevance_set.SAMPLE_SIZE)
        for it in items:
            self.assertTrue(set(it["grades"].values()) <= {0, 1, 2})
            # every ranked document was judged, so reordering the pool needs no new grades
            self.assertTrue(set(it["rankings"]["hybrid"]) <= set(it["grades"]))


if __name__ == "__main__":
    unittest.main()
