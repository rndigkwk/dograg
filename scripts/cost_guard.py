"""Before an evaluation calls the model many times: say how many, keep a daily count, and stop at a
threshold unless asked to go on (2026-10-15: one day of experiments was far above the usual use).

    from cost_guard import confirm
    if not confirm("judge_validation judge", calls=264, detail="relevance 3 x 48, answers 2 x 30", yes=args.yes):
        return 1

Prints the estimate and today's total so far (output/experiments/model_calls.jsonl, this machine
only). Up to THRESHOLD calls it goes on. Above it, it goes on with --yes, with RAGDOG_EVAL_YES=1, or
in CI (the workflows' runs are budgeted there: PR quality only for answer-path changes, the weekly
regression once a week); on a terminal it asks; otherwise it stops. The counts are estimates of model
calls (judge and answer calls), not tokens.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
LOG = PROJECT_DIR / "output" / "experiments" / "model_calls.jsonl"
THRESHOLD = 200


def today_total(day: date | None = None) -> int:
    day = (day or date.today()).isoformat()
    if not LOG.exists():
        return 0
    total = 0
    for line in LOG.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("at", "").startswith(day):
            total += int(row.get("calls", 0))
    return total


def _log(script: str, calls: int) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as file:
        file.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "script": script, "calls": calls},
                              ensure_ascii=False) + "\n")


def confirm(script: str, calls: int, detail: str = "", yes: bool = False) -> bool:
    """True when the run may go on (and is logged); False to stop."""
    calls = int(calls)
    print(f"[모델 호출 예상] {script}: 약 {calls}번{f' ({detail})' if detail else ''} · 오늘 실험 누계 {today_total()}번",
          flush=True)
    go = calls <= THRESHOLD or yes or os.environ.get("RAGDOG_EVAL_YES") == "1" or os.environ.get("CI") == "true"
    if not go and sys.stdin is not None and sys.stdin.isatty():
        try:
            go = input(f"{THRESHOLD}번을 넘습니다. 계속할까요? [y/N] ").strip().lower() == "y"
        except EOFError:  # no one to answer (Windows reports NUL as a terminal)
            go = False
    if not go:
        print(f"{THRESHOLD}번을 넘어 멈춥니다. 계속하려면 --yes를 붙이세요.", flush=True)
        return False
    _log(script, calls)
    return True
