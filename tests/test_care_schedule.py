"""src/care_schedule.py: the care schedule's next dates on the server, the same as the web page's."""

import re
import unittest
from datetime import date
from pathlib import Path

from src import care_schedule as care
from src.health_safety import SAVED_NOTES_HEADING, detect_urgent_sign, todays_text

WEB = Path(__file__).resolve().parents[1] / "web" / "src" / "lib" / "careSchedule.ts"
TODAY = date(2026, 10, 20)


class NextDueTests(unittest.TestCase):
    def test_the_guide_intervals_and_month_ends(self):
        item = care.ITEMS_BY_ID
        self.assertEqual(care.next_due(item["deworming"], date(2026, 6, 10), TODAY)[:2], (date(2026, 9, 10), date(2026, 12, 10)))
        self.assertEqual(care.next_due(item["heartworm"], date(2026, 1, 31), TODAY)[0], date(2026, 2, 28))
        self.assertEqual(care.next_due(item["nails"], date(2026, 10, 1), TODAY)[:2], (date(2026, 10, 15), date(2026, 10, 22)))

    def test_states(self):
        item = care.ITEMS_BY_ID
        self.assertEqual(care.next_due(item["rabies"], date(2025, 9, 1), TODAY)[2], "overdue")
        self.assertEqual(care.next_due(item["deworming"], date(2026, 6, 10), TODAY)[2], "due")
        self.assertEqual(care.next_due(item["vaccine"], date(2026, 3, 1), TODAY)[2], "later")

    def test_only_due_or_overdue_items_become_lines(self):
        lines = care.due_lines({"rabies": "2025-09-01", "vaccine": "2026-03-01", "deworming": "2026-06-10",
                                "unknown": "2026-01-01", "nails": "2026-13-01", "checkup": "2027-01-01"}, TODAY)
        self.assertEqual(lines, [
            "- 내부 기생충 구충제: 마지막 2026-06-10, 다음 예정 2026-09-10 ~ 2026-12-10 (3~6개월 간격, 지침 40쪽) — 지금 할 때",
            "- 광견병 추가접종: 마지막 2025-09-01, 다음 예정 2026-09-01 (매년 1회, 지침 39쪽) — 기한이 지났음",
        ])
        self.assertEqual(care.care_section({"vaccine": "2026-03-01"}, TODAY), "")

    def test_the_server_and_the_web_page_use_the_same_items(self):
        web = WEB.read_text(encoding="utf-8")
        found = re.findall(r'\{ id: "(\w+)", label: "([^"]+)", interval: \{ unit: "(\w+)", min: (\d+), max: (\d+) \}, '
                           r'wording: "([^"]+)", page: (\d+) \}', web)
        server = [(i.id, i.label, i.unit, str(i.min), str(i.max), i.wording, str(i.page)) for i in care.CARE_ITEMS]
        self.assertEqual(found, server)


class UrgentTextTests(unittest.TestCase):
    def test_the_urgent_check_reads_the_guardians_own_words_only(self):
        consultation = (f"기침을 조금 해요\n\n{care.CARE_HEADING}\n- 광견병 추가접종: … — 기한이 지났음\n\n"
                        f"{SAVED_NOTES_HEADING}\n- 2026-10-01: 숨을 못 쉬어 응급실에 감")
        self.assertEqual(todays_text(consultation), "기침을 조금 해요")
        self.assertIsNone(detect_urgent_sign(todays_text(consultation)))


if __name__ == "__main__":
    unittest.main()
