"""Write notebooks/kb_ocr_8b_runpod.ipynb: the KB report pages read again by Qwen3-VL-8B on a rented GPU (RunPod).

    uv run python scripts/build_kb_ocr_8b_notebook.py

Follows docs/wiki/kb-ocr-gpu.md "다음에 할 것" (2026-10-26). The 4B vision model read the nine
hand-checked figures right where Tesseract did not, but looped on five pages and lost their second
half, and the L4 memory check skipped the 8B model. This notebook:
- reads the same 93 pages with Qwen3-VL-8B: bf16 (about 17 GB on disk and GPU) where it fits, else the
  official FP8 copy (9.9 GB download; the 2026-11-02 pod had 11.2 GB of disk left);
- keeps a page from looping: a light repetition_penalty, and a page that still hits the output cap
  or repeats itself is read again in a top and a bottom half; a half that loops too is marked
  `tesseract` (the page keeps its Tesseract text in the app);
- scores it the same way as the 2026-10-26 run, next to that run's EasyOCR and 4B texts;
- lists the figures where the 8B model and Tesseract differ by one digit ("50.2%" against 30.2%),
  with whether the 4B model and EasyOCR agree. Only figures checked against the page image go into
  scripts/add_kb_ocr_chunks.OCR_CORRECTIONS; this notebook does not change the search chunks.
No OpenAI calls. Page texts stay private (the private Hugging Face dataset <user>/dograg-kb-ocr-gpu);
MLflow (DagsHub) gets the scores only. SMOKE=True reads two pages with the same model.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "notebooks" / "kb_ocr_8b_runpod.ipynb"

CELLS = [
    ("markdown", """# KB 보고서 숫자 다시 읽기: Qwen3-VL-8B (RunPod GPU, MLflow 기록)

[위키](../docs/wiki/kb-ocr-gpu.md)의 2026-10-26 비교에서 비전 모델(4B)이 숫자를 가장 정확히 읽었지만(손으로 확인한 오독 9곳 모두 맞음), **5쪽에서 같은 문장을 되풀이하다 출력 상한에 닿아** 쪽 뒷부분을 잃었고 8B는 메모리 기준에 걸려 돌리지 못했습니다. 이 노트북은 그 "다음에 할 것" 1~3입니다.

1. **8B로 다시 읽기:** `Qwen/Qwen3-VL-8B-Instruct`, 온도 0. bf16(약 17GB)이 디스크·GPU에 들어가지 않으면 공식 FP8판(`-FP8`, 약 10GB)을 씁니다
2. **되풀이 막기:** 약한 `repetition_penalty`. 그래도 출력 상한에 닿거나 같은 구절을 되풀이한 쪽은 **위·아래 절반으로 나눠 다시 읽고**, 절반도 되풀이하면 그 쪽은 `tesseract`로 표시합니다(앱은 그 쪽에 Tesseract 글을 그대로 씀)
3. **갈리는 숫자 목록:** 8B와 Tesseract가 **한 자리만 다른 숫자**(`50.2%` ↔ 30.2%)를 쪽별로 모으고, 4B·EasyOCR(10-26 실행)도 같은 숫자를 읽었는지 붙입니다. 이 목록은 쪽 그림과 대조한 뒤 확인된 것만 정정표(`OCR_CORRECTIONS`)에 넣습니다. 검색 조각은 바꾸지 않습니다

- **임베딩 학습이 끝난 뒤에 실행하세요.** GPU 메모리와 디스크를 함께 쓰면 모자랍니다. 학습 노트북의 마지막 정리 셀까지 돌린 다음 시작하면 됩니다(첫 셀이 확인합니다).
- **OpenAI 호출 없음.** 쪽 글은 비공개 데이터셋 `<사용자>/dograg-kb-ocr-gpu`에만 올리고, MLflow(DagsHub) `kb-report-ocr`에는 점수만 남깁니다.
- **시간:** 93쪽에 1~2시간 정도(쪽당 40~80초, 나눠 읽는 쪽은 두 배). 중간에 끊겨도 다시 실행하면 읽은 쪽은 건너뜁니다.
- **토큰 두 개:** Hugging Face(쓰기: 비공개 데이터 읽기 + 결과 올리기)와 DagsHub. 입력은 화면에 남지 않습니다.
"""),
    ("code", r"""# 설정. SMOKE=True면 두 쪽만(13쪽은 4B가 되풀이한 쪽) 같은 모델로 읽어 코드를 확인합니다(약 5분).
