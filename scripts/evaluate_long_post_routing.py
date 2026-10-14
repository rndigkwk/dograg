"""Long health consultations routed away from health search (keyword rules, 2026-10-14).

    uv run python scripts/evaluate_long_post_routing.py            # keyword rules only (no API)
    uv run python scripts/evaluate_long_post_routing.py --app      # the app's router (rules + Decisions)

scripts/evaluate_answer_quality.py found 9 of the 100 long consultations of
tests/data/health_relevance_100.json routed to facility search, small talk or reports, the same 9 in
two runs: a keyword rule decided before the model router. Every row of data/df_val.csv is a dog
owner's health consultation, so the right route is "rag" for all of them.
- dev: the 100 rows of health_relevance_100.json (the 9 misroutes were found and fixed on these)
- holdout: the other 461 rows of df_val.csv, measured, never used to choose the fix
Without --app the questions the rules leave to the model count as "model" (not a misroute by the
rules); with --app they go through the deployed router. Also prints the existing routed sets the
rules must keep (place routing 36, small talk 30, dates 22, guardrails 44), so a fix that breaks them
shows here. Results: output/experiments/long_post_routing.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
DATA = PROJECT_DIR / "tests" / "data"


def long_posts() -> dict[str, list[str]]:
    csv.field_size_limit(10**8)
    with open(PROJECT_DIR / "data" / "df_val.csv", encoding="utf-8", newline="") as f:
        val = [row["qa.input"].replace("\r", "") for row in csv.DictReader(f)]
    dev_rows = {int(item["row"]) for item in json.loads((DATA / "health_relevance_100.json").read_text(encoding="utf-8"))["items"]}
    return {"dev": [val[i] for i in sorted(dev_rows)], "holdout": [q for i, q in enumerate(val) if i not in dev_rows]}


def guard_sets() -> dict[str, list[tuple[str, str]]]:
    """(question, expected route) the rules already decide in other evaluations."""
    place = json.loads((DATA / "place_routing_questions.json").read_text(encoding="utf-8"))
    place_items = place["items"] if isinstance(place, dict) else place
    general = json.loads((DATA / "general_questions.json").read_text(encoding="utf-8"))["items"]
    guard = json.loads((DATA / "guardrail_questions.json").read_text(encoding="utf-8"))["items"]
    return {
        "place_routing": [(i["question"], i["route"]) for i in place_items if i.get("route")],
        "small_talk": [(i["question"], "none") for i in general],
        "off_scope": [(i["question"], "none") for i in guard if i["category"] == "off_scope"],
    }


def route_with_rules(question: str) -> str:
    """The keyword rules alone: "model" when they hand the question to the model router."""
    from src import resources
    from src.tools import router

    with patch.object(resources, "load_chat_model", return_value=object()), \
            patch.object(router, "decide_route", side_effect=lambda *a, **k: "model"):
        try:
            return router.classify_question(question)
        except Exception:  # noqa: BLE001 - the structured-output fallback on a fake model
            return "model"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", action="store_true", help="route with the deployed router (model calls)")
    args = parser.parse_args()
    from src.tools import router

    def route(question):
        return router.classify_question(question) if args.app else route_with_rules(question)

    result: dict = {"mode": "app" if args.app else "rules"}
    for name, questions in long_posts().items():
        with ThreadPoolExecutor(8 if args.app else 1) as pool:
            routes = list(pool.map(route, questions))
        counts = Counter(routes)
        wrong = [(q[:70], r) for q, r in zip(questions, routes) if r not in ("rag", "model")]
        result[name] = {"total": len(questions), "routes": dict(counts),
                        "misrouted_by_rules": len(wrong), "examples": wrong[:12]}
        print(name, len(questions), dict(counts), "misrouted:", len(wrong), flush=True)
    for name, items in guard_sets().items():
        routes = [route_with_rules(q) for q, _ in items]
        decided = [(q, expected, r) for (q, expected), r in zip(items, routes) if r != "model"]
        wrong = [(q[:50], expected, r) for q, expected, r in decided if r != expected]
        result[name] = {"total": len(items), "decided_by_rules": len(decided), "wrong_by_rules": wrong}
        print(name, len(items), "rules decided", len(decided), "wrong", len(wrong), wrong[:5], flush=True)
    out = PROJECT_DIR / "output" / "experiments" / "long_post_routing.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
