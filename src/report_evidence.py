"""Safe report excerpts and 1-based PDF page rendering."""

import re
from functools import lru_cache
from pathlib import Path, PurePosixPath

import pymupdf

REPORT_SOURCE_DIR = "data/source"
DEFAULT_REPORT_SOURCE = f"{REPORT_SOURCE_DIR}/2025 한국 반려동물 보고서.pdf"


def _trusted_source(value: object) -> str:
    """Keep only repository-relative PDFs under data/source; never expose other paths."""
    if not isinstance(value, str):
        return DEFAULT_REPORT_SOURCE
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or path.suffix.lower() != ".pdf":
        return DEFAULT_REPORT_SOURCE
    if path.parent.as_posix() != REPORT_SOURCE_DIR:
        return DEFAULT_REPORT_SOURCE
    return path.as_posix()


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
        source = _trusted_source(doc.metadata.get("source"))
        title = doc.metadata.get("title") or PurePosixPath(source).stem
        # Some titles come from download file names: "반려동물+장묘서비스+..._작성자".
        title = title.replace("+", " ").split("_")[0].strip()
        row = {"page": page, "excerpt": doc.page_content.strip(), "source": source, "title": title}
        if doc.metadata.get("text_source") == "ocr":
            # Read from the page image (scripts/add_kb_ocr_chunks.py): the screens say so, since
            # OCR misreads some characters ("68 > KBB8*I").
            row["scanned"] = True
        result.append(row)
    return result


# "페이지 62", "62쪽", "p.62": the pages an answer cites (REPORT_ANALYSIS_PROMPT asks for the page).
_CITED_PAGE = re.compile(r"페이지\s*(\d{1,4})|(\d{1,4})\s*쪽|p\.\s*(\d{1,4})", re.IGNORECASE)


def cited_pages(answer: str) -> set[int]:
    return {int(next(group for group in match.groups() if group)) for match in _CITED_PAGE.finditer(answer or "")}


def evidence_for_display(rows: list[dict], answer: str) -> list[dict]:
    """The evidence rows as the screens show them; the model's context is not changed.

    - A PDF-text chunk with no digit at all is dropped when the same page has an OCR chunk: the KB
      text layer loses the figures ("매달평균 만 천원"), the page image keeps them (2026-10-25
      re-review: 11 cards for one question, 3 of them figure-less copies of a page already shown).
    - Pages the answer cites come first, marked "cited"; the screens fold the others.
    """
    scanned = {(row.get("source"), row.get("page")) for row in rows if row.get("scanned")}
    kept = [row for row in rows
            if row.get("scanned") or (row.get("source"), row.get("page")) not in scanned
            or re.search(r"\d", str(row.get("excerpt", "")))]
    cited = cited_pages(answer)
    if not any(row.get("page") in cited for row in kept):
        return kept
    first = [{**row, "cited": True} for row in kept if row.get("page") in cited]
    return first + [row for row in kept if row.get("page") not in cited]


def resolve_report_pdf(project_dir: Path, source: object) -> Path | None:
    """Map an evidence row's source to a PDF inside the project's report folder."""
    if source is not None and _trusted_source(source) != source:
        return None
    path = (project_dir / _trusted_source(source)).resolve()
    if not path.is_relative_to((project_dir / REPORT_SOURCE_DIR).resolve()):
        return None
    return path


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