SMOKE = False
BRANCH = "feat/kb-ocr-8b"
DATA_REPO, REVISION = "blanden77/dograg-data", "data-v11"   # src/private_data.py
PDF = "data/source/2025 한국 반려동물 보고서.pdf"
TESSERACT_FILE = "data/source/kb_report_ocr.json"           # 지금 검색이 쓰는 OCR(Tesseract kor+eng, 300 dpi)
RESULT_REPO_NAME = "dograg-kb-ocr-gpu"   # <사용자>/dograg-kb-ocr-gpu: 10-26 실행의 쪽 글(kb_ocr_gpu_texts.json)도 여기
# scripts/add_kb_ocr_chunks.ocr_pages (2026-10-26): OCR 조각을 만드는 93쪽
PAGES = [4, 5, 6, 7, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 34, 35,
         36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 52, 53, 54, 55, 56, 57, 59, 60, 61, 62, 63, 64, 65,
         66, 67, 68, 69, 70, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 84, 85, 86, 87, 88, 89, 90, 91, 94, 95, 96,
         97, 99, 100, 101, 102, 103, 104, 105, 108, 109, 110, 111]
SMOKE_PAGES = [7, 13]
DPI = 200                       # 10-26 실행과 같은 그림
# (모델, 필요한 GPU GB, 필요한 디스크 GB). 첫 셀이 GPU와 디스크에 들어가는 첫 모델을 고릅니다
VLM_CHOICES = [("Qwen/Qwen3-VL-8B-Instruct", 20, 17.5), ("Qwen/Qwen3-VL-8B-Instruct-FP8", 20, 10.5)]   # 내려받기 16.3GB, 9.9GB
MAX_PIXELS = 2048 * 28 * 28     # 10-26 실행과 같은 상한. 절반으로 나눈 그림은 같은 상한 안에서 더 크게 읽힙니다
MAX_NEW_TOKENS = 3000
REPETITION_PENALTY = 1.05       # 표는 같은 라벨을 여러 번 쓰므로 약하게만
HALF_OVERLAP = 0.08             # 위·아래 절반이 쪽 높이의 8%씩 겹치게(경계의 숫자를 잃지 않도록)
VLM_PROMPT = ("이 보고서 페이지에 보이는 글자와 숫자를 빠짐없이 그대로 옮겨 적으세요. 요약하거나 고치거나 덧붙이지 말고, "
              "표와 그래프의 숫자와 라벨도 모두 적으세요. 읽을 수 없는 부분은 건너뛰세요.")
# 보고서, 쪽 그림, 모델 캐시, 결과를 둘 곳: 볼륨(/workspace)에 자리가 없으면 컨테이너 디스크. 마지막 셀이 지웁니다
WORK_CHOICES = ["/workspace/kb-ocr-8b", "/root/kb-ocr-8b"]
REPO_DIR = "/workspace/dograg-kbocr"
MLFLOW_URI = "https://dagshub.com/rndigkwk/dograg.mlflow"
MLFLOW_USER = "rndigkwk"
EXPERIMENT = "kb-report-ocr"
"""),
    ("code", r"""# GPU와 디스크 확인: 임베딩 학습이 돌고 있으면 멈춥니다.
import os, shutil, subprocess
from pathlib import Path
print(subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv"],
                     capture_output=True, text=True).stdout)
ps = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
training = [line for line in ps.splitlines() if "train_embedding_gpu.py" in line and "python" in line]
assert not training, "임베딩 학습이 아직 돌고 있습니다. 끝나고 학습 노트북의 정리 셀까지 실행한 뒤 다시 시작하세요."
used, total = (int(x) for x in subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                                              capture_output=True, text=True).stdout.split("\n")[0].split(","))
free_gpu = (total - used) / 1024
print(f"GPU 여유 {free_gpu:.1f} GB")
free_disks = {}
for choice in WORK_CHOICES:
    # A model already downloaded there (a rerun after a kernel restart) counts as room it can use.
    held = sum(f.stat().st_size for f in Path(choice).rglob("*") if f.is_file() and not f.is_symlink())
    free_disks[choice] = (shutil.disk_usage(os.path.dirname(choice)).free + held) / 2**30
    print(f"{os.path.dirname(choice)} 디스크 여유 {free_disks[choice]:.1f} GB")
