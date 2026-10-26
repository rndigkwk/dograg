"""Write notebooks/kb_ocr_gpu_colab.ipynb: the KB report pages read again by GPU OCR and a vision model (Colab).

    uv run python scripts/build_kb_ocr_gpu_notebook.py

Why: the KB report's figures are set in a font without Unicode digits, so the report search uses
Tesseract OCR of 93 pages (scripts/ocr_kb_report.py, scripts/add_kb_ocr_chunks.py). Tesseract misreads
some figures digit by digit ("59.2%" for 39.2% on p.7 and p.28, "589만" for 585만 on p.14); nine were
found by hand and are patched in add_kb_ocr_chunks.OCR_CORRECTIONS, others may remain. This notebook
reads the same pages with EasyOCR (GPU) and a vision-language model (Qwen-VL) and compares, without
ground truth for every figure:
- the nine hand-checked misreads: does the engine read the right figure, and not the wrong one?
- the reference answers' figures (tests/data/report_reference_answers.json) on their KB gold pages;
- figures each engine reads that no other engine reads (for the vision model: possibly invented);
- Tesseract's systematic misreads (a year's 년 read as digits, a share of 101-999%).
No OpenAI calls. The page texts stay private (the report and its OCR are in the private dataset): the
notebook writes them to output/ and the private Hugging Face repo, and only the scores go to MLflow.
SMOKE=True runs the same cells on two pages on CPU with a tiny vision model.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "notebooks" / "kb_ocr_gpu_colab.ipynb"

CELLS = [
    ("markdown", """# KB 보고서 숫자 다시 읽기: GPU OCR과 비전 모델 비교 (Colab GPU, MLflow 기록)

KB `2025 한국 반려동물 보고서`는 숫자를 유니코드가 없는 글꼴로 넣어 PDF 글에서 숫자가 빠집니다. 그래서 보고서 검색은 **Tesseract OCR로 다시 읽은 93쪽**을 씁니다(`scripts/ocr_kb_report.py`, `scripts/add_kb_ocr_chunks.py`). 그런데 Tesseract는 숫자를 한 자씩 잘못 읽기도 해서(p.7·p.28 `39.2%` → `59.2%`, p.14 `585만` → `589만`) 손으로 찾은 9건을 고쳐 넣었고, 남은 오독이 더 있을 수 있습니다.

같은 93쪽을 **EasyOCR(GPU)** 와 **비전 언어 모델(Qwen-VL)** 로 다시 읽어 비교합니다. 모든 숫자의 정답은 없으므로 이렇게 잽니다.

- **손으로 확인한 오독 9건:** 맞는 숫자를 읽고, 틀린 숫자는 읽지 않았는가
- **기준 답변의 숫자:** `tests/data/report_reference_answers.json`의 KB 정답 페이지에서 그 숫자가 나오는가
- **혼자만 읽은 숫자:** 다른 엔진 어디에도 없는 숫자(비전 모델이면 지어냈을 가능성)
- **Tesseract식 체계적 오독:** 연도 뒤 `년`을 숫자로 읽음(`202344`), 101~999% 같은 불가능한 비율

- **OpenAI 호출 없음.** 페이지 글은 비공개 데이터라 `output/`과 Hugging Face 비공개 저장소에만 두고, **MLflow(DagsHub)에는 점수만** 남깁니다.
- **GPU:** 비전 모델 8B는 L4(24GB) 이상, T4(16GB)면 설정의 작은 모델로 바뀝니다. 93쪽에 L4 기준 약 30~50분.
- **토큰 두 개:** Hugging Face(쓰기)와 DagsHub. Colab Secrets에 `HF_TOKEN`, `DAGSHUB_TOKEN`으로 넣거나 실행 중 입력합니다.
- **실행:** 런타임 → GPU → 위에서부터 차례로. 마지막 셀이 만든 `kb_ocr_gpu_scores.json`을 내려받아 전달해 주세요(점수만, 페이지 글 없음).
"""),
    ("code", """# 설정: SMOKE=True면 두 쪽과 작은 모델로 코드만 확인합니다(CPU 가능, MLflow는 로컬 폴더).
