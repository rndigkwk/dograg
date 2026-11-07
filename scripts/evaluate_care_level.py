"""The "진료 권장" badge: does the urgency check's middle answer come where it should?

    uv run python scripts/evaluate_care_level.py [--label NAME]   # OpenAI Decisions calls
    uv run python scripts/evaluate_care_level.py --holdout [--label NAME]

Runs src/tools/urgency.py urgency_level over tests/data/care_level_questions.json (15 should get
the badge, 15 should not) and the everyday questions of basic_care_questions.json (30) and
care_guide_questions.json (16), which should not get it either. One Decisions call per question
the rules leave to the model, so at most 76 calls. An emergency_now answer on a should-get item
counts as a badge (the red warning comes instead). The decision rule is the data file's
description, set before measuring. Results: output/experiments/care_level_<label>.json.

--holdout measures tests/data/urgency_holdout_questions.json instead (2026-11-07, 54 questions in
four kinds: emergency, vet_soon, info_danger, mild): for a change to the rules or the check's
instructions, measured once before and once after. At most 54 calls, fewer where the rules
answer; URGENT_SECOND_CHECK=off measures the rules alone with no call. Its decision rule is that
file's description. Results: output/experiments/urgency_holdout_<label>.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from src.tools.urgency import urgency_level  # noqa: E402

DATA = PROJECT_DIR / "tests" / "data"


def questions() -> list[dict]:
    items = json.loads((DATA / "care_level_questions.json").read_text(encoding="utf-8"))["items"]
    for name in ("basic_care_questions", "care_guide_questions"):
        for item in json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))["items"]:
            items.append({"id": item["id"], "expected": "not_urgent", "set": name, "question": item["question"]})
    return items


def holdout_summary(items: list[dict]) -> dict:
    """Per kind: how many got the red warning, the badge, or neither."""
    summary = {}
    for kind in ("emergency", "vet_soon", "info_danger", "mild"):
        got = [item["got"] for item in items if item["kind"] == kind]
        summary[kind] = {"n": len(got), **{level: got.count(level) for level in ("emergency_now", "see_vet_soon", "none")}}
    summary["wrong_ids"] = [item["id"] for item in items if item["got"] != {
        "emergency": "emergency_now", "vet_soon": "see_vet_soon"}.get(item["kind"], "none")]
    return summary


def run_holdout(label: str) -> int:
    items = json.loads((DATA / "urgency_holdout_questions.json").read_text(encoding="utf-8"))["items"]
    for item in items:
        notice, level = urgency_level(item["question"])
        item["got"] = "emergency_now" if notice else (level or "none")
    summary = holdout_summary(items)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for item in items:
        if item["id"] in summary["wrong_ids"]:
            print(item["kind"], item["got"], item["id"], item["question"])
    out = PROJECT_DIR / "output" / "experiments" / f"urgency_holdout_{label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="current")
    parser.add_argument("--holdout", action="store_true", help="tests/data/urgency_holdout_questions.json")
    args = parser.parse_args()
    if args.holdout:
        return run_holdout(args.label)
    items = questions()
    for item in items:
        notice, level = urgency_level(item["question"])
        item["got"] = "emergency_now" if notice else (level or "none")
    should = [item for item in items if item["expected"] == "vet_soon"]
    should_not = [item for item in items if item["expected"] != "vet_soon"]
    badge = [item for item in should if item["got"] != "none"]
    wrong = [item for item in should_not if item["got"] == "see_vet_soon"]
    warned = [item for item in should_not if item["got"] == "emergency_now"]
    summary = {
        "vet_soon": len(should), "badge_or_warning": len(badge),
        "should_not": len(should_not), "badge_on_should_not": len(wrong),
        "badge_rate_on_should_not": round(len(wrong) / len(should_not), 3),
        "red_warning_on_should_not": len(warned),
        "missed_ids": [item["id"] for item in should if item["got"] == "none"],
        "wrong_ids": [item["id"] for item in wrong + warned],
    }
    summary["ship"] = len(badge) >= 10 and len(wrong) / len(should_not) <= 0.10
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for item in items:
        if (item["expected"] == "vet_soon") == (item["got"] == "none") or item in warned:
            print(item["got"], item["id"], item["question"])
    out = PROJECT_DIR / "output" / "experiments" / f"care_level_{args.label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
