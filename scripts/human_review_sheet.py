"""A person checks the judge where the fine-tuned model won (no model calls).

    uv run --group tools python scripts/human_review_sheet.py           # write the sheet
    uv run --group tools python scripts/human_review_sheet.py --score   # after filling it in

The fine-tuned health model B beat the base model on the 120 short questions (useful@3 0.625 ->
0.800, docs/wiki/embedding-finetune.md), but the judge that graded them is of the same family as the
model that wrote the training queries. So for every short question B gained (base top 3 had no
grade 2, B's had one), the sheet shows the post the judge rated 2, without the judge's grade, and
a person grades it 0 / 1 / 2 with the judge's rubric (scripts/relevance_set.py JUDGE_PROMPT).
Same search as that comparison: exact Dense 12 + BM25 12 -> RRF, top 3, saved grades in
output/experiments/finetuned_embedding_grades.json.

The sheet holds AI Hub text, so it stays in output/ (not committed): output/experiments/
human_review_short.csv (UTF-8 with BOM, opens in Excel). --score reads the 사람 column back and
writes the agreement to output/experiments/human_review_short.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

SHEET = PROJECT_DIR / "output" / "experiments" / "human_review_short.csv"
OUT = PROJECT_DIR / "output" / "experiments" / "human_review_short.json"
GRADES = PROJECT_DIR / "output" / "experiments" / "finetuned_embedding_grades.json"
CANDIDATES, SHOWN_CHARS = 12, 400
COLUMNS = ("번호", "보호자 질문", "찾은 상담 (보호자)", "찾은 상담 (수의사 답변)", "사람 (0/1/2)", "메모")


def gained_rows() -> list[dict]:
    from evaluate_finetuned_embedding import ALL_TUNED, BASE
    from huggingface_hub import snapshot_download
    from langchain_core.documents import Document
    from measure_eval_overlap import read_csv
    from sentence_transformers import SentenceTransformer

    from src import resources, settings
    from src.health_answers import attach_health_answers
    from src.hybrid_retrieval import reciprocal_rank_fusion

    token = settings.get_setting("HF_TOKEN")
    a_path = Path(snapshot_download(ALL_TUNED["a"], token=token))  # the base model's vectors live in -a
    b_path = Path(snapshot_download(ALL_TUNED["b"], token=token))
    ids = json.loads((a_path / "corpus_ids.json").read_text())
    assert json.loads((b_path / "corpus_ids.json").read_text()) == ids
    vectors = {"base": np.load(a_path / "base_corpus_embeddings.npy"), "b": np.load(b_path / "corpus_embeddings.npy")}
    vectors = {name: m / np.linalg.norm(m, axis=1, keepdims=True) for name, m in vectors.items()}
    encoders = {"base": SentenceTransformer(BASE, device="cpu"), "b": SentenceTransformer(str(b_path), device="cpu")}
    for encoder in encoders.values():
        encoder.max_seq_length = 128
    rows = {row[""]: row for row in read_csv(PROJECT_DIR / "data" / "df.csv")}
    documents = [Document(page_content=rows[i]["qa.input"], id=i) for i in ids]
    bm25 = resources.load_health_bm25_index()

    short = json.loads((PROJECT_DIR / "tests" / "data" / "emergency_signs.json").read_text(encoding="utf-8"))["items"]
    questions = [item["question"] for item in short]
    extra = json.loads(GRADES.read_text(encoding="utf-8"))
    tops = {}
    for name, encoder in encoders.items():
        q = encoder.encode(questions, batch_size=64, convert_to_numpy=True)
        q = q / np.linalg.norm(q, axis=1, keepdims=True)
        order = np.argsort(-(q @ vectors[name].T), axis=1)[:, :CANDIDATES]
        tops[name] = [reciprocal_rank_fusion([[documents[k] for k in idx], bm25.search(question, CANDIDATES)], top_k=3)
                      for question, idx in zip(questions, order)]
    answers = resources.load_health_answer_table()
    gained = []
    for i, question in enumerate(questions):
        grades = extra.get(f"short:{i}", {})
        if any(grades.get(d.id) == 2 for d in tops["base"][i]):
            continue
        useful = [d for d in tops["b"][i] if grades.get(d.id) == 2]
        if useful:
            doc = attach_health_answers([useful[0]], answers)[0]
            gained.append({"question_index": i, "question": question, "doc": doc.id,
                           "post": " ".join(doc.page_content.split())[:SHOWN_CHARS],
                           "answer": " ".join(str(doc.metadata.get("qa.output", "")).split())[:SHOWN_CHARS]})
    return gained


def write_sheet() -> int:
    gained = gained_rows()
    SHEET.parent.mkdir(parents=True, exist_ok=True)
    with open(SHEET, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for n, row in enumerate(gained, 1):
            writer.writerow([n, row["question"], row["post"], row["answer"], "", ""])
    key = SHEET.with_suffix(".key.json")  # which question and post each row is; the judge gave all of them 2
    key.write_text(json.dumps([{k: r[k] for k in ("question_index", "doc")} for r in gained]), encoding="utf-8")
    print(f"{len(gained)} rows -> {SHEET}")
    return 0


def score() -> int:
    with open(SHEET, encoding="utf-8-sig", newline="") as f:
        marks = [row["사람 (0/1/2)"].strip() for row in csv.DictReader(f)]
    graded = [int(m) for m in marks if m in ("0", "1", "2")]
    if not graded:
        print("no grades yet: fill the 사람 column with 0, 1 or 2")
        return 1
    report = {"rows": len(marks), "graded": len(graded), "person_2": graded.count(2), "person_1": graded.count(1),
              "person_0": graded.count(0), "agree_with_judge": round(graded.count(2) / len(graded), 3)}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--score", action="store_true", help="read the filled sheet back")
    raise SystemExit(score() if parser.parse_args().score else write_sheet())
