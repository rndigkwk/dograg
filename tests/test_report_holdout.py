"""tests/data/report_holdout_questions.json: every holdout question has a hand-written reference, and a
two-report question counts as covered only when both reports' gold pages are in the evidence (2026-10-18)."""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

from evaluate_report_pages import (
    HOLDOUT,
    REFERENCES,
    expected_verdict,
    has_every_gold_report,
    has_gold,
)


def doc(name, page):
    return SimpleNamespace(page_content="", metadata={"source": f"data/source/{name}", "page": page})


class ReportHoldoutTests(unittest.TestCase):
    def test_every_question_has_a_reference_and_gold_pages(self):
        items = json.loads(HOLDOUT.read_text(encoding="utf-8"))["items"]
        refs = {row["id"]: row for row in json.loads(REFERENCES.read_text(encoding="utf-8"))["items"]}
        self.assertEqual(len(items), 23)
        self.assertEqual(len({item["id"] for item in items}), 23)
        for item in items:
            self.assertEqual(bool(item["gold_pages"]), item["expected"] == "answer", item["id"])
            self.assertTrue(refs[item["id"]]["reference"], item["id"])
            self.assertEqual(refs[item["id"]]["gold_pages"], item["gold_pages"], item["id"])
        unnamed = [item for item in items if item["kind"] == "multi_unnamed"]
        self.assertEqual(len(unnamed), 4)
        for item in unnamed:
            self.assertGreaterEqual(len({name for name, _ in item["gold_pages"]}), 2, item["id"])

    def test_a_two_report_question_needs_a_gold_page_of_each_report(self):
        item = {"gold_pages": [["KB.pdf", 42], ["KB.pdf", 50], ["복지.pdf", 170]]}
        one_report = [doc("KB.pdf", 42), doc("KB.pdf", 50), doc("복지.pdf", 12)]
        self.assertTrue(has_gold(one_report, item))
        self.assertFalse(has_every_gold_report(one_report, item))
        self.assertTrue(has_every_gold_report([doc("KB.pdf", 50), doc("복지.pdf", 170)], item))


    def test_a_question_the_reports_cannot_answer_is_right_when_declined(self):
        abstain = {"expected": "abstain"}
        self.assertEqual(expected_verdict(abstain, "abstained"), "correct")
        self.assertEqual(expected_verdict(abstain, "wrong"), "wrong")
        self.assertEqual(expected_verdict({"expected": "answer"}, "abstained"), "abstained")


if __name__ == "__main__":
    unittest.main()
