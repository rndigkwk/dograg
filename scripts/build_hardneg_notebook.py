"""Write notebooks/hardneg_finetune_colab.ipynb: the app's health embedding retrained with hard negatives (Colab T4).

    uv run python scripts/build_hardneg_notebook.py

Why (docs/curriculum-fit.md 4, Day 74; ADR-0001's revisit condition): the app model
(blanden77/ko-sroberta-dograg-b) learned only from in-batch negatives, other consultations that
happened to share its batch. The production search still misses 21 of 100 `기타` questions while 14
of them have a directly useful consultation further down (docs/wiki/eval-coverage.md). Hard
negatives (consultations the app model ranks high but are not the answer) teach the finer line.

Same recipe as notebooks/finetune_embedding_colab.ipynb variant B (base model, queries, batch,
learning rate, one epoch, the same dev split from SEED 13) plus one mined negative per pair, so a
difference comes from the negatives alone. Negatives are mined with the app model from ranks
RANGE_MIN..RANGE_MAX, at least RELATIVE_MARGIN less similar than the answer (the corpus has many
near-duplicate consultations: a close one may be another right answer), and never from the dev
consultations. Every run is logged to MLflow on DagsHub (scripts/mlflow_tracking.py), as the KURE
notebook does. The model and its corpus vectors go to a private Hugging Face repo in the format
scripts/evaluate_finetuned_embedding.py reads (--variants hn). SMOKE=True runs the same cells on a
small part on CPU and logs to a local folder.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "notebooks" / "hardneg_finetune_colab.ipynb"

CELLS = [
    ("markdown", """# 건강 검색 임베딩: 하드 네거티브로 다시 학습 (Colab T4, MLflow 기록)

앱 모델 `blanden77/ko-sroberta-dograg-b`는 **배치 안에 우연히 같이 들어온 다른 상담**만 오답으로 배웠습니다. 이번에는 앱 모델이 높은 순위로 찾지만 정답이 아닌 상담(**하드 네거티브**)을 오답으로 함께 넣어, 비슷한 상담 사이의 미세한 차이를 배우게 합니다(교안 Day 74).

- **왜:** 운영 검색이 `기타` 100문항 중 21문항에서 상위 3개에 바로 쓸모 있는 상담을 놓치는데, 그중 14문항은 후보 안에 그런 상담이 있습니다(2026-10-20, `docs/wiki/eval-coverage.md`).
- **같은 조건:** 앱 모델 B와 같은 기본 모델(`jhgan/ko-sroberta-multitask`), 같은 합성 질의(`short` + `detailed`), 같은 배치·학습률·1 epoch, 같은 dev 상담 300개(SEED 13)입니다. 다른 점은 **질의마다 오답 1개를 더한 것**뿐입니다.
- **오답 캐기:** 앱 모델로 질의마다 상담을 찾아 **10~50위** 사이에서 고릅니다. 1~9위는 사실상 정답일 수 있어 뺍니다. 정답보다 5% 이상 덜 비슷한 것만 씁니다(같은 증상의 상담이 많아서입니다). dev 상담은 오답으로도 쓰지 않습니다.
- **기록:** 설정, 캐낸 오답 수, 학습 손실, 기본·B·새 모델의 dev 점수를 **MLflow(DagsHub)** 에 남깁니다. 모델과 상담 벡터는 Hugging Face 비공개 저장소에 올립니다.
- **토큰 두 개:** Hugging Face(쓰기)와 DagsHub. Colab Secrets에 `HF_TOKEN`, `DAGSHUB_TOKEN`으로 넣거나 실행 중 입력합니다. 화면에는 길이만 표시합니다.
- **예상 시간(T4):** 오답 캐기 약 2분, 학습 약 6~8분(B는 4.6분), dev 평가 모델당 약 1분, 상담 임베딩 약 2분.
- **OpenAI 호출 없음.** 최종 평가는 로컬에서 `scripts/evaluate_finetuned_embedding.py --variants b hn`로 합니다(새로 나온 후보만 채점하며 호출 수를 먼저 보여 줍니다).
"""),
    ("code", """# 설정: SMOKE=True면 작은 부분만으로 코드가 도는지 확인합니다(CPU 가능, MLflow는 로컬 폴더).
