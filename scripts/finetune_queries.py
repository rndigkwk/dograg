"""Synthetic guardian queries for fine-tuning the health embedding model (pilot first).

    uv run python scripts/finetune_queries.py pilot --n 100      # cost, copying, difficulty
    uv run python scripts/finetune_queries.py generate           # every corpus question (later)

App users ask short questions ("강아지가 이틀째 설사해요"); the corpus holds long guardian
consultations (median 257 characters). The model has never been trained on that pairing. For
each corpus question the chat model writes two queries a guardian might type (a short one and
one with a detail), and each (query, corpus question) becomes a training pair.

The pilot measures, on a fixed random sample:
- tokens and the estimated cost for all 19,206 questions
- copying: share of a query's Kiwi tokens that also occur in its source (too high = too easy)
- difficulty: the source's rank among all 19,206 for Dense alone and for the app's hybrid
  search. Nearly always first = little to learn; rarely in the top 50 = the queries drift.

Only training documents (data/df.csv) are used; evaluation questions come from data/df_val.csv.
Results: output/experiments/finetune_queries_pilot.json (texts stay local).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

CORPUS = PROJECT_DIR / "data" / "df.csv"
PILOT_OUT = PROJECT_DIR / "output" / "experiments" / "finetune_queries_pilot.json"
QUERIES = PROJECT_DIR / "data" / "finetune" / "queries.jsonl"
USAGE = PROJECT_DIR / "output" / "experiments" / "finetune_queries_usage.json"
SEED = 13
RANK_DEPTH = 50
# Third-party trackers, 2026-10 (OpenAI's page was not reachable): per million tokens.
PRICE_INPUT, PRICE_OUTPUT = 0.10, 0.50

PROMPT = """반려견 건강 챗봇에 보호자가 실제로 입력할 법한 질문을 만듭니다. 아래 상담 글이 좋은 답이 될 질문 두 개를 쓰세요.

- short: 15~40자. 핵심 증상이나 고민 하나를 일상 말투로. 예: "강아지가 밥 먹고 자꾸 토해요"
- detailed: 40~100자. 증상에 나이·기간·상황 중 하나를 더한 질문.

규칙:
- 상담 글의 문장을 그대로 베끼지 마세요. 보호자가 채팅창에 직접 치는 말투로 다시 쓰세요.
- 보호자가 모를 의학 용어·진단명은 쓰지 말고 눈에 보이는 증상으로 말하세요. 상담 글에서 이미 진단받았다고 밝힌 병명은 써도 됩니다.
- 품종·이름·정확한 수치는 빼거나 바꾸세요.

