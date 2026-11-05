"""Add OCR chunks for the KB report pages whose figures the PDF text lost (2026-10-17).

    uv run python scripts/add_kb_ocr_chunks.py --dry-run          # pages, chunks, embedding tokens
    uv run python scripts/add_kb_ocr_chunks.py --local            # data/chroma_db + data/vector_store
    uv run python scripts/add_kb_ocr_chunks.py --supabase         # ragdog_report (admin SUPABASE_DB_URL)
    uv run python scripts/add_kb_ocr_chunks.py --local --replace  # drop the stored OCR chunks first (clean_ocr changed)

Reads data/source/kb_report_ocr.json (scripts/ocr_kb_report.py) and, for each page marked
needs_ocr, splits the OCR text like the original ingestion (1,000 characters, 200 overlap) into
extra chunks next to the page's PDF chunks, which stay as they are (their wording is exact where the
OCR misreads). The metadata is the page's own plus text_source "ocr", so the evidence shows the same
report and page. One embedding call per chunk batch (text-embedding-3-small, as the stored vectors);
no chat model calls. Chunks already present (same id) are skipped, so each target can be filled once.
With --replace the target's OCR chunks (text_source "ocr") are deleted first and written again: a
clean_ocr change shifts the chunk boundaries, so the ids no longer match the old pieces.
--supabase stops unless the checkout is the fetched origin/main with no local changes in scripts/
and src/ (src/git_guard.py): an older main once replaced newer production rows (2026-11-05).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

OCR_FILE = PROJECT_DIR / "data" / "source" / "kb_report_ocr.json"
STORE = PROJECT_DIR / "data" / "vector_store" / "report"
KB_SOURCE = "data/source/2025 한국 반려동물 보고서.pdf"


def page_metadata() -> dict[int, dict]:
    """The first PDF chunk's metadata of each KB page (from the exact store, the same rows as Supabase)."""
    pages: dict[int, dict] = {}
    for meta, _ in pdf_chunks():
        pages.setdefault(meta["page"], meta)
    return pages


def pdf_chunks():
    """(metadata, text) of each KB PDF-text chunk in the exact store."""
    with (STORE / "documents.jsonl").open(encoding="utf-8") as file:
        for line in file:
            row = json.loads(line)
            meta = row["metadata"]
            if meta.get("source") == KB_SOURCE and meta.get("text_source") != "ocr":
                yield meta, row.get("text") or row.get("page_content") or ""


def ocr_pages(data: dict) -> list[int]:
    """Pages that get OCR chunks: the OCR read at least MIN_EXTRA_DIGITS more digits than the PDF text
    (needs_ocr, scripts/ocr_kb_report.py), or the PDF text shows a lost figure ("평균 만 천원").
    The second rule (2026-10-26) adds p.70 and p.82: they lost a few amounts ("보유자금은 평균 만
    천원") but kept enough other digits to stay under the digit gap."""
    from src.report_evidence import DROPPED_FIGURE

    lost = {meta["page"] for meta, text in pdf_chunks() if DROPPED_FIGURE.search(text)}
    return sorted(int(p) for p, v in data["pages"].items() if v["needs_ocr"] or int(p) in lost)


# Tesseract's common misreads in this report (counted in its 91 OCR pages, 2026-10-17/18):
# - the 년 after a year read as "14", "44" or "4": "202314 가입률", "202344 말 기준" (7) for "2023년 …"
# - %p read as "%0" or "%00": "(7.8%0)", "(2.2%00)" (2)
# - the decimal point dropped from a share: "(124%)" for 12.4%, "(826%)" for 82.6% (12). A share
#   of 101-999% is impossible here, so the point goes back before the last digit; 100% stays. One
#   checked against the page image had another digit misread too ("592%" for 39.2%): the point is
#   right, the digit stays wrong.
# Other misreads stay ("2025년 11.9%" for 2023년, "589만" for 585만); the page's PDF chunks keep the
# exact wording next to these.
YEAR_NYEON = re.compile(r"\b(20[0-3]\d)(?:44|14|4)(?=[\s,.)(]|$)")
PERCENT_POINT = re.compile(r"(\d)%00?(?!\d)")
DROPPED_POINT = re.compile(r"(?<![\d.,])(?!100%)([1-9]\d)(\d)%")


