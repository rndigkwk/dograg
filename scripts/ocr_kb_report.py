"""OCR the KB report pages whose numbers the PDF text lost (2026-10-17, docs/wiki/retrieval-experiments.md).

    uv run --with pymupdf python scripts/ocr_kb_report.py [--pages 77 82] [--tesseract PATH]

"2025 한국 반려동물 보고서" (KB) sets most figures in its own font (KBFG), whose digits have no Unicode
mapping: pypdf and PyMuPDF both drop them ("2023년 11.9%와 비교해" -> "년와비교해"). 33 of its 127
report chunks show the gap, and a question about the pet-insurance rate got "did not rise" back
(r04). Tesseract (kor+eng, 300 dpi) reads the figures again.

For every page this writes the OCR text and the digits found by each method to
data/source/kb_report_ocr.json; a page "needs OCR" when OCR finds at least MIN_EXTRA_DIGITS more
digits than the PDF text. scripts/add_kb_ocr_chunks.py turns those pages into extra report chunks.
No model calls.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
PDF = PROJECT_DIR / "data" / "source" / "2025 한국 반려동물 보고서.pdf"
OUT = PROJECT_DIR / "data" / "source" / "kb_report_ocr.json"
TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
MIN_EXTRA_DIGITS = 10


def digits(text: str) -> int:
    return sum(ch.isdigit() for ch in text)


def ocr(page, tesseract: str, folder: Path) -> str:
    image = folder / f"p{page.number + 1}.png"
    page.get_pixmap(dpi=300).save(image)
    out = subprocess.run([tesseract, str(image), "stdout", "-l", "kor+eng", "--psm", "3"],
                         capture_output=True, text=True, encoding="utf-8", check=True)
    return " ".join(out.stdout.split())


def main(argv: list[str] | None = None) -> int:
    import pymupdf

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pages", type=int, nargs="*", help="1-based pages (default: all)")
    parser.add_argument("--tesseract", default=TESSERACT)
    args = parser.parse_args(argv)
    result = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"pages": {}}
    with pymupdf.open(PDF) as doc, tempfile.TemporaryDirectory() as folder:
        for number in args.pages or range(1, doc.page_count + 1):
            page = doc[number - 1]
            pdf_text = " ".join(page.get_text().split())
            text = ocr(page, args.tesseract, Path(folder))
            result["pages"][str(number)] = {"pdf_digits": digits(pdf_text), "ocr_digits": digits(text),
                                            "needs_ocr": digits(text) - digits(pdf_text) >= MIN_EXTRA_DIGITS, "ocr": text}
            print(number, digits(pdf_text), "->", digits(text), flush=True)
    result.update(source=PDF.name, method="Tesseract kor+eng, 300 dpi, psm 3", min_extra_digits=MIN_EXTRA_DIGITS)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    needs = sorted(int(p) for p, v in result["pages"].items() if v["needs_ocr"])
    print(f"{len(needs)} of {len(result['pages'])} pages need OCR: {needs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
