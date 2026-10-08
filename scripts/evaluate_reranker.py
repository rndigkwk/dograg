"""Rerank the hybrid search's candidates with ONNX cross-encoders, scored on the relevance set.

    uv run python scripts/evaluate_reranker.py                  # every model below
    uv run python scripts/evaluate_reranker.py --models mminilm

Uses tests/data/health_relevance_100.json (scripts/relevance_set.py): every candidate there
is already graded, so reordering the same pool needs no new judgments. Reports the
relevance metrics for the top 3, the time to rerank one question's candidates on 2 threads,
and the process memory after loading each model.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

MODELS = {
    # name: (repo, onnx file, license)
    "mminilm": ("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1", "onnx/model_qint8_avx512_vnni.onnx", "apache-2.0"),
    "jina-v2": ("jinaai/jina-reranker-v2-base-multilingual", "onnx/model_int8.onnx", "cc-by-nc-4.0"),
    "bge-base": ("BAAI/bge-reranker-base", "onnx/model.onnx", "mit"),
}
OUT = PROJECT_DIR / "output" / "reranker_eval.json"


def rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / 2**20


def candidate_texts(items: list[dict]) -> dict[str, str]:
    """Question + answer of every graded candidate, the same text the judge saw."""
    from relevance_set import candidate_text

    from src import resources
    from src.health_answers import attach_health_answers

    ids = sorted({doc_id for item in items for doc_id in item["grades"]})
    with tempfile.TemporaryDirectory(prefix="ragdog-rerank-", ignore_cleanup_errors=True) as directory:
        resources.CHROMA_DIR = Path(directory) / "chroma_db"
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", resources.CHROMA_DIR)
        db = resources.load_vector_db()
        stored = db.get(ids=ids, include=["documents", "metadatas"])
        from langchain_core.documents import Document

        docs = [Document(id=i, page_content=t, metadata=m or {})
                for i, t, m in zip(stored["ids"], stored["documents"], stored["metadatas"])]
        attach_health_answers(docs, resources.load_health_answer_table())
    return {str(doc.id): candidate_text(doc) for doc in docs}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="*", default=list(MODELS))
    parser.add_argument("--limit", type=int, help="first N questions only (slow models: a trend and a timing, not a verdict)")
    parser.add_argument("--candidates", type=int, nargs="*", default=[12, 24],
                        help="rerank the first N fused candidates (12: what CRAG reviews today is 5)")
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "0")
    import pandas as pd
    from onnx_reranker import OnnxCrossEncoder
    from relevance_set import load_items, metrics

    items = load_items()[: args.limit] if args.limit else load_items()
    questions = pd.read_csv(PROJECT_DIR / "data" / "df_val.csv").fillna("")["qa.input"]
    texts = candidate_texts(items)
    results = {"hybrid": metrics(items, lambda item: item["rankings"]["hybrid"])}
    print("hybrid", results["hybrid"], flush=True)
    for name in args.models:
        repo, onnx_file, license_ = MODELS[name]
        gc.collect()
        before = rss_mb()
        model = OnnxCrossEncoder.from_hub(repo, onnx_file)
        loaded = rss_mb() - before
        for n in args.candidates:
            rankings, seconds = {}, []
            for item in items:
                pool = item["rankings"]["hybrid"][:n]
                started = time.perf_counter()
                scores = model.score(str(questions[item["row"]]), [texts[doc_id] for doc_id in pool])
                seconds.append(time.perf_counter() - started)
                rankings[item["row"]] = [doc_id for _, doc_id in sorted(zip(scores, pool), key=lambda pair: -pair[0])]
            key = f"{name}@{n}"
            results[key] = {
                **metrics(items, lambda item, rankings=rankings: rankings[item["row"]]),
                "rerank_seconds_p50": round(statistics.median(seconds), 2),
                "rerank_seconds_p90": round(sorted(seconds)[int(0.9 * (len(seconds) - 1))], 2),
                "model_rss_mb": round(loaded), "license": license_,
            }
            print(key, results[key], flush=True)
        del model
    OUT.parent.mkdir(exist_ok=True)
    out = OUT.with_name(f"{OUT.stem}_{'_'.join(args.models)}_{len(items)}.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