# Figures the OCR misread digit by digit, which no rule can tell: checked one by one against the page
# images of the pages a holdout answer quoted them from (2026-10-18; h08 answered "59.2%" from p.7,
# which p.28 repeats).
# The rest (2026-11-05) are the figures Qwen3-VL-8B read differently from Tesseract, each checked against
# the PDF's own text or a crop of the page image; Tesseract mostly read 3 as 5. Left out: pairings where
# one Tesseract figure met several 8B figures, and figures that occur twice on the page
# (docs/wiki/kb-ocr-gpu.md). Those were settled on 2026-11-06 from the sentence around each figure and the
# page image (15 more; p.6 "7만" stays: the 8B figure there belongs to another sentence).
# Matched with any whitespace between the words, each exactly once on its page.
OCR_CORRECTIONS: dict[int, list[tuple[str, str]]] = {
    4: [("51.6%", "31.6%")],
    5: [("59.8%", "39.8%")],
    6: [("259만", "239만"), ("67.6%", "57.6%")],
    7: [("59.2%", "39.2%")],
    12: [("155만", "135만")],
    13: [("501만", "301만")],
    14: [("2025년 말 대비", "2023년 말 대비"), ("589만", "585만"), ("1 fu 196만", "1,196만"), ("0.5%", "0.3%")],
    16: [("55.6%", "35.6%"), ("56.1%", "36.1%"), ("56.5%", "36.5%"), ("59.1%", "39.1%")],
    17: [("27.5%", "27.3%"), ("50.2%", "30.2%"), ("57.9%", "37.9%"), ("45.6%", "43.6%"), ("65.9%", "63.9%")],
    20: [("51.5%", "31.5%")],
    21: [("53.2%", "33.2%")],
    23: [("9.5%p", "9.3%p")],
    24: [("65.7%", "63.7%")],
    25: [("59.8%", "39.8%"), ("65.2%", "63.2%"), ("66.5%", "66.3%")],
    26: [("35.4%", "33.4%")],
    28: [("59.2%", "39.2%"), ("45.9%", "43.9%")],
    29: [("52.5%", "32.5%"), ("54.6%", "34.6%")],
    35: [("50.4%", "30.4%"), ("58.5%", "38.5%"), ("59.5%", "39.5%"), ("59.7%", "39.7%")],
    36: [("51.5%", "31.5%")],
    38: [("14.5%", "14.3%"), ("58.5%", "58.3%"), ("75.2%", "73.2%"), ("53.4%", "33.4%")],
    39: [("25.4%", "23.4%")],
    40: [("59.5%", "59.3%")],
    43: [("54.8%", "34.8%"), ("54.9%", "34.9%"), ("45.1%", "43.1%"), ("55.1%", "35.1%")],
    47: [("15.5%", "15.3%"), ("51.6%", "31.6%"), ("50.5%", "50.3%")],
    48: [("67.5%", "67.3%")],
    52: [("58.8%", "38.8%"), ("87.5%", "87.3%")],
    54: [("75.4%", "73.4%")],
    55: [("53.9%", "33.9%"), ("54.1%", "34.1%")],
    60: [("16.5%", "16.3%"), ("25만", "23만")],
    61: [("52.9%", "32.9%"), ("55.9%", "35.9%"), ("56.2%", "36.2%"), ("56.4%", "36.4%")],
    62: [("25.6%", "23.6%")],
    63: [("20.5%", "20.3%"), ("21.5%", "21.3%"), ("55.1%", "35.1%"), ("56.8%", "36.8%"), ("2.4%p", "0.4%p"), ("5.0%", "3.0%"), ("5.5%", "5.3%"), ("2.5% 0", "2.3%p")],
    65: [("105만", "103만"), ("51.1%", "31.1%"), ("59.6%", "39.6%"), ("45만", "43만")],
    66: [("56.5%", "36.5%"), ("57.5%", "37.5%"), ("65.3%", "63.3%"), ("57.8%", "37.8%"), ("55.8%", "53.8%")],
    67: [("50.9%", "30.9%"), ("51.4%", "31.4%")],
    70: [("145만", "143만"), ("58만", "38만")],
    72: [("65.7%", "63.7%")],
    73: [("251만", "231만"), ("75.3%", "73.3%")],
    74: [("51.9%", "31.9%"), ("54.4%", "34.4%"), ("56.2%", "36.2%")],
    75: [("16.5%", "16.3%"), ("56.7%", "36.7%")],
    76: [("25.5%", "25.3%"), ("8.5%", "8.3%")],
    77: [("2025년 11.9%", "2023년 11.9%"), ("15.79%", "15.7%")],
    78: [("55.8%", "35.8%"), ("57.4%", "37.4%"), ("45.1%", "43.1%")],
    79: [("15.5%", "13.5%"), ("52.4%", "32.4%"), ("55.6%", "35.6%")],
    82: [("259만", "239만"), ("56.2%", "36.2%"), ("73.5%", "73.3%"), ("보장범위'(55.8%)", "보장범위'(35.8%)"), ("보장 범위'(55.8%)", "보장 범위'(35.8%)")],
    86: [("85.2%", "83.2%"), ("85.5%", "85.3%")],
    88: [("16.5%", "16.3%")],
    94: [("45.8%", "43.8%"), ("51.5%", "51.3%")],
    95: [("11.5%", "11.3%"), ("14.5%", "14.3%")],
    100: [("58.8%", "38.8%")],
}


