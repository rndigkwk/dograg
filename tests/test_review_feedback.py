"""scripts/review_feedback.py: 👎 rows become evaluation candidates once each."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from review_feedback import candidates  # noqa: E402

ROW = {"id": 7, "created_at": datetime(2026, 10, 15, tzinfo=timezone.utc), "trace_id": "t", "route": "rag",
       "reason": "틀린 정보", "question": "기침해요 [전화번호]", "answer": "병원에 가세요", "evidence": ["성견 / 내과"]}


class CandidateTests(unittest.TestCase):
    def test_a_row_becomes_a_candidate_with_blanks_for_a_person(self):
        [item] = candidates([ROW], set())
        self.assertEqual((item["id"], item["question"], item["route"], item["reason"]), ("fb-7", "기침해요 [전화번호]", "rag", "틀린 정보"))
        self.assertEqual((item["expected"], item["reference"]), ("", ""))

    def test_exported_rows_are_skipped(self):
        self.assertEqual(candidates([ROW], {"fb-7"}), [])


if __name__ == "__main__":
    unittest.main()
