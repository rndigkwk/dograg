"""Offline Dense vs BM25 vs Dense+BM25 RRF retrieval benchmark.

This benchmark uses the health-Q&A validation set and a disposable Chroma copy.
It does not call an LLM and does not modify the production vector database.
The project's runtime needs `rank_bm25` and `kiwipiepy` available to run it.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

METADATA_FIELDS = ("meta.lifeCycle", "meta.department", "meta.disease")
SEARCH_K = 12
FUSION_C = 60


def rank_of_match(row: Any, documents: list[Any]) -> int | None:
    for rank, document in enumerate(documents, start=1):
        if all(str(document.metadata.get(field)) == str(row[field]) for field in METADATA_FIELDS):
            return rank
    return None


def reciprocal_rank_fusion(
    result_lists: list[list[Any]], top_k: int, c: int = FUSION_C
) -> list[Any]:
    """Apply the course's equal-weight reciprocal-rank fusion, preserving first docs."""
    scores: dict[str, float] = defaultdict(float)
    documents_by_id: dict[str, Any] = {}
    for result_list in result_lists:
        for rank, document in enumerate(result_list, start=1):
            source_id = str(getattr(document, "id", None) or document.metadata.get("source_id"))
            if source_id in {"None", ""}:
                raise ValueError("RRF documents need a stable id or metadata.source_id")
            documents_by_id.setdefault(source_id, document)
            scores[source_id] += 0.5 / (c + rank)
    ordered_ids = sorted(scores, key=scores.__getitem__, reverse=True)
    return [documents_by_id[source_id] for source_id in ordered_ids[:top_k]]


def summarize_latencies(samples: list[float]) -> dict[str, float | int | None]:
    if not samples:
        return {"count": 0, "mean_ms": None, "median_ms": None, "p95_ms": None}
    values = sorted(sample * 1000 for sample in samples)
    p95_position = (len(values) - 1) * 0.95
    lower = math.floor(p95_position)
    upper = math.ceil(p95_position)
    p95 = values[lower] if lower == upper else values[lower] + (values[upper] - values[lower]) * (p95_position - lower)
    return {
        "count": len(values),
        "mean_ms": statistics.fmean(values),
        "median_ms": statistics.median(values),
        "p95_ms": p95,
    }


def _make_tokenizer():
    try:
        from kiwipiepy import Kiwi
    except ImportError as exc:
        raise RuntimeError("kiwipiepy is required; install it in the evaluation Python environment") from exc

    kiwi = Kiwi()

    def tokenize(text: str) -> list[str]:
        normalized = text.replace("･", "·")
        return [
            token.form.lower()
            for token in kiwi.tokenize(normalized)
            if token.tag.startswith("N") or token.tag in {"SL", "SN"}
        ]

    return tokenize