def correct_ocr(page: int, text: str) -> str:
    for wrong, right in OCR_CORRECTIONS.get(page, []):
        text, count = re.subn(r"\s+".join(map(re.escape, wrong.split())), right, text)
        if count != 1:
            raise ValueError(f"OCR correction {wrong!r} matched {count} times on page {page}")
    return text


def clean_ocr(text: str) -> str:
    text = YEAR_NYEON.sub(r"\1년", text)
    return DROPPED_POINT.sub(r"\1.\2%", PERCENT_POINT.sub(r"\1%p", text))


def ocr_chunks() -> list[dict]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200,
                                              separators=["\n\n", "\n", ". ", "다. ", "; ", " ", ""])
    data = json.loads(OCR_FILE.read_text(encoding="utf-8"))
    base = page_metadata()
    chunks = []
    for page in ocr_pages(data):
        text = correct_ocr(page, clean_ocr(data["pages"][str(page)]["ocr"]))
        for index, piece in enumerate(splitter.split_text(text)):
            meta = {**base[page], "text_source": "ocr", "ocr_method": data["method"], "chunk_index": index,
                    "text_sha256": hashlib.sha256(piece.encode("utf-8")).hexdigest()}
            chunks.append({"id": f"p_{meta['source_sha256'][:12]}_ocr_{page:04d}_{index:03d}", "text": piece, "metadata": meta})
    return chunks


def embed(texts: list[str]) -> np.ndarray:
    from src import resources

    model = resources.create_embedding_model()
    if model is None:
        raise SystemExit("OPENAI_API_KEY is needed for the embeddings.")
    return np.asarray(model.embed_documents(texts), dtype=np.float32)


def drop_local_ocr() -> None:
    """Remove the OCR chunks from the exact store and the source Chroma database."""
    from src import resources

    rows = [json.loads(line) for line in (STORE / "documents.jsonl").open(encoding="utf-8")]
    keep = [i for i, row in enumerate(rows) if row["metadata"].get("text_source") != "ocr"]
    np.save(STORE / "vectors.npy", np.load(STORE / "vectors.npy")[keep])
    with (STORE / "documents.jsonl").open("w", encoding="utf-8") as file:
        for i in keep:
            file.write(json.dumps(rows[i], ensure_ascii=False) + "\n")
    import chromadb

    collection = chromadb.PersistentClient(path=str(resources.SOURCE_CHROMA_DIR)).get_collection(resources.REPORT_COLLECTION_NAME)
    old = collection.get(where={"text_source": "ocr"})["ids"]
    if old:
        collection.delete(ids=old)
    print(f"exact store: {len(rows) - len(keep)} OCR chunks removed; chroma: {len(old)} removed")


