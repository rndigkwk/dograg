"""A person checks the judge where the fine-tuned model won (no model calls).

    uv run --group tools python scripts/human_review_sheet.py           # write the sheets
    uv run --group tools python scripts/human_review_sheet.py --score human_review_short_labels.json

The fine-tuned health model B beat the base model on the 120 short questions (useful@3 0.625 ->
0.800, docs/wiki/embedding-finetune.md), but the judge that graded them is of the same family as the
model that wrote the training queries. So for every short question B gained (base top 3 had no
grade 2, B's had one), the sheet shows the post the judge rated 2, without the judge's grade, and
a person grades it 0 / 1 / 2 with the judge's rubric (scripts/relevance_set.py JUDGE_PROMPT).
Same search as that comparison: exact Dense 12 + BM25 12 -> RRF, top 3, saved grades in
output/experiments/finetuned_embedding_grades.json.

The sheets hold AI Hub text, so they stay in output/ (not committed). The page output/experiments/
human_review_short.html shows the whole post and answer with 0/1/2 buttons (or keys), keeps the
input in the browser and downloads human_review_short_labels.json. It starts from the grades already
typed into output/experiments/human_review_short.csv (UTF-8 with BOM, for Excel), which is written
only when missing, so those grades are never overwritten. --score reads the JSON (or, without a
path, the CSV's 사람 column) and writes the agreement to output/experiments/human_review_short.json.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

SHEET = PROJECT_DIR / "output" / "experiments" / "human_review_short.csv"
PAGE_PATH = SHEET.with_suffix(".html")
KEY = SHEET.with_suffix(".key.json")  # which question and post each row is; the judge gave all of them 2
OUT = PROJECT_DIR / "output" / "experiments" / "human_review_short.json"
GRADES = PROJECT_DIR / "output" / "experiments" / "finetuned_embedding_grades.json"
CANDIDATES, SHOWN_CHARS = 12, 400
COLUMNS = ("번호", "보호자 질문", "찾은 상담 (보호자)", "찾은 상담 (수의사 답변)", "사람 (0/1/2)", "메모")

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>검색 결과 채점</title>
<style>
:root { --bg:#fafaf7; --card:#fff; --ink:#1f2328; --muted:#646b73; --line:#d9dcd6; --accent:#2f6f5e; --pick:#e3f1ec; }
@media (prefers-color-scheme: dark) { :root { --bg:#16181b; --card:#1f2226; --ink:#e7e9ea; --muted:#9aa1a8; --line:#33373c; --accent:#7fc6b1; --pick:#22352f; } }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.6 system-ui, "Malgun Gothic", sans-serif; }
main { max-width:900px; margin:0 auto; padding:16px; }
header { position:sticky; top:0; background:var(--bg); padding:8px 0 12px; border-bottom:1px solid var(--line); z-index:1; }
h1 { font-size:20px; margin:0 0 4px; } .muted { color:var(--muted); font-size:14px; }
.rubric { font-size:14px; margin:6px 0; } .rubric b { color:var(--accent); }
section { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; margin:16px 0; scroll-margin-top:150px; }
section.done { border-color:var(--accent); }
.q { font-weight:600; font-size:17px; margin-bottom:10px; }
.box { border:1px solid var(--line); border-radius:8px; padding:10px 12px; margin:8px 0; white-space:pre-wrap; }
.box h3 { margin:0 0 4px; font-size:14px; color:var(--muted); }
.grades { display:flex; gap:8px; margin-top:12px; flex-wrap:wrap; }
.grades button { flex:1; min-width:150px; background:var(--card); color:var(--ink); border:1px solid var(--line);
  border-radius:8px; padding:10px; font-size:15px; cursor:pointer; text-align:left; }
.grades button.on { background:var(--pick); border-color:var(--accent); font-weight:600; }
textarea { width:100%; box-sizing:border-box; margin-top:8px; min-height:36px; background:var(--bg); color:var(--ink);
  border:1px solid var(--line); border-radius:6px; font:inherit; }
.bar { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-top:6px; }
.bar button { background:var(--accent); color:var(--bg); border:0; border-radius:8px; padding:8px 14px; font-size:15px; cursor:pointer; }
</style></head><body><main>
<header><h1>보호자 질문에 이 상담이 쓸모 있나요? (__N__문항)</h1>
<div class="rubric"><b>2</b> 같은 문제(같은 증상·상황)이고 답변이 바로 도움이 된다 · <b>1</b> 관련은 있지만 일부만 도움(원인·상황이
다르거나 일반 요령만 겹침) · <b>0</b> 다른 문제이거나 도움이 안 된다. 나이·견종이 달라도 같은 문제면 2.</div>
<div class="bar"><span id="progress" class="muted"></span><button id="save">결과 내려받기 (JSON)</button>
<span class="muted">입력은 이 브라우저에 자동 저장됩니다. 키보드 0·1·2로 맨 위 문항을 채점하고 다음으로 넘어갑니다.</span></div></header>
__ITEMS__
</main>
<script>
const KEY = "ragdog-human-review-short-v1";
const START = __START__;
let state = START;
try { state = JSON.parse(localStorage.getItem(KEY) || "null") || START; } catch (e) { state = START; }
const sections = [...document.querySelectorAll("section[data-n]")];
function persist() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} paint(); }
function paint() {
  let done = 0;
  sections.forEach(sec => {
    const s = state[sec.dataset.n] || {};
    sec.querySelectorAll(".grades button").forEach(b => b.classList.toggle("on", String(s.grade) === b.dataset.g));
    sec.classList.toggle("done", s.grade !== undefined);
    if (s.grade !== undefined) done++;
  });
  document.getElementById("progress").textContent = `${done} / ${sections.length} 완료`;
}
function grade(sec, g) { const n = sec.dataset.n; state[n] = {...(state[n] || {}), grade: g}; persist(); }
sections.forEach(sec => {
  const n = sec.dataset.n;
  sec.querySelectorAll(".grades button").forEach(b => b.addEventListener("click", () => grade(sec, Number(b.dataset.g))));
  const memo = sec.querySelector("textarea");
  memo.value = (state[n] || {}).memo || "";
  memo.addEventListener("input", () => { state[n] = {...(state[n] || {}), memo: memo.value}; persist(); });
});
document.addEventListener("keydown", e => {
  if (!["0", "1", "2"].includes(e.key) || e.target.tagName === "TEXTAREA") return;
  const top = sections.find(sec => sec.getBoundingClientRect().bottom > 160);
  if (!top) return;
  grade(top, Number(e.key));
  const next = sections[sections.indexOf(top) + 1];
  if (next) next.scrollIntoView({behavior: "smooth", block: "start"});
});
document.getElementById("save").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(state, null, 1)], {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "human_review_short_labels.json"; a.click();
});
paint();
</script></body></html>
"""