VLM = WORK = None
for name, need_gpu, need_disk in VLM_CHOICES:
    place = next((c for c in WORK_CHOICES if free_disks[c] >= need_disk), None)
    if free_gpu >= need_gpu and place:
        VLM, WORK = name, place
        break
assert VLM, f"GPU {free_gpu:.1f}GB, 디스크 {max(free_disks.values()):.1f}GB로는 8B 모델이 들어가지 않습니다: {VLM_CHOICES}"
print("모델:", VLM)
os.makedirs(WORK, exist_ok=True)
os.environ["HF_HOME"] = f"{WORK}/hf"   # 모델과 데이터를 WORK 아래에 받아 마지막에 한 번에 지웁니다
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
print("WORK =", WORK)
"""),
    ("code", r"""# 코드와 패키지. blinker·cryptography는 이미지에 debian이 깔아 pip이 지우지 못해 덮어 설치합니다.
%cd /workspace
!rm -rf {REPO_DIR}
!git clone -q --depth 1 --branch {BRANCH} https://github.com/rndigkwk/dograg.git {REPO_DIR}
%cd {REPO_DIR}
!pip install -q --ignore-installed blinker cryptography
!pip install -q pymupdf "transformers>=4.57" accelerate qwen-vl-utils mlflow huggingface_hub
import sys, torch, transformers
print(sys.version.split()[0], "torch", torch.__version__, "transformers", transformers.__version__, torch.cuda.get_device_name(0))"""),
    ("code", r"""# 토큰. 화면에 남지 않고, 값은 출력하지 않습니다.
from getpass import getpass

def secret(name, prompt):
    value = getpass(prompt).strip()
    # A token typed with the Korean input mode on turns into Hangul and fails much later.
    if not value or not value.isascii():
        raise ValueError(f"{name}: 비어 있거나 영문이 아닌 글자가 있습니다(한글 입력 상태?). 길이 {len(value)}")
    print(name, "ok, length", len(value))
    return value

HF_TOKEN = secret("HF_TOKEN", "Hugging Face 토큰(쓰기): ")
if SMOKE:   # the smoke run's scores stay in a local SQLite file, not on DagsHub
    os.environ["MLFLOW_TRACKING_URI"] = f"sqlite:///{WORK}/smoke_mlflow.db"
else:
    os.environ["MLFLOW_TRACKING_URI"] = MLFLOW_URI
    os.environ["MLFLOW_TRACKING_USERNAME"] = MLFLOW_USER
    os.environ["MLFLOW_TRACKING_PASSWORD"] = secret("DAGSHUB_TOKEN", "DagsHub 토큰: ")"""),
    ("code", r"""# 데이터: 보고서 PDF, 지금의 Tesseract OCR, 10-26 실행의 EasyOCR·4B 쪽 글. 쪽 그림은 DPI로 그립니다.
import json, re, time
from pathlib import Path
from huggingface_hub import HfApi, hf_hub_download
import pymupdf

api = HfApi(token=HF_TOKEN)
result_repo = f"{api.whoami()['name']}/{RESULT_REPO_NAME}"
data_file = lambda name: hf_hub_download(DATA_REPO, name, repo_type="dataset", revision=REVISION, token=HF_TOKEN)
pages = SMOKE_PAGES if SMOKE else PAGES
tesseract = json.load(open(data_file(TESSERACT_FILE), encoding="utf-8"))["pages"]
previous = json.load(open(hf_hub_download(result_repo, "kb_ocr_gpu_texts.json", repo_type="dataset", token=HF_TOKEN),
                          encoding="utf-8"))
images = {}
Path(f"{WORK}/pages").mkdir(parents=True, exist_ok=True)
with pymupdf.open(data_file(PDF)) as doc:
    for number in pages:
        images[number] = Path(f"{WORK}/pages/p{number:03d}.png")
        doc[number - 1].get_pixmap(dpi=DPI).save(images[number])