SMOKE = False
BRANCH = "main"
DATA_REPO, REVISION = "blanden77/dograg-data", "data-v11"   # src/private_data.py
PDF = "data/source/2025 한국 반려동물 보고서.pdf"
TESSERACT_FILE = "data/source/kb_report_ocr.json"           # 지금 검색이 쓰는 OCR(Tesseract kor+eng, 300 dpi)
# scripts/add_kb_ocr_chunks.ocr_pages (2026-10-26): OCR 조각을 만드는 93쪽
PAGES = [4, 5, 6, 7, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 34, 35,
         36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 52, 53, 54, 55, 56, 57, 59, 60, 61, 62, 63, 64, 65,
         66, 67, 68, 69, 70, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 84, 85, 86, 87, 88, 89, 90, 91, 94, 95, 96,
         97, 99, 100, 101, 102, 103, 104, 105, 108, 109, 110, 111]
SMOKE_PAGES = [7, 14]
DPI = 200
# (모델, 필요한 GPU 메모리 GB). 앞에서부터 GPU에 맞고 받을 수 있는 첫 모델을 씁니다.
VLM_MODELS = [("Qwen/Qwen3-VL-8B-Instruct", 22), ("Qwen/Qwen2.5-VL-7B-Instruct", 22),
              ("Qwen/Qwen3-VL-4B-Instruct", 12), ("Qwen/Qwen2.5-VL-3B-Instruct", 10)]
SMOKE_VLM = "HuggingFaceTB/SmolVLM-256M-Instruct"
MAX_PIXELS = 2048 * 28 * 28     # 비전 모델에 넣는 그림 크기 상한(작은 글자를 읽을 만큼)
MAX_NEW_TOKENS = 3000
VLM_PROMPT = ("이 보고서 페이지에 보이는 글자와 숫자를 빠짐없이 그대로 옮겨 적으세요. 요약하거나 고치거나 덧붙이지 말고, "
              "표와 그래프의 숫자와 라벨도 모두 적으세요. 읽을 수 없는 부분은 건너뛰세요.")