def add_local(chunks: list[dict], vectors: np.ndarray) -> None:
    from src import resources

    have = {json.loads(line)["id"] for line in (STORE / "documents.jsonl").open(encoding="utf-8")}
    new = [i for i, c in enumerate(chunks) if c["id"] not in have]
    if new:
        old = np.load(STORE / "vectors.npy")
        np.save(STORE / "vectors.npy", np.vstack([old, vectors[new].astype(old.dtype)]))
        with (STORE / "documents.jsonl").open("a", encoding="utf-8") as file:
            for i in new:
                file.write(json.dumps({"id": chunks[i]["id"], "text": chunks[i]["text"], "metadata": chunks[i]["metadata"]},
                                      ensure_ascii=False) + "\n")
    print(f"exact store: {len(new)} added, {len(chunks) - len(new)} already there")
    # The source database, not the local run's copy (resources.chroma_dir): the copy is refreshed
    # from it, and the evaluation scripts copy the source too.
    import chromadb

    collection = chromadb.PersistentClient(path=str(resources.SOURCE_CHROMA_DIR)).get_collection(resources.REPORT_COLLECTION_NAME)
    present = set(collection.get(ids=[c["id"] for c in chunks])["ids"])
    todo = [i for i, c in enumerate(chunks) if c["id"] not in present]
    if todo:
        collection.add(ids=[chunks[i]["id"] for i in todo], documents=[chunks[i]["text"] for i in todo],
                       metadatas=[chunks[i]["metadata"] for i in todo], embeddings=vectors[todo].tolist())
    print(f"chroma: {len(todo)} added, {len(chunks) - len(todo)} already there")


def add_supabase(chunks: list[dict], vectors: np.ndarray, replace: bool = False) -> None:
    from src import resources, settings
    from src.supabase_store import connector

    table = resources.SUPABASE_REPORT_TABLE
    with connector(settings.get_setting("SUPABASE_DB_URL"))() as conn:
        if replace:
            removed = conn.execute(f"delete from {table} where metadata->>'text_source' = 'ocr'").rowcount
            print(f"supabase {table}: {removed} OCR chunks removed")
        present = {row[0] for row in conn.execute(f"select id from {table} where id = any(%s)", [[c["id"] for c in chunks]]).fetchall()}
        todo = [i for i, c in enumerate(chunks) if c["id"] not in present]
        for i in todo:
            conn.execute(f"insert into {table} (id, body, metadata, embedding) values (%s, %s, %s, %s)",
                         [chunks[i]["id"], chunks[i]["text"], json.dumps(chunks[i]["metadata"], ensure_ascii=False),
                          "[" + ",".join(f"{x:.6f}" for x in vectors[i]) + "]"])
    print(f"supabase {table}: {len(todo)} added, {len(chunks) - len(todo)} already there")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--supabase", action="store_true")
    parser.add_argument("--replace", action="store_true", help="delete the target's OCR chunks first")
    parser.add_argument("--allow-unmerged", action="store_true",
                        help="write Supabase from a checkout that is not origin/main (src/git_guard.py)")
    args = parser.parse_args(argv)
    chunks = ocr_chunks()
    pages = sorted({c["metadata"]["page"] for c in chunks})
    print(f"{len(pages)} pages, {len(chunks)} OCR chunks, about {sum(len(c['text']) for c in chunks)} characters: {pages}")
    if args.dry_run or not (args.local or args.supabase):
        return 0
    if args.supabase and not args.allow_unmerged:
        from src.git_guard import unmerged_reason

        if reason := unmerged_reason(PROJECT_DIR):
            print(f"not writing Supabase: {reason} (or pass --allow-unmerged)")
            return 1
    vectors = embed([c["text"] for c in chunks])
    if args.local:
        if args.replace:
            drop_local_ocr()
        add_local(chunks, vectors)
    if args.supabase:
        add_supabase(chunks, vectors, replace=args.replace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
