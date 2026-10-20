"""Write notebooks/rerank_colab.ipynb: rerankers on Colab's GPU over the judged candidate pools.

    uv run python scripts/build_rerank_notebook.py

Kept as code so the notebook can be regenerated and reviewed in diffs, like build_finetune_notebook.py.
SMOKE=True in the first code cell runs the same cells on a few questions with a tiny model (CPU is fine).
No OpenAI calls: the pools were graded once (scripts/relevance_set.py); a reranker only reorders them.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "notebooks" / "rerank_colab.ipynb"

CELLS = [
    ("markdown", """# 건강 검색 재정렬 실험 (Colab GPU)

운영 검색(Supabase 하이브리드)이 상위 3개에 바로 쓸모 있는 상담을 놓친 질문이 있습니다. 그 질문의 대부분은 후보 안에 쓸모 있는 상담이 있습니다(`기타` 100문항: 놓친 21개 중 14개). **후보 순서를 다시 매기는 리랭커가 이 차이를 메우는지** GPU에서 큰 모델로 잽니다.

- **OpenAI 호출은 없습니다.** 질문마다 후보 약 24개를 이미 한 번 채점해 두었습니다(`tests/data/health_relevance_*.json`, 2: 바로 쓸모, 1: 일부, 0: 아님). 리랭커는 그 후보의 순서만 바꾸고, 점수는 저장된 채점으로 셉니다.
- **세트:** 검증 100문항, 치과 10문항, `기타` 학습 질문 100문항, 라벨 있는 대조군 50문항.
- **기준선:** 운영 검색(`supabase`, 상위 12개 저장). 이것보다 나아야 의미가 있습니다.
- **배포 조건:** 예전 측정(ADR-0005)은 CPU 2코어에서 돌 수 있는 작은 ONNX 모델만 봤습니다. 여기서는 GPU로 더 큰 모델을 봅니다. 크게 나아지면 CPU용 경량화를 따로 따집니다. 마지막 셀이 **CPU 1스레드 시간**도 재 둡니다(Cloud Run API는 CPU 1개).
- **데이터:** 상담 원문(AI Hub)은 공개 저장소에 없어 비공개 데이터셋 `blanden77/dograg-data`에서 받습니다. 처음에 Hugging Face 토큰(읽기)을 입력합니다.
- **실행:** 런타임 → T4 GPU → 위에서부터 차례로 실행합니다. 마지막 셀이 만든 `rerank_results.json`을 내려받아 전달해 주세요.
"""),
    ("code", """# 설정: SMOKE=True면 세트마다 몇 문항과 작은 모델로 코드만 확인합니다(CPU도 가능).
SMOKE = False
BRANCH = "main"
DATA_REPO = "blanden77/dograg-data"   # 비공개 데이터셋 (src/private_data.py)
REVISION = "data-v11"
SETS = ["health_relevance_100", "health_relevance_dental", "health_relevance_train_etc", "health_relevance_train_labeled"]
# (모델, 라이선스 메모). 받을 수 없거나 실패한 모델은 건너뜁니다.
MODELS = [
    ("BAAI/bge-reranker-v2-m3", "Apache-2.0, 다국어 568M"),
    ("dragonkue/bge-reranker-v2-m3-ko", "bge-v2-m3 한국어 미세조정"),
    ("Alibaba-NLP/gte-multilingual-reranker-base", "Apache-2.0, 다국어 306M"),
    ("jinaai/jina-reranker-v2-base-multilingual", "비상업 라이선스: 참고용(ADR-0005의 0.76 모델)"),
]
SMOKE_MODEL = ("cross-encoder/ms-marco-MiniLM-L-2-v2", "코드 확인용")
ANSWER_CHARS = 300      # 채점자가 본 것과 같은 후보 글: 질문 + 답변 앞 300자
MAX_LENGTH = 512
BATCH_SIZE = 32
PROD_TOP = 12           # 운영 검색 상위 12개만 다시 정렬하는 경우
RRF_K = 60"""),
    ("code", """import subprocess, sys
print(sys.version)
try:
    print(subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv"], capture_output=True, text=True).stdout)
except FileNotFoundError:
    print("GPU 없음 (SMOKE 확인용으로만 사용)")"""),
    ("code", """# 저장소와 비공개 데이터 받기. 로컬에서 SMOKE로 돌릴 때는 저장소 루트에서 실행되므로 건너뜁니다.
import os
if os.path.exists("/content"):
    %cd /content
    !rm -rf dograg
    !git clone --depth 1 --branch {BRANCH} https://github.com/rndigkwk/dograg.git
    %cd /content/dograg
    !pip install -q "sentence-transformers>=5.1"
if not os.path.exists("data/df.csv"):
    from getpass import getpass
    token = None
    try:
        from google.colab import userdata
        token = userdata.get("HF_TOKEN")
    except Exception:
        pass
    token = token or getpass("Hugging Face 토큰: ")
    from huggingface_hub import snapshot_download
    snapshot_download(DATA_REPO, repo_type="dataset", revision=REVISION, token=token, local_dir=".",
                      allow_patterns=["data/df.csv", "data/df_val.csv"])
print(os.path.exists("data/df.csv"), os.path.exists("data/df_val.csv"))"""),
    ("code", """import csv, json, math, time
csv.field_size_limit(10**8)

def read_rows(path):
    # Rows by position, as pandas reads them: a set's "row" and a document id are positions.
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))

