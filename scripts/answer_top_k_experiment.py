"""Do five consultations instead of three make the health answer carry more of the vet's answer? (2026-11-09)

The answer-prompt experiment (scripts/answer_prompt_experiment.py, dev 15) stopped at the prompt: in 4
of the 6 answers the judge failed for a missing action, that action was in none of the three retrieved
consultations. The app gives the answer model the first DEFAULT_RAG_TOP_K = 3 kept consultations
(src/chat_graph.py answer_documents); the CRAG search already fetches HEALTH_CANDIDATE_K = 5, so five
would cost no extra search, only input tokens and answer time. top-k was never varied before.

    uv run python scripts/answer_top_k_experiment.py generate --set dev --limit 3
    uv run --no-project --python 3.12 --with "ragas==0.4.3" --with "langchain-community<0.4" --with python-dotenv \
        python scripts/answer_top_k_experiment.py recall --set dev
    uv run python scripts/answer_top_k_experiment.py judge --set dev
    (the same three with --set holdout, then)  uv run python scripts/answer_top_k_experiment.py report --set holdout

Questions and references: the 100 long consultations of tests/data/health_relevance_100.json (vet answer
= the reference), split as in answer_prompt_experiment.py (dev 60 read before, holdout 40 never read).
Both arms: production search (SEARCH_BACKEND=supabase, set here), retrieve_health without CRAG, the
deployed prompt and answer model; only k differs (3 or 5). Measured per arm: RAGAS Context Recall (share
of the vet answer's claims backed by the passages, as the weekly regression scores it), rubric-2 judge
fails (scripts/judge_validation.py ANSWER_CRITERION_V2), sentences with a number in none of their
evidence (src/citations.py, no model), answer time and evidence length.

Decision, set before measuring, on holdout only (40): change DEFAULT_RAG_TOP_K to 5 if
(1) mean Context Recall rises by at least 0.05 (judge spread of the mean on 100 questions: 0.018),
(2) rubric-2 fails fall by at least 4 (k5 <= k3 - 4),
(3) sentences with an unsupported number rise by at most 2 (more cases, more chance to copy another dog's), and
(4) the median answer time rises by at most 1.0 s.
Result (2026-11-09): Context Recall 0.464 -> 0.544, fails 25 -> 24; three kept (docs/wiki/judge-validation.md).

Holdout 2 (--set holdout2, the default): neither five cases (above) nor rules 6 and 17 (dev 15 of
answer_prompt_experiment.py) cut the fails alone, and the 100 questions have now all been read. So both
together, on 40 new rows: `build-holdout2` picks them (tests/data/answer_holdout_2.json, fixed seed,
no model call) from the df_val rows no earlier evaluation read. Arms: k3 (the app now) and k5_rules
(5 cases and the candidate prompt of answer_prompt_experiment.candidate_template). Decision, set before
measuring, on these 40: the same four checks as above, k5_rules against k3; all four, and the app
takes both changes.
Model calls: generate 2, recall 2, judge 2 per question (scripts/cost_guard.py).
Results: output/experiments/answer_top_k_<set>.json (local).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

OUT_DIR = PROJECT_DIR / "output" / "experiments"
ARMS = {"k3": 3, "k5": 5}
# holdout2: the current answer (3 cases, current prompt) against both changes together (5 cases and
# rules 6 and 17 of scripts/answer_prompt_experiment.py), since neither alone cut the fails.
COMBINED = {"k3": (3, False), "k5_rules": (5, True)}
HOLDOUT2 = PROJECT_DIR / "tests" / "data" / "answer_holdout_2.json"
HOLDOUT2_SIZE = 40
HOLDOUT2_SEED = 20261109
JUDGE_MODEL = "gpt-6-luna"
WORKERS = 4


def arms(split: str) -> dict[str, tuple[int, bool]]:
    """Arm name -> (cases given to the answer model, candidate prompt rules)."""
    return COMBINED if split == "holdout2" else {name: (k, False) for name, k in ARMS.items()}


def _normal(text: str) -> str:
    return " ".join(text.split())


def _val_rows() -> list[dict]:
    import csv

    csv.field_size_limit(10**8)
    with open(PROJECT_DIR / "data" / "df_val.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build_holdout2() -> dict:
    """40 data/df_val.csv rows no earlier evaluation has read: not the 100 answer-quality questions
    (tests/data/health_relevance_100.json), the 치과 set, the CRAG grader labels or the CRAG answerable
    questions, and not a row whose consultation is retold in the corpus (eval_overlap_labels.json
    `same`, which hands the search its own answer)."""
    import random

    val = _val_rows()
    data = PROJECT_DIR / "tests" / "data"

    def read(name):
        return json.loads((data / name).read_text(encoding="utf-8"))

    excluded = {
        "health_relevance_100": {int(item["row"]) for item in read("health_relevance_100.json")["items"]},
        "health_relevance_dental": {int(item["row"]) for item in read("health_relevance_dental.json")["items"]},
        "crag_grader_labels": {int(item["row"]) for item in read("crag_grader_labels.json")["items"]},
        "eval_overlap_same": {int(row) for row in read("eval_overlap_labels.json")["same"]},
    }
    # Three of the CRAG questions are shortened copies of their row, so the first 60 characters match.
    asked = {_normal(item["question"])[:60] for item in read("crag_eval_questions.json")["items"]
             if item["group"] == "health_answerable"}
    excluded["crag_eval_questions"] = {i for i, row in enumerate(val) if _normal(row["qa.input"])[:60] in asked}
    left = sorted(set(range(len(val))) - set().union(*excluded.values()))
    rows = sorted(random.Random(HOLDOUT2_SEED).sample(left, HOLDOUT2_SIZE))
    return {"description": "Answer-quality holdout 2 (scripts/answer_top_k_experiment.py build-holdout2): data/df_val.csv "
                           "rows no earlier evaluation read; the vet answer (qa.output) is the reference.",
            "seed": HOLDOUT2_SEED, "excluded": {name: len(ids) for name, ids in excluded.items()},
            "candidates": len(left), "rows": rows}


def load_questions(split: str) -> list[dict]:
    if split != "holdout2":
        from answer_prompt_experiment import questions

        return questions(split)
    val = _val_rows()
    rows = json.loads(HOLDOUT2.read_text(encoding="utf-8"))["rows"]
    return [{"id": f"val-{row}", "question": val[row]["qa.input"].replace("\r", ""),
             "reference": val[row]["qa.output"].replace("\r", "")} for row in rows]


def result_path(split: str) -> Path:
    return OUT_DIR / f"answer_top_k_{split}.json"


def load(split: str) -> dict:
    path = result_path(split)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(split: str, data: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result_path(split).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def confirm_calls(name: str, calls: int) -> None:
    from cost_guard import confirm

    if calls and not confirm(f"answer_top_k_experiment {name}", calls):
        raise SystemExit(1)


def generate(split: str, limit: int | None) -> None:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ["SEARCH_BACKEND"] = "supabase"
    from answer_prompt_experiment import candidate_template
    from langchain_core.prompts import ChatPromptTemplate

    from src import resources
    from src.tools import health

    assert resources.search_backend() == "supabase", "SUPABASE_DB_URL is needed: the arms are measured on production search"
    data = load(split)
    specs = arms(split)
    todo = [q for q in load_questions(split) if q["id"] not in data][: limit or None]
    confirm_calls(f"generate {split}", len(specs) * len(todo))
    chain = health.load_rag_chain()
    assert chain is not None, "OPENAI_API_KEY is needed"
    system = candidate_template(health.RAG_PROMPT.messages[0].prompt.template)
    rules = ChatPromptTemplate.from_messages([("system", system), ("human", "{question}")])
    chains = {False: chain, True: rules | chain.middle[0] | chain.last}

    def one(item):
        index, q = item
        out = {**q, "backend": resources.search_backend()}
        # The arm order alternates, so a slower first or second call does not side with one arm.
        for arm in (list(specs) if index % 2 == 0 else list(specs)[::-1]):
            k, with_rules = specs[arm]
            docs = health.retrieve_health(q["question"], k=k)
            context = health.format_rag_context(docs)
            inputs = {"context": context, "chat_history": "없음", "filters": health.build_filter_context(None),
                      "profile": "없음", "notes": "없음", "question": q["question"],
                      "first_aid": "\n".join(f"- {s}" for s in health.first_aid_steps(q["question"], False)) or "없음"}
            started = time.perf_counter()
            answer = chains[with_rules].invoke(inputs)
            out[arm] = {"answer": answer, "seconds": round(time.perf_counter() - started, 2),
                        "docs": [doc.id for doc in docs], "context_chars": len(context),
                        "contexts": [health.format_rag_context([doc]) for doc in docs],
                        "cases": [f"{d.page_content}\n{d.metadata.get('qa.output', '')}" for d in docs
                                  if d.metadata.get("kind") != "care_guide"]}
        return out

    with ThreadPoolExecutor(WORKERS) as pool:
        for row in pool.map(one, enumerate(todo)):
            data[row["id"]] = row
            print("generated", row["id"], flush=True)
    save(split, data)


def recall(split: str) -> None:
    """RAGAS Context Recall, as scripts/evaluate_answer_quality.py judges it (run in the ragas environment)."""
    import asyncio

    from dotenv import load_dotenv
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import ContextRecall

    load_dotenv(PROJECT_DIR / ".env")
    os.environ["RAGAS_DO_NOT_TRACK"] = "true"
    data = load(split)
    jobs = [(rid, arm) for rid, row in data.items() for arm in arms(split) if "context_recall" not in row[arm]]
    confirm_calls(f"recall {split}", len(jobs))
    llm = llm_factory(os.getenv("OPENAI_EVAL_MODEL", JUDGE_MODEL), client=AsyncOpenAI(), max_tokens=8192,
                      system_prompt="모든 출력 문장(질문·주장·이유)은 한국어로 작성하세요.")
    metric = ContextRecall(llm=llm)
    semaphore = asyncio.Semaphore(WORKERS)

    async def score(rid, arm):
        row = data[rid]
        async with semaphore:
            for attempt in range(3):
                try:
                    result = await metric.ascore(user_input=row["question"], retrieved_contexts=row[arm]["contexts"],
                                                 reference=row["reference"])
                    return None if result.value is None else float(result.value)
                except Exception as exc:  # noqa: BLE001 - a judge failure is a missing score, retried twice
                    print("recall retry", rid, arm, type(exc).__name__, flush=True)
                    await asyncio.sleep(2 + attempt * 3)
        return None

    async def run():
        return await asyncio.gather(*(score(rid, arm) for rid, arm in jobs))

    for (rid, arm), value in zip(jobs, asyncio.run(run())):
        if value is not None:
            data[rid][arm]["context_recall"] = value
    save(split, data)


def judge(split: str) -> None:
    from judge_validation import (
        ANSWER_CRITERION_V2,
        ANSWER_JUDGE,
        Verdict,
        answer_prompt,
        chat_model,
    )

    data = load(split)
    jobs = [(rid, arm) for rid, row in data.items() for arm in arms(split) if "verdict" not in row[arm]]
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


def unsupported(row: dict, arm: str) -> int:
    from src import citations

    problems = citations.check_answer(citations.attach_citations(row[arm]["answer"]), row[arm]["cases"], [],
                                      context=row["question"])
    return len(problems.unsupported)


def summarize(rows: list[dict], names=tuple(ARMS), count_unsupported=unsupported) -> dict:
    """names = (current arm, new arm)."""
    out = {"n": len(rows)}
    for arm in names:
        recalls = [r[arm]["context_recall"] for r in rows if "context_recall" in r[arm]]
        judged = [r for r in rows if "verdict" in r[arm]]
        out[arm] = {"context_recall": round(statistics.fmean(recalls), 3) if recalls else None, "recall_scored": len(recalls),
                    "fail": sum(r[arm]["verdict"] == "fail" for r in judged), "judged": len(judged),
                    "unsupported_sentences": sum(count_unsupported(r, arm) for r in rows),
                    "median_seconds": round(statistics.median(r[arm]["seconds"] for r in rows), 2) if rows else None,
                    "mean_context_chars": round(statistics.fmean(r[arm]["context_chars"] for r in rows)) if rows else None}
    old, new = names
    both = [r for r in rows if "verdict" in r[old] and "verdict" in r[new]]
    out["fail_to_pass"] = sum(r[old]["verdict"] == "fail" and r[new]["verdict"] == "pass" for r in both)
    out["pass_to_fail"] = sum(r[old]["verdict"] == "pass" and r[new]["verdict"] == "fail" for r in both)
    return out


def decide(out: dict, names=tuple(ARMS)) -> dict | None:
    """The decision set before measuring (the same four checks on holdout and holdout2); None until
    every row is scored and judged."""
    k3, k5 = out[names[0]], out[names[1]]
    if not out["n"] or any(arm[key] != out["n"] for arm in (k3, k5) for key in ("recall_scored", "judged")):
        return None
    checks = {"recall_up_0_05": k5["context_recall"] >= k3["context_recall"] + 0.05,
              "fails_fall_by_4": k5["fail"] <= k3["fail"] - 4,
              "unsupported_up_at_most_2": k5["unsupported_sentences"] <= k3["unsupported_sentences"] + 2,
              "median_seconds_up_at_most_1": k5["median_seconds"] <= k3["median_seconds"] + 1.0}
    return {**checks, "change": all(checks.values())}


def report(split: str) -> dict:
    names = tuple(arms(split))
    out = {"set": split, **summarize(list(load(split).values()), names)}
    if split in ("holdout", "holdout2") and (decision := decide(out, names)):
        out["decision"] = decision
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["build-holdout2", "generate", "recall", "judge", "report"])
    parser.add_argument("--set", choices=["dev", "holdout", "holdout2"], default="holdout2")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")  # experiments stay out of the Langfuse quota
    if args.step == "build-holdout2":  # no model call; the file is committed before any answer is made
        HOLDOUT2.write_text(json.dumps(build_holdout2(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(HOLDOUT2.read_text(encoding="utf-8")[:400])
        return 0
    if args.step == "recall":  # the ragas environment has neither the project's packages nor its LangChain
        recall(args.set)
        print(json.dumps({rid: {arm: row[arm].get("context_recall") for arm in arms(args.set)} for rid, row in load(args.set).items()}))
        return 0
    from dotenv import load_dotenv

    load_dotenv(PROJECT_DIR / ".env")
    if args.step == "generate":
        generate(args.set, args.limit)
    elif args.step == "judge":
        judge(args.set)
    report(args.set)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
