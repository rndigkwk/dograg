"""Compare saved experiment results (output/experiments/<set>_<run>.json) with fixed limits.

    uv run python scripts/check_regression.py crag ci-2026-10-12 routing ci-2026-10-12 visit ci-2026-10-12 answer ci-2026-10-12
    uv run python scripts/check_regression.py --make-baseline crag base-1 base-2 base-3   # after a merge

A set with a baseline (tests/data/baselines/<set>.json: crag, routing) must pass four checks, which
the PR quality check requires before a pull request that changes the answer path merges:
1. completeness: the same question ids as the baseline, each with an output and its score (a
   question that raised an error has neither)
2. absolute floor: every score inside its fixed limit (LIMITS below)
3. relative floor: every quality score within its allowed drop (DROPS) of the baseline's mean
4. regression: every stable question (passed in every baseline run) passes again
A set without a baseline (visit, answer) gets check 2 only. The baseline is made from several runs
of the merged code (--make-baseline): one run moves by a question or two, so a question counts as
stable only when it passed every time.

Prints a Markdown table (appended to $GITHUB_STEP_SUMMARY when set) and exits 1 when any
score crosses its limit. Limits sit a little below the merged results (docs/wiki/observability.md)
so model-call noise does not fail the job, but a real drop does.

Scores are of two kinds (the "구분" column). Quality scores are what a change is judged by; each set
keeps them to a few strong ones (at most 5, as DeepEval and Ragas advise). Alarms are operational
checks (latency, loops, researchers without an answer): they also fail the job, because they catch
breakage, but they are not quality measures.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import eval_history

PROJECT_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = PROJECT_DIR / "output" / "experiments"
BASELINE_DIR = PROJECT_DIR / "tests" / "data" / "baselines"

# The judge each LLM-judged set's limits were measured with. Another judge scores on another scale
# (Day 60: re-measure the judge before trusting its numbers), so a run judged by another model fails
# until the limits are measured again with it.
JUDGES = {"answer": "gpt-6-luna"}

# (score, "min" or "max", limit, merged result for reference)
# Operational alarms; every other score is a quality score.
ALARMS = {"latency_p90_s", "repeat_suspect_rate", "reask_rate", "no_answer_rate"}
LIMITS = {
    "crag": [
        ("accuracy", "min", 0.85, 0.900),
        ("over_abstain", "max", 0.10, 0.026),
        ("missed_abstain", "max", 0.35, 0.227),
        ("latency_p90_s", "max", 25.0, 12.6),
    ],
    # Health answers against the vet's own answer (scripts/evaluate_answer_quality.py): measured
    # 0.273-0.285 over three judgings and two runs, judge noise 0.012; a broken route or prompt
    # halves it (0.14 on misrouted consultations).
    "answer": [
        ("answer_correctness", "min", 0.25, 0.28),
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


# The score an item passes on, per set with a baseline.
ITEM_SCORES = {"crag": ("correct_behavior",), "routing": ("route_correct",)}
# Allowed drop from the baseline's mean, quality scores only (alarms like latency stay absolute).
# About one question of 60 (crag) or of 41 (routing) on top of the run-to-run spread of the baseline.
DROPS = {
    "crag": {"accuracy": 0.05, "over_abstain": 0.05, "missed_abstain": 0.10},
    "routing": {"route_accuracy": 0.03, "kind_accuracy": 0.0},
}


def item_passed(set_name: str, item: dict) -> bool:
    scores = item.get("scores") or {}
    if any(scores.get(name) != 1.0 for name in ITEM_SCORES[set_name]):
        return False
    return set_name != "routing" or scores.get("kind_correct", 1.0) == 1.0


def item_complete(set_name: str, item: dict) -> bool:
    output, scores = item.get("output"), item.get("scores") or {}
    return isinstance(output, dict) and not output.get("error") and all(name in scores for name in ITEM_SCORES[set_name])


def load_baseline(set_name: str) -> dict | None:
    path = BASELINE_DIR / f"{set_name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def make_baseline(set_name: str, run_names: list[str]) -> dict:
    """From saved runs of the merged code: question ids, mean scores, and the questions that passed
    every run (stable). Ids and numbers only, no question text."""
    results = [json.loads((RESULTS_DIR / f"{set_name}_{run}.json").read_text(encoding="utf-8")) for run in run_names]
    ids = sorted({item["id"] for item in results[0]["items"]})
    for run, result in zip(run_names, results):
        if sorted(item["id"] for item in result["items"]) != ids:
            raise SystemExit(f"{run}: not the same questions as {run_names[0]}")
        if not all(item_complete(set_name, item) for item in result["items"]):
            raise SystemExit(f"{run}: a question without an output or a score; run it again")
    passes = {i: sum(item_passed(set_name, item) for r in results for item in r["items"] if item["id"] == i) for i in ids}
    names = sorted({name for r in results for name in r["run_scores"]})
    means = {name: round(sum(r["run_scores"][name] for r in results) / len(results), 4)
             for name in names if all(isinstance(r["run_scores"].get(name), (int, float)) for r in results)}
    baseline = {"set": set_name, "runs": run_names, "means": means,
                "spread": {name: [min(r["run_scores"][name] for r in results), max(r["run_scores"][name] for r in results)]
                           for name in means},
                "ids": ids, "passes": passes, "stable": [i for i in ids if passes[i] == len(results)]}
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    (BASELINE_DIR / f"{set_name}.json").write_text(json.dumps(baseline, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return baseline


def gate_rows(set_name: str, result: dict, baseline: dict) -> tuple[list[str], bool]:
    """Checks 1, 3 and 4 against the baseline (check 2 is the LIMITS rows)."""
    rows, ok = [], True
    items = {item["id"]: item for item in result.get("items") or [] if isinstance(item, dict) and "id" in item}
    missing = sorted(set(baseline["ids"]) - items.keys())
    extra = sorted(items.keys() - set(baseline["ids"]))
    broken = sorted(i for i, item in items.items() if not item_complete(set_name, item))
    complete = not (missing or extra or broken)
    detail = f"빠짐 {len(missing)}, 추가 {len(extra)}, 오류 {len(broken)}"
    if not complete:
        detail += " (" + ", ".join((missing + extra + broken)[:5]) + ")"
    rows.append(f"| {set_name} | 완전성 | 문항 {len(items)}/{len(baseline['ids'])} | {detail} | 기준선과 같음 | - | {'✅' if complete else '❌'} |")
    ok &= complete
    directions = {name: direction for name, direction, *_ in LIMITS[set_name]}
    for name, drop in DROPS.get(set_name, {}).items():
        value, base = result["run_scores"].get(name), baseline["means"].get(name)
        if base is None:
            continue
        if directions[name] == "min":
            limit, passed = round(base - drop, 4), value is not None and value >= base - drop - 1e-9
        else:
            limit, passed = round(base + drop, 4), value is not None and value <= base + drop + 1e-9
        sign = "≥" if directions[name] == "min" else "≤"
        shown = "없음" if value is None else f"{value:.3f}"
        rows.append(f"| {set_name} | 상대 | {name} | {shown} | {sign} {limit} (기준선 {base:.3f}) | {base:.3f} | {'✅' if passed else '❌'} |")
        ok &= passed
    regressed = sorted(i for i in baseline["stable"] if i in items and not item_passed(set_name, items[i]))
    rows.append(f"| {set_name} | 회귀 | 안정 문항 {len(baseline['stable'])} | 실패 {len(regressed)}"
                f"{' (' + ', '.join(regressed[:8]) + ')' if regressed else ''} | 0 | - | {'✅' if not regressed else '❌'} |")
    ok &= not regressed
    return rows, ok


def check(set_name: str, run_name: str) -> tuple[list[str], bool, dict]:
    path = RESULTS_DIR / f"{set_name}_{run_name}.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    scores = result["run_scores"]
    rows, ok = [], True
    if set_name in JUDGES and result.get("judge_model") != JUDGES[set_name]:
        rows.append(f"| {set_name} | 판사 | judge_model | {result.get('judge_model') or '기록 없음'} | = {JUDGES[set_name]} | "
                    f"{JUDGES[set_name]} | ❌ |")
        ok = False
    for name, direction, limit, reference in LIMITS[set_name]:
        value = scores.get(name)
        passed = value is not None and (value >= limit if direction == "min" else value <= limit)
        ok &= passed
        sign = "≥" if direction == "min" else "≤"
        shown = "없음" if value is None else f"{value:.3f}"
        kind = "경보" if name in ALARMS else "절대"
        rows.append(f"| {set_name} | {kind} | {name} | {shown} | {sign} {limit} | {reference} | {'✅' if passed else '❌'} |")
    baseline = load_baseline(set_name)
    if baseline is not None:
        gate, gate_ok = gate_rows(set_name, result, baseline)
        rows += gate
        ok &= gate_ok
    return rows, ok, result


def main(argv: list[str]) -> int:
    if argv[:1] == ["--make-baseline"] and len(argv) >= 3:
        baseline = make_baseline(argv[1], argv[2:])
        print(f"{argv[1]}: {len(baseline['ids'])} questions, stable {len(baseline['stable'])}, means {baseline['means']}")
        return 0
    if not argv or len(argv) % 2:
        print(__doc__)
        return 2
    lines = ["| 평가 세트 | 구분 | 지표 | 이번 실행 | 기준 | 병합 시 결과 | 판정 |", "| --- | --- | --- | ---: | --- | ---: | :---: |"]
    all_ok = True
    for set_name, run_name in zip(argv[::2], argv[1::2]):
        rows, ok, result = check(set_name, run_name)
        lines += rows
        metrics = dict(result["run_scores"])
        if result.get("judge_model"):
            metrics["judge_model"] = result["judge_model"]
        eval_history.record("regression", set_name, ok, metrics, run=run_name)  # only with SUPABASE_DB_URL
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
