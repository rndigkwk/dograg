"""Log experiments to the project's MLflow server on DagsHub (2026-10-16, docs/wiki/lecture-review.md Day 61).

    from mlflow_tracking import start_run
    with start_run("health-embedding", "kure-v1-ft compare") as run:
        mlflow.log_metric("useful3_all", 0.81)

Server: https://dagshub.com/rndigkwk/dograg.mlflow (user rndigkwk). The password is a DagsHub
token: MLFLOW_TRACKING_PASSWORD, DAGSHUB_TOKEN (GitHub Actions), or `dagshub` in .env (the name it
was saved under). Nothing is printed about it. --local logs to output/mlflow.db (artifacts in output/mlartifacts) instead,
for trying a script without the server.

    uv run --group tools python scripts/mlflow_tracking.py --check   # can we reach the server?
"""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

TRACKING_URI = "https://dagshub.com/rndigkwk/dograg.mlflow"
USERNAME = "rndigkwk"
LOCAL_URI = "sqlite:///" + (PROJECT_DIR / "output" / "mlflow.db").as_posix()  # MLflow 3: SQLite, not a folder
LOCAL_ARTIFACTS = (PROJECT_DIR / "output" / "mlartifacts").as_uri()
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")  # a note for coding agents printed on import


def configure(local: bool = False) -> str:
    """Point MLflow at DagsHub (or the local folder) and return the tracking URI."""
    from src import settings  # loads .env

    if local:
        os.environ["MLFLOW_TRACKING_URI"] = LOCAL_URI
        return LOCAL_URI
    os.environ.setdefault("MLFLOW_TRACKING_URI", TRACKING_URI)
    if os.environ["MLFLOW_TRACKING_URI"].startswith("https://dagshub.com/"):
        # MLFLOW_TRACKING_PASSWORD, DAGSHUB_TOKEN (the GitHub Actions secret) or `dagshub` in .env
        token = (os.environ.get("MLFLOW_TRACKING_PASSWORD") or os.environ.get("DAGSHUB_TOKEN")
                 or settings.get_setting("dagshub"))
        if not token:
            raise SystemExit("No DagsHub token: set MLFLOW_TRACKING_PASSWORD or `dagshub` in .env, or use --local.")
        os.environ.setdefault("MLFLOW_TRACKING_USERNAME", USERNAME)
        os.environ["MLFLOW_TRACKING_PASSWORD"] = token.strip()
    return os.environ["MLFLOW_TRACKING_URI"]


@contextmanager
def start_run(experiment: str, run_name: str, *, local: bool = False, tags: dict | None = None):
    import mlflow

    uri = configure(local)
    mlflow.set_tracking_uri(uri)
    if uri == LOCAL_URI and mlflow.get_experiment_by_name(experiment) is None:
        mlflow.create_experiment(experiment, artifact_location=LOCAL_ARTIFACTS)
    mlflow.set_experiment(experiment)
    with mlflow.start_run(run_name=run_name, tags=tags or {}) as run:
        yield run


def metric_key(name: str) -> str:
    return name.replace("@", "").replace(" ", "_").replace("-", "_")


def system_metrics(useful: dict, mode: str, system: str) -> dict[str, float]:
    """useful@3 per question set ("short", "long_useful", "all") and the p value against the reference,
    under one name in every comparison: e.g. hybrid_useful3_all, hybrid_p_short."""
    entry = useful.get(f"{system} {mode}", {})
    metrics = {f"{mode}_useful3_{s.replace('long_useful', 'long')}": v for s, v in entry.items() if isinstance(v, (int, float))}
    for key, values in entry.items():
        if key.startswith("vs_") and isinstance(values, dict):
            metrics.update({f"{mode}_p_{s.replace('long_useful', 'long')}": p for s, p in values.items()})
    return metrics


def log_comparison(experiment: str, name: str, systems: dict[str, dict], *, params: dict, tags: dict,
                   artifact: Path | None = None, local: bool = False) -> str:
    """One parent run per comparison and one child run per system with the same metric names, so the
    MLflow table shows, say, hybrid_useful3_all for the app, KURE-v1 and KURE-v1-ft side by side."""
    import mlflow

    with start_run(experiment, name, local=local, tags=tags) as parent:
        mlflow.log_params(params)
        if artifact is not None:
            mlflow.log_artifact(str(artifact))
        for system, metrics in systems.items():
            with mlflow.start_run(run_name=system, nested=True, tags={**tags, "system": system}):
                mlflow.log_params({"system": system, **params})
                mlflow.log_metrics(metrics)
        return parent.info.run_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="list the server's experiments")
    parser.add_argument("--local", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        import mlflow

        mlflow.set_tracking_uri(configure(args.local))
        for experiment in mlflow.search_experiments():
            print(experiment.experiment_id, experiment.name)
        print("reached", mlflow.get_tracking_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
