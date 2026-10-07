"""Measure place-kind detection and question routing on tests/data/place_routing_questions.json.

    uv run python scripts/evaluate_place_routing.py            # keyword rules only (no API)
    uv run python scripts/evaluate_place_routing.py --llm      # also the real router (OpenAI calls)

Kind accuracy counts only the place-search questions (route "sql"); for the others the
router decides, so their kind is not graded. Route accuracy is reported twice: with the
keyword rules alone (what runs without an API key) and with the LLM router for the
questions the rules leave to it. Writes output/place_routing.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

QUESTIONS = PROJECT_DIR / "tests" / "data" / "place_routing_questions.json"


def evaluate(items: list[dict], use_llm: bool) -> dict:
    from src import resources
    from src.tools import places, router

    rows = []
    for item in items:
        question = item["question"]
        with patch.object(resources, "load_chat_model", return_value=None):
            rule_route = router.classify_question(question)
        row = {**item, "detected_kind": places.place_kind(question), "rule_route": rule_route}
        if use_llm:
            started = time.perf_counter()
            row["llm_route"] = router.classify_question(question)
            row["llm_ms"] = round((time.perf_counter() - started) * 1000)
        rows.append(row)

    searches = [row for row in rows if row["route"] == "sql"]
    summary = {
        "questions": len(rows),
        "place_searches": len(searches),
        "kind_accuracy": sum(row["detected_kind"] == row["kind"] for row in searches) / len(searches),
        "rule_route_accuracy": sum(row["rule_route"] == row["route"] for row in rows) / len(rows),
        "kinds": dict(Counter(row["kind"] for row in searches)),
    }
    if use_llm:
        summary["llm_route_accuracy"] = sum(row["llm_route"] == row["route"] for row in rows) / len(rows)
        summary["llm_called"] = sum(row["llm_ms"] > 50 for row in rows)  # rules answer in well under 1 ms
    summary["errors"] = [
        {key: row.get(key) for key in ("id", "question", "route", "kind", "detected_kind", "rule_route", "llm_route")}
        for row in rows
        if (row["route"] == "sql" and row["detected_kind"] != row["kind"])
        or row["rule_route"] != row["route"]
        or (use_llm and row["llm_route"] != row["route"])
    ]
    return {"summary": summary, "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--llm", action="store_true", help="also run the LLM router (needs OPENAI_API_KEY)")
    parser.add_argument("--output", type=Path, default=PROJECT_DIR / "output" / "place_routing.json")
    args = parser.parse_args()
    items = json.loads(QUESTIONS.read_text(encoding="utf-8"))["items"]
    report = evaluate(items, use_llm=args.llm)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