ITEM = """<section data-n="{n}"><div class="q">{n}. {question}</div>
<div class="box"><h3>찾은 상담 · 보호자</h3>{post}</div>
<div class="box"><h3>찾은 상담 · 수의사 답변</h3>{answer}</div>
<div class="grades"><button data-g="2">2 · 바로 도움이 된다</button><button data-g="1">1 · 일부만 도움</button>
<button data-g="0">0 · 다른 문제</button></div>
<textarea placeholder="메모 (선택)"></textarea></section>"""


def gained_rows() -> list[dict]:
    from evaluate_finetuned_embedding import ALL_TUNED, BASE
    from huggingface_hub import snapshot_download
    from langchain_core.documents import Document
    from measure_eval_overlap import read_csv
    from sentence_transformers import SentenceTransformer

    from src import resources, settings
    from src.health_answers import attach_health_answers
    from src.hybrid_retrieval import reciprocal_rank_fusion

    token = settings.get_setting("HF_TOKEN")
    a_path = Path(snapshot_download(ALL_TUNED["a"], token=token))  # the base model's vectors live in -a
    b_path = Path(snapshot_download(ALL_TUNED["b"], token=token))
    ids = json.loads((a_path / "corpus_ids.json").read_text())
    assert json.loads((b_path / "corpus_ids.json").read_text()) == ids
    vectors = {"base": np.load(a_path / "base_corpus_embeddings.npy"), "b": np.load(b_path / "corpus_embeddings.npy")}
    vectors = {name: m / np.linalg.norm(m, axis=1, keepdims=True) for name, m in vectors.items()}
    encoders = {"base": SentenceTransformer(BASE, device="cpu"), "b": SentenceTransformer(str(b_path), device="cpu")}
    for encoder in encoders.values():
        encoder.max_seq_length = 128
    rows = {row[""]: row for row in read_csv(PROJECT_DIR / "data" / "df.csv")}
    documents = [Document(page_content=rows[i]["qa.input"], id=i) for i in ids]
    bm25 = resources.load_health_bm25_index()

    short = json.loads((PROJECT_DIR / "tests" / "data" / "emergency_signs.json").read_text(encoding="utf-8"))["items"]
    questions = [item["question"] for item in short]
    extra = json.loads(GRADES.read_text(encoding="utf-8"))
    tops = {}
    for name, encoder in encoders.items():
        q = encoder.encode(questions, batch_size=64, convert_to_numpy=True)
        q = q / np.linalg.norm(q, axis=1, keepdims=True)
        order = np.argsort(-(q @ vectors[name].T), axis=1)[:, :CANDIDATES]
        tops[name] = [reciprocal_rank_fusion([[documents[k] for k in idx], bm25.search(question, CANDIDATES)], top_k=3)
                      for question, idx in zip(questions, order)]
    answers = resources.load_health_answer_table()
    gained = []
    for i, question in enumerate(questions):
        grades = extra.get(f"short:{i}", {})
        if any(grades.get(d.id) == 2 for d in tops["base"][i]):
            continue
        useful = [d for d in tops["b"][i] if grades.get(d.id) == 2]
        if useful:
            doc = attach_health_answers([useful[0]], answers)[0]
            gained.append({"question_index": i, "question": question, "doc": doc.id,
                           "post": doc.page_content.strip(), "answer": str(doc.metadata.get("qa.output", "")).strip()})
    return gained


