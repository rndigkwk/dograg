"""Does the CRAG grader work as a reranker? hit@3 on the 561 validation questions.

    uv run python scripts/evaluate_llm_rerank.py --limit 20     # smoke run
    uv run python scripts/evaluate_llm_rerank.py --sample 100   # fixed random 100 (seed 47)
    uv run python scripts/evaluate_llm_rerank.py                # all 561 (real model calls)
    uv run python scripts/evaluate_llm_rerank.py --reuse        # re-analyze saved results

For each question the production hybrid retrieval returns 12 candidates. Compared:
- hybrid: the first 3 candidates (what the app shows without CRAG)
- oracle@5 / oracle@12: a gold document anywhere in the first 5 / 12 (rerank ceiling)
- llm@5 / llm@12: the CRAG grader (review_evidence) reads the first 5 / 12 candidates;
  documents it selects come first in its order, the rest keep their hybrid order.
  "kept" variants count only selected documents, as the app shows them.

A gold document has the question's life stage, department and disease (same rule as
scripts/evaluate_hybrid_search.py). The grader judges relevance from text, so it can
prefer useful documents with other labels; hit@3 is a proxy, not answer quality.
Runs on a disposable Chroma copy; candidate texts are sent to the OpenAI API.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from scripts.evaluate_hybrid_search import METADATA_FIELDS

POOL = 12
DEFAULT_OUTPUT = PROJECT_DIR / "output" / "llm_rerank.json"


def llm_order(ids: list[str], useful_ids: list[str]) -> tuple[list[str], list[str]]:
    """(full ranking, kept only): selected ids first in grader order, then the rest."""
    valid = set(ids)
    kept = [value for value in dict.fromkeys(v.strip("[] \t\r\n") for v in useful_ids) if value in valid]
    return kept + [value for value in ids if value not in kept], kept


def hit_at(ranked: list[str], gold: set[str], k: int = 3) -> bool:
    return any(value in gold for value in ranked[:k])


def mcnemar_p(gained: int, lost: int) -> float:
    """Exact two-sided McNemar test on the discordant pairs."""
    n = gained + lost
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(gained, lost) + 1)) / 2**n
    return min(1.0, 2 * tail)


def collect(rag, rows, limit_workers: int) -> list[dict]:
    from langchain_core.callbacks import get_usage_metadata_callback

    from src.chat_graph import _health_text
    from src.crag import format_candidates

    records = []
    for index, row in rows:
        question = str(row["qa.input"])
        docs = rag.retrieve_health(question, k=POOL, filters=None)
        gold = [d.id for d in docs if all(str(d.metadata.get(f)) == str(row[f]) for f in METADATA_FIELDS)]
        records.append({"row": int(index), "question": question, "ids": [d.id for d in docs], "gold": gold,
                        "contexts": {str(pool): format_candidates(docs[:pool], _health_text) for pool in (5, POOL)}})
        if len(records) % 100 == 0:
            print(f"retrieved {len(records)}/{len(rows)}", flush=True)

    def grade(record: dict, pool: int) -> dict:
        started = time.perf_counter()
        with get_usage_metadata_callback() as usage:
            try:
                review = rag.review_evidence("health", record["question"], record["contexts"][str(pool)])
                useful, error = list(review.useful_ids), None
            except Exception as exc:  # noqa: BLE001 - count the failure, keep the hybrid order
                useful, error = [], type(exc).__name__
        tokens = sum(v.get("total_tokens", 0) for v in usage.usage_metadata.values())
        return {"useful_ids": useful, "error": error, "tokens": tokens,
                "seconds": round(time.perf_counter() - started, 1)}

    jobs = [(record, pool) for record in records for pool in (5, POOL)]
    with ThreadPoolExecutor(max_workers=limit_workers) as pool_executor:
        for done, ((record, pool), result) in enumerate(
            zip(jobs, pool_executor.map(lambda job: grade(*job), jobs)), start=1
        ):
            record[f"llm{pool}"] = result
            if done % 50 == 0:
                print(f"graded {done}/{len(jobs)}", flush=True)
    for record in records:
        record.pop("contexts")
    return records


def analyze(records: list[dict]) -> dict:
    count = len(records)
    rankings = {"hybrid": [], "llm@5": [], "llm@5 kept": [], "llm@12": [], "llm@12 kept": []}
    oracle = {"oracle@5": 0, "oracle@12": 0}
    for record in records:
        ids, gold = record["ids"], set(record["gold"])
        rankings["hybrid"].append(hit_at(ids, gold))
        oracle["oracle@5"] += any(v in gold for v in ids[:5])
        oracle["oracle@12"] += any(v in gold for v in ids)
        for pool in (5, POOL):
            full, kept = llm_order(ids[:pool], record[f"llm{pool}"]["useful_ids"])
            rankings[f"llm@{pool}"].append(hit_at(full, gold))
            rankings[f"llm@{pool} kept"].append(hit_at(kept, gold))
    summary = {name: {"hit@3": round(sum(hits) / count, 4), "hits": sum(hits)} for name, hits in rankings.items()}
    summary.update({name: {"ceiling": round(value / count, 4), "hits": value} for name, value in oracle.items()})
    baseline = rankings["hybrid"]
    for name in ("llm@5", "llm@12"):
        gained = sum(new and not old for old, new in zip(baseline, rankings[name]))
        lost = sum(old and not new for old, new in zip(baseline, rankings[name]))
        summary[name].update(gained=gained, lost=lost, mcnemar_p=round(mcnemar_p(gained, lost), 4))
        calls = [r[f"llm{name[4:]}"] for r in records]
        summary[name].update(
            mean_tokens=round(sum(c["tokens"] for c in calls) / count),
            mean_seconds=round(sum(c["seconds"] for c in calls) / count, 1),
            errors=sum(c["error"] is not None for c in calls),
            empty_selection=sum(not c["useful_ids"] for c in calls),
        )
    return {"questions": count, **summary}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--sample", type=int, help="random N questions with a fixed seed")
    parser.add_argument("--seed", type=int, default=47)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reuse", action="store_true", help="re-analyze the saved records")
    args = parser.parse_args()

    if args.reuse:
        records = json.loads(args.output.read_text(encoding="utf-8"))["records"]
    else:
        os.environ["HF_HUB_OFFLINE"] = "1"
        import pandas as pd

        from pages import rag

        validation = pd.read_csv(PROJECT_DIR / "data" / "df_val.csv").fillna("")
        if args.sample:
            validation = validation.sample(n=args.sample, random_state=args.seed)
        rows = list(validation.iterrows())[: args.limit]
        with tempfile.TemporaryDirectory(prefix="dograg-rerank-", ignore_cleanup_errors=True) as directory:
            rag.CHROMA_DIR = Path(directory) / "chroma_db"
            shutil.copytree(PROJECT_DIR / "data" / "chroma_db", rag.CHROMA_DIR)
            records = collect(rag, rows, args.workers)
    report = {"summary": analyze(records), "records": records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
