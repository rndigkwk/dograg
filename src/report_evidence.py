"""Safe report excerpts and 1-based PDF page rendering."""

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
        result.append({"page": page, "excerpt": doc.page_content.strip(), "source": source, "title": title})
    return result


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
