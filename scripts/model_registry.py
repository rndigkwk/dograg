"""The health embedding model's path from evaluation to the app: gate -> registry -> promotion.

    uv run --group tools python scripts/model_registry.py register --report output/experiments/finetuned_embedding_short2.json \
        --candidate gist-s13-e3 --repo blanden77/ko-sroberta-dograg-gist --revision f0c2ab5... --subfolder gist-s13-e3
    uv run --group tools python scripts/model_registry.py promote 3        # alias champion -> version 3
    uv run --group tools python scripts/model_registry.py status
    python scripts/model_registry.py check                                 # the app's model is the champion?

1. Gate. A candidate is judged on the report of scripts/evaluate_finetuned_embedding.py against the
   app's model "b", by the rule written before the GIST runs (docs/wiki/embedding-finetune.md): on
   the short-question sets (holdout splits, summed) McNemar p < 0.05 with more gained than lost,
   and the long consultations' useful@3 not below b. No model calls: the report already holds the
   judged hits.
2. Registry. Every candidate becomes a version of the MLflow registered model RAGDOG_MODEL on
   DagsHub (scripts/mlflow_tracking.py), passed or not, with the gate's numbers as tags and the report
   as an artifact. The weights stay in their private Hugging Face repo; the version holds a pointer
   (repo, commit, subfolder), since AI Hub-derived weights may not be copied elsewhere.
3. Promotion. Only a version whose gate passed can take the alias "champion" (the one before keeps
   "previous"). The app does not read the registry at run time: swapping the model also means new
   document vectors (Chroma and Supabase), so it is a pull request that changes src/resources.py and
   the vectors together, and that the PR quality gate and the canary deploy check. `check` runs in the
   deploy workflow and stops a deploy whose src/resources.py points at a model that is not the
   champion. If DagsHub cannot be reached it warns and lets the deploy go on (--strict fails instead).
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import math
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

RAGDOG_MODEL = "ragdog-health-embedding"
REFERENCE = "b"
SHORT_SETS = ("short", "short2")  # the human-written short questions (holdout splits)
LONG_SET = "long_useful"
P_LIMIT = 0.05
RESOURCES = PROJECT_DIR / "src" / "resources.py"


def mcnemar(gained: int, lost: int) -> float:
    """Exact two-sided McNemar: a binomial test on the discordant pairs. Disjoint sets can be summed."""
    n = gained + lost
    if not n:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(gained, lost) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def gate(report: dict, candidate: str) -> dict:
    """The adoption rule on one evaluation report. Returns the numbers and passed True/False."""
    gained = lost = 0
    used = []
    for name in SHORT_SETS:
        versus = (report.get(f"{name}_useful_vs_b") or {}).get(candidate)
        if versus:
            gained, lost = gained + versus["gained"], lost + versus["lost"]
            used.append(name)
    if not used:
        raise SystemExit(f"the report has no short set compared with {REFERENCE} for {candidate}")
    p = mcnemar(gained, lost)
    long = report.get(LONG_SET) or {}
    long_candidate = (long.get(candidate) or {}).get("useful@3")
    long_reference = (long.get(REFERENCE) or {}).get("useful@3")
    if long_candidate is None or long_reference is None:
        raise SystemExit(f"the report has no {LONG_SET} useful@3 for {candidate} and {REFERENCE}")
    checks = {"short_p_below_limit": p < P_LIMIT, "short_more_gained": gained > lost,
              "long_not_below_reference": long_candidate >= long_reference}
    return {"short_sets": "+".join(used), "short_gained": gained, "short_lost": lost, "short_p": round(p, 4),
            "long_useful3": long_candidate, "long_useful3_reference": long_reference, **checks,
            "passed": all(checks.values())}


def app_model(path: Path = RESOURCES) -> tuple[str, str]:
    """The model repo and commit src/resources.py ships, read as text (no heavy imports)."""
    text = path.read_text(encoding="utf-8")
    repo = re.search(r'^HEALTH_EMBEDDING_MODEL_NAME = "([^"]+)"', text, re.MULTILINE)
    revision = re.search(r'^HEALTH_EMBEDDING_REVISION = "([^"]+)"', text, re.MULTILINE)
    if not (repo and revision):
        raise SystemExit(f"no HEALTH_EMBEDDING_MODEL_NAME / HEALTH_EMBEDDING_REVISION in {path}")
    return repo.group(1), revision.group(1)


def matches(tags: dict, repo: str, revision: str) -> bool:
    return tags.get("hf_repo") == repo and tags.get("hf_revision") == revision and not tags.get("subfolder")


# --- registry (MLflow on DagsHub) ---------------------------------------------------------------

def client():
    import mlflow_tracking

    mlflow_tracking.configure()
    from mlflow import MlflowClient

    return MlflowClient()


def register(args) -> int:
    import mlflow
    from mlflow_tracking import start_run

    if args.reference:
        result = {"passed": None}
        status = "reference"
    else:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        result = gate(report, args.candidate)
        status = "passed" if result["passed"] else "failed"
    pointer = {"hf_repo": args.repo, "hf_revision": args.revision, "subfolder": args.subfolder or "",
               "onnx_file": args.onnx or "", "candidate": args.candidate}
    tracking = client()
    with start_run("health-embedding-registry", f"register {args.candidate}",
                   tags={"script": "scripts/model_registry.py", "gate": status}) as run:
        mlflow.log_params({k: v for k, v in pointer.items() if v})
        mlflow.log_metrics({k: float(v) for k, v in result.items() if isinstance(v, (int, float)) and not isinstance(v, bool)})
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "pointer.json").write_text(json.dumps(pointer, indent=1), encoding="utf-8")
            (Path(folder) / "gate.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
            mlflow.log_artifacts(folder, "pointer")
        if args.report:
            mlflow.log_artifact(str(args.report), "report")
        source = f"{run.info.artifact_uri}/pointer"
        run_id = run.info.run_id
    try:
        tracking.create_registered_model(RAGDOG_MODEL, description="Health question embedding for the RagDog app "
                                         "(pointers to private Hugging Face repos; scripts/model_registry.py)")
    except Exception as error:
        if "RESOURCE_ALREADY_EXISTS" not in str(error) and "already exists" not in str(error):
            raise
    tags = {**{k: v for k, v in pointer.items() if v}, "gate": status,
            **{f"gate.{k}": str(v) for k, v in result.items() if k != "passed"}}
    version = tracking.create_model_version(RAGDOG_MODEL, source, run_id=run_id, tags=tags,
                                            description=args.note or "")
    print(f"{RAGDOG_MODEL} version {version.version}: gate {status} {json.dumps(result, ensure_ascii=False)}")
    return 0


def promote(args) -> int:
    tracking = client()
    version = tracking.get_model_version(RAGDOG_MODEL, str(args.version))
    status = version.tags.get("gate")
    try:
        current = tracking.get_model_version_by_alias(RAGDOG_MODEL, "champion")
    except Exception:  # noqa: BLE001 - no champion yet
        current = None
    if status != "passed" and not (status == "reference" and current is None):
        raise SystemExit(f"version {args.version}: gate {status}; only a version that passed can be champion "
                         "(a reference only when there is no champion yet)")
    if current and current.version == version.version:
        print(f"version {version.version} is already champion")
        return 0
    if current:
        tracking.set_registered_model_alias(RAGDOG_MODEL, "previous", current.version)
    tracking.set_registered_model_alias(RAGDOG_MODEL, "champion", version.version)
    print(f"champion: version {version.version} ({version.tags.get('hf_repo')}@{version.tags.get('hf_revision', '')[:7]}"
          f"{'/' + version.tags['subfolder'] if version.tags.get('subfolder') else ''})"
          + (f", previous: version {current.version}" if current else ""))
    repo, revision = app_model()
    if not matches(version.tags, repo, revision):
        print("next: a pull request that points src/resources.py at this model and rebuilds the document vectors "
              "(scripts/rebuild_health_collection.py, Supabase); the deploy stops until they match")
    return 0


def status(args) -> int:
    tracking = client()
    aliases = {}
    for name in ("champion", "previous"):
        with contextlib.suppress(Exception):  # an alias not set yet
            aliases[tracking.get_model_version_by_alias(RAGDOG_MODEL, name).version] = name
    for version in sorted(tracking.search_model_versions(f"name='{RAGDOG_MODEL}'"), key=lambda v: int(v.version)):
        t = version.tags
        print(f"v{version.version:<3} {aliases.get(version.version, ''):<9} gate {t.get('gate', '-'):<9} "
              f"{t.get('candidate', '-'):<14} {t.get('hf_repo')}@{t.get('hf_revision', '')[:7]} "
              f"short {t.get('gate.short_gained', '-')}/{t.get('gate.short_lost', '-')} p {t.get('gate.short_p', '-')} "
              f"long {t.get('gate.long_useful3', '-')} vs {t.get('gate.long_useful3_reference', '-')}")
    return 0


def champion_tags(uri: str, user: str, token: str) -> dict:
    """The champion's tags over MLflow's REST API: the standard library only, for the deploy job."""
    query = urllib.parse.urlencode({"name": RAGDOG_MODEL, "alias": "champion"})
    auth = base64.b64encode(f"{user}:{token}".encode()).decode()
    request = urllib.request.Request(f"{uri}/api/2.0/mlflow/registered-models/alias?{query}",
                                     headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        version = json.loads(response.read())["model_version"]
    return {tag["key"]: tag["value"] for tag in version.get("tags", [])} | {"version": version["version"]}


def check(args) -> int:
    from mlflow_tracking import TRACKING_URI, USERNAME

    repo, revision = app_model()
    token = os.environ.get("DAGSHUB_TOKEN") or os.environ.get("MLFLOW_TRACKING_PASSWORD")
    if not token:  # locally: `dagshub` in .env (src/settings.py needs python-dotenv, the deploy job has none)
        from src import settings

        token = settings.get_setting("dagshub")
    try:
        if not token:
            raise OSError("no DagsHub token")
        tags = champion_tags(os.environ.get("MLFLOW_TRACKING_URI", TRACKING_URI), USERNAME, token.strip())
    except (OSError, urllib.error.URLError, KeyError, ValueError) as error:
        print(f"registry not read ({type(error).__name__}): {repo}@{revision[:7]} not checked")
        return 1 if args.strict else 0
    if matches(tags, repo, revision):
        print(f"src/resources.py ships the champion, {RAGDOG_MODEL} version {tags['version']} ({repo}@{revision[:7]})")
        return 0
    print(f"src/resources.py ships {repo}@{revision[:7]}, but the champion is version {tags['version']} "
          f"({tags.get('hf_repo')}@{tags.get('hf_revision', '')[:7]}{'/' + tags['subfolder'] if tags.get('subfolder') else ''}). "
          "Promote the shipped model or point the code at the champion (scripts/model_registry.py).")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("register", help="gate a candidate and add it to the registry")
    add.add_argument("--report", type=Path, help="scripts/evaluate_finetuned_embedding.py output")
    add.add_argument("--candidate", required=True, help="the candidate's name in the report (or the reference's)")
    add.add_argument("--repo", required=True)
    add.add_argument("--revision", required=True, help="the model repo's commit")
    add.add_argument("--subfolder", help="the checkpoint folder in the repo, if any")
    add.add_argument("--onnx", help="the int8 ONNX file the app loads, once exported")
    add.add_argument("--reference", action="store_true", help="the model the app ships now: no gate")
    add.add_argument("--note", help="the version's description")
    move = commands.add_parser("promote", help="make a version that passed the champion")
    move.add_argument("version", type=int)
    commands.add_parser("status", help="list the versions")
    verify = commands.add_parser("check", help="does src/resources.py ship the champion?")
    verify.add_argument("--strict", action="store_true", help="fail when the registry cannot be read")
    args = parser.parse_args(argv)
    if args.command == "register" and not args.reference and not args.report:
        parser.error("register needs --report, or --reference for the model the app ships")
    return {"register": register, "promote": promote, "status": status, "check": check}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
