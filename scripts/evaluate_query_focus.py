"""Does condensing a long health question before search raise hit@3? And do the inferred filters help?

Runs the app's retrieval (infer_rag_filters + retrieve_health, hybrid) on the 561 AI Hub
validation questions (data/df_val.csv), on an isolated Chroma copy, in these variants:

- original: the question as typed, life-stage and department filters inferred from it
  (what the app did before experiment 8)
- focused: an LLM rewrite to 1-2 sentences of age/breed + symptoms + what is asked;
  filters inferred from the rewrite (life stage still from the original's age)
- *_no_department, *_no_filters: the same queries with fewer or no filters

Gold rule as in the other retrieval experiments: a top-3 document whose lifeCycle,
department and disease all match the question's metadata (not clinical accuracy).
Rewrites are cached in output/query_focus_cache.json, so reruns cost nothing.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

FIELDS = ("meta.lifeCycle", "meta.department", "meta.disease")
CACHE = PROJECT_DIR / "output" / "query_focus_cache.json"
RUNS = ("original", "focused", "focused_original_filters", "original_no_department", "focused_no_department",
        "original_no_filters", "focused_no_filters")


# The condensing step under test. Not adopted (no gain once the filters were dropped), so it
# lives here rather than in src/.
FOCUS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", (
        "반려견 보호자의 질문을 검색용 문장으로 줄이세요.\n"
        "- 반려견의 나이·견종·성별(질문에 있을 때만), 증상과 상황(언제부터, 어디가, 얼마나), 묻는 것만 남깁니다.\n"
        "- 인사, 감사, 걱정 표현, 부탁, 같은 말의 반복은 지웁니다.\n"
        "- 질문에 없는 질병명, 원인, 검사는 넣지 않습니다. 보호자가 쓴 표현을 되도록 그대로 씁니다.\n"
        "- 1~2문장, 120자 이내로 답만 쓰세요."
    )),
    ("human", "{question}"),
])
SHORT_ENOUGH = 80  # characters: short questions are searched as typed


def focus_question(question: str) -> str:
    """The condensed question, or the question itself when it is short or no model is set."""
    if len(question) <= SHORT_ENOUGH:
        return question
    from src import resources

    model = resources.load_review_model()
    if model is None:
        return question
    focused = (FOCUS_PROMPT | model).invoke({"question": question}).content
    if isinstance(focused, list):  # content blocks
        focused = "".join(part.get("text", "") for part in focused if isinstance(part, dict))
    return focused.strip() or question


def rank_of_match(row, docs) -> int | None:
    for rank, doc in enumerate(docs, 1):
        if all(str(doc.metadata.get(field)) == str(row[field]) for field in FIELDS):
            return rank
    return None


def focus_all(questions: list[str], workers: int) -> dict[str, str]:
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    todo = [q for q in dict.fromkeys(questions) if q not in cache]
    with ThreadPoolExecutor(workers) as pool:
        for done, (question, focused) in enumerate(zip(todo, pool.map(focus_question, todo)), 1):
            cache[question] = focused
            if done % 50 == 0:
                print(f"focused={done}/{len(todo)}", flush=True)
                CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return cache


def mcnemar_p(only_a: int, only_b: int) -> float:
    """Exact two-sided McNemar test on the discordant pairs."""
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import pandas as pd

    from src import resources
    from src.tools import health

    # The app no longer filters the search; turn filters on here so every variant below gets
    # exactly the filters it is given.
    health.SEARCH_FILTER_KEYS = ("life_cycle", "department")
    rows = pd.read_csv(PROJECT_DIR / "data" / "df_val.csv").fillna("")
    if args.limit:
        rows = rows.head(args.limit)
    questions = [str(q) for q in rows["qa.input"]]
    focused = focus_all(questions, args.workers)

    records = []
    with tempfile.TemporaryDirectory(prefix="ragdog-focus-", ignore_cleanup_errors=True) as directory:
        resources.CHROMA_DIR = Path(directory) / "chroma_db"
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", resources.CHROMA_DIR)
        for index, (row, question) in enumerate(zip(rows.to_dict("records"), questions), 1):
            short = focused[question]
            original_filters = health.infer_rag_filters(question)
            focused_filters = health.infer_rag_filters(short)
            if "life_cycle" in original_filters:
                focused_filters["life_cycle"] = original_filters["life_cycle"]
            else:
                focused_filters.pop("life_cycle", None)
            life_only = {key: value for key, value in original_filters.items() if key == "life_cycle"}
            runs = {
                "original": health.retrieve_health(question, k=3, filters=original_filters),
                "focused": health.retrieve_health(short, k=3, filters=focused_filters),
                "focused_original_filters": health.retrieve_health(short, k=3, filters=original_filters),
                "original_no_department": health.retrieve_health(question, k=3, filters=life_only),
                "focused_no_department": health.retrieve_health(short, k=3, filters=life_only),
                "original_no_filters": health.retrieve_health(question, k=3, filters={}),
                "focused_no_filters": health.retrieve_health(short, k=3, filters={}),
            }
            records.append({
                "group": "기타" if str(row["meta.disease"]).strip() == "기타" else "non_other",
                "department_gold": row["meta.department"],
                "department_original": original_filters.get("department"),
                "department_focused": focused_filters.get("department"),
                **{name: rank_of_match(row, docs) for name, docs in runs.items()},
            })
            if index % 100 == 0:
                print(f"evaluated={index}/{len(rows)}", flush=True)

    def hit(name, subset=records):
        return sum(r[name] is not None for r in subset) / len(subset)

    def mrr(name):
        return sum(1 / r[name] for r in records if r[name]) / len(records)

    summary = {"questions": len(records)}
    for name in RUNS:
        summary[name] = {
            "hit@3": round(hit(name), 4), "mrr@3": round(mrr(name), 4),
            "hit@3_non_other": round(hit(name, [r for r in records if r["group"] == "non_other"]), 4),
        }
        if name != "original":
            only_new = sum(r[name] is not None and r["original"] is None for r in records)
            only_old = sum(r[name] is None and r["original"] is not None for r in records)
            summary[name].update(gained=only_new, lost=only_old, mcnemar_p=round(mcnemar_p(only_new, only_old), 4))
    for source in ("original", "focused"):
        chosen = [r for r in records if r[f"department_{source}"]]
        summary[f"department_filter_{source}"] = {
            "applied": len(chosen),
            "matches_gold": sum(r[f"department_{source}"] == r["department_gold"] for r in chosen),
        }
    out = PROJECT_DIR / "output" / "query_focus_eval.json"
    out.write_text(json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