def csv_marks() -> dict[str, dict]:
    """What was typed into the CSV so far, by row number: the page's starting state."""
    if not SHEET.exists():
        return {}
    marks = {}
    with open(SHEET, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            entry = {}
            if row["사람 (0/1/2)"].strip() in ("0", "1", "2"):
                entry["grade"] = int(row["사람 (0/1/2)"].strip())
            if row["메모"].strip():
                entry["memo"] = row["메모"].strip()
            if entry:
                marks[row["번호"]] = entry
    return marks


def write_sheet() -> int:
    gained = gained_rows()
    key = [{k: r[k] for k in ("question_index", "doc")} for r in gained]
    if KEY.exists() and json.loads(KEY.read_text(encoding="utf-8")) != key:
        raise SystemExit(f"the rows differ from {KEY}: grades typed so far would land on other rows")
    SHEET.parent.mkdir(parents=True, exist_ok=True)
    if not SHEET.exists():
        with open(SHEET, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(COLUMNS)
            for n, row in enumerate(gained, 1):
                writer.writerow([n, row["question"], " ".join(row["post"].split())[:SHOWN_CHARS],
                                 " ".join(row["answer"].split())[:SHOWN_CHARS], "", ""])
    KEY.write_text(json.dumps(key), encoding="utf-8")
    start = csv_marks()
    items = [ITEM.format(n=n, question=html.escape(r["question"]), post=html.escape(r["post"]),
                         answer=html.escape(r["answer"])) for n, r in enumerate(gained, 1)]
    page = (PAGE.replace("__N__", str(len(gained))).replace("__ITEMS__", "\n".join(items))
            .replace("__START__", json.dumps(start, ensure_ascii=False).replace("</", "<\\/")))
    PAGE_PATH.write_text(page, encoding="utf-8")
    print(f"{len(gained)} rows -> {PAGE_PATH} (starts with {len(start)} rows from {SHEET.name})")
    return 0


def score(labels: Path | None) -> int:
    if labels is not None:
        state = json.loads(labels.read_text(encoding="utf-8"))
        rows = len(json.loads(KEY.read_text(encoding="utf-8")))
        marks = [str(state.get(str(n), {}).get("grade", "")) for n in range(1, rows + 1)]
    else:
        with open(SHEET, encoding="utf-8-sig", newline="") as f:
            marks = [row["사람 (0/1/2)"].strip() for row in csv.DictReader(f)]
    graded = [int(m) for m in marks if m in ("0", "1", "2")]
    if not graded:
        print("no grades yet")
        return 1
    report = {"rows": len(marks), "graded": len(graded), "person_2": graded.count(2), "person_1": graded.count(1),
              "person_0": graded.count(0), "agree_with_judge": round(graded.count(2) / len(graded), 3)}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--score", nargs="?", const="", metavar="LABELS_JSON",
                        help="read the grades back: the page's JSON, or the CSV when no path is given")
    args = parser.parse_args()
    if args.score is None:
        raise SystemExit(write_sheet())
    raise SystemExit(score(Path(args.score) if args.score else None))
