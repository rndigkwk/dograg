"""Clinic fee questions: does the chatbot take the fee path, and quote the right number?

    uv run python scripts/evaluate_fees.py

tests/data/fee_questions.json: 24 fee questions with the expected region, item and weight/species
variant, and 14 questions that mention costs or fee items but belong elsewhere. For a fee question
the answer (src/tools/fees.py, no model call) must contain the expected row's median, taken from
data/vet_fees/vet_fees.csv. Also counts how many questions of the other evaluation sets would be
taken by the fee path (they should not be). Needs no API key. Results: output/experiments/fees.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from src.tools import fees  # noqa: E402

DATA = PROJECT_DIR / "tests" / "data"
OTHER_SETS = {
    "place_routing_questions.json": "question", "jev_router_questions.json": "question",
    "emergency_signs.json": "question", "region_names.json": "question", "crag_eval_questions.json": "question",
}


def expected_median(item: dict) -> str | None:
    level = "sigungu" if item["sigungu"] else ("sido" if item["sido"] else "national")
    for row in fees.load_fee_rows():
        if (row["level"] == level and row["item"] == item["item"] and row["detail"] == item["detail"]
                and (level == "national" or row["sido"] == item["sido"])
                and (level != "sigungu" or row["sigungu"] == item["sigungu"])):
            return f"{int(row['median']):,}원"
    return None


def main() -> int:
    items = json.loads((DATA / "fee_questions.json").read_text(encoding="utf-8"))["items"]
    rows, report = [], {}
    for item in items:
        routed = fees.is_fee_question(item["question"])
        entry = {"id": item["id"], "fee": item["fee"], "routed": routed}
        if item["fee"]:
            median = expected_median(item)
            answer = fees.fee_answer(item["question"]) if routed else ""
            place = " ".join(filter(None, (item["sido"], item["sigungu"]))) or "전국"
            line = next((line for line in answer.splitlines() if line.startswith(f"- {place}:")), "")
            entry.update(expected=median, correct=bool(median and routed and f"중간 {median}" in line))
            if not entry["correct"]:
                print("WRONG", item["id"], item["question"], "| expected", place, median, "| got", line or answer[:120])
        elif routed:
            print("FALSE ROUTE", item["id"], item["question"])
        rows.append(entry)
    fee_items = [r for r in rows if r["fee"]]
    report["fee_questions"] = {"total": len(fee_items), "routed": sum(r["routed"] for r in fee_items),
                               "correct_median": sum(r.get("correct", False) for r in fee_items)}
    others = [r for r in rows if not r["fee"]]
    report["other_questions"] = {"total": len(others), "routed_to_fee": sum(r["routed"] for r in others)}
    taken = {}
    for name, key in OTHER_SETS.items():
        path = DATA / name
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        questions = [q[key] for q in (data["items"] if isinstance(data, dict) else data) if isinstance(q, dict) and key in q]
        hits = [q for q in questions if fees.is_fee_question(q)]
        taken[name] = {"questions": len(questions), "routed_to_fee": len(hits), "examples": hits[:5]}
    report["other_evaluation_sets"] = taken
    print(json.dumps(report, ensure_ascii=False, indent=1))
    out = PROJECT_DIR / "output" / "experiments" / "fees.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"report": report, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
