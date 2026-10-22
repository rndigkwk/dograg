"""A blind side-by-side sheet: the same health answer at two reasoning efforts (no model calls).

    uv run python scripts/answer_effort_sheet.py make output/latency/answer_default.json output/latency/answer_low.json
    uv run python scripts/answer_effort_sheet.py score answer_effort_labels.json

scripts/measure_health_latency.py ran the 40 health questions with the answer model at its default
effort and at ANSWER_REASONING_EFFORT=low (2026-10-21): low was 7 s faster at p90 but cited less
(0.46 -> 0.35). No judge is trusted on answers (docs/wiki/judge-validation.md, AUC 0.568), so a
person reads the pairs. make writes output/answer_effort/sheet.html: per question the question and
two answers as A and B in an order shuffled per question (seed 21), with the evidence the app showed
when the run kept it (runs after 2026-10-21).
The order lives in output/answer_effort/key.json, outside the page. The reader picks the better
answer (or "same") and marks an answer with a wrong or missing point; the page saves a JSON file.
score unblinds it: wins per effort, and wrong/missing marks per effort.
The sheet holds consultation text (private data): it stays in output/, never in the repository.
"""

from __future__ import annotations

import html
import json
import random
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
OUT = PROJECT_DIR / "output" / "answer_effort"
QUESTIONS = PROJECT_DIR / "tests" / "data" / "crag_eval_questions.json"

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>답변 비교</title>
<style>
:root { --bg:#fafaf7; --card:#fff; --ink:#1f2328; --muted:#646b73; --line:#d9dcd6; --accent:#2f6f5e; --mark:#fff4d6; }
@media (prefers-color-scheme: dark) { :root { --bg:#16181b; --card:#1f2226; --ink:#e7e9ea; --muted:#9aa1a8; --line:#33373c; --accent:#7fc6b1; --mark:#3a3420; } }
body { margin:0; background:var(--bg); color:var(--ink); font:16px/1.6 system-ui, "Malgun Gothic", sans-serif; }
main { max-width:1100px; margin:0 auto; padding:16px; }
header { position:sticky; top:0; background:var(--bg); padding:8px 0 12px; border-bottom:1px solid var(--line); z-index:1; }
h1 { font-size:20px; margin:0 0 4px; } .muted { color:var(--muted); font-size:14px; }
section { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; margin:16px 0; }
.q { font-weight:600; margin-bottom:12px; }
.pair { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
@media (max-width:760px) { .pair { grid-template-columns:1fr; } }
.ans { border:1px solid var(--line); border-radius:8px; padding:12px; white-space:pre-wrap; }
.ans h3 { margin:0 0 6px; font-size:15px; color:var(--accent); }
details { margin-top:10px; font-size:14px; } details pre { white-space:pre-wrap; background:var(--mark); padding:8px; border-radius:6px; }
.choices { display:flex; flex-wrap:wrap; gap:16px; margin-top:12px; align-items:center; }
textarea { width:100%; box-sizing:border-box; margin-top:8px; min-height:40px; background:var(--bg); color:var(--ink); border:1px solid var(--line); border-radius:6px; }
button { background:var(--accent); color:var(--bg); border:0; border-radius:8px; padding:8px 14px; font-size:15px; cursor:pointer; }
</style></head><body><main>
<header><h1>같은 질문, 두 답변 비교 (__N__쌍)</h1>
<div class="muted">어느 쪽이 보호자에게 더 나은 답인지 고르세요. A·B 순서는 문항마다 섞여 있습니다. 근거가 저장된 실행이면 펼쳐 볼 수 있습니다.
틀린 내용이나 빠진 중요한 내용이 있으면 그 답에 표시하세요. 입력은 이 브라우저에 자동 저장됩니다.</div>
<div class="choices"><span id="progress" class="muted"></span><button id="save">결과 내려받기 (JSON)</button></div></header>
__ITEMS__
</main>
<script>
const KEY = "ragdog-answer-effort-v1";
let state = {};
try { state = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { state = {}; }
const ids = [...document.querySelectorAll("section[data-id]")].map(s => s.dataset.id);
function persist() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} progress(); }
function progress() { const done = ids.filter(id => state[id] && state[id].better).length;
  document.getElementById("progress").textContent = `${done} / ${ids.length} 완료`; }
document.querySelectorAll("section[data-id]").forEach(sec => {
  const id = sec.dataset.id; state[id] = state[id] || {};
  sec.querySelectorAll("input").forEach(input => {
    const key = input.name.split("__")[1];
    if (input.type === "radio") { input.checked = state[id].better === input.value;
      input.addEventListener("change", () => { state[id].better = input.value; persist(); }); }
    else { input.checked = !!state[id][key]; input.addEventListener("change", () => { state[id][key] = input.checked; persist(); }); }
  });
  const memo = sec.querySelector("textarea"); memo.value = state[id].memo || "";
  memo.addEventListener("input", () => { state[id].memo = memo.value; persist(); });
});
document.getElementById("save").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(state, null, 1)], {type: "application/json"});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "answer_effort_labels.json"; a.click();
});
progress();
</script></body></html>
"""

ITEM = """<section data-id="{id}"><div class="q">{n}. {question}</div>
<div class="pair"><div class="ans"><h3>A</h3>{a}</div><div class="ans"><h3>B</h3>{b}</div></div>
{evidence}
<div class="choices"><strong>더 나은 답:</strong>
<label><input type="radio" name="{id}__better" value="A"> A</label>
<label><input type="radio" name="{id}__better" value="same"> 비슷함</label>
<label><input type="radio" name="{id}__better" value="B"> B</label>
<label><input type="checkbox" name="{id}__wrong_A"> A에 틀리거나 빠진 내용</label>
<label><input type="checkbox" name="{id}__wrong_B"> B에 틀리거나 빠진 내용</label></div>
<textarea placeholder="메모 (선택)"></textarea></section>"""


def evidence_text(row: dict) -> str:
    parts = []
    for i, ev in enumerate(row.get("evidence") or [], start=1):
        parts.append(f"[{i}] {ev}")
    if not parts:  # the 2026-10-21 runs did not keep the evidence
        return ""
    return f"<details><summary>검색된 근거 보기</summary><pre>{html.escape(chr(10).join(parts))}</pre></details>"


def make(default_path: Path, low_path: Path) -> int:
    default = {r["id"]: r for r in json.loads(default_path.read_text(encoding="utf-8"))["rows"]}
    low = {r["id"]: r for r in json.loads(low_path.read_text(encoding="utf-8"))["rows"]}
    questions = {item["id"]: item["question"] for item in json.loads(QUESTIONS.read_text(encoding="utf-8"))["items"]}
    # Only pairs where both runs answered: an abstention has nothing to compare.
    ids = [i for i in default if "sentences" in default[i] and "sentences" in low.get(i, {})]
    rng = random.Random(21)
    key, items = {}, []
    for n, i in enumerate(ids, start=1):
        low_first = rng.random() < 0.5
        key[i] = {"A": "low" if low_first else "default", "B": "default" if low_first else "low"}
        a, b = (low[i], default[i]) if low_first else (default[i], low[i])
        items.append(ITEM.format(id=i, n=n, question=html.escape(questions.get(i, i)),
                                 a=html.escape(a["answer"]), b=html.escape(b["answer"]),
                                 evidence=evidence_text(default[i])))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sheet.html").write_text(PAGE.replace("__N__", str(len(ids))).replace("__ITEMS__", "\n".join(items)), encoding="utf-8")
    (OUT / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"{len(ids)} pairs -> {OUT / 'sheet.html'}")
    return 0


def score(labels_path: Path) -> int:
    key = json.loads((OUT / "key.json").read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    wins = {"default": 0, "low": 0, "same": 0}
    wrong = {"default": [], "low": []}
    for i, mapping in key.items():
        label = labels.get(i) or {}
        better = label.get("better")
        if better in ("A", "B"):
            wins[mapping[better]] += 1
        elif better == "same":
            wins["same"] += 1
        for side in ("A", "B"):
            if label.get(f"wrong_{side}"):
                wrong[mapping[side]].append(i)
    judged = sum(wins.values())
    print(json.dumps({"pairs": len(key), "judged": judged, "wins": wins, "wrong_or_missing": wrong}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "make":
        raise SystemExit(make(Path(sys.argv[2]), Path(sys.argv[3])))
    if len(sys.argv) == 3 and sys.argv[1] == "score":
        raise SystemExit(score(Path(sys.argv[2])))
    print(__doc__)
    raise SystemExit(2)
