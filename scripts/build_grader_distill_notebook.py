"""Write notebooks/grader_distill_colab.ipynb: the CRAG evidence grader distilled into a small cross-encoder (Colab GPU).

    uv run python scripts/build_grader_distill_notebook.py

Why: every health answer waits for one grader call (src/crag.py grade_documents, p90 2.4s, about
2.3k tokens) that only decides which of 5 candidates to keep; with none kept the graph rewrites the
query once and then abstains (src/chat_graph.py route_after_health_grade). A cross-encoder that reads
(question, 400-character excerpt) pairs could make that decision on the API's CPU without a model call.

No OpenAI calls. Training labels are the relevance judge's grades already stored for 150 training
questions (tests/data/health_relevance_train_*.json, about 22 candidates each, 0/1/2; target: 1 or more,
the grader's "helps with any part"). Thresholds are chosen on the validation questions' grades
(health_relevance_100 + dental, without the test questions). The test is what the real grader kept on
100 other validation questions (tests/data/crag_grader_labels.json): pair agreement, AUC, and the
decision that matters (keep none -> rewrite/abstain). A second stage fine-tunes the chosen model on
those grader labels with 5-fold cross-validation by question, to see how far grader labels move it.
The last cells export ONNX int8, time it on one CPU thread (the API has one CPU), log everything to
MLflow on DagsHub, and upload the chosen model to a private Hugging Face repo. SMOKE=True runs the same
cells on a few questions on CPU and logs to a local folder.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "notebooks" / "grader_distill_colab.ipynb"

CELLS = [
    ("markdown", """# 근거 채점기 증류: OpenAI 채점 호출을 작은 한국어 cross-encoder로 (Colab GPU, MLflow 기록)

건강 답변은 매번 **근거 채점 호출 1번**을 기다립니다(`src/crag.py`, p90 2.4초, 약 2.3k 토큰). 이 호출이 하는 일은 검색 후보 5개 중 쓸모 있는 것을 고르는 것이고, 하나도 없으면 검색어를 한 번 바꾼 뒤 보류합니다. 같은 판단을 **질문과 후보 글을 함께 읽는 작은 모델(cross-encoder)** 이 API의 CPU에서 할 수 있는지 잽니다.

- **OpenAI 호출 없음.** 학습 라벨은 이미 저장된 관련도 채점입니다(`tests/data/health_relevance_train_*.json`, 학습 질문 150개 × 후보 약 22개, 0/1/2점). 목표는 1점 이상(채점기 기준 "질문의 일부에라도 도움")입니다.
- **나누기:** 학습은 학습 상담 질문, 임계값 선택(dev)은 검증 질문의 관련도 채점, **시험은 실제 CRAG 채점기가 고른 결과**(검증 질문 100개 × 후보 5개, `tests/data/crag_grader_labels.json`)입니다. dev와 시험 질문은 겹치지 않게 뺐습니다.
- **볼 지표:** 시험에서 채점기와의 후보 단위 일치·AUC, 그리고 앱 동작을 바꾸는 **질문 단위 판단(하나도 안 고름 → 다시 검색·보류)** 일치. 확신할 때만 작은 모델이 판단하고 나머지는 채점기를 부르면 **호출을 몇 % 줄이는지**도 셉니다.
- **2단계:** 고른 모델을 채점기 라벨로 한 번 더 학습합니다(질문 단위 5겹 교차 검증). 채점기 라벨을 더 모을 가치가 있는지 판단하는 근거입니다.
- **배포 조건:** API는 CPU 1개입니다. ONNX int8로 바꿔 **CPU 1스레드에서 질문 1개(후보 5개) 시간**을 잽니다. 로컬 SMOKE에서 `klue/roberta-small`(68M) int8이 512토큰 p50 3.2초, 256토큰 1.6초로 채점기 호출(p90 2.4초)과 비슷했습니다. 그래서 14M짜리 KoELECTRA-small을 1순위로 두고 입력을 384토큰으로 줄였고, p90 1초 이하만 배포 후보로 봅니다. 같은 int8 모델을 256토큰으로도 잘라 시간과 지표를 함께 셉니다. Colab CPU와 Cloud Run CPU는 달라 시간은 참고값입니다.
- **기록:** 설정, 에폭별 dev 손실·AUC, 시험 지표, 시간을 **MLflow(DagsHub)** 에 남깁니다. 고른 모델은 Hugging Face 비공개 저장소에 올립니다.
- **토큰 두 개:** Hugging Face(쓰기)와 DagsHub. Colab Secrets에 `HF_TOKEN`, `DAGSHUB_TOKEN`으로 넣거나 실행 중 입력합니다. 화면에는 길이만 표시합니다.
- **실행:** 런타임 → GPU(T4 이상) → 위에서부터 차례로. 마지막 셀이 만든 `grader_distill_results.json`을 내려받아 전달해 주세요.
"""),
    ("code", """# 설정: SMOKE=True면 몇 문항과 작은 모델 하나로 코드만 확인합니다(CPU 가능, MLflow는 로컬 폴더).
