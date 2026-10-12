"""Facility follow-ups without a facility word: routed to the facility search, kept out of health searches?

    uv run python scripts/evaluate_place_follow_up.py [--runs 2]

tests/data/place_follow_up_questions.json (written before measuring):
- route items: the route the app's classify step gives the question after the earlier turns
  (date and fee checks first, then classify_question; real model calls for what the keyword
  rules leave open). "24시 하는 곳은?" after "일산 동물병원 알려줘" should go to the facility search.
- query items: a health question after such a follow-up. earlier_health_questions must list only
  the expected earlier questions, and the health search query (memory_search_query, one model
  call when there are earlier health questions) must not contain the forbidden words.
History turns carry the route the app recorded for them, as the app's chat history does.
Results: output/experiments/place_follow_up.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

PLACE_ANSWER = "조건에 맞는 곳 3곳을 찾았습니다.\n1. 가 (주소)\n2. 나 (주소)\n3. 다 (주소)"
OTHER_ANSWER = "(답변)"


def past_messages(history: list[list[str]]) -> list[dict]:
    messages = []
    for question, route in history:
        messages.append({"role": "user", "content": question})
        messages.append({"role": "assistant", "content": PLACE_ANSWER if route == "sql" else OTHER_ANSWER,
                         "route": route})
    return messages


def app_route(question: str, past: list[dict]) -> str:
    """The route src/chat_graph.py classify gives (date, fee, then the router)."""
    from src.tools import fees, router

    if router.is_date_question(question):
        return "date"
    if fees.is_fee_question(question):
        return "fee"
    return router.classify_question(question, chat_history=past)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1, help="repeat the model-dependent checks")
    args = parser.parse_args()
    from src.tools import history

    items = json.loads((PROJECT_DIR / "tests" / "data" / "place_follow_up_questions.json").read_text(encoding="utf-8"))["items"]
    runs = []
    for run in range(args.runs):
        rows = []
        for item in items:
            past = past_messages(item["history"])
            if item["part"] == "route":
                route = app_route(item["question"], past)
                rows.append({"id": item["id"], "part": "route", "expected": item["expected"], "got": route,
                             "ok": route == item["expected"]})
                continue
            earlier = history.earlier_health_questions(item["question"], past)
            started = time.perf_counter()
            query = history.memory_search_query(item["question"], past)
            seconds = round(time.perf_counter() - started, 2)
            leaked = [word for word in item["forbidden"] if word in query]
            rows.append({"id": item["id"], "part": "query", "earlier": earlier, "query": query, "leaked": leaked,
                         "rewrite_call": bool(earlier), "seconds": seconds,
                         "earlier_ok": earlier == item["earlier_health"], "ok": not leaked})
        runs.append(rows)
        route_rows = [row for row in rows if row["part"] == "route"]
        query_rows = [row for row in rows if row["part"] == "query"]
        place = [row for row in route_rows if row["expected"] == "sql"]
        print(f"run {run + 1}: facility follow-ups to sql {sum(r['ok'] for r in place)}/{len(place)}, "
              f"others kept {sum(r['ok'] for r in route_rows if r['expected'] != 'sql')}/{len(route_rows) - len(place)}, "
              f"earlier list right {sum(r['earlier_ok'] for r in query_rows)}/{len(query_rows)}, "
              f"query without facility words {sum(r['ok'] for r in query_rows)}/{len(query_rows)}, "
              f"rewrite calls {sum(r['rewrite_call'] for r in query_rows)}/{len(query_rows)} "
              f"({sum(r['seconds'] for r in query_rows):.1f} s)")
        for row in rows:
            if not row["ok"] or not row.get("earlier_ok", True):
                detail = (f"{row['expected']} -> {row['got']}" if row["part"] == "route"
                          else f"leaked {row['leaked']} earlier {row['earlier']} | {row['query']}")
                print(f"  {row['id']} {detail}")
    output = PROJECT_DIR / "output" / "experiments" / "place_follow_up.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
