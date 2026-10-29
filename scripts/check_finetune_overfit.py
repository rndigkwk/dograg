"""Is the fine-tuned health embedding (B) overfit? Three checks without model calls (2026-10-29).

    uv run --group tools python scripts/check_finetune_overfit.py   # needs the model repos in the HF cache

1. Copies left out: useful@3 of the base model and B on the 100 graded long questions, with and
   without the 13 whose rewritten copy is in the corpus (tests/data/eval_overlap_labels.json; B trained
   on 51 of those copies). Saved grades only: a top-3 post never graded counts as not useful and is
   counted in `ungraded`. Two searches: the hybrid of the 2026-10-09 evaluation (Dense 12 + BM25 12 ->
   RRF) and Dense alone, as the app runs since 2026-10-20.
2. Trained posts first? The 300 dev consultations were left out of training (random.Random(13)). Their
   share of the Dense top 3 and top 12 for the 120 short and 561 long questions, base vs B. A model that
   learned to put the posts it trained on first would show them less often than the base model does.
3. Train vs dev gap: Dense rank of the original consultation for the synthetic queries of 300 trained
   consultations (random.Random(7)) and of the 300 dev consultations. Memorised training queries would
   score far above the dev ones.

Exact cosine over the 19,206 corpus vectors from the model repos, queries encoded here (CPU, 128
tokens), as in scripts/evaluate_finetuned_embedding.py. Results: output/experiments/finetune_overfit.json.
"""

from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

from evaluate_finetuned_embedding import (
    ALL_TUNED,
    BASE,
    CANDIDATE_K,
    EXTRA_GRADES,
    mcnemar,
)

OUT = PROJECT_DIR / "output" / "experiments" / "finetune_overfit.json"
DEV_SEED, DEV_SIZE, TRAIN_SEED = 13, 300, 7


def read_csv(path: Path) -> list[dict]:
    csv.field_size_limit(10**8)
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def share(found: list[list[int]], ids: list[str], dev: set[str]) -> float:
    return round(sum(ids[k] in dev for row in found for k in row) / sum(len(row) for row in found), 4)