HF_RESULT_REPO = "dograg-kb-ocr-gpu"   # <사용자>/dograg-kb-ocr-gpu (비공개 데이터셋): 엔진별 페이지 글
MLFLOW_URI = "https://dagshub.com/rndigkwk/dograg.mlflow"
MLFLOW_USER = "rndigkwk"
EXPERIMENT = "kb-report-ocr\""""),
    ("code", """import os, sys
if os.path.exists("/content"):
    %cd /content
    !rm -rf dograg
    !git clone -q --depth 1 --branch {BRANCH} https://github.com/rndigkwk/dograg.git
    %cd /content/dograg
    !pip -q install -U pymupdf easyocr "transformers>=4.57" accelerate qwen-vl-utils "mlflow>=3.4" huggingface_hub
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
import torch
gpu_gb = torch.cuda.get_device_properties(0).total_memory / 2**30 if torch.cuda.is_available() else 0
print(sys.version, torch.__version__, torch.cuda.get_device_name(0) if gpu_gb else "GPU 없음 (SMOKE만 가능)", f"{gpu_gb:.0f} GB")
if not SMOKE:
    assert gpu_gb, "런타임 유형을 GPU로 바꾸세요\""""),
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
    ("code", """# 데이터: 보고서 PDF와 지금의 Tesseract OCR. 페이지는 300 dpi가 아닌 DPI로 그려 두 엔진이 같은 그림을 읽습니다.
import json, re, time
from pathlib import Path
from huggingface_hub import hf_hub_download
import pymupdf

def data_file(name):
    if os.path.exists(name):
        return name
    return hf_hub_download(DATA_REPO, name, repo_type="dataset", revision=REVISION, token=HF_TOKEN)

pages = SMOKE_PAGES if SMOKE else PAGES
tesseract = json.load(open(data_file(TESSERACT_FILE), encoding="utf-8"))["pages"]
images, pdf_text = {}, {}
Path("output/kb_pages").mkdir(parents=True, exist_ok=True)
with pymupdf.open(data_file(PDF)) as doc:
    for number in pages:
        page = doc[number - 1]
        path = Path(f"output/kb_pages/p{number:03d}.png")
        page.get_pixmap(dpi=DPI).save(path)
        images[number] = path
        pdf_text[number] = " ".join(page.get_text().split())
sys.path.insert(0, ".")
from scripts.add_kb_ocr_chunks import clean_ocr
# tesseract: as read. tesseract_rules: with the general rules the app applies (年 and %p, a dropped
# decimal point), before the nine hand fixes: what the app would have without them.
texts = {"pdf_text": pdf_text, "tesseract": {p: tesseract[str(p)]["ocr"] for p in pages},
         "tesseract_rules": {p: clean_ocr(tesseract[str(p)]["ocr"]) for p in pages}}
seconds = {}
print(len(pages), "pages")"""),
    ("code", """# EasyOCR(한국어+영어, GPU). 문단으로 묶어 위에서 아래로 읽은 순서대로 이어 붙입니다.
import easyocr
reader = easyocr.Reader(["ko", "en"], gpu=torch.cuda.is_available())
texts["easyocr"], seconds["easyocr"] = {}, []
for number in pages:
    started = time.perf_counter()
    texts["easyocr"][number] = " ".join(reader.readtext(str(images[number]), detail=0, paragraph=True))
    seconds["easyocr"].append(time.perf_counter() - started)
print("easyocr", f"{sum(seconds['easyocr']) / len(pages):.1f}s per page")
del reader
torch.cuda.empty_cache() if torch.cuda.is_available() else None"""),
    ("code", """# 비전 언어 모델: GPU에 맞는 첫 모델로 페이지를 그대로 옮겨 적게 합니다(온도 0).
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor

def load_vlm():
    for name, need in ([(SMOKE_VLM, 0)] if SMOKE else VLM_MODELS):
        if need > gpu_gb * 0.95 and not SMOKE:
            continue
        try:
            try:   # Qwen-VL takes a pixel cap; other processors do not
                processor = AutoProcessor.from_pretrained(name, max_pixels=MAX_PIXELS)
            except TypeError:
                processor = AutoProcessor.from_pretrained(name)
            model = AutoModelForImageTextToText.from_pretrained(name, dtype="auto", device_map="auto" if gpu_gb else None)
            return name, processor, model.eval()
        except Exception as error:   # a model that cannot be downloaded or loaded is skipped
            print("skip", name, str(error)[:200])
    raise RuntimeError("비전 모델을 불러오지 못했습니다")

vlm_name, processor, vlm = load_vlm()
print("vision model:", vlm_name)
texts["vlm"], seconds["vlm"] = {}, []
for number in pages:
    messages = [{"role": "user", "content": [{"type": "image", "image": Image.open(images[number]).convert("RGB")},
                                             {"type": "text", "text": VLM_PROMPT}]}]
    inputs = processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_dict=True,
                                           return_tensors="pt").to(vlm.device)
    started = time.perf_counter()
    with torch.no_grad():
        out = vlm.generate(**inputs, max_new_tokens=60 if SMOKE else MAX_NEW_TOKENS, do_sample=False)
    seconds["vlm"].append(time.perf_counter() - started)
    text = processor.batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0]
    texts["vlm"][number] = " ".join(text.split())
    print(number, f"{seconds['vlm'][-1]:.0f}s", len(texts["vlm"][number]), "chars", flush=True)
del vlm
torch.cuda.empty_cache() if torch.cuda.is_available() else None"""),
    ("code", """# 점수. 숫자는 공백과 쉼표를 빼고 비교합니다("1,546 만" = "1546만").
from scripts.add_kb_ocr_chunks import OCR_CORRECTIONS, YEAR_NYEON

ENGINES = ["tesseract", "tesseract_rules", "easyocr", "vlm"]
FAMILY = {"tesseract": "tesseract", "tesseract_rules": "tesseract", "easyocr": "easyocr", "vlm": "vlm"}
squash = lambda text: re.sub(r"[\\s,]", "", text)
FIGURE = re.compile(r"\\d[\\d,]*(?:\\.\\d+)?\\s*(?:%p|%|만|억|시간|배)")
figures = lambda text: {squash(f) for f in FIGURE.findall(text)}
IMPOSSIBLE_SHARE = re.compile(r"(?<![\\d.,])(?!100%)[1-9]\\d\\d%")

def known_misreads(engine):
    rows = []
    for page, pairs in OCR_CORRECTIONS.items():
        if page not in texts[engine]:
            continue
        text = squash(texts[engine][page])
        for wrong, right in pairs:
            rows.append({"page": page, "right": right, "right_read": squash(right) in text, "wrong_read": squash(wrong) in text})
    return rows

reference = json.load(open("tests/data/report_reference_answers.json", encoding="utf-8"))["items"]
def reference_figures(engine):
    rows = []
    for item in reference:
        gold = [p for source, p in item.get("gold_pages", []) if "한국 반려동물 보고서" in source and p in texts[engine]]
        if not gold or not item.get("reference"):
            continue
        page_text = squash(" ".join(texts[engine][p] for p in gold))
        for figure in figures(item["reference"]):
            rows.append({"id": item["id"], "figure": figure, "found": figure in page_text})
    return rows

scores = {"vision_model": vlm_name, "pages": len(pages), "dpi": DPI, "engines": {}}
for engine in ENGINES:
    misreads, refs = known_misreads(engine), reference_figures(engine)
    others = [e for e in ENGINES if FAMILY[e] != FAMILY[engine]]
    alone = sum(len(figures(texts[engine][p]) - set().union(*(figures(texts[o][p]) for o in others))) for p in pages)
    scores["engines"][engine] = {
        "known_right": sum(r["right_read"] for r in misreads), "known_wrong": sum(r["wrong_read"] for r in misreads),
        "known_total": len(misreads),
        "reference_found": sum(r["found"] for r in refs), "reference_total": len(refs),
        "figures": sum(len(figures(texts[engine][p])) for p in pages), "figures_alone": alone,
        "year_misreads": sum(len(YEAR_NYEON.findall(texts[engine][p])) for p in pages),
        "impossible_shares": sum(len(IMPOSSIBLE_SHARE.findall(texts[engine][p])) for p in pages),
        "seconds_per_page": round(sum(seconds[engine]) / len(pages), 1) if engine in seconds else None,  # Tesseract ran on 2026-10-17, CPU
        "known": misreads, "reference": refs,
    }
for engine in ENGINES:
    print(engine, {k: v for k, v in scores["engines"][engine].items() if not isinstance(v, list)})"""),
    ("code", """# 엔진끼리 숫자가 갈리는 쪽: EasyOCR과 비전 모델이 같은 숫자를 읽었는데 Tesseract가 다르면 Tesseract 오독 후보입니다.
# 쪽마다 그 숫자를 남겨 페이지 그림과 대조할 목록을 만듭니다(점수 파일에는 숫자와 쪽만, 문장은 없음).
disagreements = []
for p in pages:
    both = figures(texts["easyocr"][p]) & figures(texts["vlm"][p])
    missing = sorted(both - figures(texts["tesseract_rules"][p]))
    if missing:
        disagreements.append({"page": p, "read_by_easyocr_and_vlm_not_tesseract": missing})
scores["tesseract_suspects"] = disagreements
print(len(disagreements), "pages with figures Tesseract did not read the same way")
for row in disagreements[:15]:
    print(row)"""),
    ("code", """# MLflow에 점수만 남기고, 페이지 글은 비공개 데이터셋에 올립니다.
import mlflow
mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
if SMOKE and mlflow.get_experiment_by_name(EXPERIMENT) is None:  # artifacts under output/, not ./mlruns
    mlflow.create_experiment(EXPERIMENT, artifact_location=Path("output/smoke_mlartifacts").resolve().as_uri())
mlflow.set_experiment(EXPERIMENT)
with mlflow.start_run(run_name="gpu-ocr-vs-tesseract" + ("-smoke" if SMOKE else "")) as run:
    mlflow.log_params({"vision_model": vlm_name, "pages": len(pages), "dpi": DPI, "max_pixels": MAX_PIXELS, "smoke": SMOKE})
    for engine, found in scores["engines"].items():
        mlflow.log_metrics({f"{engine}_{k}": v for k, v in found.items() if isinstance(v, (int, float))})
    mlflow.log_metric("tesseract_suspect_pages", len(disagreements))
    Path("output/kb_ocr_gpu_scores.json").write_text(json.dumps(scores, ensure_ascii=False, indent=1), encoding="utf-8")
    mlflow.log_artifact("output/kb_ocr_gpu_scores.json")   # figures and pages only, no page text
Path("output/kb_ocr_gpu_texts.json").write_text(json.dumps({e: {str(p): t for p, t in texts[e].items()} for e in texts},
                                                           ensure_ascii=False, indent=1), encoding="utf-8")
if not SMOKE:
    from huggingface_hub import HfApi
    api = HfApi(token=HF_TOKEN)
    repo = f"{api.whoami()['name']}/{HF_RESULT_REPO}"
    api.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
    api.upload_file(path_or_fileobj="output/kb_ocr_gpu_texts.json", path_in_repo="kb_ocr_gpu_texts.json", repo_id=repo, repo_type="dataset")
    api.upload_file(path_or_fileobj="output/kb_ocr_gpu_scores.json", path_in_repo="kb_ocr_gpu_scores.json", repo_id=repo, repo_type="dataset")
    print("uploaded", repo)
    del HF_TOKEN, api
os.environ.pop("MLFLOW_TRACKING_PASSWORD", None)
if os.path.exists("/content"):
    from google.colab import files
    files.download("output/kb_ocr_gpu_scores.json")
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
        "metadata": {"accelerator": "GPU", "colab": {"gpuType": "L4"},
                     "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python"}},
        "nbformat": 4, "nbformat_minor": 5,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
