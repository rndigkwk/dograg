"""Measure process memory as the app's heavy resources load, plus reranker options.

Streamlit Community Cloud allows at most 2.7 GB of RAM per app, so every new
model or index should be checked against that budget. This loads the same
cached resources the app loads (via pages.rag) one stage at a time on a
disposable Chroma copy, then optionally a reranker on top of the full stack.

    uv run python scripts/measure_memory.py
    uv run python scripts/measure_memory.py --reranker qwen3      # + Qwen3-Reranker-0.6B
    uv run python scripts/measure_memory.py --reranker bge-dense  # rescore with the loaded bge-m3

Torch is limited to 2 threads to approximate Community Cloud's 2-core ceiling.
No LLM is called.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

CLOUD_LIMIT_MB = 2700
QUERIES = ["강아지가 계속 구토하고 설사를 해요", "고양이 눈곱이 많이 껴요", "슬개골 탈구 수술 후 관리"]


def rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / 2**20


def peak_mb() -> float | None:
    import psutil

    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", None)  # Windows only
    return peak / 2**20 if peak else None


def run(copy_path: Path, reranker: str | None) -> dict:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    stages: list[dict] = []

    def mark(name: str, started: float) -> None:
        gc.collect()
        stages.append({"stage": name, "rss_mb": round(rss_mb()), "seconds": round(time.perf_counter() - started, 1)})
        print(json.dumps(stages[-1], ensure_ascii=False), flush=True)

    started = time.perf_counter()
    mark("python", started)

    started = time.perf_counter()
    from pages import rag
    from src.hybrid_retrieval import retrieve_hybrid

    mark(f"imports (streamlit, langchain; torch loaded={'torch' in sys.modules})", started)

    rag.CHROMA_DIR = copy_path
    started = time.perf_counter()
    health_db = rag.load_vector_db()
    health_db.similarity_search(QUERIES[0], k=3)
    mark(f"+ health Chroma + {type(health_db.embeddings).__name__}", started)

    started = time.perf_counter()
    bm25 = rag.load_health_bm25_index()
    mark("+ BM25 index (Kiwi, 19,206 docs)", started)

    started = time.perf_counter()
    report_db = rag.load_report_vector_db()
    report_db.similarity_search(QUERIES[0], k=6)
    mark(f"+ report Chroma + {type(report_db.embeddings).__name__}", started)

    candidates = {q: retrieve_hybrid(health_db, bm25, q, top_k=24) for q in QUERIES}

    rerank_ms: list[float] = []
    if reranker == "qwen3":
        started = time.perf_counter()
        import torch
        from sentence_transformers import CrossEncoder

        torch.set_num_threads(2)

        model = CrossEncoder("Qwen/Qwen3-Reranker-0.6B", device="cpu")
        mark("+ Qwen3-Reranker-0.6B (CrossEncoder)", started)
        for query, docs in candidates.items():
            t = time.perf_counter()
            model.predict([(query, doc.page_content) for doc in docs], batch_size=8)
            rerank_ms.append((time.perf_counter() - t) * 1000)
        mark("after reranking 3 queries x 24 candidates", time.perf_counter())
    elif reranker == "bge-dense":
        embeddings = report_db.embeddings  # the bge-m3 model the app already holds
        for query, docs in candidates.items():
            t = time.perf_counter()
            query_vector = embeddings.embed_query(query)
            doc_vectors = embeddings.embed_documents([doc.page_content for doc in docs])
            sorted(range(len(docs)), key=lambda i: -sum(a * b for a, b in zip(query_vector, doc_vectors[i])))
            rerank_ms.append((time.perf_counter() - t) * 1000)
        mark("after bge-m3 dense rescoring 3 queries x 24 candidates", time.perf_counter())

    return {
        "cloud_limit_mb": CLOUD_LIMIT_MB,
        "reranker": reranker,
        "stages": stages,
        "final_rss_mb": round(rss_mb()),
        "peak_mb": round(peak_mb()) if peak_mb() else None,
        "rerank_ms_per_query": [round(ms) for ms in rerank_ms],
        "torch_threads": 2,
        "platform": sys.platform,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reranker", choices=["qwen3", "bge-dense"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or PROJECT_DIR / "output" / f"memory_{args.reranker or 'baseline'}.json"
    # Chroma keeps its files open on Windows, so the copy may outlive this process.
    with tempfile.TemporaryDirectory(prefix="dograg-mem-", ignore_cleanup_errors=True) as directory:
        copy_path = Path(directory) / "chroma_db"
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", copy_path)
        result = run(copy_path, args.reranker)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: result[k] for k in ("final_rss_mb", "peak_mb", "rerank_ms_per_query")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
