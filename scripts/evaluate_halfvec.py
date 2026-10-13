"""Can the Supabase vectors be stored as float16 (pgvector halfvec) without losing search quality?

    uv run --group tools python scripts/evaluate_halfvec.py

The Supabase database is near the free plan's 500 MB, and halfvec halves the vectors and their HNSW
index. This measures the accuracy side without touching the database: the exported vectors
(data/vector_store/, scripts/export_vector_store.py) are searched exactly in numpy as float32 and
rounded to float16 (questions rounded too, as `%s::halfvec` does), which orders documents the same
way as an exact halfvec search. Questions are embedded as the app does (ONNX int8 for health, OpenAI
for reports).
- Health: the 220 judged questions (short 120, long 100); top-12 agreement with float32, and useful@3
  for Dense and the app's hybrid (Kiwi BM25, 12 candidates each, RRF, top 3). New top-3 documents are
  graded by the same judge; paired McNemar.
- Reports: the 18 report questions with gold pages; the gold page in the hybrid top 6.
Results: output/experiments/halfvec.json.
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

GRADES = PROJECT_DIR / "output" / "experiments" / "finetuned_embedding_grades.json"
STORE = PROJECT_DIR / "data" / "vector_store"
OUT = PROJECT_DIR / "output" / "experiments" / "halfvec.json"
CANDIDATES, REPORT_CANDIDATES, REPORT_TOP = 12, 20, 6
FORMATS = ("float32", "float16")


def mcnemar(a: list[bool], b: list[bool]) -> float:
    from math import comb

    only_a = sum(x and not y for x, y in zip(a, b))
    only_b = sum(y and not x for x, y in zip(a, b))
    n = only_a + only_b
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, k) for k in range(min(only_a, only_b) + 1)) / 2**n)


def load_store(name: str) -> tuple[list[str], np.ndarray]:
    ids = [json.loads(line)["id"] for line in (STORE / name / "documents.jsonl").open(encoding="utf-8")]
    vectors = np.load(STORE / name / "vectors.npy").astype(np.float32)
    return ids, vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def as_format(vectors: np.ndarray, fmt: str) -> np.ndarray:
    return vectors.astype(np.float16).astype(np.float32) if fmt == "float16" else vectors


def main() -> int:
    from relevance_set import judge, judge_model
    from src import resources
    from src.health_answers import attach_health_answers
    from src.hybrid_retrieval import reciprocal_rank_fusion

    with open(PROJECT_DIR / "data" / "df_val.csv", encoding="utf-8", newline="") as f:
        val = list(csv.DictReader(f))
    relevance = json.loads((PROJECT_DIR / "tests" / "data" / "health_relevance_100.json").read_text(encoding="utf-8"))["items"]
    short = json.loads((PROJECT_DIR / "tests" / "data" / "emergency_signs.json").read_text(encoding="utf-8"))["items"]
    sets = {"short": ([i["question"] for i in short], [{} for _ in short]),
            "long_useful": ([val[int(i["row"])]["qa.input"] for i in relevance], [i["grades"] for i in relevance])}
    report_items = [i for i in json.loads((PROJECT_DIR / "tests" / "data" / "crag_eval_questions.json").read_text(encoding="utf-8"))["items"]
                    if i["group"] == "report_answerable" and i.get("gold_pages")]
    extra = json.loads(GRADES.read_text(encoding="utf-8")) if GRADES.exists() else {}
    health_ids, health_vectors = load_store("health")
    report_ids, report_vectors = load_store("report")
    report: dict = {"bytes_per_vector": {"health float32": 4 * 768 + 8, "health float16": 2 * 768 + 8,
                                         "report float32": 4 * 1536 + 8, "report float16": 2 * 1536 + 8}}

    with tempfile.TemporaryDirectory(prefix="ragdog-halfvec-", ignore_cleanup_errors=True) as directory:
        resources.CHROMA_DIR = Path(directory) / "chroma_db"
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", resources.CHROMA_DIR)
        db, bm25 = resources.load_vector_db(), resources.load_health_bm25_index()
        report_db, report_bm25 = resources.load_report_vector_db(), resources.load_report_bm25_index()
        by_id = {d.id: d for d in bm25.documents}
        report_by_id = {d.id: d for d in report_bm25.documents}

        tops: dict = {}
        overlap12, same3 = [], []
        for set_name, (questions, _) in sets.items():
            tops[set_name] = []
            queries = np.array(db.embeddings.embed_documents(questions), dtype=np.float32)
            for question, query in zip(questions, queries):
                lexical = bm25.search(question, CANDIDATES)
                row, ranked = {}, {}
                for fmt in FORMATS:
                    order = np.argsort(-(as_format(health_vectors, fmt) @ as_format(query[None], fmt)[0]), kind="stable")[:CANDIDATES]
                    ranked[fmt] = [health_ids[i] for i in order]
                    dense = [by_id[i] for i in ranked[fmt]]
                    row[f"{fmt} dense"] = dense[:3]
                    row[f"{fmt} hybrid"] = reciprocal_rank_fusion([dense, lexical], top_k=3)
                overlap12.append(len(set(ranked["float32"]) & set(ranked["float16"])) / CANDIDATES)
                same3.append(ranked["float32"][:3] == ranked["float16"][:3])
                tops[set_name].append(row)
        report["health_top12_overlap"] = round(float(np.mean(overlap12)), 4)
        report["health_same_top3_order"] = f"{sum(same3)}/{len(same3)}"

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
                    hits.setdefault(name, []).append(any(grades.get(d.id) == 2 for d in docs))
        report["health_useful@3"] = {name: round(sum(v) / len(v), 3) for name, v in hits.items()}
        report["health_float16_vs_float32_p"] = {s: round(mcnemar(hits[f"float32 {s}"], hits[f"float16 {s}"]), 3)
                                                 for s in ("dense", "hybrid")}

        def gold_hit(item, docs):
            gold = {(name, page) for name, page in item["gold_pages"]}
            return bool(gold & {(Path(d.metadata.get("source", "")).name, d.metadata.get("page")) for d in docs})

        report_hits: dict = {fmt: [] for fmt in FORMATS}
        report_overlap = []
        queries = np.array(report_db.embeddings.embed_documents([item["question"] for item in report_items]), dtype=np.float32)
        queries /= np.linalg.norm(queries, axis=1, keepdims=True)
        for item, query in zip(report_items, queries):
            lexical = report_bm25.search(item["question"], REPORT_CANDIDATES)
            ranked = {}
            for fmt in FORMATS:
                order = np.argsort(-(as_format(report_vectors, fmt) @ as_format(query[None], fmt)[0]), kind="stable")[:REPORT_CANDIDATES]
                ranked[fmt] = [report_ids[i] for i in order]
                dense = [report_by_id[i] for i in ranked[fmt]]
                report_hits[fmt].append(gold_hit(item, reciprocal_rank_fusion([dense, lexical], top_k=REPORT_TOP)))
            report_overlap.append(len(set(ranked["float32"]) & set(ranked["float16"])) / REPORT_CANDIDATES)
        report["report_top20_overlap"] = round(float(np.mean(report_overlap)), 4)
        report["report_gold_page_top6_hybrid"] = {fmt: f"{sum(v)}/{len(v)}" for fmt, v in report_hits.items()}

    print(json.dumps(report, ensure_ascii=False, indent=1))
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
