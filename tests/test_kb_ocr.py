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


if __name__ == "__main__":
    unittest.main()
