"""The model's crisis check (src/crisis.py) alone: what it catches and what it wrongly flags.

    uv run python scripts/evaluate_crisis_check.py [--sample 200] [--yes]

Should flag: every crisis question of the red team sets (tests/data/guardrail_questions.json, written
by us; _claude.json and _claude2.json, written by Claude). Should not flag: every other question of
those sets (look-alikes, attacks, benign questions) and --sample guardians' questions from the
consultations (data/df.csv, seed 22), which stand for ordinary traffic. One model call each.
Prints recall, the false flags with their text, and the call's seconds (it runs while the graph
answers, so only a check slower than the answer adds time). Results: output/experiments/crisis_check.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

SETS = ("guardrail_questions.json", "guardrail_questions_claude.json", "guardrail_questions_claude2.json")


def cases(sample: int) -> list[dict]:
    rows = []
    for name in SETS:
        for item in json.loads((PROJECT_DIR / "tests" / "data" / name).read_text(encoding="utf-8"))["items"]:
            rows.append({"id": item["id"], "source": name, "category": item["category"], "question": item["question"],
                         "history": item.get("history"), "crisis": item["category"] == "crisis"})
    csv.field_size_limit(10**8)
    with open(PROJECT_DIR / "data" / "df.csv", encoding="utf-8", newline="") as f:
        questions = [row["qa.input"] for row in csv.DictReader(f)]
    for i, question in enumerate(random.Random(22).sample(questions, sample)):
        rows.append({"id": f"consult-{i}", "source": "df.csv", "category": "consultation", "question": question,
                     "history": None, "crisis": False})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sample", type=int, default=200)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    from dotenv import load_dotenv

    load_dotenv(PROJECT_DIR / ".env")
    from cost_guard import confirm

    from src import crisis, guardrails

    rows = cases(args.sample)
    if not confirm("evaluate_crisis_check", len(rows), "one check per question", args.yes):
        return 1

    def check(row):
        started = time.perf_counter()
        try:
            flagged = crisis.judge(row["question"], row["history"])
        except Exception as exc:  # noqa: BLE001 - recorded, not fatal
            return {**row, "flagged": None, "error": type(exc).__name__, "seconds": round(time.perf_counter() - started, 2)}
        return {**row, "flagged": flagged, "rule": guardrails.is_crisis(row["question"]),
                "seconds": round(time.perf_counter() - started, 2)}

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(check, rows))
    positives = [r for r in results if r["crisis"]]
    negatives = [r for r in results if not r["crisis"]]
    seconds = sorted(r["seconds"] for r in results)
    summary = {
        "caught": f"{sum(r['flagged'] is True for r in positives)}/{len(positives)}",
        "caught_by_rule": f"{sum(r.get('rule') is True for r in positives)}/{len(positives)}",
        "false_flags": f"{sum(r['flagged'] is True for r in negatives)}/{len(negatives)}",
        "false_flags_by_source": {s: sum(r["flagged"] is True for r in negatives if r["source"] == s)
                                  for s in sorted({r["source"] for r in negatives})},
        "errors": sum(r["flagged"] is None for r in results),
        "seconds_p50": seconds[len(seconds) // 2], "seconds_p90": seconds[int(0.9 * (len(seconds) - 1))],
        "missed": [r["id"] for r in positives if r["flagged"] is not True],
        "false_flagged": [{"id": r["id"], "category": r["category"], "question": r["question"][:120]}
                          for r in negatives if r["flagged"] is True],
    }
    out = PROJECT_DIR / "output" / "experiments" / "crisis_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
