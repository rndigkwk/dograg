"""Which health evaluation questions have a rewritten copy in the corpus (day69, no model calls).

    uv run python scripts/measure_eval_overlap.py

The evaluation questions are not corpus rows: the long ones come from data/df_val.csv, the corpus
is data/df.csv (0 shared questions, scripts/audit_health_data.py). But AI Hub tells many
consultations twice in different words (same breed, age, weight and event), one copy in each file.
A question whose copy is in the corpus is an easy one: the search finds the copy, and the score says
little about the search.

Character overlap does not find them (trigram Jaccard 0.22-0.35 for clear copies), and the
embedding alone joins different dogs told with the same template. So a candidate needs both:

- cosine >= 0.8 with the app's question embedding (fine-tuned ko-sroberta, int8 ONNX)
- IDF-weighted overlap >= 0.4 of the question's nouns, numbers and roots (Kiwi), over the
  embedding's 20 nearest corpus questions: the rare words a retelling keeps (진돗개, 단감 씨, 4.8kg)

Every candidate was read and labelled by hand (tests/data/eval_overlap_labels.json). On the 100
graded questions (tests/data/health_relevance_100.json) the app's saved hybrid ranking and the
grades give useful@3 with and without the copies. On all 561 long questions the label hit@3 (a top-3
post with the same life stage, department and disease) is split the same way, with the health search
as it runs now: the app's embedding alone, exact search (BM25 left the health search on 2026-10-20). The short set (tests/data/emergency_signs.json)
was written by hand and is checked for candidates only. Corpus vectors are cached in
output/experiments/. Results: output/experiments/eval_overlap.json.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

OUT = PROJECT_DIR / "output" / "experiments" / "eval_overlap.json"
CACHE = PROJECT_DIR / "output" / "experiments" / "eval_overlap_corpus_vectors.npy"
LABELS = PROJECT_DIR / "tests" / "data" / "eval_overlap_labels.json"
MIN_COSINE, MIN_OVERLAP, NEIGHBOURS = 0.8, 0.4, 20
LABELS_FIELDS = ("meta.lifeCycle", "meta.department", "meta.disease")
WORD_TAGS = ("NNG", "NNP", "SN", "SL", "XR")


def read_csv(path: Path) -> list[dict]:
    csv.field_size_limit(10**8)
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def embed(texts: list[str]) -> np.ndarray:
    from src import resources

    model = resources.load_health_embeddings()
    vectors = []
    for start in range(0, len(texts), 256):
        vectors += model.embed_documents(texts[start:start + 256])
        print(f"  embedded {min(start + 256, len(texts))}/{len(texts)}", flush=True)
    return np.asarray(vectors, dtype=np.float32)


def candidates(questions: list[str], corpus: list[str], corpus_vectors: np.ndarray, kiwi, corpus_words: list[set],
               idf) -> list[dict]:
    """For each question, the corpus question of its embedding's NEIGHBOURS nearest that shares the most rare words."""
    rows = []
    for question, scores in zip(questions, embed(questions) @ corpus_vectors.T, strict=True):
        words = words_of(kiwi, question)
        total = sum(idf(w) for w in words) or 1.0
        best = max(np.argsort(-scores)[:NEIGHBOURS], key=lambda k: sum(idf(w) for w in words & corpus_words[k]))
        overlap = sum(idf(w) for w in words & corpus_words[best]) / total
        rows.append({"corpus": int(best), "cosine": round(float(scores[best]), 3), "overlap": round(overlap, 3),
                     "candidate": bool(scores[best] >= MIN_COSINE and overlap >= MIN_OVERLAP),
                     "top3": [int(k) for k in np.argsort(-scores)[:3]]})
    return rows


def words_of(kiwi, text: str) -> set[str]:
    return {token.form for token in kiwi.tokenize(text[:1500]) if token.tag in WORD_TAGS}


