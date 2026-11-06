"""scripts/eval_coverage.py: kinds held up by one question."""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from eval_coverage import AUTOMATED, SET_FILES, kind_of, load_sets, set_table  # noqa: E402

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


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

    def test_the_labels_follow_the_workflows(self):
        weekly = (WORKFLOWS / "regression-eval.yml").read_text(encoding="utf-8")
        line = next(l for l in weekly.splitlines() if "scripts/check_regression.py crag" in l)
        weekly_sets = re.findall(r'(\w+) "\$RUN_NAME"', line)
        self.assertEqual(sorted(weekly_sets), sorted(SET_FILES))
        self.assertEqual(sorted(AUTOMATED), sorted(SET_FILES.values()))
        pr_lines = [l for l in (WORKFLOWS / "pr-quality.yml").read_text(encoding="utf-8").splitlines() if 'sets="' in l]
        pr_sets = {name for name in SET_FILES for l in pr_lines if re.search(rf"\b{name}\b", l)}
        self.assertEqual(pr_sets, {"crag", "routing", "guard"})
        for name, file in SET_FILES.items():
            self.assertIn("주간", AUTOMATED[file], name)
            self.assertEqual("PR" in AUTOMATED[file], name in pr_sets, name)


if __name__ == "__main__":
    unittest.main()
