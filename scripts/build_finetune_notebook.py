"""Write notebooks/finetune_embedding_colab.ipynb (the training notebook run on Colab's T4).

    uv run python scripts/build_finetune_notebook.py

Kept as code so the notebook can be regenerated and reviewed in diffs. SMOKE=True in the
first code cell runs the same cells on a tiny subset (CPU is fine) to check the code.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "notebooks" / "finetune_embedding_colab.ipynb"

CELLS = [
    ("markdown", """# 건강 상담 임베딩 미세조정 (Colab T4)

`jhgan/ko-sroberta-multitask`를 **보호자가 실제로 치는 짧은 질문 → 긴 상담 글**에 맞게 미세조정합니다.

- **학습 짝:** `data/finetune/queries.jsonl`. 상담 19,206개마다 LLM이 쓴 질의 2개(`short` 15~40자, `detailed` 40~100자)입니다. 만드는 법은 `scripts/finetune_queries.py`에 있습니다.
- **데이터:** AI Hub 말뭉치와 합성 질의는 공개 저장소에 없습니다(재배포 금지). 비공개 데이터셋 `blanden77/dograg-data`에서 받으므로 처음에 Hugging Face 토큰(읽기, 업로드까지 하려면 쓰기)을 입력합니다.
- **비교:** 기준 모델과 A(`detailed`만), B(`short` + `detailed`)를 비교합니다. 학습에 쓰지 않은 상담 300개의 질의로 원래 상담을 19,206개 중 몇 위에 찾는지 잽니다.
- **최종 평가는 로컬에서 합니다.** 앱과 같은 하이브리드 경로의 `useful@3`(100문항)와 `hit@3`(561문항)으로 잽니다. 이 노트북의 점수는 A·B를 고르는 데만 씁니다.
- **실행:** VS Code Colab 확장 → 런타임 T4 GPU → 위에서부터 차례로 실행합니다. 마지막 셀은 같은 토큰으로 **비공개** 모델 저장소에 올립니다.
- **기록:** 2026-10-09 실행(T4, 학습 2.4분·4.6분)의 결과와 해석은 `docs/wiki/embedding-finetune.md`에 있습니다.
"""),
    ("code", """# 설정: SMOKE=True면 작은 부분만으로 코드가 도는지 확인합니다(CPU도 가능).