def main() -> int:
    from huggingface_hub import snapshot_download
    from sentence_transformers import SentenceTransformer

    from src import resources
    from src.hybrid_retrieval import reciprocal_rank_fusion

    tuned = Path(snapshot_download(ALL_TUNED["b"], local_files_only=True))
    base_repo = Path(snapshot_download(ALL_TUNED["a"], local_files_only=True))  # base vectors live in -a
    ids = json.loads((base_repo / "corpus_ids.json").read_text())
    assert json.loads((tuned / "corpus_ids.json").read_text()) == ids
    vectors = {"base": np.load(base_repo / "base_corpus_embeddings.npy"), "b": np.load(tuned / "corpus_embeddings.npy")}
    vectors = {name: m / np.linalg.norm(m, axis=1, keepdims=True) for name, m in vectors.items()}
    encoders = {"base": SentenceTransformer(BASE, device="cpu"), "b": SentenceTransformer(str(tuned), device="cpu")}
    for encoder in encoders.values():
        encoder.max_seq_length = 128

    def dense(name: str, queries: list[str], k: int) -> np.ndarray:
        q = encoders[name].encode(queries, batch_size=64, convert_to_numpy=True, show_progress_bar=False)
        scores = (q / np.linalg.norm(q, axis=1, keepdims=True)) @ vectors[name].T
        return np.argsort(-scores, axis=1)[:, :k]

    queries = [json.loads(line) for line in (PROJECT_DIR / "data" / "finetune" / "queries.jsonl").open(encoding="utf-8")]
    dev = set(random.Random(DEV_SEED).sample(sorted(q["id"] for q in queries), DEV_SIZE))
    val = read_csv(PROJECT_DIR / "data" / "df_val.csv")
    relevance = json.loads((PROJECT_DIR / "tests" / "data" / "health_relevance_100.json").read_text(encoding="utf-8"))["items"]
    short = json.loads((PROJECT_DIR / "tests" / "data" / "emergency_signs.json").read_text(encoding="utf-8"))["items"]
    copies = set(json.loads((PROJECT_DIR / "tests" / "data" / "eval_overlap_labels.json").read_text(encoding="utf-8"))["same"])
    extra = json.loads(EXTRA_GRADES.read_text(encoding="utf-8")) if EXTRA_GRADES.exists() else {}
    report: dict = {"dev_posts": len(dev), "expected_dev_share": round(len(dev) / len(ids), 4)}

    # 1. copies left out
    bm25 = resources.load_local_health_bm25_index()  # Kiwi BM25, as on 2026-10-09
    long_questions = [val[int(item["row"])]["qa.input"] for item in relevance]
    grades = [{**item["grades"], **extra.get(f"long_useful:{i}", {})} for i, item in enumerate(relevance)]
    is_copy = [int(item["row"]) in copies for item in relevance]
    first = {}
    for search in ("hybrid", "dense"):
        useful, ungraded = {}, {}
        for name in encoders:
            top = dense(name, long_questions, CANDIDATE_K)
            useful[name], ungraded[name] = [], 0
            for question, row, known in zip(long_questions, top, grades):
                top3 = [ids[k] for k in row[:3]]
                if search == "hybrid":
                    from langchain_core.documents import Document

                    fused = reciprocal_rank_fusion([[Document(page_content="", id=ids[k]) for k in row],
                                                    bm25.search(question, CANDIDATE_K)], top_k=3)
                    top3 = [d.id for d in fused]
                ungraded[name] += sum(doc not in known for doc in top3)
                useful[name].append(any(known.get(doc) == 2 for doc in top3))
        part = {}
        for subset, keep in (("all", lambda c: True), ("without_copy", lambda c: not c), ("with_copy", lambda c: c)):
            chosen = [i for i, c in enumerate(is_copy) if keep(c)]
            part[subset] = {"n": len(chosen),
                            **{name: round(sum(useful[name][i] for i in chosen) / len(chosen), 3) for name in encoders},
                            "b_vs_base": mcnemar([useful["base"][i] for i in chosen], [useful["b"][i] for i in chosen])}
        first[search] = {**part, "ungraded_in_top3": ungraded}
        print("1.", search, json.dumps(first[search], ensure_ascii=False), flush=True)
    report["1_copies_left_out"] = first

    # 2. dev posts' share of what the search finds
    second = {}
    for set_name, questions in (("short", [item["question"] for item in short]), ("long", [row["qa.input"] for row in val])):
        second[set_name] = {}
        for name in encoders:
            top = dense(name, questions, CANDIDATE_K)
            second[set_name][name] = {"top3": share([list(r[:3]) for r in top], ids, dev),
                                      "top12": share([list(r) for r in top], ids, dev)}
        print("2.", set_name, second[set_name], flush=True)
    report["2_dev_share"] = second

    # 3. trained vs dev queries
    position = {doc: k for k, doc in enumerate(ids)}
    trained = random.Random(TRAIN_SEED).sample(sorted({q["id"] for q in queries} - dev), DEV_SIZE)
    by_id = {q["id"]: q for q in queries}
    third = {}
    for group, chosen in (("trained", trained), ("dev", sorted(dev))):
        third[group] = {}
        for kind in ("short", "detailed"):
            texts, targets = [by_id[i][kind] for i in chosen], [position[i] for i in chosen]
            third[group][kind] = {}
            for name in encoders:
                top = dense(name, texts, 10)
                ranks = [list(row).index(t) + 1 if t in row else None for row, t in zip(top, targets)]
                third[group][kind][name] = {
                    "top1": round(sum(r == 1 for r in ranks) / len(ranks), 3),
                    "top10": round(sum(r is not None for r in ranks) / len(ranks), 3),
                    "mrr@10": round(sum(1 / r for r in ranks if r) / len(ranks), 3)}
        print("3.", group, third[group], flush=True)
    report["3_trained_vs_dev"] = third

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT.relative_to(PROJECT_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
