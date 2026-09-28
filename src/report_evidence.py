"""Safe report excerpts and 1-based PDF page rendering."""

from functools import lru_cache
from pathlib import Path

import pymupdf


def report_evidence_from_docs(docs: list) -> list[dict]:
    result = []
    for doc in docs:
        raw_page = doc.metadata.get("page")
        try:
            page = int(raw_page)
            if page < 1:
                page = None
        except (ValueError, TypeError):
            page = None
        result.append({"page": page, "excerpt": doc.page_content.strip(), "source": "2025 한국 반려동물 보고서.pdf"})
    return result


@lru_cache(maxsize=64)
def render_pdf_page(pdf_path: Path, page: int) -> bytes | None:
    if not isinstance(page, int) or page < 1:
        return None
    try:
        with pymupdf.open(pdf_path) as pdf:
            if page > len(pdf):
                return None
            return pdf[page - 1].get_pixmap(matrix=pymupdf.Matrix(1.25, 1.25)).tobytes("png")
    except (OSError, ValueError, RuntimeError):
        return None
