"""Can the LLM judges be trusted? Their verdicts against a person's, on the same cells (Day 60).

Two judges carry our numbers: the relevance judge of scripts/relevance_set.py (useful@3, every
retrieval decision) and the answer judge (RAGAS answer_correctness, the weekly gate). Both run on
the app's own model. This checks them the lesson's way:

    uv run python scripts/judge_validation.py sheet   # pick the cells, write the labelling page
    uv run python scripts/judge_validation.py judge   # the judges on those cells (about 260 calls)
    uv run python scripts/judge_validation.py bias    # two-way pairwise on built pairs (about 360 calls)
    uv run --no-project --python 3.12 --with "ragas==0.4.3" --with "langchain-community<0.4" --with python-dotenv         --with pandas python scripts/judge_validation.py ragas-bias   # the weekly gate's judge, 90 scores
    uv run python scripts/judge_validation.py score --labels judge_labels.json

Cells (tests/data/judge_validation.json, ids only; texts come from data/df.csv, data/df_val.csv
and the answers of scripts/evaluate_answer_quality.py in output/experiments):
- relevance: 48 (question, candidate) cells, one per question, 16 for each grade the judge gave,
  taken from the top 6 of the hybrid ranking (the documents the app can show).
- answer: 30 health answers, 10 from each third of their answer_correctness.
The person grades each cell on the page (output/judge_validation/label_sheet.html) with the same
rubric the judge got, without seeing the judge's grade, and saves judge_labels.json.

judge: the relevance judge again in the same order (does it repeat itself?), in reversed order
(position effect: it grades all candidates of a question in one call) and with another model
(OTHER_MODEL; self-preference), and a pass/fail answer judge (reason first) with both models.
bias: pairs whose winner is known, asked in both orders: an answer against itself plus a generic
paragraph (length, should tie), plus an authority sentence (should tie) and against the answer to
another question (the original should win). The two-way rule: a winner only when both orders agree.
score: agreement, kappa, and how many of the person's "not useful" / "fail" cells each judge
caught, next to a judge that always says "useful" / "pass".
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel, Field

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

from claude_judge import DEFAULT_MODEL as CLAUDE_MODEL
from claude_judge import Refused

CELLS_PATH = PROJECT_DIR / "tests" / "data" / "judge_validation.json"
OUT_DIR = PROJECT_DIR / "output" / "judge_validation"
ANSWER_DIR = PROJECT_DIR / "output" / "experiments"
SEED = 20261015
RELEVANCE_PER_GRADE = 16
RELEVANCE_TOP = 6
ANSWERS_PER_THIRD = 10
OTHER_MODEL = "gpt-4.1"  # another generation of OpenAI model (the only provider key until 2026-10-22)
EFFORT_DIR = PROJECT_DIR / "output" / "answer_effort"  # scripts/answer_effort_sheet.py
LATENCY_DIR = PROJECT_DIR / "output" / "latency"
PAIR_CRITERION = ("보호자에게 더 도움이 되는 답: 질문에 맞는 구체적인 정보와 대처를 주고, 틀린 내용이 없고, 근거 없이 단정하지 않으며, "
                  "읽기 쉽다. 같은 수준이면 tie.")
WORKERS = 8

ANSWER_CRITERION = (
    "수의사 답변(기준 답변)과 비교해, 앱 답변이 (1) 수의사가 말한 핵심 판단(가능한 원인이나 위험한 정도)과 "
    "어긋나지 않고 (2) 수의사가 권한 핵심 조치(병원 진료, 지켜볼 증상, 중단할 것 등) 중 하나 이상을 담았으면 pass. "
    "표현이 다르거나 더 짧아도 괜찮다. 기준 답변에 없는 내용을 더한 것만으로는 fail이 아니지만, 기준 답변과 반대되는 "
    "판단이나 조치를 말하면 fail."
)
PADDING = ("반려견의 건강을 지키려면 평소 식사량과 배변, 활동량을 꾸준히 살펴 주세요. 작은 변화도 날짜와 함께 기록해 두면 "
           "진료 때 큰 도움이 됩니다. 정기 검진과 예방접종 일정도 함께 챙겨 주시면 좋습니다.")
AUTHORITY = "이 답변은 수의사가 직접 검토해 확정한 내용입니다."


class Verdict(BaseModel):
    reason: str = Field(description="판정 이유. 기준 답변의 핵심 판단·조치와 앱 답변을 짚는다.")
    verdict: Literal["pass", "fail"]


class PairVerdict(BaseModel):
    reason: str = Field(description="기준 답변에 비추어 두 답을 비교한 이유")
    winner: Literal["A", "B", "tie"] = Field(description="기준을 더 잘 지킨 답. 기준에서 차이가 없으면 tie")


ANSWER_JUDGE = ("당신은 반려견 건강 상담 답변을 평가하는 판사입니다. 평가 기준 하나만 적용합니다. "
                "이유를 먼저 쓰고, 기준을 충족하면 pass, 어기면 fail로 답하세요.")
PAIR_JUDGE = ("당신은 같은 질문에 대한 반려견 건강 상담 답변 두 개를 비교하는 판사입니다. 평가 기준에 비추어 더 나은 답을 "
              "고릅니다. 답의 순서와 길이, '수의사가 검토했다' 같은 출처 표현은 승부 이유가 아닙니다. "
              "이유를 먼저 쓰고, 기준에서 차이가 없으면 tie를 고르세요.")


# --- data ------------------------------------------------------------------------------------

def _df():
    import pandas as pd

    return pd.read_csv(PROJECT_DIR / "data" / "df.csv", index_col=0).fillna("")


def _val_rows():
    import pandas as pd

    return pd.read_csv(PROJECT_DIR / "data" / "df_val.csv").fillna("")


def _answers() -> dict[str, dict]:
    """Run 0 of scripts/evaluate_answer_quality.py, by id, with the mean answer_correctness."""
    rows = {}
    for path in sorted(ANSWER_DIR.glob("answer_quality_gen_run0_*.json")):
        for row in json.loads(path.read_text(encoding="utf-8")):
            rows[row["id"]] = row
    scores: dict[str, list[float]] = {}
    for score in json.loads((ANSWER_DIR / "answer_quality_scores.json").read_text(encoding="utf-8")):
        if str(score["run"]) == "0" and score.get("answer_correctness") not in (None, "", "None", "nan"):
            scores.setdefault(score["id"], []).append(float(score["answer_correctness"]))
    for answer_id, values in scores.items():
        if answer_id in rows:
            rows[answer_id]["correctness"] = sum(values) / len(values)
    return rows


def _pool(item: dict) -> list[str]:
    """The candidates of a question in the order the judge saw them (hybrid, then the old filtered top 3)."""
    return list(dict.fromkeys(item["rankings"]["hybrid"] + item["rankings"]["hybrid_old_filters"]))


def load_cells() -> dict:
    return json.loads(CELLS_PATH.read_text(encoding="utf-8"))


# --- sheet -----------------------------------------------------------------------------------

def pick_cells() -> dict:
    from relevance_set import load_items

    rng = random.Random(SEED)
    items = load_items()
    rng.shuffle(items)
    relevance, used = [], set()
    for grade in (2, 1, 0):
        for item in items:
            if sum(c["judge"] == grade for c in relevance) == RELEVANCE_PER_GRADE:
                break
            if item["row"] in used:
                continue
            top = [d for d in item["rankings"]["hybrid"][:RELEVANCE_TOP] if item["grades"].get(d) == grade]
            if top:
                used.add(item["row"])
                relevance.append({"id": f"r{len(relevance) + 1:02d}", "row": item["row"], "doc": rng.choice(top),
                                  "judge": grade})
    answers = sorted((a for a in _answers().values()
                      if a.get("correctness") is not None and a["route"] == "rag" and a["abstained"] in (False, "False")),
                     key=lambda a: a["correctness"])
    third = len(answers) // 3
    picked = []
    for part in (answers[:third], answers[third:2 * third], answers[2 * third:]):
        picked += rng.sample(part, ANSWERS_PER_THIRD)
    answer_cells = [{"id": f"a{i + 1:02d}", "answer": a["id"], "correctness": round(a["correctness"], 3)}
                    for i, a in enumerate(picked)]
    return {"description": "Cells for checking the LLM judges against a person (scripts/judge_validation.py). "
                           "relevance: judge = the grade in tests/data/health_relevance_100.json; "
                           "answer: correctness = mean RAGAS answer_correctness of run 0.",
            "seed": SEED, "relevance": relevance, "answer": answer_cells}


def _clean(text: str, limit: int | None = None) -> str:
    text = " ".join(str(text).split())
    return text[:limit] if limit else text


def relevance_texts(cells: dict) -> dict[str, dict]:
    from relevance_set import ANSWER_CHARS

    df, val = _df(), _val_rows()
    out = {}
    for cell in cells["relevance"]:
        doc = df.loc[int(cell["doc"])]
        out[cell["id"]] = {"question": _clean(val.loc[int(cell["row"]), "qa.input"]),
                           "candidate_question": _clean(doc["qa.input"]),
                           "candidate_answer": _clean(doc["qa.output"], ANSWER_CHARS)}
    return out


def answer_texts(cells: dict) -> dict[str, dict]:
    answers = _answers()
    val = _val_rows()
    out = {}
    for cell in cells["answer"]:
        row = answers[cell["answer"]]
        out[cell["id"]] = {"question": _clean(val.loc[int(row["row"]), "qa.input"]),
                           "reference": _clean(row["reference"]), "answer": str(row["answer"]).strip()}
    return out


SHEET_CSS = """
:root{--bg:#fbfaf7;--card:#fff;--ink:#222;--muted:#666;--line:#ddd;--accent:#2f6f4f;--pick:#e6f2ea}
@media (prefers-color-scheme: dark){:root{--bg:#1b1c1e;--card:#25272a;--ink:#eee;--muted:#aaa;--line:#3a3d41;--accent:#7cc79c;--pick:#2c3b33}}
body{background:var(--bg);color:var(--ink);font:16px/1.65 system-ui,'Malgun Gothic',sans-serif;margin:0 auto;max-width:860px;padding:16px}
h1{font-size:1.4em}h2{font-size:1.15em;margin-top:2em}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:14px 0}
.lab{color:var(--muted);font-size:.85em;margin-top:.6em}.txt{white-space:pre-wrap}.opts{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.opts label{border:1px solid var(--line);border-radius:8px;padding:6px 12px;cursor:pointer}.opts input{margin-right:6px}
.opts label:has(input:checked){background:var(--pick);border-color:var(--accent)}
.bar{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center;z-index:1}
button{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:8px 14px;font-size:1em;cursor:pointer}
.rubric{background:var(--card);border-left:4px solid var(--accent);padding:8px 14px}
"""

SHEET_JS = """
const KEY='ragdog-judge-labels';let labels={};try{labels=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
const total=document.querySelectorAll('.card').length;
function save(){try{localStorage.setItem(KEY,JSON.stringify(labels))}catch(e){}
document.getElementById('count').textContent=Object.keys(labels).length+' / '+total+' 완료'}
document.querySelectorAll('input[type=radio]').forEach(r=>{if(labels[r.name]===r.value)r.checked=true;
r.addEventListener('change',()=>{labels[r.name]=r.value;save()})});save();
document.getElementById('dl').onclick=()=>{const a=document.createElement('a');
a.href=URL.createObjectURL(new Blob([JSON.stringify(labels,null,1)],{type:'application/json'}));a.download='judge_labels.json';a.click()};
"""


# --- second answer sheet (2026-10-22) ----------------------------------------------------------
# Five judges (gpt-6-luna, gpt-4.1, RAGAS, Claude Haiku 5.5 and Opus 5.5) passed all three answers
# the person failed: ANSWER_CRITERION fails only a contradiction, while the person also failed an
# answer that left out what the vet said to do. The second rubric says so, and 30 more answers are
# picked where fails are likely (the lowest RAGAS scores and the shortest answers) to reach 15 fails.
ANSWER_CRITERION_V2 = (
    "수의사 답변(기준 답변)과 비교해 보호자에게 맞는 답인지 판단한다. 다음 중 하나라도 있으면 fail: "
    "(1) 수의사의 핵심 판단(가능한 원인, 위험한 정도)과 반대되는 말을 한다. "
    "(2) 수의사가 권한 핵심 조치(병원 진료 여부와 시급성, 지켜볼 증상, 멈출 것) 가운데 보호자가 꼭 알아야 할 것이 빠졌다. "
    "(3) 기준 답변에 없는 진단·약·용량을 단정한다. 표현이 다르거나 더 짧다는 것만으로는 fail이 아니다."
)
ANSWERS2_PATH = PROJECT_DIR / "tests" / "data" / "judge_validation_answers2.json"


def pick_answers2(lowest: int = 20, shortest: int = 10) -> list[dict]:
    used = {cell["answer"] for cell in load_cells()["answer"]}
    answers = [a for a in _answers().values()
               if a.get("correctness") is not None and a["route"] == "rag" and a["abstained"] in (False, "False")
               and a["id"] not in used]
    low = sorted(answers, key=lambda a: a["correctness"])[:lowest]
    short = sorted((a for a in answers if a not in low), key=lambda a: len(str(a["answer"])))[:shortest]
    picked = [(a, "low score") for a in low] + [(a, "short") for a in short]
    random.Random(SEED + 2).shuffle(picked)
    return [{"id": f"b{i + 1:02d}", "answer": a["id"], "correctness": round(a["correctness"], 3), "picked_for": why}
            for i, (a, why) in enumerate(picked)]


def write_sheet2(cells2: list[dict]) -> Path:
    esc = html.escape
    texts = answer_texts({"answer": cells2})
    head = ("<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>답변 판정 2</title><style>{SHEET_CSS}</style></head><body>")
    intro = ("<h1>답변 판정 2: 앱 답변이 수의사 답변과 맞나요? (30칸)</h1><p>지난번 30칸과 같은 방식입니다. 기준이 조금 바뀌었습니다: "
             "<b>보호자가 꼭 알아야 할 조치가 빠진 답도 fail</b>입니다. 고른 값은 이 브라우저에 자동 저장됩니다.</p>")
    parts = [head, "<div class='bar'><button id='dl'>결과 저장 (judge_labels2.json)</button><span id='count'></span></div>",
             intro, f"<div class='rubric'>{esc(ANSWER_CRITERION_V2)}</div>"]
    for n, cell in enumerate(cells2, 1):
        t = texts[cell["id"]]
        options = "".join(f"<label><input type='radio' name='{cell['id']}' value='{value}'>{esc(label)}</label>"
                          for value, label in (("pass", "pass 맞음"), ("fail", "fail 어긋남·빠짐·단정")))
        parts.append(f"<div class='card'><b>{n}.</b><div class='lab'>보호자 질문</div><div class='txt'>{esc(t['question'])}</div>"
                     f"<div class='lab'>수의사 답변 (기준)</div><div class='txt'>{esc(t['reference'])}</div>"
                     f"<div class='lab'>앱 답변</div><div class='txt'>{esc(t['answer'])}</div><div class='opts'>{options}</div></div>")
    script = SHEET_JS.replace("ragdog-judge-labels", "ragdog-judge-labels2").replace("'judge_labels.json'", "'judge_labels2.json'")
    parts.append(f"<script>{script}</script></body></html>")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "label_sheet2.html"
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def write_sheet(cells: dict) -> Path:
    rng = random.Random(SEED + 1)
    rel, ans = relevance_texts(cells), answer_texts(cells)
    rel_ids, ans_ids = list(rel), list(ans)
    rng.shuffle(rel_ids)
    rng.shuffle(ans_ids)
    esc = html.escape

    def radios(cell_id, options):
        return "<div class='opts'>" + "".join(
            f"<label><input type='radio' name='{cell_id}' value='{value}'>{esc(text)}</label>" for value, text in options) + "</div>"

    parts = [f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>판사 검증 라벨</title><style>{SHEET_CSS}</style></head><body>",
             "<div class='bar'><button id='dl'>결과 저장 (judge_labels.json)</button><span id='count'></span></div>",
             "<h1>판사 검증: 사람 판정</h1><p>판사의 점수는 숨겨 두었습니다. 고른 값은 이 브라우저에 자동 저장되고, "
             "끝나면 위의 버튼으로 내려받아 주세요. 수의학 지식이 없어도 보호자 눈높이로 판단하면 됩니다.</p>",
             "<h2>1부. 검색 후보가 질문에 쓸모 있나요? (48칸)</h2><div class='rubric'>"
             "<b>2</b>: 같은 문제(같은 증상·상황)를 다루고, 그 답변이 이 질문에 바로 도움이 된다.<br>"
             "<b>1</b>: 관련 있는 상황이나 일부 도움이 되는 조언이 있다(증상은 같지만 원인·상황이 다르거나, 일반적인 관리 요령만 겹침).<br>"
             "<b>0</b>: 다른 문제를 다루거나 도움이 되지 않는다.<br>나이·견종이 달라도 같은 문제를 다루면 2가 될 수 있습니다.</div>"]
    for n, cell_id in enumerate(rel_ids, 1):
        t = rel[cell_id]
        parts.append(f"<div class='card'><b>{n}.</b><div class='lab'>보호자 질문</div><div class='txt'>{esc(t['question'])}</div>"
                     f"<div class='lab'>검색 후보 · 다른 보호자의 질문</div><div class='txt'>{esc(t['candidate_question'])}</div>"
                     f"<div class='lab'>검색 후보 · 수의사 답변(앞 300자)</div><div class='txt'>{esc(t['candidate_answer'])}</div>"
                     + radios(cell_id, [("2", "2 바로 도움"), ("1", "1 일부 도움"), ("0", "0 도움 안 됨")]) + "</div>")
    parts.append(f"<h2>2부. 앱 답변이 수의사 답변과 맞나요? (30칸)</h2><div class='rubric'>{esc(ANSWER_CRITERION)}</div>")
    for n, cell_id in enumerate(ans_ids, 1):
        t = ans[cell_id]
        parts.append(f"<div class='card'><b>{n}.</b><div class='lab'>보호자 질문</div><div class='txt'>{esc(t['question'])}</div>"
                     f"<div class='lab'>수의사 답변 (기준)</div><div class='txt'>{esc(t['reference'])}</div>"
                     f"<div class='lab'>앱 답변</div><div class='txt'>{esc(t['answer'])}</div>"
                     + radios(cell_id, [("pass", "pass 맞음"), ("fail", "fail 어긋남·빠짐")]) + "</div>")
    parts.append(f"<script>{SHEET_JS}</script></body></html>")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "label_sheet.html"
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


# --- judges ----------------------------------------------------------------------------------

def chat_model(name: str, schema):
    if name.startswith("claude-"):  # another family (scripts/claude_judge.py), same call shape
        from claude_judge import StructuredClaude

        return StructuredClaude(schema, name)
    from langchain_openai import ChatOpenAI

    from src import settings

    extra = {"reasoning_effort": "low"} if name.startswith(("gpt-5", "gpt-6", "o")) else {"temperature": 0}
    return ChatOpenAI(model=name, api_key=settings.get_openai_api_key(), **extra).with_structured_output(schema)


def relevance_grades(model_name: str, cells: dict, reverse: bool = False) -> dict[str, int | None]:
    """Grade each cell's candidate the way scripts/relevance_set.py does: the whole pool in one call."""
    from relevance_set import Grades, judge, load_items

    items = {item["row"]: item for item in load_items()}
    df = _df()
    val = _val_rows()
    model = chat_model(model_name, Grades)

    def one(cell):
        ids = _pool(items[cell["row"]])
        if reverse:
            ids = ids[::-1]
        docs = [SimpleNamespace(id=d, page_content=df.loc[int(d), "qa.input"],
                                metadata={"qa.output": df.loc[int(d), "qa.output"]}) for d in ids]
        try:
            return judge(model, str(val.loc[int(cell["row"]), "qa.input"]), docs).get(cell["doc"])
        except Refused:
            return None  # counted like a missing grade

    with ThreadPoolExecutor(WORKERS) as pool:
        return dict(zip((c["id"] for c in cells["relevance"]), pool.map(one, cells["relevance"])))


def answer_verdicts(model_name: str, cells: dict) -> dict[str, dict]:
    texts = answer_texts(cells)
    model = chat_model(model_name, Verdict)

    def one(cell_id):
        t = texts[cell_id]
        try:
            result = model.invoke([("system", ANSWER_JUDGE), ("user", f"평가 기준: {ANSWER_CRITERION}\n\n보호자 질문: {t['question']}\n\n"
                                                                        f"수의사 답변(기준 답변): {t['reference']}\n\n앱 답변: {t['answer']}")])
        except Refused as refusal:
            return {"verdict": None, "reason": f"refused: {refusal}"}
        return {"verdict": result.verdict, "reason": result.reason}

    with ThreadPoolExecutor(WORKERS) as pool:
        return dict(zip(texts, pool.map(one, texts)))


def run_claude(model_name: str) -> dict:
    """The same relevance and answer judges on Claude, next to the earlier judges in judges.json
    (one entry per Claude model, under its name)."""
    cells = load_cells()
    judges = json.loads((OUT_DIR / "judges.json").read_text(encoding="utf-8"))
    judges["relevance"][model_name] = relevance_grades(model_name, cells)
    judges["answer"][model_name] = answer_verdicts(model_name, cells)
    (OUT_DIR / "judges.json").write_text(json.dumps(judges, ensure_ascii=False, indent=1), encoding="utf-8")
    return judges


EFFORT_LABELS = PROJECT_DIR / "tests" / "data" / "answer_effort_labels.json"


def effort_pairs(model_name: str) -> dict:
    """The 22 answered pairs of the answer-effort comparison (2026-10-21, medium vs low) judged by a
    model in both orders, against the person's blind read (tests/data/answer_effort_labels.json:
    "medium", "low" or "same" per question). Two-way rule: a winner only when both orders agree."""
    rows = {name: {r["id"]: r for r in json.loads((LATENCY_DIR / f"answer_{name}.json").read_text(encoding="utf-8"))["rows"]}
            for name in ("default", "low")}
    human = json.loads(EFFORT_LABELS.read_text(encoding="utf-8"))
    questions = {item["id"]: item["question"]
                 for item in json.loads((PROJECT_DIR / "tests" / "data" / "crag_eval_questions.json").read_text(encoding="utf-8"))["items"]}
    model = chat_model(model_name, PairVerdict)

    def ask(question, first, second):
        try:
            prompt = f"평가 기준: {PAIR_CRITERION}\n\n보호자 질문: {question}\n\n답 A: {first}\n\n답 B: {second}"
            return model.invoke([("system", PAIR_JUDGE), ("user", prompt)]).winner
        except Refused:
            return "refused"

    def one(qid):
        medium, low = rows["default"][qid]["answer"], rows["low"][qid]["answer"]
        forward = ask(questions[qid], medium, low)   # A = medium
        backward = ask(questions[qid], low, medium)  # A = low
        first = {"A": "medium", "B": "low"}.get(forward, "same")
        second = {"A": "low", "B": "medium"}.get(backward, "same")
        return {"forward": forward, "backward": backward, "judge": first if first == second else "same",
                "human": human[qid]}

    with ThreadPoolExecutor(WORKERS) as pool:
        out = dict(zip(human, pool.map(one, human)))
    agree = sum(r["judge"] == r["human"] for r in out.values())
    summary = {"model": model_name, "pairs": len(out), "agreement_with_person": f"{agree}/{len(out)}",
               "judge": {k: sum(r["judge"] == k for r in out.values()) for k in ("medium", "low", "same")},
               "person": {k: sum(r["human"] == k for r in out.values()) for k in ("medium", "low", "same")},
               "order_flips": sum(r["forward"] in ("A", "B") and r["backward"] in ("A", "B")
                                  and {"A": "medium", "B": "low"}[r["forward"]] != {"A": "low", "B": "medium"}[r["backward"]]
                                  for r in out.values())}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"effort_pairs_{model_name}.json").write_text(json.dumps({"summary": summary, "pairs": out}, ensure_ascii=False, indent=1),
                                                            encoding="utf-8")
    return summary


def run_judges(other: str) -> dict:
    from src import resources

    cells = load_cells()
    app = resources.CHAT_MODEL_NAME
    out = {"app_model": app, "other_model": other,
           "relevance": {"app_original": {c["id"]: c["judge"] for c in cells["relevance"]},
                         "app_again": relevance_grades(app, cells),
                         "app_reversed": relevance_grades(app, cells, reverse=True),
                         "other": relevance_grades(other, cells)},
           "answer": {"ragas_correctness": {c["id"]: c["correctness"] for c in cells["answer"]},
                      "app": answer_verdicts(app, cells), "other": answer_verdicts(other, cells)}}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "judges.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# --- bias: two-way pairwise ------------------------------------------------------------------

def two_way(first: str, second: str) -> str:
    """The winner when both orders agree, otherwise a tie (the lesson's rule)."""
    return first if first == second else "tie"


def build_pairs(cells: dict) -> list[dict]:
    """(original, variant, expected winner) for each answer cell: padded and authority should tie,
    the answer to another question should lose."""
    texts = answer_texts(cells)
    ids = list(texts)
    pairs = []
    for i, cell_id in enumerate(ids):
        t = texts[cell_id]
        other = texts[ids[(i + len(ids) // 2) % len(ids)]]["answer"]
        for kind, variant, expected in (("length", f"{t['answer']}\n\n{PADDING}", "tie"),
                                        ("authority", f"{t['answer']} {AUTHORITY}", "tie"),
                                        ("wrong", other, "original")):
            pairs.append({"cell": cell_id, "kind": kind, "expected": expected, "question": t["question"],
                          "reference": t["reference"], "original": t["answer"], "variant": variant})
    return pairs


def pair_verdicts(model_name: str, pairs: list[dict]) -> list[dict]:
    model = chat_model(model_name, PairVerdict)

    def ask(pair, original_first):
        a, b = (pair["original"], pair["variant"]) if original_first else (pair["variant"], pair["original"])
        result = model.invoke([("system", PAIR_JUDGE), ("user", f"평가 기준: {ANSWER_CRITERION}\n\n보호자 질문: {pair['question']}\n\n"
                                                                  f"수의사 답변(기준 답변): {pair['reference']}\n\n[답변 A]\n{a}\n\n[답변 B]\n{b}")])
        names = {"A": "original", "B": "variant"} if original_first else {"A": "variant", "B": "original"}
        return names.get(result.winner, "tie")

    jobs = [(pair, first) for pair in pairs for first in (True, False)]
    with ThreadPoolExecutor(WORKERS) as pool:
        winners = list(pool.map(lambda job: ask(*job), jobs))
    out = []
    for n, pair in enumerate(pairs):
        first, second = winners[2 * n], winners[2 * n + 1]
        out.append({"cell": pair["cell"], "kind": pair["kind"], "expected": pair["expected"],
                    "original_first": first, "variant_first": second, "two_way": two_way(first, second)})
    return out


def bias_summary(rows: list[dict]) -> dict:
    summary = {}
    for kind in ("length", "authority", "wrong"):
        part = [r for r in rows if r["kind"] == kind]
        orders = [w for r in part for w in (r["original_first"], r["variant_first"])]
        summary[kind] = {
            "pairs": len(part),
            "orders_disagree": sum(r["original_first"] != r["variant_first"] for r in part),
            "variant_won_one_order": sum(w == "variant" for w in orders),
            "one_order_right": sum(w == r["expected"] for r in part for w in (r["original_first"],)),
            "two_way_right": sum(r["two_way"] == r["expected"] for r in part),
        }
    return summary


def run_bias(other: str) -> dict:
    from src import resources

    pairs = build_pairs(load_cells())
    out = {}
    for label, name in (("app", resources.CHAT_MODEL_NAME), ("other", other)):
        rows = pair_verdicts(name, pairs)
        out[label] = {"model": name, "summary": bias_summary(rows), "rows": rows}
    (OUT_DIR / "bias.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def run_ragas_bias(model_name: str) -> dict:
    """The weekly gate's judge (RAGAS answer_correctness) on each answer as it is, padded, and with the
    authority sentence. Needs ragas: see the command in the module docstring of evaluate_answer_quality.py."""
    import asyncio
    import statistics

    from openai import AsyncOpenAI
    from ragas.embeddings.base import embedding_factory
    from ragas.llms import llm_factory
    from ragas.metrics.collections import AnswerCorrectness

    os.environ["RAGAS_DO_NOT_TRACK"] = "true"
    client = AsyncOpenAI()
    llm = llm_factory(model_name, client=client, max_tokens=8192,
                      system_prompt="모든 출력 문장(질문·주장·이유)은 한국어로 작성하세요.")
    metric = AnswerCorrectness(llm=llm, embeddings=embedding_factory("openai", model="text-embedding-3-large", client=client))
    texts = answer_texts(load_cells())
    variants = {"original": lambda t: t["answer"], "length": lambda t: f"{t['answer']}\n\n{PADDING}",
                "authority": lambda t: f"{t['answer']} {AUTHORITY}"}
    semaphore = asyncio.Semaphore(WORKERS)

    async def one(t, make):
        async with semaphore:
            for attempt in range(3):
                try:
                    result = await metric.ascore(user_input=t["question"], response=make(t), reference=t["reference"])
                    return float(result.value)
                except Exception:  # noqa: BLE001 - retried, then a missing score
                    await asyncio.sleep(2 + attempt * 3)
            return None

    async def run():
        jobs = [(cell, kind) for cell in texts for kind in variants]
        values = await asyncio.gather(*(one(texts[cell], variants[kind]) for cell, kind in jobs))
        return {(cell, kind): value for (cell, kind), value in zip(jobs, values)}

    scores = asyncio.run(run())
    out = {"model": model_name, "cells": {cell: {kind: scores[(cell, kind)] for kind in variants} for cell in texts}}
    for kind in ("length", "authority"):
        diffs = [scores[(c, kind)] - scores[(c, "original")] for c in texts
                 if scores[(c, kind)] is not None and scores[(c, "original")] is not None]
        out[kind] = {"mean_original": round(statistics.fmean(v for c in texts if (v := scores[(c, "original")]) is not None), 3),
                     "mean_variant": round(statistics.fmean(v for c in texts if (v := scores[(c, kind)]) is not None), 3),
                     "mean_change": round(statistics.fmean(diffs), 3), "variant_higher": sum(d > 0 for d in diffs),
                     "pairs": len(diffs)}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "ragas_bias.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# --- score -----------------------------------------------------------------------------------

def kappa(a: list, b: list, weights: str | None = None) -> float:
    """Cohen's kappa; weights="quadratic" for ordered grades (0, 1, 2)."""
    cats = sorted(set(a) | set(b))
    if len(cats) < 2:
        return 1.0 if a == b else 0.0
    index = {c: i for i, c in enumerate(cats)}
    k, n = len(cats), len(a)

    def weight(i, j):
        if weights == "quadratic":
            return (i - j) ** 2 / (k - 1) ** 2
        return 0.0 if i == j else 1.0

    observed = sum(weight(index[x], index[y]) for x, y in zip(a, b)) / n
    pa = [sum(index[x] == i for x in a) / n for i in range(k)]
    pb = [sum(index[y] == j for y in b) / n for j in range(k)]
    expected = sum(pa[i] * pb[j] * weight(i, j) for i in range(k) for j in range(k))
    return round(1 - observed / expected, 3) if expected else 1.0


def card(human: list[str], judge: list[str], failure: str) -> dict:
    """The lesson's scorecard: failure = the label that should be caught ("fail", "not useful")."""
    pairs = list(zip(human, judge))
    fails = [j for h, j in pairs if h == failure]
    passes = [j for h, j in pairs if h != failure]
    return {"cells": len(pairs), "agreement": round(sum(h == j for h, j in pairs) / len(pairs), 3),
            "failure_caught": round(sum(j == failure for j in fails) / len(fails), 3) if fails else None,
            "pass_kept": round(sum(j != failure for j in passes) / len(passes), 3) if passes else None,
            "kappa": kappa(human, judge), "human_failures": len(fails)}


def useful(grade) -> str:
    return "useful" if grade == 2 else "not useful"


def score(labels: dict[str, str]) -> dict:
    cells = load_cells()
    judges = json.loads((OUT_DIR / "judges.json").read_text(encoding="utf-8"))
    out: dict = {"relevance": {}, "answer": {}}
    rel_ids = [c["id"] for c in cells["relevance"] if c["id"] in labels]
    human = [int(labels[i]) for i in rel_ids]
    for name, grades in judges["relevance"].items():
        ids = [i for i in rel_ids if grades.get(i) is not None]
        h = [int(labels[i]) for i in ids]
        g = [int(grades[i]) for i in ids]
        out["relevance"][name] = {"exact_0_1_2": round(sum(x == y for x, y in zip(h, g)) / len(ids), 3),
                                  "weighted_kappa": kappa(h, g, "quadratic"),
                                  **card([useful(x) for x in h], [useful(x) for x in g], "not useful")}
    out["relevance"]["always_useful"] = card([useful(x) for x in human], ["useful"] * len(human), "not useful")
    ans_ids = [c["id"] for c in cells["answer"] if c["id"] in labels]
    human = [labels[i] for i in ans_ids]
    for name in ("app", "other", *sorted(k for k in judges["answer"] if k.startswith("claude-"))):
        verdicts = judges["answer"][name]
        ids = [i for i in ans_ids if verdicts[i]["verdict"]]  # a refusal is no verdict
        out["answer"][name] = card([labels[i] for i in ids], [verdicts[i]["verdict"] for i in ids], "fail")
    correctness = judges["answer"]["ragas_correctness"]
    for threshold in (0.25, 0.3, 0.35, 0.4):
        out["answer"][f"ragas>={threshold}"] = card(
            human, ["pass" if correctness[i] >= threshold else "fail" for i in ans_ids], "fail")
    out["answer"]["always_pass"] = card(human, ["pass"] * len(human), "fail")
    passed = [correctness[i] for i in ans_ids if labels[i] == "pass"]
    failed = [correctness[i] for i in ans_ids if labels[i] == "fail"]
    if passed and failed:  # the chance a human-pass answer scores above a human-fail one (AUC)
        out["answer"]["ragas_auc"] = round(sum((p > f) + 0.5 * (p == f) for p in passed for f in failed)
                                           / (len(passed) * len(failed)), 3)
    return out


def agreement_without_people() -> dict:
    """Judge against judge: what can be said before the person's labels are in."""
    judges = json.loads((OUT_DIR / "judges.json").read_text(encoding="utf-8"))
    rel = judges["relevance"]
    base = rel["app_original"]
    out = {}
    for name in ("app_again", "app_reversed", "other"):
        ids = [i for i in base if rel[name].get(i) is not None]
        a, b = [base[i] for i in ids], [rel[name][i] for i in ids]
        out[f"relevance: app_original vs {name}"] = {
            "cells": len(ids), "exact": round(sum(x == y for x, y in zip(a, b)) / len(ids), 3),
            "useful_flips": sum((x == 2) != (y == 2) for x, y in zip(a, b)), "weighted_kappa": kappa(a, b, "quadratic")}
    app, other = judges["answer"]["app"], judges["answer"]["other"]
    ids = list(app)
    out["answer: app vs other"] = {"cells": len(ids), "agreement": round(sum(app[i]["verdict"] == other[i]["verdict"] for i in ids) / len(ids), 3),
                                   "app_fail": sum(app[i]["verdict"] == "fail" for i in ids),
                                   "other_fail": sum(other[i]["verdict"] == "fail" for i in ids)}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("sheet", "judge", "bias", "ragas-bias", "agree", "score", "claude", "pairs", "sheet2"))
    parser.add_argument("--other-model", default=OTHER_MODEL)
    parser.add_argument("--claude-model", default=CLAUDE_MODEL, help="claude, pairs: the Claude model")
    parser.add_argument("--labels", type=Path, help="judge_labels.json saved from the labelling page")
    parser.add_argument("--yes", action="store_true", help="go on past the cost guard (scripts/cost_guard.py)")
    args = parser.parse_args()
    from cost_guard import confirm

    # judge: relevance 3 x 48 (one call per question's pool) + answers 2 x 30; bias: 30 answers x 3 pairs
    # x 2 orders x 2 judges; ragas-bias: 90 scores x about 3 calls
    # claude: relevance 48 + answers 30 on Claude; pairs: 22 pairs x 2 orders
    calls = {"judge": 3 * 48 + 2 * 30, "bias": 30 * 3 * 2 * 2, "ragas-bias": 90 * 3,
             "claude": 48 + 30, "pairs": 22 * 2}.get(args.command, 0)
    if calls and not confirm(f"judge_validation {args.command}", calls, yes=args.yes):
        return 1
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from dotenv import load_dotenv

    load_dotenv(PROJECT_DIR / ".env")
    sys.stdout.reconfigure(encoding="utf-8")
    if args.command == "sheet":
        if not CELLS_PATH.exists():
            CELLS_PATH.write_text(json.dumps(pick_cells(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("sheet:", write_sheet(load_cells()))
    elif args.command == "sheet2":
        if not ANSWERS2_PATH.exists():
            ANSWERS2_PATH.write_text(json.dumps(pick_answers2(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("sheet:", write_sheet2(json.loads(ANSWERS2_PATH.read_text(encoding="utf-8"))))
    elif args.command == "judge":
        run_judges(args.other_model)
        print(json.dumps(agreement_without_people(), ensure_ascii=False, indent=1))
    elif args.command == "ragas-bias":
        out = run_ragas_bias(os.getenv("OPENAI_EVAL_MODEL", "gpt-6-luna"))
        print(json.dumps({k: v for k, v in out.items() if k != "cells"}, ensure_ascii=False, indent=1))
    elif args.command == "claude":
        run_claude(args.claude_model)
        print(json.dumps(agreement_without_people(), ensure_ascii=False, indent=1))
    elif args.command == "pairs":
        print(json.dumps(effort_pairs(args.claude_model), ensure_ascii=False, indent=1))
    elif args.command == "agree":
        print(json.dumps(agreement_without_people(), ensure_ascii=False, indent=1))
    elif args.command == "bias":
        out = run_bias(args.other_model)
        print(json.dumps({k: {"model": v["model"], **v["summary"]} for k, v in out.items()}, ensure_ascii=False, indent=1))
    else:
        labels = json.loads(args.labels.read_text(encoding="utf-8"))
        result = score(labels)
        (OUT_DIR / "scores.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=1))
        with open(OUT_DIR / "labels.csv", "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows([("cell", "human")] + sorted(labels.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
