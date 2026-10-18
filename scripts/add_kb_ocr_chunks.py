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
    with (STORE / "documents.jsonl").open(encoding="utf-8") as file:
        for line in file:
            row = json.loads(line)
            meta = row["metadata"]
            if meta.get("source") == KB_SOURCE and meta.get("page") not in pages and meta.get("text_source") != "ocr":
                pages[meta["page"]] = meta
    return pages


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
    for page in sorted(int(p) for p, v in data["pages"].items() if v["needs_ocr"]):
        text = clean_ocr(data["pages"][str(page)]["ocr"])
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
    args = parser.parse_args(argv)
    chunks = ocr_chunks()
    pages = sorted({c["metadata"]["page"] for c in chunks})
    print(f"{len(pages)} pages, {len(chunks)} OCR chunks, about {sum(len(c['text']) for c in chunks)} characters: {pages}")
    if args.dry_run or not (args.local or args.supabase):
        return 0
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