corpus = read_rows("data/df.csv")
validation = read_rows("data/df_val.csv")

def candidate_text(doc_id):
    row = corpus[int(doc_id)]
    answer = " ".join(row["qa.output"].split())[:ANSWER_CHARS]
    return f"질문: {' '.join(row['qa.input'].split())}\\n답변: {answer}"

sets = {}
for name in SETS:
    saved = json.load(open(f"tests/data/{name}.json", encoding="utf-8"))
    rows = corpus if "train" in name else validation
    items = []
    for item in saved["items"]:
        items.append({
            "row": item["row"],
            "question": " ".join(rows[item["row"]]["qa.input"].split()),
            "grades": item["grades"],
            "rankings": item["rankings"],
        })
    sets[name] = items[:4] if SMOKE else items
print({name: len(items) for name, items in sets.items()})"""),
    ("code", """# 지표: scripts/relevance_set.metrics와 같은 정의(상위 3개만). 대응 비교는 McNemar 정확 검정.
def top3_useful(item, ranking):
    return any(item["grades"].get(doc) == 2 for doc in ranking[:3])

def metrics(items, ranking_of):
    n = len(items)
    useful = relevant = precision = judged = shown = 0
    for item in items:
        top = ranking_of(item)[:3]
        grades = [item["grades"].get(doc) for doc in top]
        known = [g for g in grades if g is not None]
        judged += len(known); shown += len(top)
        useful += any(g == 2 for g in known)
        relevant += any(g >= 1 for g in known)
        precision += sum(g >= 1 for g in known) / 3
    return {"useful@3": round(useful / n, 3), "relevant@3": round(relevant / n, 3),
            "precision@3": round(precision / n, 3), "judged_share": round(judged / shown, 3) if shown else 0.0}

def mcnemar(items, base_of, new_of):
    wins = sum(top3_useful(i, new_of(i)) and not top3_useful(i, base_of(i)) for i in items)
    losses = sum(top3_useful(i, base_of(i)) and not top3_useful(i, new_of(i)) for i in items)
    n = wins + losses
    tail = sum(math.comb(n, k) for k in range(0, min(wins, losses) + 1)) / 2 ** n if n else 1.0
    return wins, losses, round(min(1.0, 2 * tail), 4)

prod = lambda item: item["rankings"]["supabase"]
results = {"baselines": {}, "models": {}}
for name, items in sets.items():
    results["baselines"][name] = {
        "supabase": metrics(items, prod),
        "local_hybrid": metrics(items, lambda i: i["rankings"]["hybrid"]),
        "pool_best": metrics(items, lambda i: sorted(i["grades"], key=lambda d: -i["grades"][d])),
    }
    print(name, results["baselines"][name])"""),
    ("code", """import torch
from sentence_transformers import CrossEncoder

device = "cuda" if torch.cuda.is_available() else "cpu"

def pools(item):
    graded = list(item["grades"])
    in_prod = [d for d in item["rankings"]["supabase"][:PROD_TOP] if d in item["grades"]]
    return graded, in_prod

def rrf(*rankings):
    score = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking):
            score[doc] = score.get(doc, 0.0) + 1 / (RRF_K + rank + 1)
    return sorted(score, key=lambda d: -score[d])

def run_model(name):
    kwargs = {"model_kwargs": {"torch_dtype": torch.float16}} if device == "cuda" else {}
    model = CrossEncoder(name, max_length=MAX_LENGTH, device=device, trust_remote_code=True, **kwargs)
    out, seconds = {}, []
    for set_name, items in sets.items():
        for item in items:
            graded, _ = pools(item)
            started = time.perf_counter()
            scores = model.predict([(item["question"], candidate_text(d)) for d in graded], batch_size=BATCH_SIZE)
            seconds.append(time.perf_counter() - started)
            item.setdefault("scores", {})[name] = dict(zip(graded, map(float, scores)))
    del model
    if device == "cuda":
        torch.cuda.empty_cache()
    return sorted(seconds)

