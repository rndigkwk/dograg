"""A lighter local search for when Supabase fails: which keyword search does it still need?

    uv run --group tools python scripts/evaluate_light_fallback.py

The fallback today loads Chroma and Kiwi (about 1.2 GB at peak). Kiwi alone is about 290 MB and is
only there for the keyword half of the hybrid search. Measured on the exact in-memory store
(data/vector_store, scripts/export_vector_store.py), questions embedded as the app does:
- Health, the 220 judged questions (short 120, long 100), useful@3:
  dense only / hybrid with Kiwi BM25 (the app's local search) / hybrid with a character-bigram BM25
- Reports, the 18 questions with gold pages, gold page in the top 6:
  dense only / hybrid with Kiwi BM25 / hybrid with the bigram BM25
New top-3 health documents are graded by the same judge (scripts/relevance_set.py); paired McNemar
against the Kiwi hybrid. Results: output/experiments/light_fallback.json.
"""

from __future__ import annotations

import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

GRADES = PROJECT_DIR / "output" / "experiments" / "finetuned_embedding_grades.json"
STORE = PROJECT_DIR / "data" / "vector_store"
OUT = PROJECT_DIR / "output" / "experiments" / "light_fallback.json"
CANDIDATES, REPORT_CANDIDATES, REPORT_TOP = 12, 20, 6


def mcnemar(a: list[bool], b: list[bool]) -> float:
    from math import comb

    only_a = sum(x and not y for x, y in zip(a, b))
    only_b = sum(y and not x for x, y in zip(a, b))
    n = only_a + only_b
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, k) for k in range(min(only_a, only_b) + 1)) / 2**n)


def main() -> int:
    from relevance_set import judge, judge_model
    from src import resources
    from src.health_answers import attach_health_answers
    from src.hybrid_retrieval import HealthBM25Index, bigram_tokenize, reciprocal_rank_fusion
    from src.vector_store import ExactVectorStore

    with open(PROJECT_DIR / "data" / "df_val.csv", encoding="utf-8", newline="") as f:
        val = list(csv.DictReader(f))
    relevance = json.loads((PROJECT_DIR / "tests" / "data" / "health_relevance_100.json").read_text(encoding="utf-8"))["items"]
    short = json.loads((PROJECT_DIR / "tests" / "data" / "emergency_signs.json").read_text(encoding="utf-8"))["items"]
    sets = {"short": ([i["question"] for i in short], [{} for _ in short]),
            "long_useful": ([val[int(i["row"])]["qa.input"] for i in relevance], [i["grades"] for i in relevance])}
    report_items = [i for i in json.loads((PROJECT_DIR / "tests" / "data" / "crag_eval_questions.json").read_text(encoding="utf-8"))["items"]
                    if i["group"] == "report_answerable" and i.get("gold_pages")]
    extra = json.loads(GRADES.read_text(encoding="utf-8")) if GRADES.exists() else {}

    health = ExactVectorStore.load(STORE / "health", resources.load_health_embeddings())
    kiwi = resources.make_health_tokenizer()
    keyword = {
        "kiwi": HealthBM25Index.from_chroma(health, kiwi, token_cache=resources.BM25_TOKEN_CACHE,
                                            tokenizer_version=resources.HEALTH_TOKENIZER_VERSION),
        "bigram": HealthBM25Index.from_chroma(health, bigram_tokenize),
    }
    tops: dict = {}
    for set_name, (questions, _) in sets.items():
        tops[set_name] = []
        for question in questions:
            dense = health.similarity_search(question, k=CANDIDATES)
            row = {"dense": dense[:3]}
            for name, index in keyword.items():
                row[f"hybrid {name}"] = reciprocal_rank_fusion([dense, index.search(question, CANDIDATES)], top_k=3)
            tops[set_name].append(row)

    judge_llm, answers = judge_model(), resources.load_health_answer_table()
    hits: dict = {}
    for set_name, (questions, saved) in sets.items():
        jobs = []
        for i, question in enumerate(questions):
            known = {**saved[i], **extra.get(f"{set_name}:{i}", {})}
            missing = {d.id: d for docs in tops[set_name][i].values() for d in docs if d.id not in known}
            if missing:
                jobs.append((i, question, attach_health_answers(list(missing.values()), answers)))
        print(f"{set_name}: grading {sum(len(j[2]) for j in jobs)} new documents", flush=True)
        with ThreadPoolExecutor(8) as pool:
            for (i, _, _), grades in zip(jobs, pool.map(lambda job: judge(judge_llm, job[1], job[2]), jobs)):
                extra.setdefault(f"{set_name}:{i}", {}).update(grades)
        GRADES.write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
        for i in range(len(questions)):
            grades = {**saved[i], **extra.get(f"{set_name}:{i}", {})}
            for name, docs in tops[set_name][i].items():
                hits.setdefault(name, {}).setdefault(set_name, []).append(any(grades.get(d.id) == 2 for d in docs))
    result: dict = {"health_useful@3": {}, "health_vs_kiwi_hybrid_p": {}}
    base = hits["hybrid kiwi"]["short"] + hits["hybrid kiwi"]["long_useful"]
    for name, per_set in hits.items():
        both = per_set["short"] + per_set["long_useful"]
        result["health_useful@3"][name] = {**{s: round(sum(v) / len(v), 3) for s, v in per_set.items()},
                                           "all": round(sum(both) / len(both), 3)}
        result["health_vs_kiwi_hybrid_p"][name] = round(mcnemar(base, both), 3)

    report = ExactVectorStore.load(STORE / "report", resources.create_embedding_model())
    report_keyword = {"kiwi": HealthBM25Index.from_chroma(report, kiwi), "bigram": HealthBM25Index.from_chroma(report, bigram_tokenize)}

    def gold_hit(item, docs):
        gold = {(name, page) for name, page in item["gold_pages"]}
        return bool(gold & {(Path(d.metadata.get("source", "")).name, d.metadata.get("page")) for d in docs})

    report_hits: dict = {}
    for item in report_items:
        dense = report.similarity_search(item["question"], k=REPORT_CANDIDATES)
        report_hits.setdefault("dense", []).append(gold_hit(item, dense[:REPORT_TOP]))
        for name, index in report_keyword.items():
            fused = reciprocal_rank_fusion([dense, index.search(item["question"], REPORT_CANDIDATES)], top_k=REPORT_TOP)
            report_hits.setdefault(f"hybrid {name}", []).append(gold_hit(item, fused))
    result["report_gold_page_top6"] = {name: f"{sum(v)}/{len(v)}" for name, v in report_hits.items()}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
