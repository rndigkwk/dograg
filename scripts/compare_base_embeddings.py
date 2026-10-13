"""Base embedding models before any fine-tuning: ko-sroberta vs multilingual-e5-small (Day 58 lesson 01).

    uv run --group tools python scripts/compare_base_embeddings.py

Both models embed the 19,206 health consultation questions and the evaluation questions with
PyTorch (float) and are searched exactly (numpy), each with its own conventions:
- jhgan/ko-sroberta-multitask: text as is, 128 tokens (the app's setting)
- intfloat/multilingual-e5-small: "passage: " / "query: " prefixes, 512 tokens
Measured as Dense only and as the app's hybrid (the same Kiwi BM25, 12 candidates each, RRF, top 3)
on the judged sets: short 120 (tests/data/emergency_signs.json) and long 100
(tests/data/health_relevance_100.json). useful@3, paired McNemar against ko-sroberta. Top-3
documents never graded are graded by the same judge (scripts/relevance_set.py) and added to
output/experiments/finetuned_embedding_grades.json. Also: share of documents cut at the model's
limit, query embedding time on this CPU, dimension. Document vectors are cached in
output/experiments/base_embeddings_<model>.npy. Results: output/experiments/base_embeddings.json.
"""

from __future__ import annotations

import csv
import json
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
OUT_DIR = PROJECT_DIR / "output" / "experiments"
CANDIDATES = 12
MODELS = {
    "ko-sroberta": {"name": "jhgan/ko-sroberta-multitask", "max_len": 128, "query": "", "passage": ""},
    "e5-small": {"name": "intfloat/multilingual-e5-small", "max_len": 512, "query": "query: ", "passage": "passage: "},
}


def mcnemar(a: list[bool], b: list[bool]) -> float:
    from math import comb

    only_a = sum(x and not y for x, y in zip(a, b))
    only_b = sum(y and not x for x, y in zip(a, b))
    n = only_a + only_b
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, k) for k in range(min(only_a, only_b) + 1)) / 2**n)


