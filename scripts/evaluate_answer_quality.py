"""Are the health answers right? Answer Correctness, Context Recall and Answer Relevancy (Day 59, RAGAS).

The CRAG set only says whether the app answered or abstained. Here the reference is the real
veterinarian's answer: the 100 long consultations of tests/data/health_relevance_100.json are rows of
data/df_val.csv, whose qa.output is the answer a vet wrote for that consultation (the golden set the
lesson asks for). The vet answer also covers things only that dog's case has, so absolute scores are
low; the scores are for comparing two settings, not a pass mark by themselves.

Two steps in two environments (ragas 0.4.3 does not import with the project's LangChain):

    # 1. answers: the app as deployed (CRAG on, search in Supabase), in 4 processes per run
    uv run python scripts/evaluate_answer_quality.py generate --run 0 --shard 0/4   (... 1/4, 2/4, 3/4; run 1 the same)
    # 2. scores: ragas metrics, judged `--repeats` times to see how much the judge moves
    uv run --no-project --python 3.12 --with "ragas==0.4.3" --with "langchain-community<0.4" --with python-dotenv \
        python scripts/evaluate_answer_quality.py judge --repeats 3

generate records, per question, the answer and the evidence passages given to the answer model
(one string per retrieved case, as format_rag_context writes them). judge scores every answer of run
0 `--repeats` times and run 1 once, with the lesson's ragas metrics (evaluator: OPENAI_EVAL_MODEL or
gpt-6-luna with a Korean output rule; embeddings text-embedding-3-large):
- answer_correctness: 0.75 x claim F1 against the vet answer + 0.25 x semantic similarity
- context_recall: share of the vet answer's claims backed by the retrieved passages
- answer_relevancy: similarity of questions regenerated from the answer to the real question
Abstentions are reported apart (a correct "the material does not cover this" scores low on all three).
Noise: judge (same answers, repeats) and system (run 0 vs run 1, first judging).
Results: output/experiments/answer_quality_{gen_run<r>_<shard>,scores,summary}.json.

The weekly regression (.github/workflows/regression-eval.yml) runs one answer run and judges only
Answer Correctness once (`judge --repeats 1 --metrics answer_correctness --result-name <run>`): it was
the stable and sensitive one (docs/wiki/safety-and-evidence.md). --result-name also writes
output/experiments/answer_<run>.json in the shape scripts/check_regression.py reads.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_DIR / "output" / "experiments"
METRICS = ("answer_correctness", "context_recall", "answer_relevancy")


def golden_items() -> list[dict]:
    csv.field_size_limit(10**8)
    with open(PROJECT_DIR / "data" / "df_val.csv", encoding="utf-8", newline="") as f:
        val = list(csv.DictReader(f))
    items = json.loads((PROJECT_DIR / "tests" / "data" / "health_relevance_100.json").read_text(encoding="utf-8"))["items"]
    return [{"id": f"long-{index}", "row": int(item["row"]),
             "question": val[int(item["row"])]["qa.input"].replace("\r", ""),
             "reference": val[int(item["row"])]["qa.output"].replace("\r", "")} for index, item in enumerate(items)]


def generate(run: int, shard: int, shards: int) -> int:
    sys.path.insert(0, str(PROJECT_DIR))
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from src import chatbot as app
    from src import resources
    from src.tools import health

    items = [item for index, item in enumerate(golden_items()) if index % shards == shard]
    captured: list[list[str]] = []
    original = health.generate_health_answer

    def record(question, docs, *args, **kwargs):
        captured.append([health.format_rag_context([doc]) for doc in docs])
        return original(question, docs, *args, **kwargs)

    health.generate_health_answer = record
    rows = []
    with tempfile.TemporaryDirectory(prefix="ragdog-answer-quality-", ignore_cleanup_errors=True) as directory:
        resources.CHROMA_DIR = Path(directory) / "chroma_db"  # the local fallback, if Supabase fails
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", resources.CHROMA_DIR)
        for index, item in enumerate(items, start=1):
            captured.clear()
            started = time.perf_counter()
            try:
                result, error = app.chatbot(item["question"], crag=True, crag_reports=False), None
            except Exception as exc:  # noqa: BLE001 - one failure should not stop the evaluation
                result, error = {}, type(exc).__name__
            rows.append({**item, "run": run, "route": result.get("route", "error"), "error": error,
                         "abstained": bool(result.get("abstained")), "answer": result.get("answer", ""),
                         "contexts": captured[-1] if captured else [],
                         "latency_s": round(time.perf_counter() - started, 1)})
            print(f"[run {run} shard {shard} {index}/{len(items)}] {item['id']} {rows[-1]['route']}"
                  f"{' abstain' if rows[-1]['abstained'] else ''}", flush=True)
    path = OUT_DIR / f"answer_quality_gen_run{run}_{shard}.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", path)
    return 0


def judge(repeats: int, concurrency: int, names: tuple[str, ...] = METRICS, result_name: str | None = None) -> int:
    from dotenv import load_dotenv
    from openai import AsyncOpenAI
    from ragas.embeddings.base import embedding_factory
    from ragas.llms import llm_factory
    from ragas.metrics.collections import AnswerCorrectness, AnswerRelevancy, ContextRecall

    load_dotenv(PROJECT_DIR / ".env")
    os.environ["RAGAS_DO_NOT_TRACK"] = "true"
    client = AsyncOpenAI()
    judge_model = os.getenv("OPENAI_EVAL_MODEL", "gpt-6-luna")
    llm = llm_factory(judge_model, client=client, max_tokens=8192,
                      system_prompt="모든 출력 문장(질문·주장·이유)은 한국어로 작성하세요.")
    embeddings = embedding_factory("openai", model="text-embedding-3-large", client=client)
    metrics = {"answer_correctness": lambda: AnswerCorrectness(llm=llm, embeddings=embeddings),
               "context_recall": lambda: ContextRecall(llm=llm),
               "answer_relevancy": lambda: AnswerRelevancy(llm=llm, embeddings=embeddings)}
    metrics = {name: metrics[name]() for name in names}
    runs = {}
    for path in sorted(OUT_DIR.glob("answer_quality_gen_run*_*.json")):
        for row in json.loads(path.read_text(encoding="utf-8")):
            runs.setdefault(row["run"], {})[row["id"]] = row
    jobs = [(run, repeat) for run in sorted(runs) for repeat in range(repeats if run == 0 else 1)]
    semaphore = asyncio.Semaphore(concurrency)

    async def score(name, row):
        async with semaphore:
            for attempt in range(3):
                try:
                    if name == "answer_correctness":
                        result = await metrics[name].ascore(user_input=row["question"], response=row["answer"], reference=row["reference"])
                    elif name == "context_recall":
                        if not row["contexts"]:
                            return None
                        result = await metrics[name].ascore(user_input=row["question"], retrieved_contexts=row["contexts"],
                                                            reference=row["reference"])
                    else:
                        result = await metrics[name].ascore(user_input=row["question"], response=row["answer"])
                    return None if result.value is None else float(result.value)
                except Exception as exc:  # noqa: BLE001 - a judge failure is a missing score, retried twice
                    error = exc
                    await asyncio.sleep(2 + attempt * 3)
            print("judge failed:", name, row["id"], type(error).__name__, str(error)[:120], flush=True)
            return None

    async def main_async():
        scores = []
        for run, repeat in jobs:
            rows = [row for row in runs[run].values() if row["answer"]]
            tasks = [score(name, row) for row in rows for name in names]
            started = time.perf_counter()
            values = await asyncio.gather(*tasks)
            for i, row in enumerate(rows):
                scores.append({"id": row["id"], "run": run, "repeat": repeat, "abstained": row["abstained"],
                               **{name: values[i * len(names) + j] for j, name in enumerate(names)}})
            print(f"judged run {run} repeat {repeat}: {len(rows)} answers in {time.perf_counter() - started:.0f}s", flush=True)
        return scores

    scores = asyncio.run(main_async())
    (OUT_DIR / "answer_quality_scores.json").write_text(json.dumps(scores, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {"judge_model": judge_model, **summarize(scores, runs, names)}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    (OUT_DIR / "answer_quality_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    if result_name:
        first = [s for s in scores if s["run"] == min(runs) and s["repeat"] == 0]
        run_scores = {name: statistics.fmean(v) for name in names
                      if (v := [s[name] for s in first if s[name] is not None])}
        (OUT_DIR / f"answer_{result_name}.json").write_text(json.dumps({"judge_model": judge_model, "run_scores": run_scores}, indent=1), encoding="utf-8")
    return 0


def summarize(scores: list[dict], runs: dict, names: tuple[str, ...] = METRICS) -> dict:
    def mean(values):
        values = [v for v in values if v is not None]
        return round(statistics.fmean(values), 3) if values else None

    def pick(run, repeat, name, answered=True):
        return {s["id"]: s[name] for s in scores if s["run"] == run and s["repeat"] == repeat
                and (not answered or not s["abstained"]) and s[name] is not None}

    summary: dict = {"answers": {str(run): {"total": len(rows), "abstained": sum(r["abstained"] for r in rows.values()),
                                            "errors": sum(bool(r["error"]) for r in rows.values())}
                                 for run, rows in runs.items()}}
    repeats = sorted({s["repeat"] for s in scores if s["run"] == 0})
    for name in names:
        entry = {"run0_mean_by_repeat": [mean(pick(0, r, name).values()) for r in repeats]}
        # judge noise: the same answers judged again
        per_item = {}
        for r in repeats:
            for item_id, value in pick(0, r, name).items():
                per_item.setdefault(item_id, []).append(value)
        spreads = [max(v) - min(v) for v in per_item.values() if len(v) == len(repeats)]
        entry["judge_item_range_mean"] = mean(spreads)
        entry["judge_items_moving_0.2_or_more"] = f"{sum(s >= 0.2 for s in spreads)}/{len(spreads)}"
        means = [m for m in entry["run0_mean_by_repeat"] if m is not None]
        entry["judge_mean_range"] = round(max(means) - min(means), 3) if means else None
        # system noise: the app run again, first judging
        if 1 in runs:
            a, b = pick(0, 0, name), pick(1, 0, name)
            common = sorted(set(a) & set(b))
            entry["run1_mean"] = mean(b.values())
            entry["system_item_diff_mean"] = mean([abs(a[i] - b[i]) for i in common])
            entry["system_mean_diff"] = round(abs(mean([a[i] for i in common]) - mean([b[i] for i in common])), 3) if common else None
        entry["abstained_mean_run0"] = mean([s[name] for s in scores if s["run"] == 0 and s["repeat"] == 0 and s["abstained"]])
        summary[name] = entry
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--run", type=int, default=0)
    gen.add_argument("--shard", default="0/1", help="i/n: every n-th question starting at i")
    jud = sub.add_parser("judge")
    jud.add_argument("--repeats", type=int, default=3)
    jud.add_argument("--concurrency", type=int, default=16)
    jud.add_argument("--metrics", nargs="+", choices=METRICS, default=list(METRICS))
    jud.add_argument("--result-name", help="also write output/experiments/answer_<name>.json for check_regression.py")
    for sub_parser in (gen, jud):
        sub_parser.add_argument("--yes", action="store_true", help="go on past the cost guard (scripts/cost_guard.py)")
    args = parser.parse_args()
    from cost_guard import confirm

    if args.command == "generate":
        shard, shards = (int(x) for x in args.shard.split("/"))
        # each consultation: router, search check, answer (about 3 calls)
        if not confirm("evaluate_answer_quality generate", -(-100 // shards) * 3, f"shard {args.shard}", args.yes):
            return 1
        return generate(args.run, shard, shards)
    # ragas: about 3 judge calls per answer and metric
    if not confirm("evaluate_answer_quality judge", 100 * args.repeats * len(args.metrics) * 3,
                   f"{args.repeats} judging(s) x {len(args.metrics)} metric(s)", args.yes):
        return 1
    return judge(args.repeats, args.concurrency, tuple(args.metrics), args.result_name)


if __name__ == "__main__":
    raise SystemExit(main())