SMOKE = False
BRANCH = "main"
DATA_REPO, REVISION = "blanden77/dograg-data", "data-v11"   # src/private_data.py
# (모델, 메모). CPU 1개에서 돌 수 있는 작은 모델이 목표이고, 큰 리랭커는 GPU 상한으로만 봅니다.
MODELS = [
    ("monologg/koelectra-small-v3-discriminator", "14M, CPU 1개용 가장 작은 후보"),
    ("klue/roberta-small", "68M, CPU 후보"),
    ("klue/roberta-base", "110M, CPU 후보"),
    ("dragonkue/bge-reranker-v2-m3-ko", "568M 한국어 리랭커, 상한 참고"),
]
SMOKE_MODELS = [("monologg/koelectra-small-v3-discriminator", "코드 확인용")]
EXCERPT_CHARS = 400       # 채점기가 보는 길이(src/crag.py EXCERPT_CHARS)
POOL = 5                  # 채점기가 보는 후보 수(HEALTH_CANDIDATE_K)
MAX_LENGTH = 384          # 질문+후보 쌍의 중앙값이 약 330토큰입니다. 512는 CPU에서 너무 느렸습니다(아래 설명)
TARGET = {0: 0.0, 1: 1.0, 2: 1.0}   # 관련도 점수 -> 학습 목표
EPOCHS = 3
BATCH_SIZE = 16
LEARNING_RATES = {"dragonkue/bge-reranker-v2-m3-ko": 1e-5}   # 나머지는 2e-5
WARMUP = 0.1
SEED = 13
CV_FOLDS, CV_EPOCHS, CV_LR = 5, 2, 1e-5   # 2단계: 채점기 라벨로 질문 단위 교차 검증
CONFIDENT_AGREEMENT = 0.95   # dev에서 이 일치율 이상인 구간만 '확신'으로 봅니다
ONNX_LENGTHS = (MAX_LENGTH, 256)   # int8 모델을 이 길이들로 잘라 시간과 지표를 셉니다
LATENCY_BUDGET = 1.0         # CPU 1스레드, 질문 1개(후보 5개) p90 초. 채점기 p90 2.4초의 절반 아래만 배포 후보로 봅니다
HF_MODEL_REPO = "ko-grader-dograg"   # <사용자>/ko-grader-dograg (비공개)
MLFLOW_URI = "https://dagshub.com/rndigkwk/dograg.mlflow"
MLFLOW_USER = "rndigkwk"
EXPERIMENT = "crag-grader-distill\""""),
    ("code", """import os, sys
if os.path.exists("/content"):
    %cd /content
    !rm -rf dograg
    !git clone -q --depth 1 --branch {BRANCH} https://github.com/rndigkwk/dograg.git
    %cd /content/dograg
    !pip -q install -U "transformers>=4.56" "mlflow>=3.4" onnx onnxruntime huggingface_hub scikit-learn
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
import torch
print(sys.version, torch.__version__, torch.cuda.get_device_name(0) if torch.cuda.is_available() else "GPU 없음 (SMOKE만 가능)")
if not SMOKE:
    assert torch.cuda.is_available(), "런타임 유형을 GPU로 바꾸세요\""""),
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
    os.environ["MLFLOW_TRACKING_PASSWORD"] = secret("DAGSHUB_TOKEN", "DagsHub 토큰: ")"""),
    ("code", """# 데이터: 상담(df.csv)과 검증 질문(df_val.csv)은 위치로 읽습니다. 세트의 row와 후보 id가 위치입니다.
