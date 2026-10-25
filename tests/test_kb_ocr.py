"""scripts/add_kb_ocr_chunks.py: the OCR clean-up keeps figures and fixes only the known misreads."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from add_kb_ocr_chunks import OCR_CORRECTIONS, clean_ocr, correct_ocr


class CleanOcrTests(unittest.TestCase):
    def test_year_and_percent_point_misreads(self):
        self.assertEqual(clean_ocr("202314 가입률과 비교해 20234 대비"), "2023년 가입률과 비교해 2023년 대비")
        self.assertEqual(clean_ocr("증가했고(7.8%0), 1%0도"), "증가했고(7.8%p), 1%p도")
        self.assertEqual(clean_ocr("202344 말 기준, 202444 미국에서"), "2023년 말 기준, 2024년 미국에서")
        self.assertEqual(clean_ocr("소폭(2.2%00) 감소, (+4.9%00),"), "소폭(2.2%p) 감소, (+4.9%p),")

    def test_a_dropped_decimal_point_goes_back(self):
        self.assertEqual(clean_ocr("'메모리얼스톤'(124%으로, 반려가구(826%) +313%p"),
                         "'메모리얼스톤'(12.4%으로, 반려가구(82.6%) +31.3%p")

    def test_checked_figures_are_corrected_once_per_page(self):
        self.assertEqual(correct_ocr(7, "만지기(59.2%;, 반려견"), "만지기(39.2%;, 반려견")
        self.assertEqual(correct_ocr(14, "2025년 말\n대비 589만 1 fu\n196만 0.5%"), "2023년 말 대비 585만 1,196만 0.3%")
        self.assertEqual(correct_ocr(5, "59.2%"), "59.2%")  # only the checked page
        with self.assertRaises(ValueError):  # a correction that no longer matches is caught
            correct_ocr(7, "39.2%")
        self.assertEqual(sorted(OCR_CORRECTIONS), [7, 14, 28, 77])

    def test_figures_stay(self):
        text = "12.8%로 2024년 말 591만 가구, 2023 1월, 14.6%, 2014년, 26.7%, 사료로 100%변경, 30190%, 1,234%"
        self.assertEqual(clean_ocr(text), text)


class ScannedEvidenceTests(unittest.TestCase):
    def test_ocr_chunks_are_marked_and_pdf_chunks_unchanged(self):
        from types import SimpleNamespace

        from src.report_evidence import report_evidence_from_docs

        meta = {"title": "2025 한국 반려동물 보고서", "page": 77, "source": "data/source/2025 한국 반려동물 보고서.pdf"}
        rows = report_evidence_from_docs([SimpleNamespace(page_content="12.8%", metadata={**meta, "text_source": "ocr"}),
                                          SimpleNamespace(page_content="년와비교해", metadata=meta)])
        self.assertTrue(rows[0]["scanned"])
        self.assertNotIn("scanned", rows[1])


class DisplayEvidenceTests(unittest.TestCase):
    """src/report_evidence.py evidence_for_display, with the cards of the 2026-10-25 re-review."""

    SOURCE = "data/source/2025 한국 반려동물 보고서.pdf"

    def row(self, page, excerpt, scanned=False):
        return {"page": page, "excerpt": excerpt, "source": self.SOURCE, "title": "2025 한국 반려동물 보고서",
                **({"scanned": True} if scanned else {})}

    def test_a_pdf_chunk_that_lost_a_figure_goes_when_its_page_has_an_ocr_chunk(self):
        from src.report_evidence import evidence_for_display

        rows = [self.row(62, "반려동물양육비로매달평균 만 천원 2025 15.6%"), self.row(62, "1마리당 16만 1천 원", scanned=True),
                self.row(74, "월평균저축액은평균 만 천원"), self.row(2, "평균 19만 4천 원"),
                self.row(102, "양육비는 배 병원비는 배더지출했다"), self.row(102, "양육비는 1.3배", scanned=True),
                self.row(61, "반려가구의 방문 경험"), self.row(61, "66.0%", scanned=True)]
        shown = evidence_for_display(rows, "")
        # p.62 and p.102 keep the OCR chunk only (other digits in the chunk do not save it); p.74 has
        # nothing else, so its text stays; p.61's text lost no figure, so it stays; nothing is cited
        self.assertEqual([(row["page"], row.get("scanned", False)) for row in shown],
                         [(62, True), (74, False), (2, False), (102, True), (61, False), (61, True)])
        self.assertFalse(any("cited" in row for row in shown))

    def test_cited_pages_come_first_and_are_marked(self):
        from src.report_evidence import cited_pages, evidence_for_display

        self.assertEqual(cited_pages("— 「보고서」, 페이지 62 · 63쪽, p.7"), {62, 63, 7})
        rows = [self.row(2, "19만 4천 원"), self.row(62, "17만 8천 원"), self.row(61, "66.0%")]
        shown = evidence_for_display(rows, "월평균 17만 8천 원입니다. (「2025 한국 반려동물 보고서」, 페이지 62)")
        self.assertEqual([(row["page"], row.get("cited", False)) for row in shown], [(62, True), (2, False), (61, False)])
        # a cited page that is not among the rows: the order stays
        self.assertEqual(evidence_for_display(rows, "페이지 9"), rows)


if __name__ == "__main__":
    unittest.main()
