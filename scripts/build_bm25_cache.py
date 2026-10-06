"""Pre-tokenize the health Q&A corpus for BM25 and write data/bm25_health_tokens.json.gz.

Tokenizing 19,206 documents with Kiwi takes about two minutes; the app loads this
cache instead (about 0.2 s). Rerun after changing the health collection or the
tokenizer (and bump HEALTH_TOKENIZER_VERSION in src/resources.py for the latter).

    uv run python scripts/build_bm25_cache.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))


def main() -> int:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from src import resources
    from src.hybrid_retrieval import write_token_cache

    with tempfile.TemporaryDirectory(prefix="dograg-bm25-", ignore_cleanup_errors=True) as directory:
        resources.CHROMA_DIR = Path(directory) / "chroma_db"
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", resources.CHROMA_DIR)
        stored = resources.load_vector_db().get(include=["documents"])
        pairs = [(source_id, text) for source_id, text in zip(stored["ids"], stored["documents"]) if text]
        tokenize = resources.make_health_tokenizer()
        started = time.perf_counter()
        tokens = [tokenize(text) for _, text in pairs]
        write_token_cache(
            resources.BM25_TOKEN_CACHE,
            [source_id for source_id, _ in pairs],
            tokens,
            [text for _, text in pairs],
            resources.HEALTH_TOKENIZER_VERSION,
        )
    size_mb = resources.BM25_TOKEN_CACHE.stat().st_size / 2**20
    print(f"documents={len(pairs)} tokenize_s={time.perf_counter() - started:.1f} "
          f"cache={resources.BM25_TOKEN_CACHE.relative_to(PROJECT_DIR)} size_mb={size_mb:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