import csv, json, random
from huggingface_hub import hf_hub_download

def data_file(name):
    if os.path.exists(name):
        return name
    return hf_hub_download(DATA_REPO, name, repo_type="dataset", revision=REVISION, token=HF_TOKEN)

def read_rows(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))

csv.field_size_limit(10**8)
corpus = read_rows(data_file("data/df.csv"))
validation = read_rows(data_file("data/df_val.csv"))
clean = lambda text: str(text).replace(chr(13), "")

def candidate_text(doc_id):
    # What the grader reads for one candidate (src/chat_graph.py _health_text, cut by format_candidates).
    row = corpus[int(doc_id)]
    return f"질문: {clean(row['qa.input'])}\\n답변: {clean(row['qa.output'])}"[:EXCERPT_CHARS]

def load(name):
    return json.load(open(f"tests/data/{name}.json", encoding="utf-8"))["items"]

grader = load("crag_grader_labels")
test_rows = {item["row"] for item in grader}

def graded_items(names, rows, skip_rows=()):
    items = []
    for name in names:
        for item in load(name):
            if item["row"] in skip_rows:
                continue
            candidates = [doc for doc in item["grades"] if not ("train" in name and int(doc) == item["row"])]
            items.append({"question": clean(rows[item["row"]]["qa.input"]), "candidates": candidates,
                          "labels": [TARGET[item["grades"][doc]] for doc in candidates]})
    return items

train = graded_items(["health_relevance_train_etc", "health_relevance_train_labeled"], corpus)
dev = graded_items(["health_relevance_100", "health_relevance_dental"], validation, skip_rows=test_rows)
test = [{"question": clean(validation[item["row"]]["qa.input"]), "candidates": item["candidates"],
         "labels": [float(doc in item["useful_ids"]) for doc in item["candidates"]]} for item in grader]
if SMOKE:
    train, dev, test = train[:8], dev[:4], test[:10]
for name, items in (("train", train), ("dev", dev), ("test", test)):
    pairs = sum(len(i["candidates"]) for i in items)
    positive = sum(sum(i["labels"]) for i in items)
    print(f"{name}: {len(items)} questions, {pairs} pairs, positive {positive / pairs:.2f}")
print("test questions with nothing kept by the grader:", sum(not any(i["labels"]) for i in test))"""),
    ("code", """# 점수와 지표. 점수는 sigmoid(logit). 질문 단위 판단: 임계값을 넘는 후보가 하나도 없으면 '안 고름'.
import math, time
import numpy as np
from sklearn.metrics import roc_auc_score
from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

device = "cuda" if torch.cuda.is_available() else "cpu"
TYPES = False   # 모델마다 정합니다: 문장 구분 id(token_type_ids)는 ELECTRA만 쓰고 RoBERTa 계열은 쓰지 않습니다
torch.manual_seed(SEED); random.seed(SEED)

def pairs_of(items):
    return [(i["question"], candidate_text(doc)) for i in items for doc in i["candidates"]]

def labels_of(items):
    return np.array([label for i in items for label in i["labels"]])

@torch.no_grad()
def predict(model, tokenizer, pairs, batch_size=64):
    model.eval()
    scores = []
    for start in range(0, len(pairs), batch_size):
        chunk = pairs[start:start + batch_size]
        enc = tokenizer([q for q, _ in chunk], [d for _, d in chunk], truncation="longest_first",
                        max_length=MAX_LENGTH, padding=True, return_token_type_ids=TYPES, return_tensors="pt").to(device)
        with torch.autocast(device_type=device, enabled=device == "cuda"):
            logits = model(**enc).logits.float().reshape(-1)
        scores.append(torch.sigmoid(logits).cpu().numpy())
    return np.concatenate(scores) if scores else np.array([])

def split_by_question(items, scores):
    out, start = [], 0
    for item in items:
        out.append(scores[start:start + len(item["candidates"])]); start += len(item["candidates"])
    return out

def best_threshold(labels, scores):
    # Threshold with the best F1 against the dev grades (the grader's kept set is the positive class).
    best = (0.0, 0.5)
    for t in np.unique(np.round(scores, 3)):
        predicted = scores >= t
        tp = (predicted & (labels > 0.5)).sum()
        f1 = 2 * tp / (predicted.sum() + (labels > 0.5).sum()) if predicted.sum() else 0.0
        best = max(best, (f1, float(t)))
    return best[1]

