"""Offline RRF-weight sweep and candidate-pool recall for health retrieval.

Answers two questions before any reranker work:
1. Does a different Dense/BM25 RRF weight beat the current 0.5/0.5?
2. How often is a gold document anywhere in the candidate pool a reranker would see?

Weights are chosen on a fixed random half of the validation set ("tune") and
reported on the other half ("holdout") to avoid picking noise. Retrieval runs on
a disposable Chroma copy; no LLM is called and production data is not modified.

    uv run python scripts/evaluate_fusion_weights.py
    uv run python scripts/evaluate_fusion_weights.py --reuse-candidates   # analysis only
"""

from __future__ import annotations

import argparse
import heapq
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from langchain_core.documents import Document

from scripts.evaluate_hybrid_search import METADATA_FIELDS, _make_tokenizer
from src.hybrid_retrieval import DEFAULT_CANDIDATE_K, reciprocal_rank_fusion

POOL_K_VALUES = (12, 20, 50)
MAX_POOL_K = max(POOL_K_VALUES)
BM25_WEIGHTS = tuple(round(step / 10, 1) for step in range(11))
BASELINE_BM25_WEIGHT = 0.5
SPLIT_SEED = 47
DEFAULT_CANDIDATES = PROJECT_DIR / "output" / "fusion_candidates.json"
DEFAULT_OUTPUT = PROJECT_DIR / "output" / "fusion_weight_sweep.json"


def fused_ids(dense_ids: list[str], bm25_ids: list[str], bm25_weight: float, top_k: int = 3) -> list[str]:
    """Rank IDs with the production RRF so ties break exactly as in the app."""
    dense = [Document(id=item, page_content="") for item in dense_ids]
    lexical = [Document(id=item, page_content="") for item in bm25_ids]
    fused = reciprocal_rank_fusion(
        [dense, lexical], top_k=top_k, weights=(1 - bm25_weight, bm25_weight)
    )
    return [document.id for document in fused]


def first_gold_rank(ranked_ids: list[str], gold_ids: set[str]) -> int | None:
    for rank, item in enumerate(ranked_ids, start=1):
        if item in gold_ids:
            return rank
    return None


def summarize_ranks(ranks: list[int | None], cutoff: int = 3) -> dict[str, float | int]:
    count = len(ranks)
    hits = [rank for rank in ranks if rank is not None and rank <= cutoff]
    return {
        "count": count,
        f"hit@{cutoff}": len(hits) / count if count else 0.0,
        f"mrr@{cutoff}": sum(1 / rank for rank in hits) / count if count else 0.0,
        "misses": count - len(hits),
    }


def split_indices(count: int, seed: int = SPLIT_SEED) -> tuple[list[int], list[int]]:
    order = list(range(count))
    random.Random(seed).shuffle(order)
    half = count // 2
    return sorted(order[:half]), sorted(order[half:])