def evaluate(copy_path: Path, output_path: Path) -> dict[str, Any]:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        import pandas as pd
        from langchain_core.documents import Document
        from rank_bm25 import BM25Okapi
    except ImportError as exc:
        raise RuntimeError("pandas, rank_bm25, and LangChain core are required") from exc

    from src import resources
    from src.health_retrieval import summarize_retrieval

    validation = pd.read_csv(PROJECT_DIR / "data" / "df_val.csv").fillna("")
    required = ["qa.input", *METADATA_FIELDS]
    if any(field not in validation.columns for field in required):
        raise ValueError("Validation CSV is missing retrieval fields")

    original_chroma_dir = resources.CHROMA_DIR
    result_records = {"dense": [], "bm25": [], "hybrid": []}
    dense_latencies: list[float] = []
    bm25_latencies: list[float] = []
    hybrid_latencies: list[float] = []
    try:
        resources.load_vector_db.clear()
        resources.CHROMA_DIR = copy_path
        dense_db = resources.load_vector_db()
        stored = dense_db.get(include=["documents", "metadatas"])
        stored_ids = stored.get("ids") or []
        stored_texts = stored.get("documents") or []
        stored_metadata = stored.get("metadatas") or []
        if not stored_ids or len(stored_ids) != len(stored_texts) or len(stored_ids) != len(stored_metadata):
            raise ValueError("Chroma corpus is missing aligned IDs, documents, or metadata")
        corpus_documents = [
            Document(id=source_id, page_content=text, metadata=metadata or {})
            for source_id, text, metadata in zip(stored_ids, stored_texts, stored_metadata)
            if text
        ]
        tokenize = _make_tokenizer()
        print(f"tokenizing_corpus={len(corpus_documents)}", flush=True)
        tokenized_corpus = [tokenize(document.page_content) for document in corpus_documents]
        bm25 = BM25Okapi(tokenized_corpus)

        for index, row in validation.iterrows():
            question = str(row["qa.input"])
            started = time.perf_counter()
            dense_documents = dense_db.similarity_search(question, k=SEARCH_K)
            dense_elapsed = time.perf_counter() - started
            dense_latencies.append(dense_elapsed)

            started = time.perf_counter()
            query_tokens = tokenize(question)
            scores = bm25.get_scores(query_tokens)
            top_indices = heapq.nlargest(
                SEARCH_K,
                range(len(scores)),
                key=lambda candidate: (scores[candidate], -candidate),
            )
            bm25_documents = [corpus_documents[candidate] for candidate in top_indices]
            bm25_elapsed = time.perf_counter() - started
            bm25_latencies.append(bm25_elapsed)

            started = time.perf_counter()
            hybrid_documents = reciprocal_rank_fusion(
                [bm25_documents, dense_documents], top_k=SEARCH_K
            )
            hybrid_latencies.append(time.perf_counter() - started + dense_elapsed + bm25_elapsed)

            group = "기타" if str(row["meta.disease"]).strip() == "기타" else "non_other"
            for name, documents in (
                ("dense", dense_documents),
                ("bm25", bm25_documents),
                ("hybrid", hybrid_documents),
            ):
                result_records[name].append({
                    "group": group,
                    "hit_rank": rank_of_match(row, documents[:3]),
                })
            if (len(dense_latencies)) % 100 == 0:
                print(f"evaluated={len(dense_latencies)}/{len(validation)}", flush=True)
    finally:
        resources.CHROMA_DIR = original_chroma_dir
        resources.load_vector_db.clear()

    metrics = {name: summarize_retrieval(records) for name, records in result_records.items()}
    result = {
        "mode": "offline retrieval only; no generated answer or LLM query transforms",
        "dataset": {
            "health_corpus_documents": len(corpus_documents),
            "validation_questions": len(validation),
            "k_per_retriever": SEARCH_K,
            "reported_rank_cutoff": 3,
            "tokenizer": "Kiwi nouns, foreign tokens, and numbers; same policy as Day 47",
            "fusion": "equal-weight weighted RRF; c=60; Dense and BM25; same metadata gold rule as existing eval",
            "gold_rule": "all of meta.lifeCycle, meta.department, meta.disease match exactly; not clinical accuracy",
        },
        "retrieval_quality": metrics,
        "latency": {
            "dense_search": summarize_latencies(dense_latencies),
            "bm25_search": summarize_latencies(bm25_latencies),
            "hybrid_end_to_end_dense_plus_bm25_plus_fusion": summarize_latencies(hybrid_latencies),
        },
        "activation_candidate": (
            metrics["hybrid"]["overall"]["hit@3"] > metrics["dense"]["overall"]["hit@3"]
            and metrics["hybrid"]["non_other"]["hit@3"] >= metrics["dense"]["non_other"]["hit@3"]
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-copy", type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--output", type=Path, default=PROJECT_DIR / "output" / "hybrid_retrieval_benchmark.json"
    )
    args = parser.parse_args()
    if args.worker_copy:
        evaluate(args.worker_copy, args.output)
        return 0

    source = PROJECT_DIR / "data" / "chroma_db"
    with tempfile.TemporaryDirectory(prefix="dograg-hybrid-eval-") as directory:
        copy_path = Path(directory) / "chroma_db"
        shutil.copytree(source, copy_path)
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker-copy",
            str(copy_path),
            "--output",
            str(args.output),
        ]
        env = os.environ.copy()
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        return subprocess.run(command, cwd=PROJECT_DIR, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