def kappa(a, b):
    a, b = np.asarray(a, bool), np.asarray(b, bool)
    observed = (a == b).mean()
    expected = a.mean() * b.mean() + (1 - a.mean()) * (1 - b.mean())
    return float((observed - expected) / (1 - expected)) if expected < 1 else 1.0

def evaluate(items, scores, threshold):
    labels = labels_of(items) > 0.5
    predicted = scores >= threshold
    tp = int((predicted & labels).sum())
    by_question = split_by_question(items, scores)
    none_true = [not any(i["labels"]) for i in items]
    none_pred = [not (s >= threshold).any() for s in by_question]
    exact = [set(np.flatnonzero(s >= threshold)) == set(np.flatnonzero(np.array(i["labels"]) > 0.5))
             for i, s in zip(items, by_question)]
    return {
        "pair_accuracy": round(float((predicted == labels).mean()), 3),
        "pair_kappa": round(kappa(predicted, labels), 3),
        "precision": round(tp / predicted.sum(), 3) if predicted.sum() else 0.0,
        "recall": round(tp / labels.sum(), 3) if labels.sum() else 0.0,
        "auc": round(float(roc_auc_score(labels, scores)), 3) if 0 < labels.sum() < len(labels) else None,
        "keep_rate": round(float(predicted.mean()), 3),
        "decision_agreement": round(float(np.mean([a == b for a, b in zip(none_true, none_pred)])), 3),
        "none_true": int(sum(none_true)), "none_pred": int(sum(none_pred)),
        "none_both": int(sum(a and b for a, b in zip(none_true, none_pred))),
        "exact_set": round(float(np.mean(exact)), 3),
    }

def confident_band(labels, scores, threshold):
    # Smallest margin m such that dev pairs scored outside [t - m, t + m] agree with the labels at
    # CONFIDENT_AGREEMENT or more: inside the band the app would still call the grader.
    for m in np.arange(0.0, 0.5, 0.01):
        outside = np.abs(scores - threshold) > m
        if outside.sum() and ((scores[outside] >= threshold) == (labels[outside] > 0.5)).mean() >= CONFIDENT_AGREEMENT:
            return round(float(m), 2)
    return 0.5

def calls_saved(items, scores, threshold, margin):
    # A question skips the grader when all of its candidates are outside the band.
    by_question = split_by_question(items, scores)
    confident = [bool((np.abs(s - threshold) > margin).all()) for s in by_question]
    agree = [set(np.flatnonzero(s >= threshold)) == set(np.flatnonzero(np.array(i["labels"]) > 0.5))
             for i, s in zip(items, by_question)]
    decided = [a for a, c in zip(agree, confident) if c]
    return {"skip_share": round(float(np.mean(confident)), 3),
            "exact_set_when_skipped": round(float(np.mean(decided)), 3) if decided else None,
            "skipped": int(sum(confident))}

baseline = {"keep_all": evaluate(test, np.ones(len(labels_of(test))), 0.5)}
print("baseline keep all 5:", baseline["keep_all"])"""),
    ("code", """# MLflow: 부모 실행 하나에 모델마다 자식 실행을 둡니다.
import mlflow
from pathlib import Path
mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
if SMOKE and mlflow.get_experiment_by_name(EXPERIMENT) is None:  # artifacts under output/, not ./mlruns
    Path("output").mkdir(exist_ok=True)
    mlflow.create_experiment(EXPERIMENT, artifact_location=Path("output/smoke_mlartifacts").resolve().as_uri())
mlflow.set_experiment(EXPERIMENT)
parent = mlflow.start_run(run_name="grader-distill" + ("-smoke" if SMOKE else ""))
mlflow.log_params({"pool": POOL, "excerpt_chars": EXCERPT_CHARS, "max_length": MAX_LENGTH, "epochs": EPOCHS,
                   "batch_size": BATCH_SIZE, "target": json.dumps(TARGET), "seed": SEED, "smoke": SMOKE,
                   "train_questions": len(train), "dev_questions": len(dev), "test_questions": len(test)})
