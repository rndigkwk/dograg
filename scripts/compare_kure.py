"""KURE-v1 for the health search: is it better than the app's fine-tuned ko-sroberta?

    uv run --group tools --with psutil python scripts/compare_kure.py

nlpai-lab/KURE-v1 (BGE-M3 further trained for Korean retrieval, 1024 dimensions, 8,192 tokens) leads
the Korean MTEB health task PublicHealthQA among the models of the Day 58 lesson (81.92 vs 73.70 for
multilingual-e5-small). Supabase moved the search out of the app, so the memory a larger question
model needs may now be there (about 1 GB on Streamlit Cloud in practice).
- KURE-v1: document vectors from notebooks/kure_v1_embed_colab.ipynb (1,024 tokens, 0.11% of posts
  cut), downloaded to output/experiments/kure_v1_rows.npy (df.csv row order); questions embedded here
  in float (sentence-transformers, no prefix).
- The app: the fine-tuned ko-sroberta's document vectors (data/vector_store/health) and its int8 ONNX
  question embedding, as deployed.
Both are searched exactly (numpy), as Dense only and as the hybrid with the same Kiwi BM25 (12
candidates each, RRF, top 3), on the 220 judged questions (short 120, long 100). useful@3, paired
McNemar against the app; new top-3 documents are graded by the same judge. Also the question
embedding time on this CPU and the process memory after loading KURE-v1 in float.
Results: output/experiments/kure_v1.json.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

GRADES = PROJECT_DIR / "output" / "experiments" / "finetuned_embedding_grades.json"
KURE_ROWS = PROJECT_DIR / "output" / "experiments" / "kure_v1_rows.npy"
OUT = PROJECT_DIR / "output" / "experiments" / "kure_v1.json"
CANDIDATES = 12


def mcnemar(a: list[bool], b: list[bool]) -> float:
    from math import comb

    only_a = sum(x and not y for x, y in zip(a, b))
    only_b = sum(y and not x for x, y in zip(a, b))
    n = only_a + only_b
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, k) for k in range(min(only_a, only_b) + 1)) / 2**n)


def rss_mb() -> int:
    import psutil

    return round(psutil.Process().memory_info().rss / 2**20)


def main() -> int:
    import torch
    from sentence_transformers import SentenceTransformer

    from relevance_set import judge, judge_model
    from src import resources
    from src.health_answers import attach_health_answers
    from src.hybrid_retrieval import HealthBM25Index, reciprocal_rank_fusion
    from src.vector_store import ExactVectorStore

    torch.set_num_threads(4)
    with open(PROJECT_DIR / "data" / "df_val.csv", encoding="utf-8", newline="") as f:
        val = list(csv.DictReader(f))
    relevance = json.loads((PROJECT_DIR / "tests" / "data" / "health_relevance_100.json").read_text(encoding="utf-8"))["items"]
    short = json.loads((PROJECT_DIR / "tests" / "data" / "emergency_signs.json").read_text(encoding="utf-8"))["items"]
    sets = {"short": ([i["question"] for i in short], [{} for _ in short]),
            "long_useful": ([val[int(i["row"])]["qa.input"] for i in relevance], [i["grades"] for i in relevance])}
    extra = json.loads(GRADES.read_text(encoding="utf-8")) if GRADES.exists() else {}
    report: dict = {}

    app = ExactVectorStore.load(PROJECT_DIR / "data" / "vector_store" / "health", resources.load_health_embeddings())
    kure_vectors = np.load(KURE_ROWS)[[int(doc_id) for doc_id in app.ids]]  # app order
    bm25 = HealthBM25Index.from_chroma(app, resources.make_health_tokenizer(), token_cache=resources.BM25_TOKEN_CACHE,
                                       tokenizer_version=resources.HEALTH_TOKENIZER_VERSION)
    documents = {d.id: d for d in bm25.documents}

    before = rss_mb()
    kure = SentenceTransformer("nlpai-lab/KURE-v1", device="cpu", token=os.environ.get("HF_TOKEN"))
    kure.max_seq_length = 1024
    report["kure_float_model_mb"] = rss_mb() - before

    timings: dict = {"app": [], "kure": []}
    tops: dict = {}
    for set_name, (questions, _) in sets.items():
        tops[set_name] = []
        for question in questions:
            lexical = bm25.search(question, CANDIDATES)
            row = {}
            for name in ("app", "kure"):
                started = time.perf_counter()
                if name == "app":
                    query = np.asarray(app.embeddings.embed_query(question), dtype=np.float32)
                    matrix = app.vectors
                else:
                    query = kure.encode(question, normalize_embeddings=True, convert_to_numpy=True)
                    matrix = kure_vectors
                timings[name].append(time.perf_counter() - started)
                order = np.argsort(-(matrix @ query))[:CANDIDATES]
                dense = [documents[app.ids[i]] for i in order]
                row[f"{name} dense"] = dense[:3]
                row[f"{name} hybrid"] = reciprocal_rank_fusion([dense, lexical], top_k=3)
            tops[set_name].append(row)
    report["query_ms_p50"] = {name: round(float(np.median(v)) * 1000, 1) for name, v in timings.items()}

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

    report["useful@3"] = {}
    for name, per_set in hits.items():
        both = per_set["short"] + per_set["long_useful"]
        entry = {**{s: round(sum(v) / len(v), 3) for s, v in per_set.items()}, "all": round(sum(both) / len(both), 3)}
        if name.startswith("kure"):
            base = hits[name.replace("kure", "app")]
            entry["vs_app_p"] = {s: round(mcnemar(base[s], per_set[s]), 3) for s in per_set}
            entry["vs_app_p"]["all"] = round(mcnemar(base["short"] + base["long_useful"], both), 3)
        report["useful@3"][name] = entry
    print(json.dumps(report, ensure_ascii=False, indent=1))
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
