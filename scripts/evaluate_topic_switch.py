"""Does the conversation so far help or hurt the health search?

    uv run python scripts/evaluate_topic_switch.py [--set holdout]

tests/data/topic_switch_questions.json: questions asked after earlier ones. For each, the app's
query (src/tools/history.py memory_search_query: one low-effort model call when there are earlier
health questions; --rules for the rule-built query without a model call) and
the gold query (the question as a person would write it alone) go through the same health search
(retrieve_health, the 5 candidates CRAG grades, filters inferred from the query as the app does).
Score: the share of the gold query's 5 documents the app's query also finds. kind=switch should
not be pulled away by earlier topics; kind=follow should still carry the earlier topic.
kind=place (holdout): the regions the facility search reads from the query must be the expected ones.
Sets: dev (topic_switch_questions.json, the rule was chosen on it) and holdout
(topic_switch_holdout.json, written before the rule was implemented).
Results: output/experiments/topic_switch_<set>.json.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

CANDIDATES = 5


def doc_ids(docs) -> list[str]:
    return [doc.metadata.get("id") or doc.page_content[:80] for doc in docs]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=["dev", "holdout"], default="dev")
    parser.add_argument("--rules", action="store_true", help="the rule-built query only (no model call)")
    args = parser.parse_args()
    from src import resources
    from src.tools import health, history, places

    name = {"dev": "topic_switch_questions.json", "holdout": "topic_switch_holdout.json"}[args.set]
    items = json.loads((PROJECT_DIR / "tests" / "data" / name).read_text(encoding="utf-8"))["items"]
    rows = []
    with tempfile.TemporaryDirectory(prefix="ragdog-topic-", ignore_cleanup_errors=True) as directory:
        resources.CHROMA_DIR = Path(directory) / "chroma_db"
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", resources.CHROMA_DIR)

        def search(query: str) -> list[str]:
            return doc_ids(health.retrieve_health(query, k=CANDIDATES, filters=health.infer_rag_filters(query)))

        for item in items:
            past = [message for question in item["history"]
                    for message in ({"role": "user", "content": question}, {"role": "assistant", "content": "(답변)"})]
            if item["kind"] == "place":
                query = history.build_rag_search_query(item["question"], past)
                regions = places.extract_search_parameters(query)
                rows.append({"id": item["id"], "kind": "place", "query": query, "regions": regions,
                             "overlap": 1.0 if regions == item["expected_regions"] else 0.0})
                continue
            query = (history.build_rag_search_query(item["question"], past, health=True) if args.rules
                     else history.memory_search_query(item["question"], past))
            gold, got = search(item["gold"]), search(query)
            overlap = len(set(gold) & set(got)) / len(gold) if gold else 0.0
            rows.append({"id": item["id"], "kind": item["kind"], "query": query, "overlap": round(overlap, 2)})
    report = {}
    for kind in ("switch", "follow", "place"):
        scores = [row["overlap"] for row in rows if row["kind"] == kind]
        if not scores:
            continue
        report[kind] = {"questions": len(scores), "mean_overlap": round(statistics.mean(scores), 3),
                        "no_overlap": sum(score == 0 for score in scores)}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    for row in rows:
        if row["overlap"] < 0.6:
            print(f"{row['id']} {row['overlap']:.1f} | {' / '.join(row['query'].splitlines())}")
    out = PROJECT_DIR / "output" / "experiments" / f"topic_switch_{args.set}{'_rules' if args.rules else ''}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"report": report, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
