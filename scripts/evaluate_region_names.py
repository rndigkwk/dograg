"""Facility questions with short region names ("수원", "부산", "강남"): right places, how fast.

    uv run python scripts/evaluate_region_names.py [--label NAME]

Runs src/tools/places.run_sql_search on tests/data/region_names.json as the app does (the
LLM writes the SQL when no region is recognized, so this needs OPENAI_API_KEY). For each
question: the region words extracted, whether every listed place is in the expected region,
whether the LLM was called, and the time. Results: output/experiments/region_names_<label>.json.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

DATA = PROJECT_DIR / "tests" / "data" / "region_names.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="current")
    args = parser.parse_args()
    from src import resources
    from src.tools import places

    real_model = resources.load_chat_model
    rows = []
    for item in json.loads(DATA.read_text(encoding="utf-8"))["items"]:
        calls = []

        def counting_model(calls=calls):
            calls.append(1)
            return real_model()

        started = time.perf_counter()
        with patch.object(resources, "load_chat_model", counting_model):
            _, found = places.run_sql_search(item["question"])
        seconds = round(time.perf_counter() - started, 2)
        region = item["expected"] or item["also_in"]
        addresses = [f"{row.get('road_address') or ''} {row.get('lot_address') or ''}" for row in found]
        rows.append({
            "id": item["id"], "question": item["question"], "expected": region,
            "keywords": places.extract_search_parameters(item["question"]),
            "places": len(found), "in_region": sum(region in address for address in addresses),
            "kind_ok": all(row.get("kind") == item["kind"] for row in found),
            "used_model": bool(calls), "seconds": seconds,
        })
        row = rows[-1]
        print(row["id"], row["keywords"], f"{row['in_region']}/{row['places']}", row["kind_ok"],
              "model" if row["used_model"] else "fixed", f"{seconds}s", flush=True)
    correct = [r for r in rows if r["places"] and r["in_region"] == r["places"] and r["kind_ok"]]
    summary = {
        "questions": len(rows),
        "all_places_in_region": len(correct),
        "no_places": sum(not r["places"] for r in rows),
        "used_model": sum(r["used_model"] for r in rows),
        "seconds_p50": statistics.median(r["seconds"] for r in rows),
        "seconds_max": max(r["seconds"] for r in rows),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    out = PROJECT_DIR / "output" / "experiments" / f"region_names_{args.label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