sys.path.insert(0, ".")
from scripts.add_kb_ocr_chunks import OCR_CORRECTIONS, YEAR_NYEON, clean_ocr
# tesseract_rules: the app's general rules (年, %p, a dropped decimal point) before the nine hand fixes.
texts = {"tesseract": {p: tesseract[str(p)]["ocr"] for p in pages},
         "tesseract_rules": {p: clean_ocr(tesseract[str(p)]["ocr"]) for p in pages},
         "easyocr": {p: previous["easyocr"][str(p)] for p in pages},
         "vlm4b": {p: previous["vlm"][str(p)] for p in pages}}
print(len(pages), "pages; previous run:", sorted(previous))"""),
    ("code", r"""# Qwen3-VL-8B로 읽기. 쪽마다 결과 파일에 바로 써서, 끊긴 뒤 다시 실행하면 읽은 쪽은 건너뜁니다.
from collections import Counter
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor, FineGrainedFP8Config

try:   # the same pixel cap as the 10-26 run, where the processor takes it
    processor = AutoProcessor.from_pretrained(VLM, max_pixels=MAX_PIXELS)
except TypeError:
    processor = AutoProcessor.from_pretrained(VLM)
# The FP8 copy is unpacked to bf16 on load: its FP8 matmul needs a hub kernel that the pod's triton
# could not import (2026-11-02). Disk stays at the FP8 size; GPU memory is that of bf16 (about 16 GB).
fp8 = {"quantization_config": FineGrainedFP8Config(dequantize=True)} if VLM.endswith("-FP8") else {}
vlm = AutoModelForImageTextToText.from_pretrained(VLM, dtype=torch.bfloat16, device_map="cuda", **fp8).eval()
print("loaded", VLM, f"{torch.cuda.memory_allocated() / 2**30:.1f} GB")

def read(image):
    messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": VLM_PROMPT}]}]
    inputs = processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_dict=True,
                                           return_tensors="pt").to(vlm.device)
    with torch.no_grad():
        out = vlm.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False, repetition_penalty=REPETITION_PENALTY)
    new = out[:, inputs["input_ids"].shape[1]:]
    text = " ".join(processor.batch_decode(new, skip_special_tokens=True)[0].split())
    return text, new.shape[1] >= MAX_NEW_TOKENS

def loops(text, cut):
    # The 4B model's failure: the output cap reached, or the same 12 words four times or more.
    words = text.split()
    shingles = Counter(" ".join(words[i:i + 12]) for i in range(max(len(words) - 11, 0)))
    return cut or (max(shingles.values(), default=0) >= 4)

out_file = Path(f"{WORK}/kb_ocr_8b_texts{'_smoke' if SMOKE else ''}.json")
done = json.loads(out_file.read_text(encoding="utf-8")) if out_file.exists() else {}
for number in pages:
    if str(number) in done:
        continue
    image = Image.open(images[number]).convert("RGB")
    started = time.perf_counter()
    text, cut = read(image)
    status = "full"
    if loops(text, cut):
        w, h = image.size
        top, top_cut = read(image.crop((0, 0, w, int(h * (0.5 + HALF_OVERLAP)))))
        bottom, bottom_cut = read(image.crop((0, int(h * (0.5 - HALF_OVERLAP)), w, h)))
        text = f"{top} {bottom}"
        status = "tesseract" if loops(top, top_cut) or loops(bottom, bottom_cut) else "halves"
    done[str(number)] = {"text": text, "status": status, "seconds": round(time.perf_counter() - started, 1)}
    out_file.write_text(json.dumps(done, ensure_ascii=False), encoding="utf-8")
    print(number, status, f"{done[str(number)]['seconds']:.0f}s", len(text), "chars", flush=True)
texts["vlm8b"] = {p: done[str(p)]["text"] for p in pages}
status = {p: done[str(p)]["status"] for p in pages}
print(Counter(status.values()))
del vlm
torch.cuda.empty_cache()"""),
    ("code", r"""# 점수: 10-26 실행과 같은 기준. 숫자는 공백과 쉼표를 빼고 비교합니다("1,546 만" = "1546만").
