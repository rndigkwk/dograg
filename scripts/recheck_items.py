"""Run again the stable questions a gated run failed, to tell a regression from a judge's wobble.

    uv run python scripts/recheck_items.py crag ci-2026-10-20 [--repeats 2]

scripts/check_regression.py writes the stable questions a run failed to
output/experiments/<set>_<run>_regressed.json. This asks each of them again (--repeats times, the
app's real path: the router, the evidence grader, the answer) and saves the verdicts to
<set>_<run>_recheck.json, which check_regression.py reads: a question that passes every recheck
counted as a wobble, one that fails again as a regression.

Why: the baseline calls a question stable when it passed all three baseline runs, yet the evidence
grader's own verdict wobbles. On #218 two runs of unchanged code each failed one different stable
question (r20, then u20), which passed when asked again. A real regression fails again.
The guide set has no stable questions: there check_regression.py lists the questions a rate below
its limit missed (RECHECKED_RATES), and one that passes every recheck counts toward the rate.
Costs: a crag or guide question is one chat run (2-4 model calls); a routing question at most one
call; a guard question one chat run and one judge call.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

RESULTS_DIR = PROJECT_DIR / "output" / "experiments"
QUESTION_FILES = {"crag": PROJECT_DIR / "tests" / "data" / "crag_eval_questions.json",
                  "routing": PROJECT_DIR / "tests" / "data" / "place_routing_questions.json",
                  "guard": PROJECT_DIR / "tests" / "data" / "guardrail_questions.json",
                  "guide": PROJECT_DIR / "tests" / "data" / "care_guide_questions.json"}
_GUARD_RUNNER = []  # the app and its judge, loaded once for the guard set


def passes(set_name: str, item: dict) -> bool:
    """One run of the app on one question, scored as scripts/langfuse_experiments.py scores it."""
    if set_name == "guard":  # scripts/evaluate_guardrails.py: the judge and the rule checks
        import evaluate_guardrails

        if not _GUARD_RUNNER:
            _GUARD_RUNNER.append(evaluate_guardrails.load_runner())
        return evaluate_guardrails.run_item(_GUARD_RUNNER[0], item)["ok"]
    if set_name in ("crag", "guide"):
        from evaluate_crag import outcome

        from src.chatbot import chatbot

        result = chatbot(item["question"], crag=True, crag_reports=False)
        got = outcome(result, result.get("decision"))
        if set_name == "guide":  # answered and with a guide (guide_task in scripts/langfuse_experiments.py)
            return got in ("answer", "partial") and any(row.get("kind") == "care_guide" for row in result.get("evidence_rows", []))
        return got == "abstain" if item["expected"] == "abstain" else got in ("answer", "partial")
    from src.tools import places, router

    if router.classify_question(item["question"]) != item["route"]:
        return False
    return item["route"] != "sql" or places.place_kind(item["question"]) == item["kind"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("set", choices=tuple(QUESTION_FILES))
    parser.add_argument("run")
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args(argv)
    regressed_path = RESULTS_DIR / f"{args.set}_{args.run}_regressed.json"
    if not regressed_path.exists():
        print(f"{args.set}: no failed stable question to recheck")
        return 0
    ids = json.loads(regressed_path.read_text(encoding="utf-8"))
    items = {item["id"]: item for item in json.loads(QUESTION_FILES[args.set].read_text(encoding="utf-8"))["items"]}
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from src import resources

    verdicts = {}
    with tempfile.TemporaryDirectory(prefix="ragdog-recheck-", ignore_cleanup_errors=True) as directory:
        resources.CHROMA_DIR = Path(directory) / "chroma_db"  # Chroma writes to its folder even when reading
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", resources.CHROMA_DIR)
        for question_id in ids:
            verdicts[question_id] = [passes(args.set, items[question_id]) for _ in range(args.repeats)]
            print(f"{args.set} {question_id}: {verdicts[question_id]}", flush=True)
    (RESULTS_DIR / f"{args.set}_{args.run}_recheck.json").write_text(json.dumps(verdicts), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
