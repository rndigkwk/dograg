"""Copy a weekly regression run to MLflow on DagsHub (2026-10-17, Day 61), next to ragdog_eval_history.

    python scripts/log_regression_mlflow.py ci-2026-10-19-abc1234 crag routing visit answer

Reads the saved results (output/experiments/<set>_<run>.json, as scripts/check_regression.py does)
and logs one parent run per weekly run in the experiment "regression-weekly", with one child per
set: its run scores as metrics, passed (1/0) against the same limits, the judge model, the commit.
The MLflow charts then show each score week by week; Supabase (eval_history) stays the record the
checks read. No model calls. Without a DagsHub token (DAGSHUB_TOKEN) it says so and exits 0, and a
failed upload never fails the workflow: the regression check is check_regression.py's job.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_regression  # noqa: E402

EXPERIMENT = "regression-weekly"


def set_metrics(set_name: str, run_name: str) -> tuple[dict, dict] | None:
    """(metrics, params) for one set, or None when its result file is missing (a step failed)."""
    if not (check_regression.RESULTS_DIR / f"{set_name}_{run_name}.json").exists():
        return None
    _, ok, result = check_regression.check(set_name, run_name)
    metrics = {key: float(value) for key, value in result["run_scores"].items() if isinstance(value, (int, float))}
    metrics["passed"] = 1.0 if ok else 0.0
    params = {"set": set_name, "judge_model": result.get("judge_model") or "-", "items": len(result.get("items", []))}
    prompts = result.get("prompts")  # src/prompt_versions.py: the digest, and each prompt's hash
    if prompts:
        params |= {"prompts": prompts["digest"], **{f"prompt.{k}": v for k, v in prompts["versions"].items()}}
    return metrics, params


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    run_name, sets = argv[0], argv[1:]
    if not (os.environ.get("DAGSHUB_TOKEN") or os.environ.get("MLFLOW_TRACKING_PASSWORD")):
        print("MLflow: no DAGSHUB_TOKEN secret, skipped")
        return 0
    found = {name: values for name in sets if (values := set_metrics(name, run_name))}
    if not found:
        print("MLflow: no result files, skipped")
        return 0
    try:
        import mlflow
        from mlflow_tracking import start_run

        commit = os.environ.get("GITHUB_SHA", "")[:7]
        tags = {"run": run_name, "commit": commit, "trigger": os.environ.get("GITHUB_EVENT_NAME", "local"),
                "script": "scripts/log_regression_mlflow.py"}
        with start_run(EXPERIMENT, run_name, tags=tags) as parent:
            mlflow.log_metric("passed", float(all(m["passed"] for m, _ in found.values())))
            for name, (metrics, params) in found.items():
                with mlflow.start_run(run_name=name, nested=True, tags={**tags, "set": name}):
                    mlflow.log_params(params)
                    mlflow.log_metrics(metrics)
        print(f"MLflow: logged {', '.join(found)} as run {parent.info.run_id}")
    except Exception as error:  # noqa: BLE001 - the history copy must never fail the regression job
        print(f"MLflow: not logged ({type(error).__name__}: {error})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