def main() -> int:
    import torch
    from sentence_transformers import SentenceTransformer

    from relevance_set import judge, judge_model
    from src import resources
    from src.health_answers import attach_health_answers
    from src.hybrid_retrieval import reciprocal_rank_fusion

    torch.set_num_threads(4)
    with open(PROJECT_DIR / "data" / "df_val.csv", encoding="utf-8", newline="") as f:
        val = list(csv.DictReader(f))
    relevance = json.loads((PROJECT_DIR / "tests" / "data" / "health_relevance_100.json").read_text(encoding="utf-8"))["items"]
    short = json.loads((PROJECT_DIR / "tests" / "data" / "emergency_signs.json").read_text(encoding="utf-8"))["items"]
    sets = {
        "short": ([item["question"] for item in short], [{} for _ in short]),
        "long_useful": ([val[int(item["row"])]["qa.input"] for item in relevance], [item["grades"] for item in relevance]),
    }
    extra = json.loads(GRADES.read_text(encoding="utf-8")) if GRADES.exists() else {}
    report: dict = {"models": {}}
    with tempfile.TemporaryDirectory(prefix="ragdog-base-emb-", ignore_cleanup_errors=True) as directory:
        resources.CHROMA_DIR = Path(directory) / "chroma_db"
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", resources.CHROMA_DIR)
        db, bm25 = resources.load_vector_db(), resources.load_health_bm25_index()
        stored = db.get(include=["documents"])
        ids, texts = stored["ids"], stored["documents"]
        by_id = {doc.id: doc for doc in bm25.documents}
        answers = resources.load_health_answer_table()
        judge_llm = judge_model()
        tops: dict[str, dict[str, list]] = {}
        for key, spec in MODELS.items():
            model = SentenceTransformer(spec["name"], device="cpu")
            model.max_seq_length = spec["max_len"]
            lengths = [len(t) for t in model.tokenizer([spec["passage"] + text for text in texts], add_special_tokens=True)["input_ids"]]
            cache = OUT_DIR / f"base_embeddings_{key}.npy"
            rows_cache = OUT_DIR / f"base_embeddings_{key}_rows.npy"  # from notebooks/e5_small_embed_colab.ipynb: df.csv row order
            if cache.exists():
                vectors = np.load(cache)
            elif rows_cache.exists():
                vectors = np.load(rows_cache)[[int(i) for i in ids]]
            else:
                started = time.perf_counter()
                vectors = model.encode([spec["passage"] + text for text in texts], batch_size=64, normalize_embeddings=True,
                                       show_progress_bar=False, convert_to_numpy=True).astype(np.float32)
                np.save(cache, vectors)
                print(f"{key}: embedded {len(texts)} documents in {time.perf_counter() - started:.0f}s", flush=True)
            report["models"][key] = {"dimension": int(vectors.shape[1]), "max_tokens": spec["max_len"],
                                     "cut_share": round(sum(n > spec["max_len"] for n in lengths) / len(lengths), 4)}
            timings = []
            tops[key] = {}
            for set_name, (questions, _) in sets.items():
                rows = []
                for question in questions:
                    started = time.perf_counter()
                    query = model.encode(spec["query"] + question, normalize_embeddings=True, convert_to_numpy=True)
                    timings.append(time.perf_counter() - started)
                    order = np.argsort(-(vectors @ query))[:CANDIDATES]
                    dense = [by_id[ids[i]] for i in order]
                    lexical = bm25.search(question, CANDIDATES)
                    rows.append({"dense": dense[:3], "hybrid": reciprocal_rank_fusion([dense, lexical], top_k=3)})
                tops[key][set_name] = rows
            report["models"][key]["query_ms_p50"] = round(float(np.median(timings)) * 1000, 1)
            del model

        results: dict = {}
        for set_name, (questions, saved) in sets.items():
            jobs = []
            for i, question in enumerate(questions):
                known = {**saved[i], **extra.get(f"{set_name}:{i}", {})}
                missing = {d.id: d for key in MODELS for s in ("dense", "hybrid") for d in tops[key][set_name][i][s] if d.id not in known}
                if missing:
                    jobs.append((i, question, attach_health_answers(list(missing.values()), answers)))
            print(f"{set_name}: grading {sum(len(j[2]) for j in jobs)} new documents", flush=True)
            with ThreadPoolExecutor(8) as pool:
                for (i, _, _), grades in zip(jobs, pool.map(lambda job: judge(judge_llm, job[1], job[2]), jobs)):
                    extra.setdefault(f"{set_name}:{i}", {}).update(grades)
            GRADES.write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
            for key in MODELS:
                for s in ("dense", "hybrid"):
                    results.setdefault(key, {}).setdefault(s, {})[set_name] = [
                        any({**saved[i], **extra.get(f"{set_name}:{i}", {})}.get(d.id) == 2 for d in tops[key][set_name][i][s])
                        for i in range(len(questions))]

    summary = {}
    for key in MODELS:
        for s in ("dense", "hybrid"):
            per_set = results[key][s]
            both = per_set["short"] + per_set["long_useful"]
            entry = {name: round(sum(v) / len(v), 3) for name, v in per_set.items()}
            entry["all"] = round(sum(both) / len(both), 3)
            if key != "ko-sroberta":
                base = results["ko-sroberta"][s]
                entry["vs_ko-sroberta_p"] = {name: round(mcnemar(base[name], per_set[name]), 3) for name in per_set}
                entry["vs_ko-sroberta_p"]["all"] = round(mcnemar(base["short"] + base["long_useful"], both), 3)
            summary[f"{key} {s}"] = entry
    report["useful@3"] = summary
    print(json.dumps(report, ensure_ascii=False, indent=1))
    (OUT_DIR / "base_embeddings.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
