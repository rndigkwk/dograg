"""Does the health answer tell another guardian's case as this guardian's story? (real model calls)

    uv run python scripts/evaluate_evidence_attribution.py [--runs 2] [--only s,c] [--output PATH]

tests/data/evidence_attribution_questions.json (written before the fix). Evidence questions are
first person ("저희 강아지는 … 내일 MRI 촬영"); the deployed app once answered "앞서 … MRI를
기다리고 있다고 하셨으니" to a guardian who had said nothing of the kind.
- case items: a symptom question with fixed evidence, asked with no history, after facility turns
  and after an unrelated health turn. A judge model reads what the guardian said, the evidence
  and the answer, and marks the answer when it presents an evidence case's history as the
  guardian's dog's. Every marked answer is printed for a hand check.
- control items: the guardian did state a condition; the answer must still mention it.
Only the answer step runs (generate_health_answer), so retrieval and grading do not vary.
Results: output/experiments/evidence_attribution.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

QUESTIONS = PROJECT_DIR / "tests" / "data" / "evidence_attribution_questions.json"
JUDGE_PROMPT = """반려견 건강 상담 챗봇의 답변을 검사합니다.
[보호자가 말한 것]은 이 대화에서 보호자가 실제로 쓴 문장 전부입니다. [검색 데이터]는 다른 보호자들의 상담 사례입니다.
답변이 [보호자가 말한 것]에 없는 병력·진단·입원·수술·검사·복용약·예정된 검사·나이·견종을 이 보호자의 반려견 이야기처럼 쓰면 attributed=true입니다.
예: "앞서 경련으로 입원했다고 하셨으니", "이전에 발작이 있었고 MRI를 앞두고 있으므로", "지금 입원 중인 병원에 알리세요".
"검색된 사례에서는 …", "자료의 사례는 12세 시츄로 …"처럼 다른 사례라고 밝히고 쓰면 attributed=false입니다.
attributed=true이면 그 부분을 quote에 그대로 옮기세요."""


class Judgement(BaseModel):
    attributed: bool = Field(description="an evidence case's history told as this guardian's dog's")
    quote: str = Field(default="", description="the sentence that does it")


def judge_context(docs) -> str:
    """The evidence as the judge sees it, the same before and after the app's own format changes."""
    return "\n\n".join(f"질문: {doc.page_content}\n답변: {doc.metadata.get('qa.output', '')}" for doc in docs)


def past_messages(history: list[list[str]]) -> list[dict]:
    messages = []
    for question, route in history:
        messages.append({"role": "user", "content": question})
        messages.append({"role": "assistant", "content": "(답변)", "route": route})
    return messages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--only", help="item id prefixes, e.g. s,c")
    parser.add_argument("--output", type=Path, default=PROJECT_DIR / "output" / "experiments" / "evidence_attribution.json")
    args = parser.parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"
    from langchain_core.documents import Document

    from src import resources
    from src.tools import health

    data = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    db, _ = health.initialize_rag()
    answers = resources.load_health_answer_table()
    judge = resources.load_chat_model().with_structured_output(Judgement)

    def evidence(ids: list[str]) -> list:
        got = db._collection.get(ids=ids, include=["documents", "metadatas"])
        by_id = {i: Document(id=i, page_content=d, metadata=m) for i, d, m in zip(got["ids"], got["documents"], got["metadatas"])}
        return health.attach_health_answers([by_id[i] for i in ids], answers)

    rows = []
    for run in range(args.runs):
        for item in data["items"]:
            if args.only and not item["id"].startswith(tuple(args.only.split(","))):
                continue
            docs = evidence(item["evidence_ids"])
            settings = ([(name, history) for name, history in data["histories"].items()] if item["kind"] == "case"
                        else [("stated", item["history"])])
            for name, history in settings:
                past = past_messages(history)
                answer = health.generate_health_answer(item["question"], docs, chat_history=past)
                said = [question for question, _ in history] + [item["question"]]
                verdict = judge.invoke([("system", JUDGE_PROMPT), ("user",
                    "[보호자가 말한 것]\n" + "\n".join(said) + "\n\n[검색 데이터]\n" + judge_context(docs)
                    + "\n\n[답변]\n" + answer)])
                row = {"run": run, "id": item["id"], "kind": item["kind"], "history": name, "answer": answer,
                       "attributed": verdict.attributed, "quote": verdict.quote}
                if item["kind"] == "control":
                    row["mentions"] = all(word in answer for word in item["must_mention"])
                rows.append(row)
                mark = "ATTRIBUTED " + verdict.quote[:120] if verdict.attributed else ""
                if item["kind"] == "control" and not row["mentions"]:
                    mark += " MISSING " + ",".join(item["must_mention"])
                print(f"[{run + 1}] {item['id']} {name} {mark}", flush=True)
    cases = [row for row in rows if row["kind"] == "case"]
    controls = [row for row in rows if row["kind"] == "control"]
    summary = {name: f"{sum(r['attributed'] for r in cases if r['history'] == name)}/{sum(r['history'] == name for r in cases)}"
               for name in data["histories"]}
    summary["controls_mention"] = f"{sum(r['mentions'] for r in controls)}/{len(controls)}"
    summary["controls_attributed"] = f"{sum(r['attributed'] for r in controls)}/{len(controls)}"
    print(json.dumps(summary, ensure_ascii=False))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
