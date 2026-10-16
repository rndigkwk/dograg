"""Write notebooks/kure_finetune_colab.ipynb: KURE-v1 fine-tuned on the app's synthetic queries (Colab T4).

    uv run python scripts/build_kure_finetune_notebook.py

Why (docs/wiki/embedding-finetune.md, 2026-10-13): KURE-v1 as published scored useful@3 0.723 on the
health search against the app's 0.809 (p=0.008), and the gap was the app's fine-tuning on our own
question style. The open question is whether KURE-v1 with the same fine-tuning beats the app. Same
recipe as notebooks/finetune_embedding_colab.ipynb, variant B (short + detailed queries, the app's
model), with CachedMultipleNegativesRankingLoss so a 568M model keeps batch 64 on a T4.

Every run is logged to MLflow on DagsHub (scripts/mlflow_tracking.py): settings, the dev scores
before and after, training time and loss, and the result file. The model goes to a private Hugging
Face repo and the document vectors to the private dataset (branch experiments), as before; the final
comparison runs locally: scripts/compare_kure.py --finetuned. SMOKE=True runs the same cells on a
small part on CPU and logs to a local folder, to check the code.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "notebooks" / "kure_finetune_colab.ipynb"

CELLS = [
    ("markdown", """# KURE-v1 미세조정 (Colab T4, MLflow 기록)

`nlpai-lab/KURE-v1`(BGE-M3 한국어 추가 학습, 5.7억 파라미터)을 앱 모델과 **같은 합성 질의**로 미세조정합니다.

- **왜:** 2026-10-13 비교에서 미세조정하지 않은 KURE-v1은 하이브리드 `useful@3` 0.723으로 앱(미세조정 ko-sroberta, 0.809)보다 유의하게 낮았습니다(p=0.008). 차이는 우리 질문 말투로 한 미세조정이었습니다. 같은 미세조정을 KURE-v1에 하면 앱보다 나은지 봅니다.
- **학습 짝:** `data/finetune/queries.jsonl`의 `short` + `detailed`(앱 모델 B와 같은 방식). 학습에 쓰지 않은 상담 300개의 질의로 dev 점수를 냅니다.
- **손실:** `CachedMultipleNegativesRankingLoss`. 큰 모델이라 작은 묶음(MINI_BATCH)으로 나눠 계산하되, 배치 64 안의 다른 상담을 오답으로 쓰는 효과는 같습니다.
- **기록:** 설정, 학습 전·후 dev 점수, 학습 시간·손실, 결과 파일을 **MLflow(DagsHub)** 에 남깁니다. 모델 가중치(약 2.2GB)는 Hugging Face 비공개 저장소에 올립니다.
- **토큰 두 개:** Hugging Face(쓰기)와 DagsHub. Colab Secrets에 `HF_TOKEN`, `DAGSHUB_TOKEN`으로 넣거나 실행 중 입력합니다. 화면에는 길이만 표시합니다.
- **메모리(T4 14.5GB):** 일반 AdamW는 가중치·기울기·옵티마이저 상태만 약 9GB라 첫 실행(2026-10-17)이 학습 중 OOM으로 멈췄습니다. 그래서 8비트 AdamW(`adamw_bnb_8bit`, 상태 약 1.1GB)와 gradient checkpointing을 씁니다. 또 OOM이 나면 런타임을 다시 시작하고 `MINI_BATCH`를 4로 줄입니다.
- **예상 시간(T4):** 학습 전 dev 평가 약 9분(아래 `BASE_SCORES`가 있으면 건너뜀), 학습 약 30~50분, 학습 후 dev 평가 약 9분, 문서 19,206개 임베딩 약 10분.
- **최종 평가는 로컬에서:** `uv run --group tools python scripts/compare_kure.py --finetuned` (같은 220문항, judge 호출 수를 먼저 보여 줍니다).
"""),
    ("code", """# 설정: SMOKE=True면 작은 부분만으로 코드가 도는지 확인합니다(CPU 가능, MLflow는 로컬 폴더).
