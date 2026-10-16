"""Log experiments to the project's MLflow server on DagsHub (2026-10-16, docs/wiki/lecture-review.md Day 61).

    from mlflow_tracking import start_run
    with start_run("health-embedding", "kure-v1-ft compare") as run:
        mlflow.log_metric("useful3_all", 0.81)

Server: https://dagshub.com/rndigkwk/dograg.mlflow (user rndigkwk). The password is a DagsHub
token: MLFLOW_TRACKING_PASSWORD, or `dagshub` in .env (the name it was saved under). Nothing is
printed about it. --local logs to output/mlflow.db (artifacts in output/mlartifacts) instead,
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
        token = os.environ.get("MLFLOW_TRACKING_PASSWORD") or settings.get_setting("dagshub")
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
