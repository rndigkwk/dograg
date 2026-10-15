"""Routing of everyday dog-care questions (tests/data/care_routing_questions.json) and of the
care questions of tests/data/basic_care_questions.json, with the app's router (rules + model).

    uv run python scripts/evaluate_care_routing.py [--repeats 2]

Prints per split how many went where they should; a care question routed to none gets the service
menu instead of an answer, a non-dog question routed to rag gets a health answer about nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
DATA = PROJECT_DIR / "tests" / "data"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    sys.stdout.reconfigure(encoding="utf-8")
    from src.tools.router import classify_question

    items = json.loads((DATA / "care_routing_questions.json").read_text(encoding="utf-8"))["items"]
    items += [{"id": i["id"], "split": "basic_care", "expected": "rag", "question": i["question"]}
              for i in json.loads((DATA / "basic_care_questions.json").read_text(encoding="utf-8"))["items"]]
    jobs = [item for item in items for _ in range(args.repeats)]
    with ThreadPoolExecutor(8) as pool:
        routes = list(pool.map(lambda item: classify_question(item["question"]), jobs))
    wrong = Counter()
    totals = Counter()
    for item, route in zip(jobs, routes):
        key = (item["split"], item["expected"])
        totals[key] += 1
        if route != item["expected"]:
            wrong[key] += 1
            print(f"  {item['id']} -> {route}: {item['question']}")
    for key in sorted(totals):
        print(f"{key[0]:10} expected {key[1]:4}: {totals[key] - wrong[key]}/{totals[key]} right")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
