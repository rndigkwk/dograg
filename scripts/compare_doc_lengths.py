"""Health documents cut at 128 tokens: longer limits and chunking with the fine-tuned model.

    uv run --group tools python scripts/compare_doc_lengths.py

The app's fine-tuned ko-sroberta (blanden77/ko-sroberta-dograg-b) embeds each consultation post as
one vector cut at 128 tokens, which cuts 52% of the 19,206 posts. Document vectors come from
notebooks/doc_length_embed_colab.ipynb (private dataset, experiments branch, doclen/*.npy, in
df.csv row order = document ID); download them to output/experiments/doclen/ first. Variants:
- len128: as now (the baseline)
- len256 / len512: longer document limit; questions at 128 as in the app, and at the same limit (q)
- chunk128: 126-token windows sliding by 63; a post scores its best window (max over windows)
Questions are embedded locally with the same model in float (sentence-transformers). Measured as
Dense only and as the app's hybrid (the same Kiwi BM25, 12 candidates each, RRF, top 3) on the
judged sets: short 120 (tests/data/emergency_signs.json) and long 100
(tests/data/health_relevance_100.json). useful@3, paired McNemar against len128. Top-3 documents
never graded are graded by the same judge (scripts/relevance_set.py) and added to
output/experiments/finetuned_embedding_grades.json. Results: output/experiments/doc_lengths.json.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

GRADES = PROJECT_DIR / "output" / "experiments" / "finetuned_embedding_grades.json"
VECTORS = PROJECT_DIR / "output" / "experiments" / "doclen"
OUT = PROJECT_DIR / "output" / "experiments" / "doc_lengths.json"
MODEL = "blanden77/ko-sroberta-dograg-b"
CANDIDATES = 12
# variant -> (document vectors, question token limit)
VARIANTS = {
    "len128": ("len128", 128),
    "len256": ("len256", 128),
    "len256q": ("len256", 256),
    "len512": ("len512", 128),
    "len512q": ("len512", 512),
    "chunk128": ("chunk128", 128),
}


def mcnemar(a: list[bool], b: list[bool]) -> float:
    from math import comb

    only_a = sum(x and not y for x, y in zip(a, b))
    only_b = sum(y and not x for x, y in zip(a, b))
    n = only_a + only_b
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, k) for k in range(min(only_a, only_b) + 1)) / 2**n)


def top_rows(vectors: np.ndarray, owner: np.ndarray | None, query: np.ndarray, k: int) -> list[int]:
    scores = vectors @ query
    if owner is None:
        return [int(i) for i in np.argsort(-scores)[:k]]
    best = np.full(int(owner.max()) + 1, -np.inf, dtype=np.float32)
    np.maximum.at(best, owner, scores)
    return [int(i) for i in np.argsort(-best)[:k]]


def main() -> int:
    import torch
    from dotenv import load_dotenv
    from sentence_transformers import SentenceTransformer

    from relevance_set import judge, judge_model
    from src import resources
    from src.health_answers import attach_health_answers
    from src.hybrid_retrieval import reciprocal_rank_fusion

    load_dotenv(PROJECT_DIR / ".env")
    torch.set_num_threads(4)
    docs = {name: np.load(VECTORS / f"{name}.npy") for name in ("len128", "len256", "len512", "chunk128")}
    owner = np.load(VECTORS / "chunk128_owner.npy")
    with open(PROJECT_DIR / "data" / "df_val.csv", encoding="utf-8", newline="") as f:
        val = list(csv.DictReader(f))
    relevance = json.loads((PROJECT_DIR / "tests" / "data" / "health_relevance_100.json").read_text(encoding="utf-8"))["items"]
    short = json.loads((PROJECT_DIR / "tests" / "data" / "emergency_signs.json").read_text(encoding="utf-8"))["items"]
    sets = {
        "short": ([item["question"] for item in short], [{} for _ in short]),
        "long_useful": ([val[int(item["row"])]["qa.input"] for item in relevance], [item["grades"] for item in relevance]),
    }
    extra = json.loads(GRADES.read_text(encoding="utf-8")) if GRADES.exists() else {}
    report: dict = {"documents": {name: list(v.shape) for name, v in docs.items()},
                    "chunks_per_post": round(len(owner) / docs["len128"].shape[0], 2)}

    model = SentenceTransformer(MODEL, device="cpu", token=os.environ.get("HF_TOKEN"))
    queries: dict[int, dict[str, np.ndarray]] = {}
    for limit in sorted({limit for _, limit in VARIANTS.values()}):
        model.max_seq_length = limit
        started = time.perf_counter()
        queries[limit] = {name: model.encode(questions, normalize_embeddings=True, convert_to_numpy=True)
                          for name, (questions, _) in sets.items()}
        report.setdefault("query_seconds", {})[limit] = round(time.perf_counter() - started, 1)
    del model

    with tempfile.TemporaryDirectory(prefix="ragdog-doclen-", ignore_cleanup_errors=True) as directory:
        resources.CHROMA_DIR = Path(directory) / "chroma_db"
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", resources.CHROMA_DIR)
        bm25 = resources.load_health_bm25_index()
        by_id = {doc.id: doc for doc in bm25.documents}
        answers = resources.load_health_answer_table()
        judge_llm = judge_model()
        tops: dict[str, dict[str, list]] = {}
        for variant, (doc_name, limit) in VARIANTS.items():
            tops[variant] = {}
            for set_name, (questions, _) in sets.items():
                rows = []
                for question, query in zip(questions, queries[limit][set_name]):
                    rows_top = top_rows(docs[doc_name], owner if doc_name == "chunk128" else None, query, CANDIDATES)
                    dense = [by_id[str(row)] for row in rows_top]
                    lexical = bm25.search(question, CANDIDATES)
                    rows.append({"dense": dense[:3], "hybrid": reciprocal_rank_fusion([dense, lexical], top_k=3)})
                tops[variant][set_name] = rows

        results: dict = {}
        for set_name, (questions, saved) in sets.items():
            jobs = []
            for i, question in enumerate(questions):
                known = {**saved[i], **extra.get(f"{set_name}:{i}", {})}
                missing = {d.id: d for v in VARIANTS for s in ("dense", "hybrid") for d in tops[v][set_name][i][s] if d.id not in known}
                if missing:
                    jobs.append((i, question, attach_health_answers(list(missing.values()), answers)))
            print(f"{set_name}: grading {sum(len(j[2]) for j in jobs)} new documents", flush=True)
            with ThreadPoolExecutor(8) as pool:
                for (i, _, _), grades in zip(jobs, pool.map(lambda job: judge(judge_llm, job[1], job[2]), jobs)):
                    extra.setdefault(f"{set_name}:{i}", {}).update(grades)
            GRADES.write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
            for v in VARIANTS:
                for s in ("dense", "hybrid"):
                    results.setdefault(v, {}).setdefault(s, {})[set_name] = [
                        any({**saved[i], **extra.get(f"{set_name}:{i}", {})}.get(d.id) == 2 for d in tops[v][set_name][i][s])
                        for i in range(len(questions))]

    summary = {}
    for v in VARIANTS:
        for s in ("dense", "hybrid"):
            per_set = results[v][s]
            both = per_set["short"] + per_set["long_useful"]
            entry = {name: round(sum(x) / len(x), 3) for name, x in per_set.items()}
            entry["all"] = round(sum(both) / len(both), 3)
            if v != "len128":
                base = results["len128"][s]
                entry["vs_len128_p"] = {name: round(mcnemar(base[name], per_set[name]), 3) for name in per_set}
                entry["vs_len128_p"]["all"] = round(mcnemar(base["short"] + base["long_useful"], both), 3)
            summary[f"{v} {s}"] = entry
    report["useful@3"] = summary
    print(json.dumps(report, ensure_ascii=False, indent=1))
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
