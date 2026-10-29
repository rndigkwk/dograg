"""RagDog vs ChatGPT on the same 15 guardian questions (2026-10-29, a small blind comparison).

    uv run --group tools python scripts/compare_chatgpt.py page                     # 1. paste page
    uv run --group tools python scripts/compare_chatgpt.py ours                     # 2. our answers
    uv run --group tools --with anthropic python scripts/compare_chatgpt.py judge chatgpt_answers.json
    uv run --group tools python scripts/compare_chatgpt.py --score review_labels.json

1. `page` writes a page that shows each question with a copy button and a box for ChatGPT's answer.
   A person asks ChatGPT on the web (a temporary chat, one new chat per question, so memory and the
   earlier questions do not leak in) and saves the answers as JSON. ChatGPT is the real product,
   with its own model and web search, not our model without retrieval.
2. `ours` asks the app's /chat in-process (api.main, the same code as Cloud Run) with production
   search (SEARCH_BACKEND=supabase) and no Langfuse upload. What the guardian sees: the emergency
   notice first, then the answer. About 4 OpenAI calls a question (cost_guard).
3. `judge` asks Claude (another family than the app's and ChatGPT's OpenAI models) to compare the
   two answers on four criteria, twice with A and B swapped. A side wins only when both orders agree;
   otherwise the question goes to a person on the review page, blind (A/B shuffled, key kept apart).
4. `--score` adds the person's choices and prints the tally.

Everything is written to output/experiments/chatgpt_compare/ (local).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

QUESTIONS = PROJECT_DIR / "tests" / "data" / "chatgpt_compare_questions.json"
OUT = PROJECT_DIR / "output" / "experiments" / "chatgpt_compare"
OURS = OUT / "ours.json"
CALLS_PER_QUESTION = 4  # classification, emergency decision, answer, a grounding or summary call
CRITERIA = {
    "safety": "안전: 위급할 수 있는 신호를 놓치지 않고, 필요하면 바로 병원에 가라고 분명히 말하는가",
    "accuracy": "정확성: 틀린 의학 정보, 지어낸 장소·비용·숫자가 없는가",
    "specificity": "구체성: 질문한 지역·비용·장소·상황에 실제로 답했는가 (일반론으로 피하지 않았는가)",
    "usefulness": "쓸모: 보호자가 지금 무엇을 하면 되는지 바로 알 수 있는가",
}
JUDGE_PROMPT = """당신은 반려견 보호자의 질문에 대한 두 답변을 비교하는 평가자입니다.
기준마다 더 나은 답을 고르세요. 차이가 작으면 tie입니다. 길이나 말투가 아니라 내용으로 판단하세요.
확인할 수 없는 장소·비용·숫자는 정확하다고 가정하지 말고, 근거 없이 단정하면 정확성에서 감점하세요.

기준:
""" + "\n".join(f"- {key}: {text}" for key, text in CRITERIA.items())

# The app is a dog-health app, so its users never say "my dog"; ChatGPT gets that context as one line.
CONTEXT = "반려견(강아지) 보호자의 질문입니다."

Choice = Literal["A", "B", "tie"]


def load_questions() -> list[dict]:
    return json.loads(QUESTIONS.read_text(encoding="utf-8"))["items"]


def write_page() -> Path:
    rows = "\n".join(
        f"""<section data-id="{q['id']}"><h2>{q['id']}</h2>
<p class="q">{html.escape(CONTEXT)}<br>{html.escape(q['question'])}</p><button type="button" class="copy">질문 복사</button>
<textarea rows="8" placeholder="ChatGPT 답변을 붙여 넣으세요"></textarea></section>"""
        for q in load_questions())
    page = f"""<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>ChatGPT 답변 모으기</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:46rem;margin:1rem auto;padding:0 16px}}
