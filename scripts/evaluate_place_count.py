"""How many places a facility answer lists, against tests/data/place_count_questions.json.

    uv run python scripts/evaluate_place_count.py

Runs the SQL facility search (src/tools/places.py run_sql_search, no model call) and compares the
number of rows with the count the question asks for ("3곳", "세 곳", "2개만"; 10 when none is
asked, "count" for "몇 곳 있어?" questions answered with a single count row). A question that asks
no count passes with fewer than 10 rows when its limit is 10: fewer places match ("24시" names).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from src.tools import places  # noqa: E402


def main() -> int:
    items = json.loads((PROJECT_DIR / "tests" / "data" / "place_count_questions.json").read_text(encoding="utf-8"))["items"]
    correct = 0
    for item in items:
        _, rows = places.run_sql_search(item["question"])
        got = "count" if len(rows) == 1 and "count" in rows[0] else len(rows)
        unlimited = item["expected"] == places.DEFAULT_HOSPITAL_LIMIT
        ok = got == item["expected"] or (
            unlimited and isinstance(got, int) and got < item["expected"]
            and places.get_hospital_result_limit(item["question"]) == places.DEFAULT_HOSPITAL_LIMIT)
        correct += ok
        if not ok:
            print("WRONG", item["id"], item["question"], "| expected", item["expected"], "| got", got)
    print(f"correct {correct}/{len(items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
