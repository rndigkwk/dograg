"""Train the health embedding again on a rented GPU: copies left out, a checkpoint per epoch, three seeds.

    python scripts/train_embedding_gpu.py --smoke --no-upload --local-mlflow   # a few steps, any machine
    python scripts/train_embedding_gpu.py                                      # the run (RunPod, 2026-11-02)
    python scripts/train_embedding_gpu.py --loss gist --seeds 13               # GISTEmbedLoss, guide B (2026-11-05)

The app's model B (2026-10-09, notebooks/finetune_embedding_colab.ipynb) was trained once, for one epoch,
and on the synthetic queries of 51 corpus posts that retell a validation question
(tests/data/finetune_excluded_posts.json). The overfit check (scripts/check_finetune_overfit.py) found no
leak, and left two things for the next training: leave the copies out, and keep a checkpoint per epoch.
This script does both, with the same settings otherwise (ko-sroberta-multitask, short + detailed queries,
MultipleNegativesRankingLoss with no duplicate posts in a batch, batch 64, lr 2e-5, 128 tokens) and
three seeds, so the spread between runs is measured too.

- Dev: the same 300 posts as before (random.Random(13) over the sorted ids), whatever the training seed.
  Their queries pick the epoch; the 220 hand-written questions are only for the final report, run
  locally by scripts/evaluate_finetuned_embedding.py --retrain (the judge grades new candidates there).
- Each epoch's model is saved with its 19,206 corpus vectors and uploaded to the private model repo
  <user>/ko-sroberta-dograg-b2 as one folder per checkpoint (s13-e1, ...), with results.json at the root.
- MLflow on DagsHub (scripts/mlflow_tracking.py): experiment health-embedding, one parent run, a child
  run per seed with the dev scores per epoch (step = epoch) and the training loss.

--loss gist (2026-11-05): the same data and settings with GISTEmbedLoss instead. A guide model (the
app's model B) scores each in-batch candidate; one the guide finds as close to the query as its own
post is not counted as a wrong answer. The hard-negative run (2026-10-21) lost short questions to B,
and the guess was false negatives: many posts describe the same symptoms. GIST tests that guess.
Temperature 0.05, the scale MNRL uses (20), so only the masking differs. Checkpoints go to
<user>/ko-sroberta-dograg-gist (gist-s13-e1, ...).

Environment: HF_TOKEN (read the private dataset, write the model repo) and MLFLOW_TRACKING_PASSWORD (a
DagsHub token). Nothing about either is printed.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import shutil
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

BASE_MODEL = "jhgan/ko-sroberta-multitask"
MAX_SEQ_LENGTH = 128  # the app's ONNX tokenizer
BATCH_SIZE = 64
LEARNING_RATE = 2e-5
DEV_SEED, DEV_DOCS = 13, 300
EXCLUDED = PROJECT_DIR / "tests" / "data" / "finetune_excluded_posts.json"
REPO_NAME = {"mnrl": "ko-sroberta-dograg-b2", "gist": "ko-sroberta-dograg-gist"}
GUIDE_MODEL = "blanden77/ko-sroberta-dograg-b"  # the app's model B
GIST_TEMPERATURE = 0.05  # MNRL's scale 20 is 1/0.05
WORK = Path(os.environ.get("TRAIN_WORK_DIR", "/workspace/embedding-retrain"))


def load_data(token: str | None, smoke: bool) -> tuple[dict[str, str], list[dict]]:
    from src.private_data import REPO_ID, REVISION

    if token:
        from huggingface_hub import snapshot_download

        snapshot_download(REPO_ID, repo_type="dataset", revision=REVISION, token=token, local_dir=str(PROJECT_DIR),
                          allow_patterns=["data/df.csv", "data/finetune/queries.jsonl"])
    csv.field_size_limit(10**8)
    with open(PROJECT_DIR / "data" / "df.csv", encoding="utf-8", newline="") as f:
        corpus = {row[""]: row["qa.input"] for row in csv.DictReader(f)}
    with open(PROJECT_DIR / "data" / "finetune" / "queries.jsonl", encoding="utf-8") as f:
        queries = [json.loads(line) for line in f if line.strip()]
    if smoke:
        queries = queries[:400]
        keep = {q["id"] for q in queries} | set(random.Random(1).sample(sorted(corpus), 600))
        corpus = {k: v for k, v in corpus.items() if k in keep}
    return corpus, queries


def dev_evaluator(corpus: dict[str, str], queries: list[dict], dev_ids: set[str]):
    from sentence_transformers.evaluation import InformationRetrievalEvaluator

    dev_queries, relevant = {}, {}
    for q in queries:
        if q["id"] in dev_ids:
            for kind in ("short", "detailed"):
                dev_queries[f"{q['id']}-{kind}"] = q[kind]
                relevant[f"{q['id']}-{kind}"] = {q["id"]}
    return InformationRetrievalEvaluator(
        queries=dev_queries, corpus=corpus, relevant_docs=relevant, name="dev",
        accuracy_at_k=[1, 10, 50], precision_recall_at_k=[10], mrr_at_k=[10], ndcg_at_k=[10], map_at_k=[10],
        batch_size=256, show_progress_bar=False,
    )


def scores_of(evaluator, model) -> dict[str, float]:
    scores = evaluator(model)
    names = ("accuracy@1", "accuracy@10", "accuracy@50", "mrr@10")
    missing = [n for n in names if f"dev_cosine_{n}" not in scores]
    assert not missing, f"evaluator keys changed: {sorted(scores)}"
    return {n: round(scores[f"dev_cosine_{n}"], 4) for n in names}


def load_base(device: str):
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(BASE_MODEL, device=device)
    model.max_seq_length = MAX_SEQ_LENGTH
    return model


def make_loss(kind: str, model, device: str, token: str | None):
    from sentence_transformers import SentenceTransformer, losses

    if kind == "mnrl":
        return losses.MultipleNegativesRankingLoss(model)
    guide = SentenceTransformer(GUIDE_MODEL, device=device, token=token)
    guide.max_seq_length = MAX_SEQ_LENGTH
    return losses.GISTEmbedLoss(model, guide, temperature=GIST_TEMPERATURE)


def train_seed(seed: int, epochs: int, train_rows: list[dict], corpus: dict[str, str], evaluator, device: str,
               smoke: bool, loss_kind: str = "mnrl", token: str | None = None) -> list[dict]:
    """Train one seed; save each epoch's model and corpus vectors under WORK/upload/<prefix>s<seed>-e<epoch>."""
    import numpy as np
    from datasets import Dataset
    from sentence_transformers import (
        SentenceTransformer,
        SentenceTransformerTrainer,
        SentenceTransformerTrainingArguments,
    )
    from sentence_transformers.training_args import BatchSamplers

    model = load_base(device)
    rows = [{"anchor": q[kind], "positive": corpus[q["id"]]} for q in train_rows for kind in ("short", "detailed")]
    data = Dataset.from_list(rows).shuffle(seed=seed)
    out = WORK / f"trainer-s{seed}"
    args = SentenceTransformerTrainingArguments(
        output_dir=str(out), num_train_epochs=epochs,
        per_device_train_batch_size=8 if smoke else BATCH_SIZE, learning_rate=LEARNING_RATE,
        warmup_ratio=0.1, bf16=device == "cuda", seed=seed,
        # Two queries per post: the same post twice in a batch would be scored as a wrong answer for itself.
        batch_sampler=BatchSamplers.NO_DUPLICATES,
        eval_strategy="no", save_only_model=True, logging_steps=2 if smoke else 50, report_to="none",
        # max_steps stops before an epoch ends, so the smoke run saves every 6 steps instead.
        **({"max_steps": 6 * epochs, "save_strategy": "steps", "save_steps": 6} if smoke else {"save_strategy": "epoch"}),
    )
    trainer = SentenceTransformerTrainer(model=model, args=args, train_dataset=data,
                                         loss=make_loss(loss_kind, model, device, token))
    started = time.perf_counter()
    trainer.train()
    minutes = round((time.perf_counter() - started) / 60, 1)
    checkpoints = sorted(out.glob("checkpoint-*"), key=lambda p: int(p.name.split("-")[1]))
    assert len(checkpoints) == epochs, f"expected {epochs} checkpoints, got {[p.name for p in checkpoints]}"
    ids = sorted(corpus, key=int)
    results = []
    for epoch, checkpoint in enumerate(checkpoints, start=1):
        tuned = SentenceTransformer(str(checkpoint), device=device)
        tuned.max_seq_length = MAX_SEQ_LENGTH
        name = ("gist-" if loss_kind == "gist" else "") + f"s{seed}-e{epoch}"
        folder = WORK / "upload" / name
        tuned.save(str(folder))
        vectors = tuned.encode([corpus[i] for i in ids], batch_size=256, convert_to_numpy=True, show_progress_bar=False)
        np.save(folder / "corpus_embeddings.npy", vectors.astype("float32"))
        (folder / "corpus_ids.json").write_text(json.dumps(ids))
        results.append({"name": name, "seed": seed, "epoch": epoch, "dev": scores_of(evaluator, tuned)})
        print(name, results[-1]["dev"], flush=True)
    shutil.rmtree(out)  # trainer checkpoints: the saved folders above are what is kept
    loss = [(entry["step"], entry["loss"]) for entry in trainer.state.log_history if "loss" in entry]
    for result in results:
        result.update(pairs=len(rows), train_minutes=minutes)
    results[0]["loss"] = loss
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, nargs="+", default=[13, 21, 34])
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--smoke", action="store_true", help="a few steps on a small subset (CPU is fine)")
    parser.add_argument("--no-upload", action="store_true", help="keep the checkpoints in TRAIN_WORK_DIR only")
    parser.add_argument("--local-mlflow", action="store_true", help="log to output/mlflow.db, not DagsHub")
    parser.add_argument("--loss", choices=["mnrl", "gist"], default="mnrl", help="gist: GISTEmbedLoss with model B as guide")
    args = parser.parse_args()

    import mlflow
    import torch
    from mlflow_tracking import configure

    token = os.environ.get("HF_TOKEN")
    if not token and not (PROJECT_DIR / "data" / "finetune" / "queries.jsonl").is_file():
        raise SystemExit("HF_TOKEN is needed to download the private training data.")
    if not args.no_upload and not token:
        raise SystemExit("HF_TOKEN is needed to upload the checkpoints (or pass --no-upload).")
    (PROJECT_DIR / "output").mkdir(exist_ok=True)  # --local-mlflow writes output/mlflow.db (a fresh clone has no output/)
    configure(local=args.local_mlflow)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    WORK.mkdir(parents=True, exist_ok=True)

    corpus, queries = load_data(token, args.smoke)
    excluded = set(json.loads(EXCLUDED.read_text(encoding="utf-8"))["posts"])
    # The dev split is drawn before anything is left out, so it is the same 300 posts as the app's model's.
    dev_ids = set(random.Random(DEV_SEED).sample(sorted(q["id"] for q in queries), min(DEV_DOCS, len(queries) // 4)))
    train_rows = [q for q in queries if q["id"] not in dev_ids and q["id"] not in excluded]
    left_out = sum(q["id"] in excluded and q["id"] not in dev_ids for q in queries)
    gpu = torch.cuda.get_device_name(0) if device == "cuda" else "cpu"
    print(f"corpus {len(corpus)}, train posts {len(train_rows)} ({left_out} copies left out), dev {len(dev_ids)}, {gpu}",
          flush=True)
    evaluator = dev_evaluator(corpus, queries, dev_ids)

    settings = {"base_model": BASE_MODEL, "batch_size": BATCH_SIZE, "lr": LEARNING_RATE, "epochs": args.epochs,
                "max_seq_length": MAX_SEQ_LENGTH, "queries": "short+detailed",
                "loss": "MNRL, no duplicates" if args.loss == "mnrl" else f"GISTEmbedLoss (guide {GUIDE_MODEL}, temperature {GIST_TEMPERATURE}), no duplicates",
                "dev_posts": len(dev_ids), "copies_left_out": left_out, "seeds": args.seeds, "gpu": gpu, "smoke": args.smoke}
    mlflow.set_experiment("health-embedding")
    report = {"settings": settings, "base": {}, "runs": []}
    repo_name = REPO_NAME[args.loss]
    run_name = "ko-sroberta retrain b2" if args.loss == "mnrl" else "ko-sroberta gist"
    with mlflow.start_run(run_name=run_name + (" (smoke)" if args.smoke else "")):
        mlflow.log_params({k: str(v) for k, v in settings.items()})
        mlflow.set_tags({"task": "retrain", "model_repo": repo_name})
        report["base"] = scores_of(evaluator, load_base(device))
        mlflow.log_metrics({f"dev_base_{k.replace('@', '_at_')}": v for k, v in report["base"].items()})
        print("base", report["base"], flush=True)
        for seed in args.seeds:
            with mlflow.start_run(run_name=f"seed {seed}", nested=True):
                mlflow.log_params({"seed": seed, "epochs": args.epochs})
                runs = train_seed(seed, args.epochs, train_rows, corpus, evaluator, device, args.smoke, args.loss, token)
                for run in runs:
                    mlflow.log_metrics({f"dev_{k.replace('@', '_at_')}": v for k, v in run["dev"].items()}, step=run["epoch"])
                for step, value in runs[0].pop("loss"):
                    mlflow.log_metric("train_loss", value, step=step)
                mlflow.log_metric("train_minutes", runs[0]["train_minutes"])
                report["runs"].extend(runs)
                if device == "cuda":
                    mlflow.log_metric("gpu_peak_gb", round(torch.cuda.max_memory_allocated() / 1e9, 1))
                    torch.cuda.reset_peak_memory_stats()
        best = max(report["runs"], key=lambda r: (r["dev"]["mrr@10"], r["dev"]["accuracy@10"]))
        report["best_by_dev"] = best["name"]
        mlflow.set_tag("best_by_dev", best["name"])
        (WORK / "upload" / "results.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        mlflow.log_artifact(str(WORK / "upload" / "results.json"))

        if not args.no_upload:
            from huggingface_hub import HfApi

            api = HfApi(token=token)
            repo = f"{api.whoami()['name']}/{repo_name}"
            api.create_repo(repo, private=True, exist_ok=True)
            api.upload_folder(repo_id=repo, folder_path=str(WORK / "upload"),
                              commit_message=f"retrain {len(report['runs'])} checkpoints" + (" (smoke)" if args.smoke else ""))
            mlflow.set_tag("model_repo", repo)
            print("uploaded", repo, flush=True)
    print(json.dumps({k: v for k, v in report.items() if k != "settings"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