mlflow.log_metrics({f"keep_all_{k}": v for k, v in baseline["keep_all"].items() if isinstance(v, (int, float))})
print("MLflow run", parent.info.run_id)"""),
    ("code", """# 1단계: 관련도 채점으로 학습. 에폭마다 dev AUC를 보고 가장 좋은 에폭의 가중치를 남깁니다.
import copy, gc

def train_model(model, tokenizer, items, epochs, lr, log_prefix=None):
    pairs, labels = pairs_of(items), labels_of(items)
    order = list(range(len(pairs)))
    steps = epochs * math.ceil(len(pairs) / BATCH_SIZE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    schedule = get_linear_schedule_with_warmup(optimizer, int(WARMUP * steps), steps)
    scaler = torch.amp.GradScaler(enabled=device == "cuda")
    loss_fn = torch.nn.BCEWithLogitsLoss()
    best = (-1.0, None, 0)
    for epoch in range(epochs):
        model.train(); random.shuffle(order); total = 0.0
        for start in range(0, len(order), BATCH_SIZE):
            batch = order[start:start + BATCH_SIZE]
            enc = tokenizer([pairs[i][0] for i in batch], [pairs[i][1] for i in batch], truncation="longest_first",
                            max_length=MAX_LENGTH, padding=True, return_token_type_ids=TYPES, return_tensors="pt").to(device)
            target = torch.tensor(labels[batch], dtype=torch.float32, device=device)
            with torch.autocast(device_type=device, enabled=device == "cuda"):
                logits = model(**enc).logits.float().reshape(-1)
            loss = loss_fn(logits, target)
            optimizer.zero_grad(); scaler.scale(loss).backward(); scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer); scaler.update(); schedule.step()
            total += loss.item() * len(batch)
        if log_prefix is None:
            continue
        dev_scores = predict(model, tokenizer, pairs_of(dev))
        dev_labels = labels_of(dev) > 0.5
        auc = float(roc_auc_score(dev_labels, dev_scores)) if 0 < dev_labels.sum() < len(dev_labels) else 0.0
        mlflow.log_metrics({"train_loss": total / len(pairs), "dev_auc": auc}, step=epoch + 1)
        print(f"  {log_prefix} epoch {epoch + 1}: loss {total / len(pairs):.4f}, dev AUC {auc:.3f}")
        if auc > best[0]:
            best = (auc, copy.deepcopy(model.state_dict()), epoch + 1)
    if best[1] is not None:
        model.load_state_dict(best[1])
    return best[2]

def scored(model, tokenizer):
    dev_scores, test_scores = predict(model, tokenizer, pairs_of(dev)), predict(model, tokenizer, pairs_of(test))
    threshold = best_threshold(labels_of(dev), dev_scores)
    margin = confident_band(labels_of(dev), dev_scores, threshold)
    return {"threshold": threshold, "margin": margin, "dev": evaluate(dev, dev_scores, threshold),
            "test": evaluate(test, test_scores, threshold), "calls": calls_saved(test, test_scores, threshold, margin)}

results, saved = {"baseline": baseline, "models": {}}, {}
for name, note in (SMOKE_MODELS if SMOKE else MODELS):
    short = name.split("/")[-1]
    try:
        tokenizer = AutoTokenizer.from_pretrained(name)
        model = AutoModelForSequenceClassification.from_pretrained(name, num_labels=1, ignore_mismatched_sizes=True).to(device)
    except Exception as error:   # a model that cannot be downloaded is skipped, as in rerank_colab
        print("skip", name, error); continue
    lr = LEARNING_RATES.get(name, 2e-5)
    TYPES = model.config.type_vocab_size > 1
    with mlflow.start_run(run_name=short, nested=True):
        mlflow.log_params({"model": name, "note": note, "lr": lr, "parameters": sum(p.numel() for p in model.parameters())})
        before = scored(model, tokenizer)   # untrained head: meaningful only for the reranker
        started = time.perf_counter()
        best_epoch = train_model(model, tokenizer, train, 1 if SMOKE else EPOCHS, lr, log_prefix=short)
        minutes = round((time.perf_counter() - started) / 60, 1)
        after = scored(model, tokenizer)
        mlflow.log_metrics({"train_minutes": minutes, "best_epoch": best_epoch, "threshold": after["threshold"],
                            "margin": after["margin"]})
        for split in ("dev", "test", "calls"):
            mlflow.log_metrics({f"{split}_{k}": v for k, v in after[split].items() if isinstance(v, (int, float))})
    results["models"][name] = {"note": note, "before": before, "after": after, "train_minutes": minutes, "best_epoch": best_epoch}
    out = Path(f"output/grader_{short}")
    model.save_pretrained(out); tokenizer.save_pretrained(out)
    saved[name] = out
    print(name, "test", after["test"], "calls", after["calls"])
    del model; gc.collect(); torch.cuda.empty_cache() if device == "cuda" else None"""),
    ("code", """# ONNX int8로 바꾸고 CPU 1스레드에서 질문 1개(후보 5개) 시간을 잽니다. int8 점수로 시험 지표도 다시 셉니다.