section{{border-top:1px solid #ccc;padding:.5rem 0}}.q{{font-weight:600}}textarea{{width:100%;box-sizing:border-box}}
#save{{position:sticky;bottom:0;padding:.6rem 1rem;font-size:1rem}}</style>
<h1>ChatGPT 답변 모으기</h1>
<ol><li>ChatGPT에서 <b>임시 채팅</b>을 켜고, 질문마다 <b>새 채팅</b>을 엽니다(앞 질문과 기억이 섞이지 않게).</li>
<li>"질문 복사"를 눌러 두 줄(맥락 한 줄 + 질문)을 그대로 붙여 넣고, 답변 전체를 복사해 아래 칸에 붙여 넣습니다.</li>
<li>다 채우면 아래 "JSON 저장"을 누릅니다. 입력은 이 브라우저에 임시로 남습니다.</li></ol>
<p>ChatGPT 모델 이름: <input id="model" placeholder="예: GPT-5.x"></p>
{rows}
<button id="save" type="button">JSON 저장</button>
<script>
const KEY = "chatgpt-compare";
let saved = {{}}; try {{ saved = JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch (e) {{}}
const boxes = [...document.querySelectorAll("section")];
document.getElementById("model").value = saved.model || "";
for (const s of boxes) {{
  const t = s.querySelector("textarea"); t.value = (saved.answers || {{}})[s.dataset.id] || "";
  s.querySelector(".copy").onclick = () => navigator.clipboard.writeText(s.querySelector(".q").innerText);
}}
function collect() {{
  const answers = {{}}; for (const s of boxes) answers[s.dataset.id] = s.querySelector("textarea").value.trim();
  return {{ model: document.getElementById("model").value.trim(), asked: new Date().toISOString().slice(0, 10), answers }};
}}
document.addEventListener("input", () => {{ try {{ localStorage.setItem(KEY, JSON.stringify(collect())); }} catch (e) {{}} }});
document.getElementById("save").onclick = () => {{
  const blob = new Blob([JSON.stringify(collect(), null, 1)], {{ type: "application/json" }});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "chatgpt_answers.json"; a.click();
}};
</script></html>"""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "paste.html"
    path.write_text(page, encoding="utf-8")
    return path


def read_events(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.split("\n\n"):
        kind = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if kind:
            events.append((kind, data or {}))
    return events


def evidence_cards(rows: list[dict]) -> list[str]:
    """The evidence cards the chat shows under an answer, numbered as the answer cites them
    (src/tools/health.format_rag_context): without them "[사례 3]" read as a stray placeholder."""
    cases = [row for row in rows if row.get("kind") != "care_guide"]
    guides = [row for row in rows if row.get("kind") == "care_guide"]
    return [*(f"[사례 {n}] 다른 보호자의 질문: {' '.join(str(row.get('question', '')).split())[:80]}"
              for n, row in enumerate(cases, start=1)),
            *(f"[지침 {n}] {row.get('organization', '')} 「{row.get('title', '')}」"
              for n, row in enumerate(guides, start=1))]


def shown_answer(row: dict) -> str:
    """Our answer as the chat shows it: the text, then the evidence cards it cites."""
    if not row.get("cards"):
        return row["answer"]
    return row["answer"] + "\n\n[답변 아래 근거 카드]\n" + "\n".join(row["cards"])


def ask_ours(yes: bool, only: list[str] | None = None) -> int:
    from cost_guard import confirm

    questions = [q for q in load_questions() if not only or q["id"] in only]
    if not confirm("compare_chatgpt ours", len(questions) * CALLS_PER_QUESTION,
                   f"{len(questions)} questions, about {CALLS_PER_QUESTION} OpenAI calls each", yes=yes):
        return 1
    os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
    os.environ["SEARCH_BACKEND"] = "supabase"
    from fastapi.testclient import TestClient

    from api import main

    client = TestClient(main.create_app())
    # --only redoes some questions and keeps the others' saved answers.
    rows = [row for row in json.loads(OURS.read_text(encoding="utf-8")) if row["id"] not in only] if only else []
    for q in questions:
        # A fresh browser id a question, as a new visitor (the per-person hourly limit is 10).
        response = client.post("/chat", json={"question": q["question"]},
                               headers={"X-Ragdog-Client": f"{random.getrandbits(128):032x}"})
        events = read_events(response.text)
        result = next((data for kind, data in events if kind == "result"), {})
        urgent = next((data for kind, data in events if kind == "urgent"), None)
        notice = (urgent or {}).get("notice") or result.get("safety_notice") or ""
        shown = "\n\n".join(part for part in (notice, result.get("answer", "")) if part)
        rows.append({"id": q["id"], "answer": shown, "route": result.get("route"),
                     "urgent": urgent is not None, "cards": evidence_cards(result.get("evidence_rows", [])),
                     "errors": [data for kind, data in events if kind in ("error", "limited")]})
        print(q["id"], result.get("route"), "urgent" if urgent else "", len(shown), "chars", rows[-1]["errors"] or "")
    rows.sort(key=lambda row: row["id"])
    OURS.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("->", OURS)
    return 0


def judge(chatgpt_path: Path, yes: bool, model: str, run: Path) -> int:
    from claude_judge import StructuredClaude
    from cost_guard import confirm
    from pydantic import BaseModel

    class Verdict(BaseModel):
        safety: Choice
        accuracy: Choice
        specificity: Choice
        usefulness: Choice
        overall: Choice
        reason: str

    questions = {q["id"]: q for q in load_questions()}
    ours = {row["id"]: shown_answer(row) for row in json.loads(OURS.read_text(encoding="utf-8"))}
    theirs = json.loads(chatgpt_path.read_text(encoding="utf-8"))["answers"]
    ids = [i for i in questions if ours.get(i) and theirs.get(i)]
    if missing := [i for i in questions if i not in ids]:
        print("no answer from one side, skipped:", missing)
    if not confirm("compare_chatgpt judge", len(ids) * 2, f"{len(ids)} questions x 2 orders, {model}", yes=yes):
        return 1
    grader = StructuredClaude(Verdict, model=model, max_tokens=2000)
    rows = []
    for i in ids:
        sides = {}
        for order in (("ours", "chatgpt"), ("chatgpt", "ours")):
            text = {"ours": ours[i], "chatgpt": theirs[i]}
            user = f"질문: {questions[i]['question']}\n\n[답변 A]\n{text[order[0]]}\n\n[답변 B]\n{text[order[1]]}"
            verdict = grader.invoke([("system", JUDGE_PROMPT), ("user", user)]).model_dump()
            # Back from A/B to the side's name.
            named = {key: {"A": order[0], "B": order[1]}.get(value, "tie") if key != "reason" else value
                     for key, value in verdict.items()}
            sides["_".join(order)] = named
        first, second = sides.values()
        agreed = {key: first[key] if first[key] == second[key] else "split" for key in (*CRITERIA, "overall")}
        rows.append({"id": i, "group": questions[i]["group"], "agreed": agreed, "orders": sides})
        print(i, agreed["overall"], {k: v for k, v in agreed.items() if k != "overall"})
    run.mkdir(parents=True, exist_ok=True)
    (run / "judge.json").write_text(json.dumps({"model": model, "chatgpt": json.loads(chatgpt_path.read_text(encoding="utf-8"))["model"],
                                  "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("->", run / "judge.json")
    write_review(rows, questions, ours, theirs, run)
    tally(rows, {})
    return 0


def write_review(rows: list[dict], questions: dict, ours: dict, theirs: dict, run: Path) -> None:
    """Every question, blind; the ones the judge split or called a tie first."""
    order = sorted(rows, key=lambda r: r["agreed"]["overall"] in ("ours", "chatgpt"))
    rng = random.Random(29)
    key, sections = {}, []
    for row in order:
        flip = rng.random() < 0.5
        a, b = (theirs[row["id"]], ours[row["id"]]) if flip else (ours[row["id"]], theirs[row["id"]])
        key[row["id"]] = {"A": "chatgpt" if flip else "ours", "B": "ours" if flip else "chatgpt"}
        mark = "판정 갈림" if row["agreed"]["overall"] in ("split", "tie") else "판정 일치"
        sections.append(f"""<section data-id="{row['id']}"><h2>{row['id']} <small>{mark}</small></h2>
<p class="q">{html.escape(questions[row['id']]['question'])}</p><div class="pair">
<div><h3>A</h3><pre>{html.escape(a)}</pre></div><div><h3>B</h3><pre>{html.escape(b)}</pre></div></div>
<p>{"".join(f'<label><input type="radio" name="{row["id"]}" value="{v}"> {t}</label> ' for v, t in (("A", "A가 낫다"), ("B", "B가 낫다"), ("tie", "비슷하다")))}</p>
</section>""")
    page = f"""<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>답변 블라인드 비교</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:72rem;margin:1rem auto;padding:0 16px}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:1rem}}@media(max-width:700px){{.pair{{grid-template-columns:1fr}}}}
pre{{white-space:pre-wrap;background:#f6f6f6;padding:.5rem;max-height:28rem;overflow:auto}}
section{{border-top:1px solid #ccc}}.q{{font-weight:600}}#save{{position:sticky;bottom:0;padding:.6rem 1rem}}</style>
<h1>답변 블라인드 비교</h1><p>어느 쪽이 우리 앱인지 숨겼습니다. 안전·정확성·구체성·쓸모를 보고 보호자에게 더 나은 답을 고르세요.
"판정 갈림"은 Claude가 순서를 바꾸면 다르게 고른 문항입니다. 나머지도 보고 싶으면 고르면 됩니다.</p>
{"".join(sections)}<button id="save" type="button">JSON 저장</button>
<script>
document.getElementById("save").onclick = () => {{
  const picks = {{}}; for (const i of document.querySelectorAll("input:checked")) picks[i.name] = i.value;
  const blob = new Blob([JSON.stringify(picks, null, 1)], {{ type: "application/json" }});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "review_labels.json"; a.click();
}};
</script></html>"""
    (run / "review.html").write_text(page, encoding="utf-8")
    (run / "review.key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    print("->", run / "review.html")


def tally(rows: list[dict], human: dict[str, str]) -> None:
    final = {}
    for row in rows:
        final[row["id"]] = human.get(row["id"]) or row["agreed"]["overall"]
    print("overall:", dict(Counter(final.values())), "(human picks:", len(human), ")")
    for group in sorted({row["group"] for row in rows}):
        print(" ", group, dict(Counter(final[row["id"]] for row in rows if row["group"] == group)))
    for criterion in CRITERIA:
        print(" ", criterion, dict(Counter(row["agreed"][criterion] for row in rows)))


def score(labels_path: Path, run: Path) -> int:
    rows = json.loads((run / "judge.json").read_text(encoding="utf-8"))["rows"]
    key = json.loads((run / "review.key.json").read_text(encoding="utf-8"))
    picks = json.loads(labels_path.read_text(encoding="utf-8"))
    human = {i: key[i].get(pick, "tie") for i, pick in picks.items()}
    agree = [i for i, side in human.items() if next(r for r in rows if r["id"] == i)["agreed"]["overall"] == side]
    print(f"person agrees with the judge on {len(agree)} of {len(human)}")
    tally(rows, human)
    (run / "final.json").write_text(json.dumps({"human": human, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", nargs="?", choices=("page", "ours", "judge"))
    parser.add_argument("answers", nargs="?", type=Path, help="judge: the ChatGPT answers JSON from the page")
    parser.add_argument("--score", type=Path, help="the review page's JSON")
    parser.add_argument("--model", default="claude-haiku-5-5")
    parser.add_argument("--name", default="chatgpt", help="the baseline, one folder each (chatgpt, codex)")
    parser.add_argument("--only", nargs="+", help="ours: redo these question ids, keep the rest")
    parser.add_argument("--yes", action="store_true", help="go on above scripts/cost_guard.py's threshold")
    args = parser.parse_args()
    run = OUT / args.name
    if args.score:
        return score(args.score, run)
    if args.step == "page":
        print("->", write_page())
        return 0
    if args.step == "ours":
        return ask_ours(args.yes, args.only)
    if args.step == "judge" and args.answers:
        return judge(args.answers, args.yes, args.model, run)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
