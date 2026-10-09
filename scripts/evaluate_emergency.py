"""Emergency-sign detection: how many urgent questions get the warning, how many others do.

    uv run python scripts/evaluate_emergency.py [--label NAME]

tests/data/emergency_signs.json holds 40 urgent and 40 non-urgent questions, half `dev` (may
be used to change the rules in src/health_safety.py) and half `holdout` (only measured). The
rules run in code, so this needs no model and no API key. Also reports how often the warning
fires on the 19,206 real guardian questions of the health corpus (data/df.csv, unlabeled).
Results: output/experiments/emergency_<label>.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from src.health_safety import detect_urgent_sign  # noqa: E402

DATA = PROJECT_DIR / "tests" / "data" / "emergency_signs.json"
CORPUS = PROJECT_DIR / "data" / "df.csv"


def score(items: list[dict]) -> dict:
    urgent = [item for item in items if item["urgent"]]
    other = [item for item in items if not item["urgent"]]
    caught = [item for item in urgent if item["flagged"]]
    false_alarms = [item for item in other if item["flagged"]]
    return {
        "urgent": len(urgent), "caught": len(caught),
        "recall": round(len(caught) / len(urgent), 3) if urgent else None,
        "non_urgent": len(other), "false_alarms": len(false_alarms),
        "missed_ids": [item["id"] for item in urgent if not item["flagged"]],
        "false_alarm_ids": [item["id"] for item in false_alarms],
    }


def corpus_rate() -> dict:
    csv.field_size_limit(10**8)
    with open(CORPUS, encoding="utf-8", newline="") as file:
        questions = [row["qa.input"] for row in csv.DictReader(file)]
    flagged = sum(bool(detect_urgent_sign(question)) for question in questions)
    return {"questions": len(questions), "flagged": flagged, "rate": round(flagged / len(questions), 4)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="current")
    args = parser.parse_args()
    items = json.loads(DATA.read_text(encoding="utf-8"))["items"]
    for item in items:
        item["flagged"] = bool(detect_urgent_sign(item["question"]))
    summary = {split: score([item for item in items if item["split"] == split]) for split in ("dev", "holdout")}
    summary["all"] = score(items)
    missed = Counter(item["category"] for item in items if item["urgent"] and not item["flagged"])
    alarms = Counter(item["category"] for item in items if not item["urgent"] and item["flagged"])
    summary["missed_by_category"] = dict(missed.most_common())
    summary["false_alarms_by_category"] = dict(alarms.most_common())
    summary["corpus"] = corpus_rate()
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for item in items:
        if item["flagged"] != item["urgent"]:
            print("MISS" if item["urgent"] else "FALSE", item["id"], item["split"], item["question"])
    out = PROJECT_DIR / "output" / "experiments" / f"emergency_{args.label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "items": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
