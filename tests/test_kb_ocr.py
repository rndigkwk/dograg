"""scripts/add_kb_ocr_chunks.py: the OCR clean-up keeps figures and fixes only the two known misreads."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from add_kb_ocr_chunks import clean_ocr  # noqa: E402


class CleanOcrTests(unittest.TestCase):
    def test_year_and_percent_point_misreads(self):
        self.assertEqual(clean_ocr("202314 가입률과 비교해 20234 대비"), "2023년 가입률과 비교해 2023년 대비")
        self.assertEqual(clean_ocr("증가했고(7.8%0), 1%0도"), "증가했고(7.8%p), 1%p도")

    def test_figures_stay(self):
        text = "12.8%로 2024년 말 591만 가구, 2023 1월, 14.6%, 2014년, 26.7%"
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
