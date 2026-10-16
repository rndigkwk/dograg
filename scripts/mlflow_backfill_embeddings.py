"""Put the earlier health-embedding comparisons on MLflow (DagsHub) as baselines (2026-10-16).

    uv run --group tools python scripts/mlflow_backfill_embeddings.py --dry-run   # what it would log
    uv run --group tools python scripts/mlflow_backfill_embeddings.py

The comparisons of 2026-10-09 to 10-13 (docs/wiki/embedding-finetune.md) were saved only as JSON in
output/experiments/. Each becomes one parent run in the experiment health-embedding, with one child
run per system and the same metric names as scripts/compare_kure.py (hybrid_useful3_all, ...), so the
KURE-v1 fine-tuning result can be read next to them. No model calls: the numbers are read from the
files, which are attached to the runs. A comparison already logged (tag baseline) is skipped.
Question sets: short = 120 short questions, long = 100 long consultations, all = the 220 together;
the 2026-10-09 fine-tuning run also has hit@3 on 561 long consultations.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
EXPERIMENTS = PROJECT_DIR / "output" / "experiments"
EXPERIMENT = "health-embedding"


def ko_sroberta_finetune(data: dict) -> dict[str, dict]:
    """2026-10-09: the base ko-sroberta and fine-tuned A (detailed) and B (short + detailed), hybrid."""
    systems = {}
    for variant, name in (("base", "ko-sroberta base"), ("a", "ko-sroberta ft-a"), ("b", "ko-sroberta ft-b (app)")):
        metrics = {"hybrid_useful3_short": data["short"][variant]["useful@3"],
                   "hybrid_useful3_long": data["long_useful"][variant]["useful@3"],
                   "hybrid_relevant3_short": data["short"][variant]["relevant@3"],
                   "hybrid_relevant3_long": data["long_useful"][variant]["relevant@3"],
                   "hybrid_hit3_long561": data["long_hit@3"][variant]}
        # The 220 together, weighted like compare_kure.py's "all" (120 short + 100 long).
        metrics["hybrid_useful3_all"] = round((metrics["hybrid_useful3_short"] * 120 + metrics["hybrid_useful3_long"] * 100) / 220, 3)
        if variant != "base":
            metrics.update({"hybrid_p_short": data["short_useful_vs_base"][variant]["p"],
                            "hybrid_p_long": data["long_useful_useful_vs_base"][variant]["p"],
                            "hybrid_p_hit3_long561": data["long_hit@3_vs_base"][variant]["p"]})
        systems[name] = metrics
    return systems


def from_useful(data: dict, names: dict[str, str], extra=None) -> dict[str, dict]:
    from mlflow_tracking import system_metrics

    systems = {}
    for key, name in names.items():
        metrics = {**system_metrics(data["useful@3"], "dense", key), **system_metrics(data["useful@3"], "hybrid", key)}
        if extra:
            metrics.update(extra(key))
        systems[name] = metrics
    return systems


def base_models(data: dict) -> dict[str, dict]:
    def extra(key):
        model = data["models"][key]
        return {"query_ms_p50": model["query_ms_p50"], "dimension": model["dimension"],
                "max_tokens": model["max_tokens"], "cut_share": model["cut_share"]}
    return from_useful(data, {"ko-sroberta": "ko-sroberta base", "e5-small": "multilingual-e5-small base"}, extra)


def kure_v1(data: dict) -> dict[str, dict]:
    return from_useful(data, {"app": "ko-sroberta ft-b (app)", "kure": "kure-v1 base"},
                       lambda key: {"query_ms_p50": data["query_ms_p50"][key]})


def doc_lengths(data: dict) -> dict[str, dict]:
    keys = sorted({name.rsplit(" ", 1)[0] for name in data["useful@3"]})
    return from_useful(data, {key: f"app model, documents {key}" for key in keys})


COMPARISONS = [
    {"key": "2026-10-09-ko-sroberta-finetune", "file": "finetuned_embedding.json", "build": ko_sroberta_finetune,
     "title": "2026-10-09 ko-sroberta fine-tuning A/B", "reference": "ko-sroberta base",
     "note": "useful@3 graded by the judge, hybrid path; B became the app model"},
    {"key": "2026-10-13-base-models", "file": "base_embeddings.json", "build": base_models,
     "title": "2026-10-13 base models (no fine-tuning)", "reference": "ko-sroberta base",
     "note": "p values: McNemar against ko-sroberta base"},
    {"key": "2026-10-13-kure-v1", "file": "kure_v1.json", "build": kure_v1,
     "title": "2026-10-13 KURE-v1 vs app", "reference": "ko-sroberta ft-b (app)",
     "note": "KURE-v1 not fine-tuned; p values: McNemar against the app"},
    {"key": "2026-10-13-doc-lengths", "file": "doc_lengths.json", "build": doc_lengths,
     "title": "2026-10-13 document length (app model)", "reference": "app model, documents len128",
     "note": "documents cut at 128/256/512 tokens or split into 128-token chunks; q = question at the same length"},
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--local", action="store_true", help="output/mlflow.db instead of DagsHub")
    args = parser.parse_args(argv)
    plans = []
    for comparison in COMPARISONS:
        path = EXPERIMENTS / comparison["file"]
        if not path.exists():
            print("missing, skipped:", path.name)
            continue
        systems = comparison["build"](json.loads(path.read_text(encoding="utf-8")))
        plans.append((comparison, path, systems))
        print(f"{comparison['title']}: {len(systems)} systems")
        for name, metrics in systems.items():
            print(f"  {name}: " + ", ".join(f"{k}={v}" for k, v in sorted(metrics.items()) if "useful3_all" in k or "hit3" in k))
    if args.dry_run:
        return 0

    import mlflow
    from mlflow_tracking import configure, log_comparison

    mlflow.set_tracking_uri(configure(args.local))
    experiment = mlflow.get_experiment_by_name(EXPERIMENT)
    done = set()
    if experiment is not None:
        runs = mlflow.search_runs([experiment.experiment_id], filter_string="tags.baseline != ''", output_format="list")
        done = {run.data.tags.get("baseline") for run in runs}
    for comparison, path, systems in plans:
        if comparison["key"] in done:
            print("already logged:", comparison["title"])
            continue
        run_id = log_comparison(
            EXPERIMENT, comparison["title"], systems, local=args.local, artifact=path,
            params={"questions": "short 120, long 100, all 220", "reference": comparison["reference"],
                    "date": comparison["key"][:10]},
            tags={"baseline": comparison["key"], "source": f"output/experiments/{comparison['file']}",
                  "note": comparison["note"], "script": "scripts/mlflow_backfill_embeddings.py"})
        print("logged:", comparison["title"], run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
