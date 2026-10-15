"""scripts/eval_coverage.py: kinds held up by one question."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from eval_coverage import AUTOMATED, kind_of, load_sets, set_table  # noqa: E402


class CoverageTests(unittest.TestCase):
    def test_kind_fields(self):
        self.assertEqual(kind_of("place_routing_questions.json", {"route": "sql", "kind": "hospital"}), "sql/hospital")
        self.assertEqual(kind_of("health_relevance_100.json", {"gold_labels": {"meta.department": "안과"}}), "안과")
        self.assertEqual(kind_of("x.json", {"group": "a", "kind": "b"}), "a")
        self.assertEqual(kind_of("x.json", {"question": "?"}), "(구분 없음)")

    def test_a_kind_with_one_question_is_flagged(self):
        table = set_table({"s.json": [{"kind": "a"}, {"kind": "a"}, {"kind": "b"}]})
        self.assertIn("| s | 수동 | 3 | 2 | b |", table)

    def test_the_automated_sets_exist(self):
        sets = load_sets()
        for name in AUTOMATED:
            self.assertTrue(sets.get(name), name)


if __name__ == "__main__":
    unittest.main()
