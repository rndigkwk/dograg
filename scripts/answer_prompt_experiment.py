"""Does a health answer prompt that keeps the evidence's key actions and urgency pass the judge more often? (Day 60 appendix)

The answer judge with rubric 2 (scripts/judge_validation.py ANSWER_CRITERION_V2, kappa 0.46 with a
person) failed 39 of the 60 labelled answers. Most of its reasons were one kind: the vet's key action
or its urgency was missing ("3일 이내 수술", "13세에도 중성화를 권함"), the vet visit was put behind a
condition for a symptom the guardian already has ("계속되면 문의하세요" for vomiting that goes on),
or the answer stopped at "검색된 자료에는 없습니다". The candidate prompt (CANDIDATE below) changes
rule 6 (a symptom that is already there gets the visit without a condition) and adds rule 17 (the
key action and its timing in the evidence's vet answers are not left out). Rule 1 stays: only what
is in the evidence.

    uv run python scripts/answer_prompt_experiment.py generate --set dev --limit 15
    uv run python scripts/answer_prompt_experiment.py judge --set dev
    uv run python scripts/answer_prompt_experiment.py generate --set holdout
    uv run python scripts/answer_prompt_experiment.py judge --set holdout
    uv run python scripts/answer_prompt_experiment.py pairs --set holdout
    uv run python scripts/answer_prompt_experiment.py report --set holdout

Questions: the 100 long consultations of tests/data/health_relevance_100.json (vet answer = the
reference). dev = the 60 whose answers were labelled and whose judge reasons were read
(tests/data/judge_validation.json answer cells and judge_validation_answers2.json); holdout = the
other 40, never read. Both prompts get the same retrieved documents (retrieve_health, no CRAG) and
the same answer model, so only the prompt differs. The answers are the chain's output before the
citation check.

Decision, set before measuring, on holdout only (40): keep the candidate if
(1) rubric-2 fails fall by at least 4 (new <= current - 4),
(2) in the two-way pairwise comparison (PAIR_CRITERION, both orders, a winner only when both agree)
    the candidate wins at least as often as the current prompt, and
(3) sentences whose number is in none of their evidence (src/citations.py, no model) rise by at most 2.
Model calls: generate 2 per question, judge 2 per question, pairs 2 per question (scripts/cost_guard.py).
Results: output/experiments/answer_prompt_<set>.json (local).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

OUT_DIR = PROJECT_DIR / "output" / "experiments"
JUDGE_MODEL = "gpt-6-luna"
WORKERS = 6

RULE6_OLD = "6. 병원 진료 권고는 답의 끝에 한 문장만 쓰고, \"○○이 보이면\"처럼 어떤 때 가야 하는지 구체적으로 적으세요."
RULE6_NEW = ("6. 병원 진료 권고는 답의 끝에 한 문장만 쓰세요. 질문에 적힌 증상이 이미 계속되거나 되풀이되고 있고(며칠째, 여러 번) "
             "[검색 데이터]의 수의사 답변이 그런 상황에 진료·검사를 권하면, 조건을 달지 말고 \"지금 증상으로 동물병원 진료를 받으세요\"처럼 "
             "바로 권하세요. 아직 없는 증상에만 \"○○이 보이면\"처럼 어떤 때 가야 하는지 구체적으로 적으세요.")
RULE17 = ("17. [검색 데이터]의 수의사 답변이 질문과 같은 상황에 권한 핵심 조치(수술, 검사, 약을 끊거나 바꾸기, 활동 제한 등)와 "
          "그 시기(예: \"3일 이내\", \"매월\")는 빠뜨리지 말고 쓰세요. 질문의 일부가 자료에 없더라도 \"검색된 자료에는 없습니다\"로 "
          "답을 끝내지 말고, 데이터에 있는 조치를 먼저 쓰세요.")
RULE16_START = "16. [응급 대처]가"


def candidate_template(current: str) -> str:
    if RULE6_NEW in current and RULE17 in current:  # the app has both since 2026-11-10
        return current
    assert current.count(RULE6_OLD) == 1, "rule 6 changed; update RULE6_OLD"
    text = current.replace(RULE6_OLD, RULE6_NEW)
    end = text.index("\n\n[응급 대처]\n")
    assert RULE16_START in text[:end]
    return text[:end] + "\n" + RULE17 + text[end:]


def questions(split: str) -> list[dict]:
    csv.field_size_limit(10**8)
    with open(PROJECT_DIR / "data" / "df_val.csv", encoding="utf-8", newline="") as f:
        val = list(csv.DictReader(f))
    items = json.loads((PROJECT_DIR / "tests" / "data" / "health_relevance_100.json").read_text(encoding="utf-8"))["items"]
    cells = json.loads((PROJECT_DIR / "tests" / "data" / "judge_validation.json").read_text(encoding="utf-8"))["answer"]
    cells2 = json.loads((PROJECT_DIR / "tests" / "data" / "judge_validation_answers2.json").read_text(encoding="utf-8"))
    dev = {cell["answer"] for cell in [*cells, *cells2]}
    assert len(dev) == 60
    rows = [{"id": f"long-{i}", "question": val[int(item["row"])]["qa.input"].replace("\r", ""),
             "reference": val[int(item["row"])]["qa.output"].replace("\r", "")} for i, item in enumerate(items)]
    return [row for row in rows if (row["id"] in dev) == (split == "dev")]


def result_path(split: str) -> Path:
    return OUT_DIR / f"answer_prompt_{split}.json"


def load(split: str) -> dict:
    path = result_path(split)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(split: str, data: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result_path(split).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def confirm_calls(name: str, calls: int) -> None:
    from cost_guard import confirm

    if calls and not confirm(f"answer_prompt_experiment {name}", calls):
        raise SystemExit(1)


def generate(split: str, limit: int | None) -> None:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from langchain_core.prompts import ChatPromptTemplate

    from src.tools import health

    data = load(split)
    todo = [q for q in questions(split) if q["id"] not in data][: limit or None]
    confirm_calls(f"generate {split}", 2 * len(todo))
    chain = health.load_rag_chain()
    assert chain is not None, "OPENAI_API_KEY is needed"
    current = health.RAG_PROMPT
    system = current.messages[0].prompt.template
    new_prompt = ChatPromptTemplate.from_messages([("system", candidate_template(system)), ("human", "{question}")])
    chains = {"current": chain, "candidate": new_prompt | chain.middle[0] | chain.last}

    def one(q):
        docs = health.retrieve_health(q["question"])
        inputs = {"context": health.format_rag_context(docs), "chat_history": "없음", "filters": health.build_filter_context(None),
                  "profile": "없음", "notes": "없음", "question": q["question"],
                  "first_aid": "\n".join(f"- {s}" for s in health.first_aid_steps(q["question"], False)) or "없음"}
        out = {**q, "docs": [doc.id for doc in docs],
               "cases": [f"{d.page_content}\n{d.metadata.get('qa.output', '')}" for d in docs if d.metadata.get("kind") != "care_guide"],
               "guides": [d.page_content for d in docs if d.metadata.get("kind") == "care_guide"]}
        for name, c in chains.items():
            out[name] = {"answer": c.invoke(inputs)}
        return out

    with ThreadPoolExecutor(WORKERS) as pool:
        for row in pool.map(one, todo):
            data[row["id"]] = row
            print("generated", row["id"], flush=True)
    save(split, data)


def unsupported(row: dict, arm: str) -> int:
    from src import citations

    problems = citations.check_answer(citations.attach_citations(row[arm]["answer"]), row["cases"], row["guides"],
                                      context=row["question"])
    return len(problems.unsupported)


def judge(split: str) -> None:
    from judge_validation import (
        ANSWER_CRITERION_V2,
        ANSWER_JUDGE,
        Verdict,
        answer_prompt,
        chat_model,
    )

    data = load(split)
    jobs = [(rid, arm) for rid, row in data.items() for arm in ("current", "candidate") if "verdict" not in row[arm]]
    confirm_calls(f"judge {split}", len(jobs))
    model = chat_model(JUDGE_MODEL, Verdict)

    def one(job):
        rid, arm = job
        row = data[rid]
        result = model.invoke([("system", ANSWER_JUDGE),
                               ("user", answer_prompt({**row, "answer": row[arm]["answer"]}, ANSWER_CRITERION_V2))])
        return job, {"verdict": result.verdict, "reason": result.reason}

    with ThreadPoolExecutor(WORKERS) as pool:
        for (rid, arm), verdict in pool.map(one, jobs):
            data[rid][arm].update(verdict)
    save(split, data)


def pairs(split: str) -> None:
    from judge_validation import (
        PAIR_CRITERION,
        PAIR_JUDGE,
        PairVerdict,
        chat_model,
        two_way,
    )

    data = load(split)
    todo = [rid for rid, row in data.items() if "pair" not in row]
    confirm_calls(f"pairs {split}", 2 * len(todo))
    model = chat_model(JUDGE_MODEL, PairVerdict)

    def ask(rid, current_first):
        row = data[rid]
        a, b = ((row["current"], row["candidate"]) if current_first else (row["candidate"], row["current"]))
        result = model.invoke([("system", PAIR_JUDGE), ("user", (f"평가 기준: {PAIR_CRITERION}\n\n보호자 질문: {row['question']}\n\n"
                                                                f"수의사 답변(기준 답변): {row['reference']}\n\n"
                                                                f"[답변 A]\n{a['answer']}\n\n[답변 B]\n{b['answer']}"))])
        names = {"A": "current", "B": "candidate"} if current_first else {"A": "candidate", "B": "current"}
        return names.get(result.winner, "tie")

    jobs = [(rid, first) for rid in todo for first in (True, False)]
    with ThreadPoolExecutor(WORKERS) as pool:
        winners = list(pool.map(lambda job: ask(*job), jobs))
    for n, rid in enumerate(todo):
        first, second = winners[2 * n], winners[2 * n + 1]
        data[rid]["pair"] = {"current_first": first, "candidate_first": second, "winner": two_way(first, second)}
    save(split, data)


def report(split: str) -> dict:
    data = load(split)
    rows = list(data.values())
    out = {"set": split, "n": len(rows)}
    for arm in ("current", "candidate"):
        judged = [r for r in rows if "verdict" in r[arm]]
        out[arm] = {"fail": sum(r[arm]["verdict"] == "fail" for r in judged), "judged": len(judged),
                    "unsupported_sentences": sum(unsupported(r, arm) for r in rows),
                    "mean_chars": round(sum(len(r[arm]["answer"]) for r in rows) / max(len(rows), 1))}
    both = [r for r in rows if "verdict" in r["current"] and "verdict" in r["candidate"]]
    out["fail_to_pass"] = sum(r["current"]["verdict"] == "fail" and r["candidate"]["verdict"] == "pass" for r in both)
    out["pass_to_fail"] = sum(r["current"]["verdict"] == "pass" and r["candidate"]["verdict"] == "fail" for r in both)
    paired = [r["pair"]["winner"] for r in rows if "pair" in r]
    if paired:
        out["pairs"] = {k: paired.count(k) for k in ("candidate", "current", "tie")}
    if split == "holdout" and paired and out["current"]["judged"] == out["n"] == out["candidate"]["judged"]:
        checks = {"fails_fall_by_4": out["candidate"]["fail"] <= out["current"]["fail"] - 4,
                  "pairs_not_worse": out["pairs"]["candidate"] >= out["pairs"]["current"],
                  "unsupported_up_at_most_2": out["candidate"]["unsupported_sentences"] <= out["current"]["unsupported_sentences"] + 2}
        out["decision"] = {**checks, "keep": all(checks.values())}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["generate", "judge", "pairs", "report"])
    parser.add_argument("--set", choices=["dev", "holdout"], required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    from dotenv import load_dotenv

    load_dotenv(PROJECT_DIR / ".env")
    if args.step == "generate":
        generate(args.set, args.limit)
    elif args.step == "judge":
        judge(args.set)
    elif args.step == "pairs":
        pairs(args.set)
    report(args.set)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