def model_rankings(item, name):
    scores = item["scores"][name]
    graded, in_prod = pools(item)
    whole = sorted(graded, key=lambda d: -scores[d])
    prod_only = sorted(in_prod, key=lambda d: -scores[d])
    return {"rerank_pool": whole, "rerank_prod12": prod_only, "rrf_prod_rerank": rrf(prod(item)[:PROD_TOP], prod_only)}

models = [SMOKE_MODEL] if SMOKE else MODELS
for name, note in models:
    try:
        seconds = run_model(name)
    except Exception as error:
        print(f"건너뜀 {name}: {type(error).__name__}: {error}")
        continue
    entry = {"note": note, "device": device,
             "seconds_per_question_p50": round(seconds[len(seconds) // 2], 3),
             "seconds_per_question_p90": round(seconds[int(0.9 * (len(seconds) - 1))], 3), "sets": {}}
    for set_name, items in sets.items():
        entry["sets"][set_name] = {}
        for mode in ("rerank_pool", "rerank_prod12", "rrf_prod_rerank"):
            of = lambda i, mode=mode: model_rankings(i, name)[mode]
            wins, losses, p = mcnemar(items, prod, of)
            entry["sets"][set_name][mode] = {**metrics(items, of), "wins": wins, "losses": losses, "p": p}
    results["models"][name] = entry
    print(name, json.dumps(entry, ensure_ascii=False)[:600])"""),
    ("code", """# 표: 운영 검색 대비 useful@3 (wins/losses = 리랭커가 새로 맞힌/놓친 질문 수, p = McNemar)
rows = []
for name, entry in results["models"].items():
    for set_name, modes in entry["sets"].items():
        base = results["baselines"][set_name]["supabase"]["useful@3"]
        for mode, m in modes.items():
            rows.append((set_name.replace("health_relevance_", ""), name.split("/")[-1], mode, base, m["useful@3"],
                         round(m["useful@3"] - base, 3), f'{m["wins"]}/{m["losses"]}', m["p"], m["judged_share"]))
print(f"{'set':<14}{'model':<38}{'mode':<17}{'prod':>6}{'new':>7}{'diff':>7}{'w/l':>8}{'p':>8}{'judged':>8}")
for r in rows:
    print(f"{r[0]:<14}{r[1]:<38}{r[2]:<17}{r[3]:>6}{r[4]:>7}{r[5]:>+7}{r[6]:>8}{r[7]:>8}{r[8]:>8}")
for name, entry in results["models"].items():
    print(name, "질문당", entry["seconds_per_question_p50"], "초 (p50,", entry["device"] + ")")"""),
    ("code", """# CPU 1스레드 시간(Cloud Run API는 CPU 1개): 가장 나은 모델로 10문항. GPU 결과가 좋을 때만 의미가 있습니다.
best = max(results["models"], default=None,
           key=lambda n: results["models"][n]["sets"]["health_relevance_100"]["rerank_prod12"]["useful@3"])
if best:
    torch.set_num_threads(1)
    cpu_model = CrossEncoder(best, max_length=MAX_LENGTH, device="cpu", trust_remote_code=True)
    sample = sets["health_relevance_100"][:3 if SMOKE else 10]
    seconds = []
    for item in sample:
        _, in_prod = pools(item)
        started = time.perf_counter()
        cpu_model.predict([(item["question"], candidate_text(d)) for d in in_prod], batch_size=BATCH_SIZE)
        seconds.append(time.perf_counter() - started)
    results["cpu_one_thread"] = {"model": best, "candidates": PROD_TOP,
                                 "seconds_per_question_p50": round(sorted(seconds)[len(seconds) // 2], 2)}
    print(results["cpu_one_thread"])"""),
    ("code", """# 결과 저장: 이 파일을 내려받아 전달해 주세요(후보 글이나 질문 원문은 들어 있지 않습니다).
results["config"] = {"smoke": SMOKE, "answer_chars": ANSWER_CHARS, "max_length": MAX_LENGTH, "prod_top": PROD_TOP,
                     "sets": {name: len(items) for name, items in sets.items()}}
with open("rerank_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=1)
print("saved rerank_results.json")
try:
    from google.colab import files
    files.download("rerank_results.json")
except Exception:
    pass"""),
]


def notebook() -> dict:
    cells = []
    for kind, text in CELLS:
        cell = {"cell_type": kind, "metadata": {}, "source": text.splitlines(keepends=True)}
        if kind == "code":
            cell.update(outputs=[], execution_count=None)
        cells.append(cell)
    return {"cells": cells, "metadata": {"accelerator": "GPU", "colab": {"gpuType": "T4", "provenance": []},
                                         "kernelspec": {"display_name": "Python 3", "name": "python3"},
                                         "language_info": {"name": "python"}},
            "nbformat": 4, "nbformat_minor": 0}


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(notebook(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
