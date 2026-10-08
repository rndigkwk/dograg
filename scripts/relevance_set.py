"""A health-retrieval evaluation that does not lean on the corpus labels.

hit@3 counts a document as correct when its life stage, department and disease labels match
the question's. Experiment 8 found those labels agree with the questions' own text only
34% / 59% of the time, so the gold is unreliable. This set judges usefulness instead:

    uv run python scripts/relevance_set.py build      # 100 questions: candidate pools + LLM grades
    uv run python scripts/relevance_set.py evaluate   # metrics for the saved rankings

For 100 validation questions (data/df_val.csv, fixed seed) the pool is every candidate the
hybrid search fuses (Dense 12 + BM25 12, up to 24 unique) plus the top 3 of the old filtered
path. An LLM grades each candidate against the question: 2 directly useful (same problem,
the answer helps), 1 partly useful (related situation or advice), 0 not useful.
Saved to tests/data/health_relevance_100.json as row numbers, document ids and grades only;
texts come from data/df_val.csv and data/df.csv.

Metrics for a ranking (top 3, as the app shows):
- useful@3: share of questions with a grade-2 document in the top 3
- relevant@3: share with a grade >= 1 document in the top 3
- precision@3: mean share of grade >= 1 documents in the top 3
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

SET_PATH = PROJECT_DIR / "tests" / "data" / "health_relevance_100.json"
SAMPLE_SIZE = 100
SEED = 20261008
POOL_K = 24
ANSWER_CHARS = 300
JUDGE_EFFORT = "low"
FIELDS = ("meta.lifeCycle", "meta.department", "meta.disease")


class Grade(BaseModel):
    index: int = Field(description="후보 번호")
    grade: Literal[0, 1, 2] = Field(description="2: 바로 쓸모 있음, 1: 일부 쓸모 있음, 0: 쓸모 없음")


class Grades(BaseModel):
    grades: list[Grade]


JUDGE_PROMPT = """반려견 보호자의 질문과, 검색된 상담 사례 후보들이 있습니다.
각 후보가 이 질문에 답하는 데 얼마나 쓸모 있는지 0~2로 매기세요.
- 2: 같은 문제(같은 증상·상황)를 다루고, 그 답변이 이 질문에 바로 도움이 된다.
- 1: 관련 있는 상황이나 일부 도움이 되는 조언이 있다(증상은 같지만 원인·상황이 다르거나, 일반적인 관리 요령만 겹침).
- 0: 다른 문제를 다루거나 도움이 되지 않는다.
나이·견종이 달라도 같은 문제를 다루면 2가 될 수 있습니다. 라벨(연령 단계, 진료과)은 보지 말고 내용으로만 판단하세요.
모든 후보에 점수를 매기세요."""


def judge_model():
    from langchain_openai import ChatOpenAI

    from src import resources, settings

    return ChatOpenAI(model=resources.CHAT_MODEL_NAME, api_key=settings.get_openai_api_key(),
                      reasoning_effort=JUDGE_EFFORT).with_structured_output(Grades)


def candidate_text(doc) -> str:
    answer = " ".join(str(doc.metadata.get("qa.output", "")).split())[:ANSWER_CHARS]
    question = " ".join(doc.page_content.split())
    return f"질문: {question}\n답변: {answer}"


def judge(model, question: str, docs: list) -> dict[str, int]:
    listing = "\n\n".join(f"[후보 {i}]\n{candidate_text(doc)}" for i, doc in enumerate(docs))
    result = model.invoke([("system", JUDGE_PROMPT), ("user", f"[보호자 질문]\n{question}\n\n{listing}")])
    grades = {item.index: item.grade for item in result.grades}
    return {str(doc.id): grades[i] for i, doc in enumerate(docs) if i in grades}


def sample_rows(rows) -> list[int]:
    return sorted(random.Random(SEED).sample(range(len(rows)), SAMPLE_SIZE))


def open_search(directory: str):
    from src import resources

    resources.CHROMA_DIR = Path(directory) / "chroma_db"  # Chroma writes to its folder even when reading
    shutil.copytree(PROJECT_DIR / "data" / "chroma_db", resources.CHROMA_DIR)
    return resources.load_vector_db(), resources.load_health_bm25_index(), resources.load_health_answer_table()


def build(workers: int) -> None:
    import pandas as pd

    from src.health_answers import attach_health_answers
    from src.hybrid_retrieval import retrieve_hybrid
    from src.tools import health

    rows = pd.read_csv(PROJECT_DIR / "data" / "df_val.csv").fillna("")
    picked = sample_rows(rows)
    pools = []
    with tempfile.TemporaryDirectory(prefix="ragdog-relevance-", ignore_cleanup_errors=True) as directory:
        db, index, answers = open_search(directory)
        for row_id in picked:
            question = str(rows.loc[row_id, "qa.input"])
            fused = retrieve_hybrid(db, index, question, top_k=POOL_K)
            where = health.build_metadata_filter(health.infer_rag_filters(question))
            filtered = retrieve_hybrid(db, index, question, top_k=3, where=where)
            docs = list({str(doc.id): doc for doc in fused + filtered}.values())
            attach_health_answers(docs, answers)
            pools.append((row_id, question, docs, [str(d.id) for d in fused], [str(d.id) for d in filtered]))
    model = judge_model()
    with ThreadPoolExecutor(workers) as pool:
        graded = list(pool.map(lambda item: judge(model, item[1], item[2]), pools))
    items = []
    for (row_id, _, docs, fused, filtered), grades in zip(pools, graded):
        items.append({
            "row": row_id,
            "gold_labels": {field: str(rows.loc[row_id, field]) for field in FIELDS},
            "grades": grades,
            "doc_labels": {str(d.id): {field: str(d.metadata.get(field)) for field in FIELDS} for d in docs},
            "rankings": {"hybrid": fused, "hybrid_old_filters": filtered},
        })
    SET_PATH.write_text(json.dumps({
        "description": "Health retrieval relevance set: LLM-graded candidate pools for 100 validation questions "
                       "(scripts/relevance_set.py). Grades: 2 directly useful, 1 partly, 0 not useful.",
        "seed": SEED, "judge": {"prompt_version": 1, "reasoning_effort": JUDGE_EFFORT},
        "items": items,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"saved {len(items)} questions, {sum(len(i['grades']) for i in items)} graded candidates -> {SET_PATH}")


def metrics(items: list[dict], ranking_of) -> dict:
    """ranking_of(item) -> document ids in rank order; only the top 3 count."""
    useful = relevant = precision = label_hit = judged = shown = 0
    for item in items:
        top = ranking_of(item)[:3]
        grades = [item["grades"].get(doc_id) for doc_id in top]
        known = [grade for grade in grades if grade is not None]
        judged += len(known)
        shown += len(top)
        useful += any(grade == 2 for grade in known)
        relevant += any(grade >= 1 for grade in known)
        precision += sum(grade >= 1 for grade in known) / 3
        label_hit += any(item["doc_labels"].get(doc_id) == item["gold_labels"] for doc_id in top)
    n = len(items)
    return {"useful@3": round(useful / n, 3), "relevant@3": round(relevant / n, 3),
            "precision@3": round(precision / n, 3), "label_hit@3": round(label_hit / n, 3),
            "judged_share": round(judged / shown, 3) if shown else 0.0}


def load_items() -> list[dict]:
    return json.loads(SET_PATH.read_text(encoding="utf-8"))["items"]


def evaluate() -> None:
    items = load_items()
    for name in ("hybrid", "hybrid_old_filters"):
        print(name, metrics(items, lambda item, name=name: item["rankings"][name]))
    # Upper bound: the best 3 of the judged pool, i.e. what a perfect reranker could reach.
    print("pool_best", metrics(items, lambda item: sorted(item["grades"], key=lambda d: -item["grades"][d])))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("build", "evaluate"))
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    build(args.workers) if args.command == "build" else evaluate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