[상담 글]
{consultation}"""


def corpus() -> list[dict]:
    csv.field_size_limit(10**8)
    with open(CORPUS, encoding="utf-8", newline="") as file:
        return [{"id": row[""], "text": row["qa.input"]} for row in csv.DictReader(file)]


def query_chain():
    from langchain_core.prompts import ChatPromptTemplate
    from pydantic import BaseModel, Field

    from src import resources

    class Queries(BaseModel):
        short: str = Field(description="15~40자 짧은 질문")
        detailed: str = Field(description="40~100자 질문")

    model = resources.load_chat_model()
    if model is None:
        raise SystemExit("OPENAI_API_KEY is needed")
    return ChatPromptTemplate.from_template(PROMPT) | model.bind(reasoning_effort="low").with_structured_output(Queries)


def generate(docs: list[dict], concurrency: int = 8) -> tuple[list[dict], dict, float]:
    from langchain_core.callbacks import get_usage_metadata_callback

    chain = query_chain()
    started = time.perf_counter()
    with get_usage_metadata_callback() as usage:
        results = chain.batch([{"consultation": doc["text"]} for doc in docs],
                              config={"max_concurrency": concurrency}, return_exceptions=True)
    seconds = time.perf_counter() - started
    rows = []
    for doc, result in zip(docs, results):
        if isinstance(result, Exception):
            rows.append({"id": doc["id"], "error": type(result).__name__})
        else:
            rows.append({"id": doc["id"], "short": result.short.strip(), "detailed": result.detailed.strip()})
    totals = {"input": 0, "output": 0, "reasoning": 0}
    for record in usage.usage_metadata.values():
        totals["input"] += record.get("input_tokens", 0)
        totals["output"] += record.get("output_tokens", 0)
        totals["reasoning"] += (record.get("output_token_details") or {}).get("reasoning", 0)
    return rows, totals, seconds


def rank_of(source_id: str, documents) -> int | None:
    for rank, doc in enumerate(documents, start=1):
        if str(getattr(doc, "id", "")) == source_id:
            return rank
    return None


def pilot(n: int) -> int:
    from src import resources
    from src.hybrid_retrieval import retrieve_hybrid

    docs = random.Random(SEED).sample(corpus(), n)
    rows, tokens, seconds = generate(docs)
    db, index = resources.load_vector_db(), resources.load_health_bm25_index()
    texts = {doc["id"]: doc["text"] for doc in docs}
    stored = db.get(ids=[docs[0]["id"]], include=["documents"])["documents"][0]
    assert stored == docs[0]["text"], "Chroma ids are not data/df.csv row numbers"
    measured = []
    for row in rows:
        if "error" in row:
            continue
        source_tokens = set(index.tokenize(texts[row["id"]]))
        for kind in ("short", "detailed"):
            query = row[kind]
            tokens_q = index.tokenize(query)
            dense = db.similarity_search(query, k=RANK_DEPTH)
            hybrid = retrieve_hybrid(db, index, query, top_k=RANK_DEPTH, candidate_k=RANK_DEPTH)
            measured.append({
                "id": row["id"], "kind": kind, "chars": len(query),
                "copied": round(sum(t in source_tokens for t in tokens_q) / len(tokens_q), 3) if tokens_q else 0.0,
                "dense_rank": rank_of(row["id"], dense), "hybrid_rank": rank_of(row["id"], hybrid),
            })

    def share(kind, key, limit):
        mine = [m for m in measured if m["kind"] == kind]
        return round(sum(m[key] is not None and m[key] <= limit for m in mine) / len(mine), 3)

    cost = (tokens["input"] * PRICE_INPUT + tokens["output"] * PRICE_OUTPUT) / 1e6
    per_doc = cost / n
    summary = {
        "documents": n, "errors": sum("error" in row for row in rows), "seconds": round(seconds, 1),
        "tokens": tokens, "cost_usd": round(cost, 4), "cost_all_19206_usd": round(per_doc * 19206, 2),
        "minutes_all_19206_at_this_concurrency": round(seconds / n * 19206 / 60, 1),
    }
    for kind in ("short", "detailed"):
        mine = [m for m in measured if m["kind"] == kind]
        summary[kind] = {
            "chars_p50": statistics.median(m["chars"] for m in mine),
            "copied_p50": statistics.median(m["copied"] for m in mine),
            "dense_top1": share(kind, "dense_rank", 1), "dense_top10": share(kind, "dense_rank", 10),
            "dense_top50": share(kind, "dense_rank", 50),
            "hybrid_top1": share(kind, "hybrid_rank", 1), "hybrid_top10": share(kind, "hybrid_rank", 10),
            "hybrid_top50": share(kind, "hybrid_rank", 50),
        }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    PILOT_OUT.parent.mkdir(parents=True, exist_ok=True)
    PILOT_OUT.write_text(json.dumps({"summary": summary, "queries": rows, "measured": measured},
                                    ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def generate_all(chunk: int = 400, concurrency: int = 16) -> int:
    """Every corpus question, appended to data/finetune/queries.jsonl in chunks; a rerun skips
    the ids already written, so an interrupted run continues where it stopped."""
    QUERIES.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if QUERIES.exists():
        done = {json.loads(line)["id"] for line in QUERIES.read_text(encoding="utf-8").splitlines() if line}
    todo = [doc for doc in corpus() if doc["id"] not in done]
    totals = json.loads(USAGE.read_text(encoding="utf-8")) if USAGE.exists() else {"input": 0, "output": 0, "reasoning": 0, "errors": 0}
    print(f"{len(done)} done, {len(todo)} to go", flush=True)
    for start in range(0, len(todo), chunk):
        rows, tokens, seconds = generate(todo[start:start + chunk], concurrency)
        with QUERIES.open("a", encoding="utf-8") as file:
            for row in rows:
                if "error" not in row:
                    file.write(json.dumps(row, ensure_ascii=False) + "\n")
        for key in ("input", "output", "reasoning"):
            totals[key] += tokens[key]
        totals["errors"] += sum("error" in row for row in rows)
        totals["cost_usd"] = round((totals["input"] * PRICE_INPUT + totals["output"] * PRICE_OUTPUT) / 1e6, 3)
        USAGE.write_text(json.dumps(totals, indent=1), encoding="utf-8")
        print(f"{min(start + chunk, len(todo))}/{len(todo)} in {seconds:.0f}s, cost so far ${totals['cost_usd']}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    pilot_parser = sub.add_parser("pilot")
    pilot_parser.add_argument("--n", type=int, default=100)
    sub.add_parser("generate")
    args = parser.parse_args()
    if args.command == "pilot":
        return pilot(args.n)
    return generate_all()


if __name__ == "__main__":
    raise SystemExit(main())