ENGINES = ["tesseract", "tesseract_rules", "easyocr", "vlm4b", "vlm8b"]
FAMILY = {"tesseract": "tesseract", "tesseract_rules": "tesseract", "easyocr": "easyocr", "vlm4b": "vlm", "vlm8b": "vlm"}
squash = lambda text: re.sub(r"[\s,]", "", text)
FIGURE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:%p|%|만|억|시간|배)")
figures = lambda text: {squash(f) for f in FIGURE.findall(text)}
IMPOSSIBLE_SHARE = re.compile(r"(?<![\d.,])(?!100%)[1-9]\d\d%")

def known_misreads(engine):
    rows = []
    for page, pairs in OCR_CORRECTIONS.items():
        if page in texts[engine]:
            text = squash(texts[engine][page])
            rows += [{"page": page, "right": right, "right_read": squash(right) in text, "wrong_read": squash(wrong) in text}
                     for wrong, right in pairs]
    return rows

reference = json.load(open("tests/data/report_reference_answers.json", encoding="utf-8"))["items"]
def reference_figures(engine):
    rows = []
    for item in reference:
        gold = [p for source, p in item.get("gold_pages", []) if "한국 반려동물 보고서" in source and p in texts[engine]]
        if gold and item.get("reference"):
            page_text = squash(" ".join(texts[engine][p] for p in gold))
            rows += [{"id": item["id"], "figure": f, "found": f in page_text} for f in figures(item["reference"])]
    return rows

scores = {"vision_model": VLM, "pages": len(pages), "dpi": DPI, "repetition_penalty": REPETITION_PENALTY,
          "status": dict(Counter(status.values())), "status_pages": {s: [p for p in pages if status[p] == s] for s in ("halves", "tesseract")},
          "seconds_per_page": round(sum(done[str(p)]["seconds"] for p in pages) / len(pages), 1), "engines": {}}
