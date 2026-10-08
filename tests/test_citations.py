"""team/core/citations.py: evidence ids become short numbers with a source list."""

import unittest

from team.core.citations import number_citations, readable_report

FINDINGS = {
    "t1": {"summary": "구토 사례 요약", "key_points": [
        {"fact": "사료는 10일에 걸쳐 바꾼다", "evidence_id": "qa-5250"},
        {"fact": "탈수 위험이 있다", "evidence_id": "qa-3029"},
    ]},
    "t2": {"summary": "강남구 병원", "key_points": [
        {"fact": "청담동물병원, 02-543-4037", "evidence_id": "hospital-3220000010199"},
    ]},
    "t3": {"summary": "진료비", "key_points": [
        {"fact": "진료비 게시 항목은 20종", "evidence_id": "report-반려동물+의료보험서비스-p68"},
    ]},
}


class NumberCitationTests(unittest.TestCase):
    def test_ids_become_numbers_in_order_of_first_use(self):
        report = "증상 [상담 내용]\n사례 [qa-5250] [qa-3029]\n다시 [qa-5250]\n병원 [hospital-3220000010199]"
        numbered, sources = number_citations(report, FINDINGS)
        self.assertEqual(numbered, "증상 ①\n사례 ②③\n다시 ②\n병원 ④")
        self.assertEqual([(mark, token) for mark, token, _ in sources],
                         [("①", "상담 내용"), ("②", "qa-5250"), ("③", "qa-3029"), ("④", "hospital-3220000010199")])

    def test_labels_say_what_each_source_is(self):
        _, sources = number_citations("비용 [report-반려동물+의료보험서비스-p68] 요약 [t1]", FINDINGS)
        labels = [label for _, _, label in sources]
        self.assertEqual(labels[0], "보고서 「반려동물 의료보험서비스」 68쪽: 진료비 게시 항목은 20종")
        self.assertEqual(labels[1], "조사 t1 요약: 구토 사례 요약")

    def test_links_and_unknown_brackets_stay_as_written(self):
        report = "[시설 찾기](https://example.com) [참고] [qa-9999] [qa-5250]"
        numbered, sources = number_citations(report, FINDINGS)
        # an unknown id in a run keeps the whole run untouched: no half-converted citation
        self.assertEqual(numbered, report)
        self.assertEqual(sources, [])

    def test_readable_report_adds_the_source_list(self):
        text = readable_report("증상 [상담 내용]", FINDINGS)
        self.assertTrue(text.startswith("증상 ①"))
        self.assertIn("#### 근거", text)
        self.assertIn("① 보호자 상담 내용", text)
        self.assertEqual(readable_report("근거 없음", FINDINGS), "근거 없음")

    def test_more_than_twenty_sources_fall_back_to_parentheses(self):
        findings = {"t1": {"summary": "", "key_points": [{"fact": str(i), "evidence_id": f"qa-{i}"} for i in range(22)]}}
        numbered, _ = number_citations(" ".join(f"[qa-{i}]" for i in range(22)), findings)
        self.assertTrue(numbered.endswith("⑳(21)(22)"))


if __name__ == "__main__":
    unittest.main()