SMOKE = False
DATA_REPO, REVISION = "blanden77/dograg-data", "data-v4"   # src/private_data.py
BASE_MODEL = "nlpai-lab/KURE-v1"
MAX_SEQ_LENGTH = 256      # 학습 길이 (앱 ko-sroberta는 128). 최종 문서 임베딩은 ENCODE_SEQ_LENGTH
ENCODE_SEQ_LENGTH = 1024  # 2026-10-13 KURE-v1 비교와 같은 길이 (상담 0.11%만 잘림)
BATCH_SIZE = 64
MINI_BATCH = 8              # CachedMNRL: 64개 배치를 8개씩 나눠 계산 (배치 안 오답 효과는 64개 그대로)
OPTIM = "adamw_bnb_8bit"    # 8비트 AdamW: 옵티마이저 상태 약 4.5GB -> 1.1GB
GRADIENT_CHECKPOINTING = True
# 학습 전 dev 점수(2026-10-17 T4 첫 실행에서 잰 값). None이면 다시 잽니다(약 9분).
BASE_SCORES = {"accuracy@1": 0.255, "accuracy@10": 0.515, "accuracy@50": 0.6617, "mrr@10": 0.333}
LEARNING_RATE = 1e-5
EPOCHS = 1
DEV_DOCS = 300
SEED = 13
HF_MODEL_REPO = "kure-v1-dograg"        # <사용자>/kure-v1-dograg (비공개)
ROWS_PATH = "kure/kure_v1_ft_rows.npy"  # DATA_REPO@experiments
MLFLOW_URI = "https://dagshub.com/rndigkwk/dograg.mlflow"
MLFLOW_USER = "rndigkwk"
EXPERIMENT = "health-embedding\""""),
    ("code", """import os, subprocess, sys
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")  # less fragmentation (set before torch)
if os.path.exists("/content"):
    !pip -q install -U "sentence-transformers[train]>=5.1" "mlflow>=3.4" huggingface_hub bitsandbytes
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
import torch
print(sys.version, torch.__version__, torch.cuda.get_device_name(0) if torch.cuda.is_available() else "GPU 없음 (SMOKE만 가능)")
if not SMOKE:
    assert torch.cuda.is_available(), "런타임 유형을 T4 GPU로 바꾸세요\""""),
    ("code", """# 토큰: Colab Secrets(HF_TOKEN, DAGSHUB_TOKEN)를 먼저 보고, 없으면 입력받습니다. 값은 출력하지 않습니다.
from getpass import getpass

def secret(name, prompt):
    value = None
    try:
        from google.colab import userdata
        value = userdata.get(name)
    except Exception:
        pass
    value = (value or getpass(prompt)).strip()
    # A token typed with the Korean input mode on turns into Hangul and fails much later.
    if not value.isascii():
        raise ValueError(f"{name}에 영문이 아닌 글자가 있습니다(한글 입력 상태?). 길이 {len(value)}")
    print(name, "ok, length", len(value))
    return value

HF_TOKEN = None if SMOKE else secret("HF_TOKEN", "Hugging Face 토큰(쓰기): ")
if SMOKE:
    os.environ["MLFLOW_TRACKING_URI"] = "sqlite:///output/smoke_mlflow.db"  # MLflow 3 keeps local runs in SQLite
else:
    os.environ["MLFLOW_TRACKING_URI"] = MLFLOW_URI
    os.environ["MLFLOW_TRACKING_USERNAME"] = MLFLOW_USER
    os.environ["MLFLOW_TRACKING_PASSWORD"] = secret("DAGSHUB_TOKEN", "DagsHub 토큰: ")
os.environ["MLFLOW_EXPERIMENT_NAME"] = EXPERIMENT"""),
    ("code", """# 데이터: 상담 19,206개(앱 문서와 같게 CR 제거)와 합성 질의. SMOKE는 로컬 파일을 씁니다.
import csv, json, random, time
from huggingface_hub import hf_hub_download

def data_file(name):
    if SMOKE and os.path.exists(name):
        return name
    return hf_hub_download(DATA_REPO, name, repo_type="dataset", revision=REVISION, token=HF_TOKEN)

csv.field_size_limit(10**8)
with open(data_file("data/df.csv"), encoding="utf-8", newline="") as f:
    corpus = {row[""]: row["qa.input"].replace(chr(13), "") for row in csv.DictReader(f)}
with open(data_file("data/finetune/queries.jsonl"), encoding="utf-8") as f:
    queries = [json.loads(line) for line in f if line.strip()]
rng = random.Random(SEED)
if SMOKE:
    queries = queries[:60]
    keep = {q["id"] for q in queries} | set(rng.sample(sorted(corpus), 140))
    corpus = {k: v for k, v in corpus.items() if k in keep}
dev_ids = set(random.Random(SEED).sample(sorted(q["id"] for q in queries), min(DEV_DOCS, len(queries) // 4)))
train_rows = [q for q in queries if q["id"] not in dev_ids]
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"corpus {len(corpus)}, queries {len(queries)}, train docs {len(train_rows)}, dev docs {len(dev_ids)}, device {device}")"""),
    ("code", """# dev 평가: 학습에 쓰지 않은 상담의 질의(short·detailed)로 원래 상담을 전체 중 몇 위에 찾는지.
from sentence_transformers import SentenceTransformer
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
    batch_size=64, show_progress_bar=False,
)
NAMES = ("accuracy@1", "accuracy@10", "accuracy@50", "mrr@10")

def evaluate(model):
    started = time.perf_counter()
    scores = evaluator(model)
    missing = [n for n in NAMES if f"dev_cosine_{n}" not in scores]
    assert not missing, f"evaluator keys changed: {sorted(scores)}"
    result = {n: round(scores[f"dev_cosine_{n}"], 4) for n in NAMES}
    print(result, f"{time.perf_counter() - started:.0f}s")
    return result

def load_base():
    model = SentenceTransformer(BASE_MODEL, device=device, token=HF_TOKEN)
    model.max_seq_length = MAX_SEQ_LENGTH
    return model"""),
    ("code", """# MLflow 실행을 열고 설정과 학습 전 점수를 남깁니다.
import mlflow
mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
if SMOKE and mlflow.get_experiment_by_name(EXPERIMENT) is None:  # artifacts under output/, not ./mlruns
    from pathlib import Path
    mlflow.create_experiment(EXPERIMENT, artifact_location=Path("output/smoke_mlartifacts").resolve().as_uri())
mlflow.set_experiment(EXPERIMENT)
run = mlflow.start_run(run_name="kure-v1-ft-b" + ("-smoke" if SMOKE else ""),
                       tags={"base_model": BASE_MODEL, "variant": "b (short + detailed)", "smoke": str(SMOKE),
                             "data": f"{DATA_REPO}@{REVISION}", "notebook": "notebooks/kure_finetune_colab.ipynb",
                             "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"})
mlflow.log_params({"max_seq_length": MAX_SEQ_LENGTH, "encode_seq_length": ENCODE_SEQ_LENGTH, "batch_size": BATCH_SIZE,
                   "mini_batch": MINI_BATCH, "learning_rate": LEARNING_RATE, "epochs": EPOCHS, "seed": SEED,
                   "loss": "CachedMultipleNegativesRankingLoss", "optim": OPTIM if not SMOKE else "adamw_torch",
                   "encoder_checkpointing": GRADIENT_CHECKPOINTING, "dev_docs": len(dev_ids), "train_docs": len(train_rows),
                   "corpus": len(corpus)})
results = {"base": dict(BASE_SCORES) if BASE_SCORES and not SMOKE else evaluate(load_base())}
mlflow.set_tag("base_scores", "measured in this run" if not BASE_SCORES or SMOKE else "from the first T4 run (BASE_SCORES)")
mlflow.log_metrics({f"base_{n.replace('@', '_at_')}": v for n, v in results["base"].items()})
print("MLflow run", run.info.run_id)"""),
    ("code", """# 학습: 상담마다 질의 2개(short, detailed). 손실은 50스텝마다 MLflow에 기록됩니다(report_to="mlflow").
from datasets import Dataset
from sentence_transformers import SentenceTransformerTrainer, SentenceTransformerTrainingArguments, losses
from sentence_transformers.training_args import BatchSamplers
import gc

gc.collect()
if torch.cuda.is_available():
    torch.cuda.empty_cache()  # the evaluation model's memory, before the training model loads
rows = [{"anchor": q[kind], "positive": corpus[q["id"]]} for q in train_rows for kind in ("short", "detailed")]
data = Dataset.from_list(rows).shuffle(seed=SEED)
model = load_base()
if GRADIENT_CHECKPOINTING:
    model[0].auto_model.gradient_checkpointing_enable()  # recompute activations instead of keeping them
args = SentenceTransformerTrainingArguments(
    output_dir="/tmp/kure-ft", num_train_epochs=EPOCHS,
    per_device_train_batch_size=8 if SMOKE else BATCH_SIZE, learning_rate=LEARNING_RATE,
    warmup_ratio=0.1, fp16=device == "cuda", seed=SEED, optim="adamw_torch" if SMOKE else OPTIM,
    # Two queries per document: the same document twice in a batch would be scored as a wrong answer for itself.
    batch_sampler=BatchSamplers.NO_DUPLICATES,
    eval_strategy="no", save_strategy="no", logging_steps=2 if SMOKE else 50, report_to=["mlflow"],
    run_name="kure-v1-ft-b", max_steps=3 if SMOKE else -1,
)
loss = losses.CachedMultipleNegativesRankingLoss(model, mini_batch_size=4 if SMOKE else MINI_BATCH)
started = time.perf_counter()
SentenceTransformerTrainer(model=model, args=args, train_dataset=data, loss=loss).train()
minutes = round((time.perf_counter() - started) / 60, 1)
results["finetuned"] = {**evaluate(model), "pairs": len(data), "train_minutes": minutes}
mlflow.log_metrics({f"ft_{n.replace('@', '_at_')}": results["finetuned"][n] for n in NAMES})
mlflow.log_metrics({"train_minutes": minutes, "train_pairs": len(data)})
if torch.cuda.is_available():
    mlflow.log_metric("gpu_peak_gb", round(torch.cuda.max_memory_allocated() / 2**30, 2))
print(f"{len(data)} pairs, {minutes} min", results)"""),
    ("code", """# 문서 19,206개를 미세조정 모델로 임베딩합니다(float16, 짧은 것부터). 로컬 비교는 이 벡터를 씁니다.
import numpy as np
from pathlib import Path

out = Path("/tmp/kure-ft-out" if not SMOKE else "output/kure_smoke_out")
model.save(str(out))
encoder = SentenceTransformer(str(out), device=device)
if device == "cuda":
    encoder = encoder.half()
encoder.max_seq_length = ENCODE_SEQ_LENGTH
ids = sorted(corpus, key=int)  # df.csv row order, like output/experiments/kure_v1_rows.npy
texts = [corpus[i] for i in ids]
order = np.argsort([len(t) for t in texts])
started = time.perf_counter()
sorted_vectors = encoder.encode([texts[i] for i in order], batch_size=64, normalize_embeddings=True,
                                convert_to_numpy=True, show_progress_bar=True).astype(np.float32)
vectors = np.empty_like(sorted_vectors)
vectors[order] = sorted_vectors
np.save(out / "kure_v1_ft_rows.npy", vectors)
encode_minutes = round((time.perf_counter() - started) / 60, 1)
(out / "finetune_results.json").write_text(json.dumps({"results": results, "smoke": SMOKE, "encode_minutes": encode_minutes,
    "settings": {"base": BASE_MODEL, "max_seq_length": MAX_SEQ_LENGTH, "encode_seq_length": ENCODE_SEQ_LENGTH,
                 "batch_size": BATCH_SIZE, "mini_batch": MINI_BATCH, "lr": LEARNING_RATE, "epochs": EPOCHS}}, indent=1))
mlflow.log_metric("encode_minutes", encode_minutes)
mlflow.log_artifact(str(out / "finetune_results.json"))
print(vectors.shape, f"{encode_minutes} min")"""),
    ("code", """# 비공개 저장소에 올리고 MLflow 실행을 닫습니다. 모델: <사용자>/kure-v1-dograg, 벡터: DATA_REPO@experiments.
if not SMOKE:
    from huggingface_hub import HfApi
    api = HfApi(token=HF_TOKEN)
    repo = f"{api.whoami()['name']}/{HF_MODEL_REPO}"
    api.create_repo(repo, private=True, exist_ok=True)
    api.upload_folder(repo_id=repo, folder_path=str(out), ignore_patterns=["kure_v1_ft_rows.npy"])
    api.create_branch(DATA_REPO, repo_type="dataset", branch="experiments", exist_ok=True)
    api.upload_file(path_or_fileobj=str(out / "kure_v1_ft_rows.npy"), path_in_repo=ROWS_PATH,
                    repo_id=DATA_REPO, repo_type="dataset", revision="experiments")
    mlflow.set_tags({"hf_model": repo, "rows": f"{DATA_REPO}@experiments/{ROWS_PATH}"})
    print("uploaded", repo, "and", ROWS_PATH)
    del HF_TOKEN, api
    os.environ.pop("MLFLOW_TRACKING_PASSWORD", None)
mlflow.end_run()
print("done:", run.info.run_id)"""),
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
