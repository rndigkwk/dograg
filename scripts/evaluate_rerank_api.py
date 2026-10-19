"""Would a hosted rerank API put the useful consultations in the top 3? Measured on the graded pools.

    uv run python scripts/evaluate_rerank_api.py --dry-run            # pools, calls, characters sent
    uv run python scripts/evaluate_rerank_api.py --provider cohere    # COHERE_API_KEY in .env

Local cross-encoders were measured and rejected (experiment 11: none fit the deployment's CPU and
memory), so this is the remaining reranking option (docs/wiki/open-questions.md). Each question of
the relevance sets (tests/data/health_relevance_100.json and, when present, _dental.json) has a pool
of up to 24 candidates, every one graded 0-2 by the judge. The API reorders the whole pool, so its
top 3 is fully graded and compares fairly with:
- app: the pool's stored hybrid ranking (the ranking the set was built from)
- pool_best: the best 3 of the pool, what a perfect reranker reaches

One API call per question (110). What leaves the machine: the validation question and each
candidate's question and the first 300 characters of its answer, all from the AI Hub corpus, no user
text. Adopting a reranker in the app would send guardians' questions too: that is a separate decision
(docs/security/README.md). Results: output/experiments/rerank_api.json.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

import relevance_set as rs

OUT = PROJECT_DIR / "output" / "experiments" / "rerank_api.json"
PROVIDERS = {
    # Multilingual rerankers with a free trial tier; Korean is among their languages.
    "cohere": ("COHERE_API_KEY", "https://api.cohere.com/v2/rerank", "rerank-v3.5"),
    "jina": ("JINA_API_KEY", "https://api.jina.ai/v1/rerank", "jina-reranker-v2-base-multilingual"),
}


def sets() -> dict[str, list[dict]]:
    found = {"random100": rs.load_items()}
    dental = rs.SET_PATH.with_name("health_relevance_dental.json")
    if dental.exists():
        found["dental10"] = json.loads(dental.read_text(encoding="utf-8"))["items"]
    return found


def pools(items: list[dict]) -> list[tuple[dict, str, list[str], list[str]]]:
    """(item, question, candidate ids, candidate texts) from data/df_val.csv and the health store."""
    import pandas as pd

    rows = pd.read_csv(PROJECT_DIR / "data" / "df_val.csv").fillna("")
    texts = {}
    with (PROJECT_DIR / "data" / "vector_store" / "health" / "documents.jsonl").open(encoding="utf-8") as file:
        for line in file:
            row = json.loads(line)
            texts[str(row["id"])] = row
    out = []
    for item in items:
        ids = [doc_id for doc_id in item["grades"] if doc_id in texts]
        docs = [_doc(texts[doc_id]) for doc_id in ids]
        out.append((item, str(rows.loc[int(item["row"]), "qa.input"]), ids, [rs.candidate_text(d) for d in docs]))
    return out


def _doc(row: dict):
    from types import SimpleNamespace

    return SimpleNamespace(page_content=row["text"], metadata=row.get("metadata") or {})


def rerank(provider: str, key: str, question: str, documents: list[str]) -> list[int]:
    _, url, model = PROVIDERS[provider]
    body = json.dumps({"model": model, "query": question, "documents": documents, "top_n": len(documents)}).encode()
    request = urllib.request.Request(url, data=body, headers={"Authorization": f"Bearer {key}",
                                                              "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        results = json.loads(response.read())["results"]
    return [result["index"] for result in sorted(results, key=lambda r: -r["relevance_score"])]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=tuple(PROVIDERS), default="cohere")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from src import settings

    built = {name: pools(items) for name, items in sets().items()}
    calls = sum(len(p) for p in built.values())
    chars = sum(len(q) + sum(map(len, texts)) for p in built.values() for _, q, _, texts in p)
    print(f"{calls} API calls, {chars:,} characters sent ({', '.join(f'{k} {len(v)}' for k, v in built.items())})")
    if args.dry_run:
        return 0
    key = settings.get_setting(PROVIDERS[args.provider][0])
    if not key:
        raise SystemExit(f"{PROVIDERS[args.provider][0]} is needed in .env")
    report = {"provider": args.provider, "model": PROVIDERS[args.provider][2]}
    for name, pool in built.items():
        rankings, seconds = {}, []
        for item, question, ids, texts in pool:
            started = time.perf_counter()
            order = rerank(args.provider, key, question, texts)
            seconds.append(time.perf_counter() - started)
            rankings[item["row"]] = [ids[i] for i in order]
        items = [item for item, *_ in pool]
        report[name] = {
            "app": rs.metrics(items, lambda item: item["rankings"]["hybrid"]),
            "rerank": rs.metrics(items, lambda item, ranked=rankings: ranked[item["row"]]),
            "pool_best": rs.metrics(items, lambda item: sorted(item["grades"], key=lambda d: -item["grades"][d])),
            "seconds_p50": round(statistics.median(seconds), 2),
        }
        print(name, json.dumps(report[name], ensure_ascii=False))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