def main() -> int:
    from kiwipiepy import Kiwi

    corpus_rows = read_csv(PROJECT_DIR / "data" / "df.csv")
    corpus, ids = [row["qa.input"] for row in corpus_rows], [row[""] for row in corpus_rows]
    if CACHE.is_file() and np.load(CACHE).shape[0] == len(corpus):
        corpus_vectors = np.load(CACHE)
    else:
        print("embedding the corpus questions (once)", flush=True)
        corpus_vectors = embed(corpus)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        np.save(CACHE, corpus_vectors)
    kiwi = Kiwi()
    corpus_words = [words_of(kiwi, text) for text in corpus]
    document_frequency = Counter(word for words in corpus_words for word in words)
    idf = lambda word: math.log(len(corpus) / (1 + document_frequency.get(word, 0)))

    val_rows = read_csv(PROJECT_DIR / "data" / "df_val.csv")
    val = [row["qa.input"] for row in val_rows]
    short = json.loads((PROJECT_DIR / "tests" / "data" / "emergency_signs.json").read_text(encoding="utf-8"))["items"]
    relevance = json.loads((PROJECT_DIR / "tests" / "data" / "health_relevance_100.json").read_text(encoding="utf-8"))["items"]
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    same = set(labels["same"])

    long_rows = candidates(val, corpus, corpus_vectors, kiwi, corpus_words, idf)
    found = {i for i, row in enumerate(long_rows) if row["candidate"]}
    unlabelled = sorted(found - same - set(labels["different"]))
    report = {
        "rule": f"cosine >= {MIN_COSINE} and rare-word overlap >= {MIN_OVERLAP} (of {NEIGHBOURS} nearest)",
        "long": {"n": len(val), "candidates": len(found), "copies": len(same & found), "unlabelled": unlabelled},
        "short": {"n": len(short), "candidates": sum(row["candidate"] for row in
                                                     candidates([i["question"] for i in short], corpus, corpus_vectors,
                                                                kiwi, corpus_words, idf))},
    }

    split, copy_in_top3 = {"copy": [], "other": []}, 0
    for item in relevance:
        row, top3 = int(item["row"]), item["rankings"]["hybrid"][:3]
        useful = any(item["grades"].get(doc) == 2 for doc in top3)
        if row in same:
            split["copy"].append(useful)
            copy_in_top3 += ids[long_rows[row]["corpus"]] in top3
        else:
            split["other"].append(useful)
    every = split["copy"] + split["other"]
    report["long_useful"] = {
        "n": len(every), "with_copy": len(split["copy"]), "copy_in_hybrid_top3": copy_in_top3,
        "useful@3_all": round(sum(every) / len(every), 3),
        "useful@3_with_copy": round(sum(split["copy"]) / len(split["copy"]), 3) if split["copy"] else None,
        "useful@3_without_copy": round(sum(split["other"]) / len(split["other"]), 3),
    }
    split, copy_in_top3 = {"copy": [], "other": []}, 0
    for i, (row, found_row) in enumerate(zip(val_rows, long_rows, strict=True)):
        hit = any(all(corpus_rows[k][f] == row[f] for f in LABELS_FIELDS) for k in found_row["top3"])
        if i in same:
            split["copy"].append(hit)
            copy_in_top3 += found_row["corpus"] in found_row["top3"]
        else:
            split["other"].append(hit)
    copies = [(val_rows[i], corpus_rows[long_rows[i]["corpus"]]) for i in sorted(same)]
    agree = {f: sum(q[f] == c[f] for q, c in copies) for f in LABELS_FIELDS}
    agree["all three"] = sum(all(q[f] == c[f] for f in LABELS_FIELDS) for q, c in copies)
    every = split["copy"] + split["other"]
    report["long_hit"] = {
        "search": "app embedding, exact, top 3", "n": len(every), "with_copy": len(split["copy"]),
        "copy_in_top3": copy_in_top3, "hit@3_all": round(sum(every) / len(every), 3),
        "hit@3_with_copy": round(sum(split["copy"]) / len(split["copy"]), 3),
        "hit@3_without_copy": round(sum(split["other"]) / len(split["other"]), 3),
        "copy_labels_agree": agree,  # of the 53 question-copy pairs: the same story, labelled twice
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