SMOKE = False
DATA_REPO, REVISION = "blanden77/dograg-data", "data-v11"   # src/private_data.py
BASE_MODEL = "jhgan/ko-sroberta-multitask"
APP_MODEL = "blanden77/ko-sroberta-dograg-b"   # 지금 앱 모델: 오답을 캐고, 비교 기준이 됩니다
MAX_SEQ_LENGTH = 128      # 앱 ONNX 토크나이저와 같은 길이
BATCH_SIZE = 64
LEARNING_RATE = 2e-5
EPOCHS = 1
DEV_DOCS = 300
SEED = 13                 # 앱 모델 B와 같은 dev 상담
RANGE_MIN, RANGE_MAX = 10, 50   # 오답 후보 순위(1~9위는 사실상 정답일 수 있음)
RELATIVE_MARGIN = 0.05          # 정답보다 5% 이상 덜 비슷한 것만
NUM_NEGATIVES = 1
HF_MODEL_REPO = "ko-sroberta-dograg-hn"   # <사용자>/ko-sroberta-dograg-hn (비공개)
MLFLOW_URI = "https://dagshub.com/rndigkwk/dograg.mlflow"
MLFLOW_USER = "rndigkwk"
EXPERIMENT = "health-embedding\""""),
    ("code", """import os, subprocess, sys
if os.path.exists("/content"):
    !pip -q install -U "sentence-transformers[train]>=5.1" "mlflow>=3.4" huggingface_hub
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
    queries = queries[:80]
    keep = {q["id"] for q in queries} | set(rng.sample(sorted(corpus), 220))
    corpus = {k: v for k, v in corpus.items() if k in keep}
# The same split as the app model's training (notebooks/finetune_embedding_colab.ipynb): its dev is unseen by B too.
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

def load(name):
    model = SentenceTransformer(name, device=device, token=HF_TOKEN)
    model.max_seq_length = MAX_SEQ_LENGTH
    return model"""),
    ("code", """# MLflow 실행을 열고 설정과 기본 모델·앱 모델(B)의 dev 점수를 남깁니다.
import mlflow
mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
if SMOKE and mlflow.get_experiment_by_name(EXPERIMENT) is None:  # artifacts under output/, not ./mlruns
    from pathlib import Path
    mlflow.create_experiment(EXPERIMENT, artifact_location=Path("output/smoke_mlartifacts").resolve().as_uri())
mlflow.set_experiment(EXPERIMENT)
run = mlflow.start_run(run_name="ko-sroberta-hard-negatives" + ("-smoke" if SMOKE else ""),
                       tags={"base_model": BASE_MODEL, "miner": APP_MODEL, "variant": "b + hard negatives",
                             "smoke": str(SMOKE), "data": f"{DATA_REPO}@{REVISION}",
                             "notebook": "notebooks/hardneg_finetune_colab.ipynb",
                             "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"})
mlflow.log_params({"max_seq_length": MAX_SEQ_LENGTH, "batch_size": BATCH_SIZE, "learning_rate": LEARNING_RATE,
                   "epochs": EPOCHS, "seed": SEED, "loss": "MultipleNegativesRankingLoss + 1 mined negative",
                   "range_min": RANGE_MIN, "range_max": RANGE_MAX, "relative_margin": RELATIVE_MARGIN,
                   "num_negatives": NUM_NEGATIVES, "dev_docs": len(dev_ids), "train_docs": len(train_rows),
                   "corpus": len(corpus)})
app_model = load(APP_MODEL)
results = {"base": evaluate(load(BASE_MODEL)), "b": evaluate(app_model)}
for name in ("base", "b"):
    mlflow.log_metrics({f"{name}_{n.replace('@', '_at_')}": v for n, v in results[name].items()})
print("MLflow run", run.info.run_id)"""),
    ("code", """# 하드 네거티브 캐기: 앱 모델이 RANGE_MIN~RANGE_MAX위로 찾았지만 정답이 아닌 상담. dev 상담은 후보에서 뺍니다.
from datasets import Dataset
from sentence_transformers.util import mine_hard_negatives

pairs = Dataset.from_list([{"anchor": q[kind], "positive": corpus[q["id"]]}
                           for q in train_rows for kind in ("short", "detailed")])
negative_pool = [text for doc_id, text in corpus.items() if doc_id not in dev_ids]
started = time.perf_counter()
triplets = mine_hard_negatives(
    pairs, app_model, corpus=negative_pool,
    range_min=2 if SMOKE else RANGE_MIN, range_max=20 if SMOKE else RANGE_MAX,
    relative_margin=RELATIVE_MARGIN, num_negatives=NUM_NEGATIVES, sampling_strategy="random",
    batch_size=128, use_faiss=False, output_format="triplet", verbose=True,
)
mine_minutes = round((time.perf_counter() - started) / 60, 1)
mlflow.log_metrics({"pairs": len(pairs), "triplets": len(triplets), "mine_minutes": mine_minutes})
print(f"{len(pairs)} pairs -> {len(triplets)} with a hard negative ({mine_minutes} min)")
print(triplets[0])"""),
    ("code", """# 학습: B와 같은 조건에 오답 1개를 더합니다. 손실은 50스텝마다 MLflow에 기록됩니다(report_to="mlflow").
from sentence_transformers import SentenceTransformerTrainer, SentenceTransformerTrainingArguments, losses
from sentence_transformers.training_args import BatchSamplers
import gc

del app_model
gc.collect()
if torch.cuda.is_available():
    torch.cuda.empty_cache()
data = triplets.shuffle(seed=SEED)
model = load(BASE_MODEL)
args = SentenceTransformerTrainingArguments(
    output_dir="/tmp/hn-ft", num_train_epochs=EPOCHS,
    per_device_train_batch_size=8 if SMOKE else BATCH_SIZE, learning_rate=LEARNING_RATE,
    warmup_steps=0.1, fp16=device == "cuda", seed=SEED,
    # Two queries per document: the same document twice in a batch would be scored as a wrong answer for itself.
    batch_sampler=BatchSamplers.NO_DUPLICATES,
    eval_strategy="no", save_strategy="no", logging_steps=2 if SMOKE else 50, report_to=["mlflow"],
    run_name="ko-sroberta-hard-negatives", max_steps=3 if SMOKE else -1,
)
loss = losses.MultipleNegativesRankingLoss(model)
started = time.perf_counter()
SentenceTransformerTrainer(model=model, args=args, train_dataset=data, loss=loss).train()
minutes = round((time.perf_counter() - started) / 60, 1)
results["hn"] = {**evaluate(model), "triplets": len(data), "train_minutes": minutes}
mlflow.log_metrics({f"hn_{n.replace('@', '_at_')}": results["hn"][n] for n in NAMES})
mlflow.log_metrics({"train_minutes": minutes})
print(f"{len(data)} triplets, {minutes} min")
for name in ("base", "b", "hn"):
    print(name, {n: results[name][n] for n in NAMES})"""),
    ("code", """# 상담 19,206개를 새 모델로 임베딩해, 로컬 평가(scripts/evaluate_finetuned_embedding.py)가 읽는 모양으로 저장합니다.
import numpy as np
from pathlib import Path

out = Path("/tmp/hn-ft-out" if not SMOKE else "output/hn_smoke_out")
model.save(str(out))
ids = sorted(corpus, key=int)  # df.csv row order
started = time.perf_counter()
vectors = model.encode([corpus[i] for i in ids], batch_size=128, normalize_embeddings=True,
                       convert_to_numpy=True, show_progress_bar=True).astype(np.float32)
np.save(out / "corpus_embeddings.npy", vectors)
(out / "corpus_ids.json").write_text(json.dumps(ids))
encode_minutes = round((time.perf_counter() - started) / 60, 1)
(out / "finetune_results.json").write_text(json.dumps({"results": results, "smoke": SMOKE, "encode_minutes": encode_minutes,
    "settings": {"base": BASE_MODEL, "miner": APP_MODEL, "max_seq_length": MAX_SEQ_LENGTH, "batch_size": BATCH_SIZE,
                 "lr": LEARNING_RATE, "epochs": EPOCHS, "range": [RANGE_MIN, RANGE_MAX],
                 "relative_margin": RELATIVE_MARGIN, "num_negatives": NUM_NEGATIVES}}, indent=1))
mlflow.log_metric("encode_minutes", encode_minutes)
mlflow.log_artifact(str(out / "finetune_results.json"))
print(vectors.shape, f"{encode_minutes} min")"""),
    ("code", """# 비공개 저장소에 올리고 MLflow 실행을 닫습니다. 모델과 벡터: <사용자>/ko-sroberta-dograg-hn.
if not SMOKE:
    from huggingface_hub import HfApi
    api = HfApi(token=HF_TOKEN)
    repo = f"{api.whoami()['name']}/{HF_MODEL_REPO}"
    api.create_repo(repo, private=True, exist_ok=True)
    api.upload_folder(repo_id=repo, folder_path=str(out))
    mlflow.set_tag("hf_model", repo)
    print("uploaded", repo)
    del HF_TOKEN, api
# Close the run while the DagsHub token is still set (the KURE run removed it first: 403 on runs/update).
mlflow.end_run()
os.environ.pop("MLFLOW_TRACKING_PASSWORD", None)
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
