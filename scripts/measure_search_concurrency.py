"""How the health search step slows when several questions search at once (Day 76). No model calls.

    uv run python scripts/measure_search_concurrency.py OUT.json             # one CPU, like Cloud Run --cpu=1
    uv run python scripts/measure_search_concurrency.py OUT.json --all-cpus

Runs src/tools/health.retrieve_health (query embedding + the search backend; set SEARCH_BACKEND=supabase
to measure production search) from 1, 4 and 16 threads, each concurrency twice in the order
1, 4, 16, 16, 4, 1. 48 questions warm up the models, the connections and the database's pages first:
without that the first runs are several times slower. Questions are the CRAG and router evaluation
questions (tests/data), so crag_eval_questions.json (private data) must be downloaded.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
CONCURRENCY = (1, 4, 16, 16, 4, 1)
WARM_UP = 48


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def questions() -> list[str]:
    pool = []
    for name in ("crag_eval_questions.json", "jev_router_questions.json"):
        data = json.loads((PROJECT_DIR / "tests" / "data" / name).read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else (data.get("items") or data.get("questions") or [])
        pool += [item["question"] for item in items if isinstance(item, dict) and item.get("question")]
    return list(dict.fromkeys(pool))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output", type=Path)
    parser.add_argument("--all-cpus", action="store_true", help="do not pin the process to one CPU")
    args = parser.parse_args()
    os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")
    if not args.all_cpus:
        import psutil

        psutil.Process().cpu_affinity([0])
    from src import resources
    from src.tools import health

    def one(question: str) -> tuple[float, int]:
        started = time.perf_counter()
        docs = health.retrieve_health(question)
        return time.perf_counter() - started, len(docs)

    pool = questions()
    for question in pool[:WARM_UP]:
        one(question)
    cursor, runs = WARM_UP, []
    for concurrency in CONCURRENCY:
        count = max(16, 2 * concurrency)
        batch = [pool[(cursor + i) % len(pool)] for i in range(count)]
        cursor += count
        started = time.perf_counter()
        with ThreadPoolExecutor(concurrency) as executor:
            results = list(executor.map(one, batch))
        wall = time.perf_counter() - started
        seconds = [r[0] for r in results]
        row = {"concurrency": concurrency, "requests": count, "p50_s": round(percentile(seconds, 0.5), 2),
               "p95_s": round(percentile(seconds, 0.95), 2), "max_s": round(max(seconds), 2),
               "searches_per_s": round(count / wall, 2), "fewest_docs": min(r[1] for r in results)}
        runs.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    report = {"backend": resources.search_backend(), "all_cpus": args.all_cpus, "runs": runs}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
