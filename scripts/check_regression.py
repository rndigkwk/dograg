"""Compare saved experiment results (output/experiments/<set>_<run>.json) with fixed limits.

    uv run python scripts/check_regression.py crag ci-2026-10-12 routing ci-2026-10-12 visit ci-2026-10-12

Prints a Markdown table (appended to $GITHUB_STEP_SUMMARY when set) and exits 1 when any
score crosses its limit. Limits sit a little below the merged results (docs/wiki/observability.md)
so model-call noise does not fail the job, but a real drop does.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_DIR / "output" / "experiments"

# (score, "min" or "max", limit, merged result for reference)
LIMITS = {
    "crag": [
        ("accuracy", "min", 0.85, 0.900),
        ("over_abstain", "max", 0.10, 0.026),
        ("missed_abstain", "max", 0.35, 0.227),
        ("latency_p90_s", "max", 25.0, 12.6),
    ],
    "routing": [
        ("route_accuracy", "min", 0.94, 1.0),
        ("kind_accuracy", "min", 1.0, 1.0),
    ],
    # Visit-prep team (12 consultations). repeat_suspect_rate is the share of runs where a worker
    # ran more often than a normal run needs (team/core/config.py VISIT_LIMITS): loops show up
    # here before they reach the hard stops.
    "visit": [
        ("dog_pass_rate", "min", 0.8, 1.0),
        ("scope_handled_rate", "min", 0.83, 1.0),
        ("urgent_accuracy", "min", 1.0, 1.0),
        ("hospitals_listed_rate", "min", 0.88, 1.0),
        ("repeat_suspect_rate", "max", 0.34, 0.167),
        ("latency_p90_s", "max", 120.0, 65.5),
        # Researchers that ended without an answer (API "incomplete" responses, 2026-10-10): asked
        # once more (reask) and, if still nothing, recorded as NoAnswer and replaced by the guide.
        # 0 in the merged runs; a model or API change that makes it common fails here first.
        ("reask_rate", "max", 0.25, 0.0),
        ("no_answer_rate", "max", 0.09, 0.0),
    ],
}


def check(set_name: str, run_name: str) -> tuple[list[str], bool]:
    path = RESULTS_DIR / f"{set_name}_{run_name}.json"
    scores = json.loads(path.read_text(encoding="utf-8"))["run_scores"]
    rows, ok = [], True
    for name, direction, limit, reference in LIMITS[set_name]:
        value = scores.get(name)
        passed = value is not None and (value >= limit if direction == "min" else value <= limit)
        ok &= passed
        sign = "≥" if direction == "min" else "≤"
        shown = "없음" if value is None else f"{value:.3f}"
        rows.append(f"| {set_name} | {name} | {shown} | {sign} {limit} | {reference} | {'✅' if passed else '❌'} |")
    return rows, ok


def main(argv: list[str]) -> int:
    if not argv or len(argv) % 2:
        print(__doc__)
        return 2
    lines = ["| 평가 세트 | 지표 | 이번 실행 | 기준 | 병합 시 결과 | 판정 |", "| --- | --- | ---: | --- | ---: | :---: |"]
    all_ok = True
    for set_name, run_name in zip(argv[::2], argv[1::2]):
        rows, ok = check(set_name, run_name)
        lines += rows
        all_ok &= ok
    table = "\n".join(lines)
    sys.stdout.reconfigure(errors="replace")  # ✅/❌ on a Windows console (cp949)
    print(table)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as file:
            file.write("## 정기 회귀 평가\n\n" + table + "\n")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
