"""Compare the base health embedding model with the fine-tuned ones on the app's hybrid path.

    uv run python scripts/evaluate_finetuned_embedding.py        # needs HF_TOKEN (private models)

Models: `jhgan/ko-sroberta-multitask` (base) and blanden77/ko-sroberta-dograg-a / -b, trained in
notebooks/finetune_embedding_colab.ipynb on synthetic guardian queries (scripts/finetune_queries.py).
Corpus vectors come from the model repos (computed on Colab for all three); queries are encoded
here with PyTorch. Dense search is exact cosine over the 19,206 vectors, so the three models are
compared the same way (the app's Chroma index is approximate). Hybrid = Dense 12 + BM25 12 -> RRF,
as in the app.

Sets:
- long: data/df_val.csv, 561 guardian consultations. hit@3 = all three labels match (as before).
- long_useful: the 100 graded questions of tests/data/health_relevance_100.json. useful@3 with
  the saved grades; candidates never graded are graded now with the same judge and kept locally.
- short: the 120 short questions of tests/data/emergency_signs.json (written by hand for the
  emergency set, not by the query generator). Their top 3 from every model are graded by the same
  judge; useful@3 and relevant@3.
Paired McNemar tests against the base model. Results: output/experiments/finetuned_embedding.json.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from math import comb
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

BASE = "jhgan/ko-sroberta-multitask"
TUNED = {"a": "blanden77/ko-sroberta-dograg-a", "b": "blanden77/ko-sroberta-dograg-b"}
FIELDS = ("meta.lifeCycle", "meta.department", "meta.disease")
CANDIDATE_K = 12
OUT = PROJECT_DIR / "output" / "experiments" / "finetuned_embedding.json"
EXTRA_GRADES = PROJECT_DIR / "output" / "experiments" / "finetuned_embedding_grades.json"


def mcnemar(base: list[bool], other: list[bool]) -> dict:
    gained = sum(o and not b for b, o in zip(base, other))
    lost = sum(b and not o for b, o in zip(base, other))
    n = gained + lost
    p = 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, k) for k in range(min(gained, lost) + 1)) / 2**n)
    return {"gained": gained, "lost": lost, "p": round(p, 4)}


def main() -> int:
    from dotenv import load_dotenv
    from huggingface_hub import snapshot_download
    from langchain_core.documents import Document
    from sentence_transformers import SentenceTransformer

    from relevance_set import judge, judge_model
    from src import resources
    from src.health_answers import attach_health_answers
    from src.hybrid_retrieval import reciprocal_rank_fusion

    load_dotenv(PROJECT_DIR / ".env")
    token = os.environ["HF_TOKEN"]
    paths = {v: Path(snapshot_download(repo, token=token)) for v, repo in TUNED.items()}
    ids = json.loads((paths["a"] / "corpus_ids.json").read_text())
    vectors = {"base": np.load(paths["a"] / "base_corpus_embeddings.npy"),
               **{v: np.load(paths[v] / "corpus_embeddings.npy") for v in TUNED}}
    vectors = {name: m / np.linalg.norm(m, axis=1, keepdims=True) for name, m in vectors.items()}
    encoders = {"base": SentenceTransformer(BASE, device="cpu"),
                **{v: SentenceTransformer(str(paths[v]), device="cpu") for v in TUNED}}
    for encoder in encoders.values():
        encoder.max_seq_length = 128

    csv.field_size_limit(10**8)
    with open(PROJECT_DIR / "data" / "df.csv", encoding="utf-8", newline="") as f:
        rows = {row[""]: row for row in csv.DictReader(f)}
    documents = [Document(page_content=rows[i]["qa.input"], id=i, metadata={k: rows[i][k] for k in FIELDS})
                 for i in ids]
    bm25 = resources.load_health_bm25_index()
    answers = resources.load_health_answer_table()

    def rank(name: str, queries: list[str]) -> list[list[Document]]:
        q = encoders[name].encode(queries, batch_size=64, convert_to_numpy=True, show_progress_bar=False)
        q = q / np.linalg.norm(q, axis=1, keepdims=True)
        scores = q @ vectors[name].T
        top = np.argsort(-scores, axis=1)[:, :CANDIDATE_K]
        results = []
        for query, idx in zip(queries, top):
            dense = [documents[i] for i in idx]
            results.append(reciprocal_rank_fusion([dense, bm25.search(query, CANDIDATE_K)], top_k=3))
        return results

    names = ["base", *TUNED]
    report = {}

    # long: hit@3 on 561 validation consultations
    with open(PROJECT_DIR / "data" / "df_val.csv", encoding="utf-8", newline="") as f:
        val = list(csv.DictReader(f))
    hits = {}
    for name in names:
        top3 = rank(name, [row["qa.input"] for row in val])
        hits[name] = [any(all(d.metadata[k] == row[k] for k in FIELDS) for d in docs) for row, docs in zip(val, top3)]
        print("long hit@3", name, round(sum(hits[name]) / len(val), 4), flush=True)
    report["long_hit@3"] = {name: round(sum(h) / len(val), 4) for name, h in hits.items()}
    report["long_hit@3_vs_base"] = {v: mcnemar(hits["base"], hits[v]) for v in TUNED}

    # useful@3 sets: grade what was never graded
    model = judge_model()
    extra = json.loads(EXTRA_GRADES.read_text(encoding="utf-8")) if EXTRA_GRADES.exists() else {}

    def useful_for(set_name: str, questions: list[str], saved: list[dict]) -> None:
        tops = {name: rank(name, questions) for name in names}
        jobs = []
        for i, question in enumerate(questions):
            known = {**saved[i], **extra.get(f"{set_name}:{i}", {})}
            missing = {d.id: d for name in names for d in tops[name][i] if d.id not in known}
            if missing:
                docs = list(missing.values())
                attach_health_answers(docs, answers)
                jobs.append((i, question, docs))
        with ThreadPoolExecutor(8) as pool:
            for (i, _, _), grades in zip(jobs, pool.map(lambda job: judge(model, job[1], job[2]), jobs)):
                extra.setdefault(f"{set_name}:{i}", {}).update(grades)
        EXTRA_GRADES.write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
        useful, relevant = {}, {}
        for name in names:
            useful[name], relevant[name] = [], []
            for i in range(len(questions)):
                grades = {**saved[i], **extra.get(f"{set_name}:{i}", {})}
                got = [grades.get(d.id) for d in tops[name][i]]
                useful[name].append(any(g == 2 for g in got))
                relevant[name].append(any(g is not None and g >= 1 for g in got))
        n = len(questions)
        report[set_name] = {name: {"useful@3": round(sum(useful[name]) / n, 3),
                                   "relevant@3": round(sum(relevant[name]) / n, 3)} for name in names}
        report[f"{set_name}_useful_vs_base"] = {v: mcnemar(useful["base"], useful[v]) for v in TUNED}
        print(set_name, json.dumps(report[set_name], ensure_ascii=False), report[f"{set_name}_useful_vs_base"], flush=True)

    relevance = json.loads((PROJECT_DIR / "tests" / "data" / "health_relevance_100.json").read_text(encoding="utf-8"))["items"]
    useful_for("long_useful", [val[item["row"]]["qa.input"] for item in relevance], [item["grades"] for item in relevance])
    short = json.loads((PROJECT_DIR / "tests" / "data" / "emergency_signs.json").read_text(encoding="utf-8"))["items"]
    useful_for("short", [item["question"] for item in short], [{} for _ in short])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
