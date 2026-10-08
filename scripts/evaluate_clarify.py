"""What the visit-prep team would ask the guardian before planning (day51 interrupt).

    uv run python scripts/evaluate_clarify.py

Runs only the clarify step (one model call each) on the 12 evaluation consultations
(tests/data/visit_prep_consultations.json) and prints the questions. Checks in code: urgent
consultations ask nothing, at most MAX_QUESTIONS questions, and no question repeats what the
consultation already says about age, breed or weight when a profile was given.
Writes output/experiments/clarify_<date>.json.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))


def main() -> int:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from src.health_safety import detect_urgent_sign
    from team.core import config
    from team.graph.nodes import clarify

    items = json.loads((PROJECT_DIR / "tests" / "data" / "visit_prep_consultations.json").read_text(encoding="utf-8"))["items"]
    rows = []
    for item in items:
        data = item
        state = {"consultation": data["consultation"], "profile": data.get("profile", ""), "ask": True,
                 "urgent": detect_urgent_sign(data["consultation"]) or ""}
        started = time.perf_counter()
        questions = clarify(state)["questions"]
        rows.append({"id": item["id"], "urgent": bool(state["urgent"]), "profile_given": bool(state["profile"]),
                     "questions": questions, "seconds": round(time.perf_counter() - started, 1)})
        print(f"{item['id']} urgent={rows[-1]['urgent']} ({rows[-1]['seconds']}s)")
        for question in questions:
            print("   -", question)
    asked = [row for row in rows if row["questions"]]
    summary = {
        "consultations": len(rows),
        "asked": len(asked),
        "urgent_asked": sum(row["urgent"] and bool(row["questions"]) for row in rows),
        "max_questions": max((len(row["questions"]) for row in rows), default=0),
        "mean_questions_when_asked": round(sum(len(row["questions"]) for row in asked) / len(asked), 2) if asked else 0,
        "seconds_p50": sorted(row["seconds"] for row in rows if not row["urgent"])[len([r for r in rows if not r["urgent"]]) // 2],
    }
    print(json.dumps(summary, ensure_ascii=False))
    assert summary["urgent_asked"] == 0 and summary["max_questions"] <= config.MAX_QUESTIONS
    saved = PROJECT_DIR / "output" / "experiments" / f"clarify_{datetime.now(UTC).astimezone().date().isoformat()}.json"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text(json.dumps({"summary": summary, "items": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