for engine in ENGINES:
    misreads, refs = known_misreads(engine), reference_figures(engine)
    others = [e for e in ENGINES if FAMILY[e] != FAMILY[engine]]
    scores["engines"][engine] = {
        "known_right": sum(r["right_read"] for r in misreads), "known_wrong": sum(r["wrong_read"] for r in misreads),
        "known_total": len(misreads),
        "reference_found": sum(r["found"] for r in refs), "reference_total": len(refs),
        "figures": sum(len(figures(texts[engine][p])) for p in pages),
        "figures_alone": sum(len(figures(texts[engine][p]) - set().union(*(figures(texts[o][p]) for o in others))) for p in pages),
        "year_misreads": sum(len(YEAR_NYEON.findall(texts[engine][p])) for p in pages),
        "impossible_shares": sum(len(IMPOSSIBLE_SHARE.findall(texts[engine][p])) for p in pages),
        "chars_median": sorted(len(texts[engine][p]) for p in pages)[len(pages) // 2],
        "known": misreads, "reference": refs,
    }
for engine in ENGINES:
    print(engine, {k: v for k, v in scores["engines"][engine].items() if not isinstance(v, list)})"""),
    ("code", r"""# 정정 후보: 8B와 Tesseract(+규칙)가 한 자리만 다른 숫자. 4B·EasyOCR도 8B와 같은 숫자를 읽었으면 표시합니다.
# 숫자와 쪽만 남기고 문장은 남기지 않습니다. 이 목록을 쪽 그림과 대조한 뒤 확인된 것만 정정표에 넣습니다.
def one_digit_apart(a, b):
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    return len(a) == len(b) and len(diff) == 1 and diff[0][0].isdigit() and diff[0][1].isdigit()

fixed = {(page, squash(wrong)) for page, pairs in OCR_CORRECTIONS.items() for wrong, _ in pairs}
candidates = []
for p in pages:
    if status[p] == "tesseract":
        continue
    v8, tess = figures(texts["vlm8b"][p]), figures(texts["tesseract_rules"][p])
    for figure in sorted(v8 - tess):
        for wrong in sorted(t for t in tess - v8 if one_digit_apart(t, figure)):
            candidates.append({"page": p, "tesseract": wrong, "vlm8b": figure,
                               "vlm4b": figure in figures(texts["vlm4b"][p]), "easyocr": figure in figures(texts["easyocr"][p]),
                               "already_fixed": (p, wrong) in fixed})
# A Tesseract figure one digit from several 8B figures (59.8% -> 39.8%, 59.1%, 59.3%) is not a sure pair.
pairs = Counter((c["page"], c["tesseract"]) for c in candidates) + Counter((c["page"], c["vlm8b"]) for c in candidates)
for c in candidates:
    c["ambiguous"] = pairs[(c["page"], c["tesseract"])] > 1 or pairs[(c["page"], c["vlm8b"])] > 1
scores["candidates"] = candidates
digit_pairs = Counter((c["tesseract"][i], c["vlm8b"][i]) for c in candidates
                      for i in range(len(c["vlm8b"])) if c["tesseract"][i] != c["vlm8b"][i])
scores["candidate_digit_pairs"] = {f"{a}->{b}": n for (a, b), n in digit_pairs.most_common()}
agree = sum(c["vlm4b"] for c in candidates)
print(len(candidates), "candidates on", len({c["page"] for c in candidates}), "pages;", agree, "also read by 4B;",
      sum(c["vlm4b"] and c["easyocr"] for c in candidates), "by 4B and EasyOCR;", sum(c["ambiguous"] for c in candidates), "ambiguous")
print("Tesseract digit -> 8B digit:", scores["candidate_digit_pairs"])
for row in candidates[:20]:
    print(row)"""),
    ("code", r"""# MLflow에는 점수만, 쪽 글은 비공개 데이터셋에.
import mlflow
mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
if SMOKE and mlflow.get_experiment_by_name(EXPERIMENT) is None:  # artifacts under WORK, not ./mlruns
    mlflow.create_experiment(EXPERIMENT, artifact_location=Path(f"{WORK}/smoke_mlartifacts").resolve().as_uri())
mlflow.set_experiment(EXPERIMENT)
name = "qwen3-vl-8b-runpod" + ("-smoke" if SMOKE else "")
scores_file = Path(f"{WORK}/kb_ocr_8b_scores{'_smoke' if SMOKE else ''}.json")
scores_file.write_text(json.dumps(scores, ensure_ascii=False, indent=1), encoding="utf-8")
with mlflow.start_run(run_name=name) as run:
    mlflow.log_params({"vision_model": VLM, "pages": len(pages), "dpi": DPI, "max_pixels": MAX_PIXELS,
                       "max_new_tokens": MAX_NEW_TOKENS, "repetition_penalty": REPETITION_PENALTY,
                       "half_overlap": HALF_OVERLAP, "gpu": torch.cuda.get_device_name(0), "smoke": SMOKE})
    for engine, found in scores["engines"].items():
        mlflow.log_metrics({f"{engine}_{k}": v for k, v in found.items() if isinstance(v, (int, float))})
    mlflow.log_metrics({f"pages_{s}": n for s, n in scores["status"].items()})
    mlflow.log_metrics({"candidates": len(candidates), "candidates_4b_agree": agree, "seconds_per_page": scores["seconds_per_page"]})
    mlflow.log_artifact(str(scores_file))   # figures and page numbers only, no page text
if not SMOKE:
    api.upload_file(path_or_fileobj=str(out_file), path_in_repo="kb_ocr_8b_texts.json", repo_id=result_repo, repo_type="dataset")
    api.upload_file(path_or_fileobj=str(scores_file), path_in_repo="kb_ocr_8b_scores.json", repo_id=result_repo, repo_type="dataset")
    print("uploaded", result_repo)
summary = {"run": run.info.run_id, "status": scores["status"], "seconds_per_page": scores["seconds_per_page"],
           "candidates": len(candidates), "candidates_4b_agree": agree,
           "engines": {e: {k: v for k, v in s.items() if not isinstance(v, list)} for e, s in scores["engines"].items()}}
print(json.dumps(summary, ensure_ascii=False))   # 이 줄을 보내 주세요(숫자만, 쪽 글 없음)"""),
    ("markdown", """## 정리

업로드가 끝난 것을 확인한 뒤 실행합니다. 보고서, 쪽 그림, 쪽 글, 모델 캐시를 지웁니다. 그다음 RunPod에서 pod을 멈추고 볼륨을 지웁니다.
"""),
    ("code", r"""!rm -rf {WORK} {REPO_DIR}
for key in ("MLFLOW_TRACKING_PASSWORD", "HF_HOME"):
    os.environ.pop(key, None)
del HF_TOKEN, api
print("지웠습니다")"""),
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
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python"}},
        "nbformat": 4, "nbformat_minor": 5,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