import onnxruntime as ort
from onnxruntime.quantization import QuantType, quantize_dynamic
from tokenizers import Tokenizer

def export_int8(folder):
    global TYPES
    model = AutoModelForSequenceClassification.from_pretrained(folder, attn_implementation="eager").eval()
    TYPES = model.config.type_vocab_size > 1
    tokenizer = AutoTokenizer.from_pretrained(folder)
    enc = tokenizer(["질문"], ["문서"], return_token_type_ids=TYPES, return_tensors="pt")
    names = [n for n in ("input_ids", "attention_mask", "token_type_ids") if n in enc]
    fp32, int8 = folder / "model.onnx", folder / "model_int8.onnx"
    axes = {n: {0: "batch", 1: "sequence"} for n in names} | {"logits": {0: "batch"}}
    torch.onnx.export(model, tuple(enc[n] for n in names), str(fp32), input_names=names, output_names=["logits"],
                      dynamic_axes=axes, opset_version=17, dynamo=False)
    quantize_dynamic(str(fp32), str(int8), weight_type=QuantType.QInt8)
    fp32.unlink()
    return int8

def onnx_scores(path, folder, items, max_length):
    options = ort.SessionOptions(); options.intra_op_num_threads = 1; options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
    inputs = {i.name for i in session.get_inputs()}
    tokenizer = Tokenizer.from_file(str(folder / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=max_length, strategy="longest_first"); tokenizer.enable_padding()
    scores, seconds = [], []
    for item in items:
        started = time.perf_counter()
        encodings = tokenizer.encode_batch([(item["question"], candidate_text(doc)) for doc in item["candidates"]])
        feeds = {"input_ids": np.array([e.ids for e in encodings], dtype=np.int64),
                 "attention_mask": np.array([e.attention_mask for e in encodings], dtype=np.int64)}
        if "token_type_ids" in inputs:
            feeds["token_type_ids"] = np.array([e.type_ids for e in encodings], dtype=np.int64)
        logits = session.run(None, feeds)[0].reshape(-1)
        seconds.append(time.perf_counter() - started)
        scores.append(1 / (1 + np.exp(-logits)))
    return np.concatenate(scores), seconds

for name, folder in saved.items():
    entry = results["models"][name]
    try:
        path = export_int8(folder)
    except Exception as error:
        print("export failed", name, error); entry["onnx"] = {"error": str(error)[:300]}; continue
    threshold = entry["after"]["threshold"]
    by_length = {}
    for length in ONNX_LENGTHS:
        scores, seconds = onnx_scores(path, folder, test, length)
        by_length[length] = {"cpu1_p50": round(float(np.percentile(seconds, 50)), 3),
                             "cpu1_p90": round(float(np.percentile(seconds, 90)), 3),
                             "test": evaluate(test, scores, threshold),
                             "calls": calls_saved(test, scores, threshold, entry["after"]["margin"])}
    # The training length decides the deployment check; the shorter one shows what cutting costs.
    entry["onnx"] = {"int8_mb": round(path.stat().st_size / 2**20, 1), **by_length[MAX_LENGTH],
                     "by_length": {str(k): v for k, v in by_length.items()}}
    with mlflow.start_run(run_name=name.split("/")[-1] + "-onnx", nested=True):
        mlflow.log_param("model", name)
        mlflow.log_metric("int8_mb", entry["onnx"]["int8_mb"])
        for length, found in by_length.items():
            mlflow.log_metrics({f"len{length}_cpu1_p50": found["cpu1_p50"], f"len{length}_cpu1_p90": found["cpu1_p90"]}
                               | {f"len{length}_test_{k}": v for k, v in found["test"].items() if isinstance(v, (int, float))})
    print(name, entry["onnx"])"""),
    ("code", """# 배포 후보 고르기: CPU 1스레드 p90이 예산 안인 모델 중 dev AUC가 가장 높은 것(시험 라벨은 보지 않습니다).
fits = [n for n, e in results["models"].items() if "cpu1_p90" in e.get("onnx", {}) and e["onnx"]["cpu1_p90"] <= LATENCY_BUDGET]
chosen = max(fits, key=lambda n: results["models"][n]["after"]["dev"]["auc"] or 0) if fits else None
results["chosen"] = chosen
print("chosen:", chosen)"""),
    ("code", """# 2단계: 고른 모델을 채점기 라벨로 한 번 더 학습(질문 단위 5겹). 접힌 질문의 점수만 모아 지표를 셉니다.
if chosen:
    folds = [test[i::CV_FOLDS] for i in range(CV_FOLDS)]
    held_items, held_scores = [], []
    tokenizer = AutoTokenizer.from_pretrained(saved[chosen])
    TYPES = AutoModelForSequenceClassification.from_pretrained(saved[chosen]).config.type_vocab_size > 1
    for k in range(CV_FOLDS):
        model = AutoModelForSequenceClassification.from_pretrained(saved[chosen]).to(device)
        train_model(model, tokenizer, [i for j, f in enumerate(folds) if j != k for i in f], 1 if SMOKE else CV_EPOCHS, CV_LR)
        held_items += folds[k]; held_scores.append(predict(model, tokenizer, pairs_of(folds[k])))
        del model; gc.collect()
    held_scores = np.concatenate(held_scores)
    threshold = results["models"][chosen]["after"]["threshold"]
    # test: the dev threshold, as deployed. test_oracle_threshold: tuned on these labels, an upper bound only.
    results["grader_cv"] = {"folds": CV_FOLDS, "epochs": CV_EPOCHS, "lr": CV_LR,
                            "test": evaluate(held_items, held_scores, threshold),
                            "test_oracle_threshold": evaluate(held_items, held_scores, best_threshold(labels_of(held_items), held_scores))}
    mlflow.log_metrics({f"cv_{k}": v for k, v in results["grader_cv"]["test"].items() if isinstance(v, (int, float))})
    print("grader-label CV:", results["grader_cv"])"""),
    ("code", """# 결과 저장, 고른 모델을 비공개 저장소에 올리고 MLflow 실행을 닫습니다.
Path("output").mkdir(exist_ok=True)
results["settings"] = {"pool": POOL, "excerpt_chars": EXCERPT_CHARS, "max_length": MAX_LENGTH, "epochs": EPOCHS,
                       "batch_size": BATCH_SIZE, "target": TARGET, "seed": SEED, "latency_budget": LATENCY_BUDGET,
                       "confident_agreement": CONFIDENT_AGREEMENT, "smoke": SMOKE, "device": torch.cuda.get_device_name(0) if device == "cuda" else "cpu"}
Path("output/grader_distill_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
mlflow.log_artifact("output/grader_distill_results.json")
if chosen and not SMOKE:
    from huggingface_hub import HfApi
    api = HfApi(token=HF_TOKEN)
    repo = f"{api.whoami()['name']}/{HF_MODEL_REPO}"
    api.create_repo(repo, private=True, exist_ok=True)
    folder = saved[chosen]
    (folder / "grader_distill_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    api.upload_folder(repo_id=repo, folder_path=str(folder), ignore_patterns=["model.safetensors"])
    mlflow.set_tag("hf_model", repo)
    print("uploaded", repo, "from", chosen)
    del HF_TOKEN, api
# Close the run while the DagsHub token is still set (the KURE run removed it first: 403 on runs/update).
mlflow.end_run()
os.environ.pop("MLFLOW_TRACKING_PASSWORD", None)
if os.path.exists("/content"):
    from google.colab import files
    files.download("output/grader_distill_results.json")
print("done:", parent.info.run_id)"""),
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