SMOKE = False
BRANCH = "main"
DATA_REPO = "blanden77/dograg-data"   # 비공개 데이터셋 (src/private_data.py)
BASE_MODEL = "jhgan/ko-sroberta-multitask"
MAX_SEQ_LENGTH = 128          # 앱의 ONNX 토크나이저와 같은 길이
BATCH_SIZE = 64
LEARNING_RATE = 2e-5
EPOCHS = 1
DEV_DOCS = 300
SEED = 13
HF_REPO_PREFIX = "ko-sroberta-dograg"   # <사용자>/ko-sroberta-dograg-a, -b"""),
    ("code", """import subprocess, sys
print(sys.version)
try:
    print(subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv"], capture_output=True, text=True).stdout)
except FileNotFoundError:
    print("GPU 없음 (SMOKE 확인용으로만 사용)")"""),
    ("code", """# 저장소 받기 (Colab). 로컬에서 SMOKE로 돌릴 때는 저장소 루트에서 실행되므로 건너뜁니다.
import os
if os.path.exists("/content"):
    %cd /content
    !rm -rf dograg
    !git clone --depth 1 --branch {BRANCH} https://github.com/rndigkwk/dograg.git
    %cd /content/dograg
    !pip install -q "sentence-transformers[train]>=5.1"
# Hugging Face 토큰: VS Code Colab 확장에서는 Colab 비밀 값을 못 읽어 직접 입력합니다.
token = None
if not SMOKE:
    from getpass import getpass
    try:
        from google.colab import userdata
        token = userdata.get("HF_TOKEN")
    except Exception:
        pass
    token = token or getpass("Hugging Face 토큰: ")
    from huggingface_hub import snapshot_download
    snapshot_download(DATA_REPO, repo_type="dataset", token=token, local_dir=".",
                      allow_patterns=["data/df.csv", "data/finetune/queries.jsonl"])
import importlib.metadata as md
for package in ("sentence-transformers", "transformers", "torch", "datasets", "accelerate"):
    print(package, md.version(package))"""),
    ("code", """import csv, json, random, time
import torch

csv.field_size_limit(10**8)
with open("data/df.csv", encoding="utf-8", newline="") as f:
    corpus = {row[""]: row["qa.input"] for row in csv.DictReader(f)}
with open("data/finetune/queries.jsonl", encoding="utf-8") as f:
    queries = [json.loads(line) for line in f if line.strip()]
rng = random.Random(SEED)
if SMOKE:
    queries = queries[:120]
    keep = {q["id"] for q in queries} | set(rng.sample(sorted(corpus), 280))
    corpus = {k: v for k, v in corpus.items() if k in keep}
dev_ids = set(random.Random(SEED).sample(sorted(q["id"] for q in queries), min(DEV_DOCS, len(queries) // 4)))
train_rows = [q for q in queries if q["id"] not in dev_ids]
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"corpus {len(corpus)}, queries {len(queries)}, train docs {len(train_rows)}, dev docs {len(dev_ids)}, device {device}")"""),
    ("code", """from sentence_transformers import SentenceTransformer
from sentence_transformers.evaluation import InformationRetrievalEvaluator

dev_queries, relevant = {}, {}
for q in queries:
    if q["id"] in dev_ids:
        for kind in ("short", "detailed"):
            dev_queries[f"{q['id']}-{kind}"] = q[kind]
            relevant[f"{q['id']}-{kind}"] = {q["id"]}
evaluator = InformationRetrievalEvaluator(
    queries=dev_queries, corpus=corpus, relevant_docs=relevant, name="dev",
    accuracy_at_k=[1, 10, 50], precision_recall_at_k=[10], mrr_at_k=[10], ndcg_at_k=[10], map_at_k=[10],
    batch_size=128, show_progress_bar=False,
)

def evaluate(model):
    scores = evaluator(model)
    names = ("accuracy@1", "accuracy@10", "accuracy@50", "mrr@10")
    missing = [n for n in names if f"dev_cosine_{n}" not in scores]
    assert not missing, f"evaluator keys changed: {sorted(scores)}"
    return {n: round(scores[f"dev_cosine_{n}"], 4) for n in names}

def load_base():
    model = SentenceTransformer(BASE_MODEL, device=device)
    model.max_seq_length = MAX_SEQ_LENGTH
    return model

results = {"base": evaluate(load_base())}
print(results["base"])"""),
    ("code", """from datasets import Dataset
from sentence_transformers import SentenceTransformerTrainer, SentenceTransformerTrainingArguments, losses
from sentence_transformers.training_args import BatchSamplers

def pairs(variant):
    kinds = ("detailed",) if variant == "a" else ("short", "detailed")
    rows = [{"anchor": q[kind], "positive": corpus[q["id"]]} for q in train_rows for kind in kinds]
    return Dataset.from_list(rows).shuffle(seed=SEED)

def train(variant):
    model = load_base()
    data = pairs(variant)
    args = SentenceTransformerTrainingArguments(
        output_dir=f"/tmp/ft-{variant}", num_train_epochs=EPOCHS,
        per_device_train_batch_size=8 if SMOKE else BATCH_SIZE, learning_rate=LEARNING_RATE,
        warmup_ratio=0.1, fp16=device == "cuda", seed=SEED,
        # B has two queries per document: the same document twice in a batch would be scored
        # as a wrong answer for itself.
        batch_sampler=BatchSamplers.NO_DUPLICATES,
        eval_strategy="no", save_strategy="no", logging_steps=50, report_to="none",
        max_steps=4 if SMOKE else -1,
    )
    started = time.perf_counter()
    SentenceTransformerTrainer(model=model, args=args, train_dataset=data,
                               loss=losses.MultipleNegativesRankingLoss(model)).train()
    minutes = round((time.perf_counter() - started) / 60, 1)
    scores = evaluate(model)
    print(variant, f"{len(data)} pairs, {minutes} min", scores)
    return model, {**scores, "pairs": len(data), "train_minutes": minutes}

models = {}
for variant in ("a", "b"):
    models[variant], results[variant] = train(variant)
    if device == "cuda":
        print("GPU memory peak (GB):", round(torch.cuda.max_memory_allocated() / 1e9, 1))
        torch.cuda.reset_peak_memory_stats()
print(json.dumps(results, indent=1))"""),
    ("code", """# 각 모델로 상담 19,206개를 임베딩해 함께 올립니다. 로컬 평가에서 다시 임베딩하지 않아도 됩니다.
import numpy as np
from pathlib import Path

ids = sorted(corpus, key=int)
# The base model's vectors too, so the local evaluation compares all three the same way
# (exact search over the same 19,206 vectors; the app's Chroma index is approximate).
base_vectors = load_base().encode([corpus[i] for i in ids], batch_size=256, convert_to_numpy=True, show_progress_bar=False)
for variant, model in models.items():
    out = Path(f"/tmp/out-{variant}")
    model.save(str(out))
    started = time.perf_counter()
    vectors = model.encode([corpus[i] for i in ids], batch_size=256, convert_to_numpy=True, show_progress_bar=False)
    np.save(out / "corpus_embeddings.npy", vectors.astype("float32"))
    np.save(out / "base_corpus_embeddings.npy", base_vectors.astype("float32"))
    (out / "corpus_ids.json").write_text(json.dumps(ids))
    (out / "finetune_results.json").write_text(json.dumps({"results": results, "variant": variant, "smoke": SMOKE,
        "settings": {"batch_size": BATCH_SIZE, "lr": LEARNING_RATE, "epochs": EPOCHS, "max_seq_length": MAX_SEQ_LENGTH}}, indent=1))
    print(variant, vectors.shape, f"encoded in {time.perf_counter() - started:.0f}s")"""),
    ("code", """# Hugging Face 비공개 모델 저장소에 올립니다(처음에 입력한 토큰, 쓰기 권한 필요).
if not SMOKE:
    from huggingface_hub import HfApi
    api = HfApi(token=token)
    user = api.whoami()["name"]
    for variant in models:
        repo = f"{user}/{HF_REPO_PREFIX}-{variant}"
        api.create_repo(repo, private=True, exist_ok=True)
        api.upload_folder(repo_id=repo, folder_path=f"/tmp/out-{variant}")
        print("uploaded", repo)
    del token"""),
]


def main() -> None:
    cells = []
    for kind, source in CELLS:
        cell = {"cell_type": kind, "metadata": {}, "source": source.splitlines(keepends=True)}
        if kind == "code":
            cell.update(execution_count=None, outputs=[])
        cells.append(cell)
    notebook = {
        "cells": cells,
        "metadata": {"accelerator": "GPU", "colab": {"gpuType": "T4"},
                     "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python"}},
        "nbformat": 4, "nbformat_minor": 5,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