def analyze(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute pool recall and the weight sweep from cached ranked candidate IDs."""
    def ranks_for(weight: float, indices: list[int]) -> list[int | None]:
        return [
            first_gold_rank(
                fused_ids(records[i]["dense_ids"], records[i]["bm25_ids"][:DEFAULT_CANDIDATE_K], weight),
                set(records[i]["gold_ids"]),
            )
            for i in indices
        ]

    everyone = list(range(len(records)))
    tune, holdout = split_indices(len(records))

    pool_recall = {}
    for k in POOL_K_VALUES:
        def in_pool(record, k=k):
            dense = record["dense_ids"] if k == DEFAULT_CANDIDATE_K else record["dense_pool_ids"][:k]
            pool = set(dense) | set(record["bm25_ids"][:k])
            return bool(pool & set(record["gold_ids"]))
        found = sum(in_pool(record) for record in records)
        pool_recall[f"dense{k}+bm25{k}"] = {
            "recall": found / len(records) if records else 0.0,
            "found": found,
            "count": len(records),
        }
    pool_recall["note"] = "dense12+bm2512 is the pool the app fuses today; larger pools need more candidates fetched"

    sweep = {
        f"{weight:.1f}": {
            "tune": summarize_ranks(ranks_for(weight, tune)),
            "holdout": summarize_ranks(ranks_for(weight, holdout)),
            "all": summarize_ranks(ranks_for(weight, everyone)),
        }
        for weight in BM25_WEIGHTS
    }
    chosen = max(
        BM25_WEIGHTS,
        key=lambda weight: (
            sweep[f"{weight:.1f}"]["tune"]["hit@3"],
            sweep[f"{weight:.1f}"]["tune"]["mrr@3"],
            -abs(weight - BASELINE_BM25_WEIGHT),
        ),
    )

    baseline_hits = [rank is not None and rank <= 3 for rank in ranks_for(BASELINE_BM25_WEIGHT, holdout)]
    chosen_hits = [rank is not None and rank <= 3 for rank in ranks_for(chosen, holdout)]
    paired = {
        "gained": sum(new and not old for old, new in zip(baseline_hits, chosen_hits)),
        "lost": sum(old and not new for old, new in zip(baseline_hits, chosen_hits)),
    }
    return {
        "candidate_pool_recall": pool_recall,
        "weight_sweep_bm25_weight": sweep,
        "selection": {
            "rule": "max tune hit@3, then tune mrr@3, then closest to 0.5",
            "split": {"seed": SPLIT_SEED, "tune": len(tune), "holdout": len(holdout)},
            "chosen_bm25_weight": chosen,
            "baseline_bm25_weight": BASELINE_BM25_WEIGHT,
            "holdout_chosen": sweep[f"{chosen:.1f}"]["holdout"],
            "holdout_baseline": sweep[f"{BASELINE_BM25_WEIGHT:.1f}"]["holdout"],
            "holdout_paired_vs_baseline": paired,
        },
    }


def collect_candidates(copy_path: Path, output_path: Path) -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import pandas as pd
    from rank_bm25 import BM25Okapi

    from pages import rag

    validation = pd.read_csv(PROJECT_DIR / "data" / "df_val.csv").fillna("")
    original_chroma_dir = rag.CHROMA_DIR
    records = []
    try:
        rag.load_vector_db.clear()
        rag.CHROMA_DIR = copy_path
        dense_db = rag.load_vector_db()
        stored = dense_db.get(include=["documents", "metadatas"])
        corpus = [
            (source_id, text, metadata or {})
            for source_id, text, metadata in zip(stored["ids"], stored["documents"], stored["metadatas"])
            if text
        ]
        tokenize = _make_tokenizer()
        print(f"tokenizing_corpus={len(corpus)}", flush=True)
        bm25 = BM25Okapi([tokenize(text) for _, text, _ in corpus])
        metadata_by_id = {source_id: metadata for source_id, _, metadata in corpus}

        def is_gold(row, source_id):
            metadata = metadata_by_id.get(source_id, {})
            return all(str(metadata.get(field)) == str(row[field]) for field in METADATA_FIELDS)

        for index, row in validation.iterrows():
            question = str(row["qa.input"])
            # The app fetches k=12 from Chroma; fetch that list exactly, plus a larger pool.
            dense_ids = [doc.id for doc in dense_db.similarity_search(question, k=DEFAULT_CANDIDATE_K)]
            dense_pool_ids = [doc.id for doc in dense_db.similarity_search(question, k=MAX_POOL_K)]
            scores = bm25.get_scores(tokenize(question))
            top = heapq.nlargest(MAX_POOL_K, range(len(scores)), key=lambda i: (scores[i], -i))
            bm25_ids = [corpus[i][0] for i in top]
            candidates = set(dense_ids) | set(dense_pool_ids) | set(bm25_ids)
            records.append({
                "row": int(index),
                "dense_ids": dense_ids,
                "dense_pool_ids": dense_pool_ids,
                "bm25_ids": bm25_ids,
                "gold_ids": sorted(item for item in candidates if is_gold(row, item)),
            })
            if len(records) % 100 == 0:
                print(f"retrieved={len(records)}/{len(validation)}", flush=True)
    finally:
        rag.CHROMA_DIR = original_chroma_dir
        rag.load_vector_db.clear()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--worker-copy", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reuse-candidates", action="store_true", help="skip retrieval and re-analyze the cache")
    args = parser.parse_args()

    if args.worker_copy:
        collect_candidates(args.worker_copy, args.candidates)
        return 0

    if not args.reuse_candidates:
        with tempfile.TemporaryDirectory(prefix="dograg-fusion-eval-") as directory:
            copy_path = Path(directory) / "chroma_db"
            shutil.copytree(PROJECT_DIR / "data" / "chroma_db", copy_path)
            env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
            command = [sys.executable, str(Path(__file__).resolve()),
                       "--worker-copy", str(copy_path), "--candidates", str(args.candidates)]
            code = subprocess.run(command, cwd=PROJECT_DIR, env=env, check=False).returncode
            if code:
                return code

    records = json.loads(args.candidates.read_text(encoding="utf-8"))
    result = {
        "mode": "offline retrieval only; no LLM; disposable Chroma copy",
        "gold_rule": "all of meta.lifeCycle, meta.department, meta.disease match exactly; not clinical accuracy",
        "fusion": f"production reciprocal_rank_fusion, c=60, dense {DEFAULT_CANDIDATE_K} + bm25 {DEFAULT_CANDIDATE_K} candidates; weights are (1-w, w) for (dense, bm25)",
        **analyze(records),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
