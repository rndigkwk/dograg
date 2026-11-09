"""Compare the base health embedding model with the fine-tuned ones on the app's hybrid path.

    uv run --group tools python scripts/evaluate_finetuned_embedding.py   # needs HF_TOKEN (private models)
    uv run --group tools python scripts/evaluate_finetuned_embedding.py --variants b hn   # the hard-negative model
    uv run --group tools python scripts/evaluate_finetuned_embedding.py --variants b --retrain   # 2026-11-02 checkpoints

--variants picks the fine-tuned models to compare with the base (default a b). hn is
blanden77/ko-sroberta-dograg-hn from notebooks/hardneg_finetune_colab.ipynb (2026-10-21): variant B plus
one mined hard negative per pair. --retrain adds the checkpoints of scripts/train_embedding_gpu.py
(blanden77/ko-sroberta-dograg-b2, one folder per seed and epoch; all of them, or the names given). Candidates not graded before are graded with the judge, and the
count is shown before it runs (scripts/cost_guard.py).

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
- short2: the 80 short questions of tests/data/short_questions_2.json (2026-11-09, everyday
  symptoms, written to double the short holdout). Asked for by name only, not in the default run.
  With short, the two are also scored together ("short+short2") for one McNemar test.
Paired McNemar tests against the base model (and against B when B is in the run).
Results: output/experiments/finetuned_embedding.json, or --out.

Choosing a checkpoint without peeking (2026-11-05): --sets short --short-split dev ranks the
checkpoints on the 40 dev questions only; the chosen one is then reported on
--short-split holdout holdout2 and on the long sets. --retrain-repo gist reads the GISTEmbedLoss
checkpoints (gist-s13-e1, ...) instead of b2.
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
ALL_TUNED = {"a": "blanden77/ko-sroberta-dograg-a", "b": "blanden77/ko-sroberta-dograg-b",
             "hn": "blanden77/ko-sroberta-dograg-hn"}
RETRAIN_REPOS = {"b2": "blanden77/ko-sroberta-dograg-b2",  # scripts/train_embedding_gpu.py: s13-e1/, ...
                 "gist": "blanden77/ko-sroberta-dograg-gist"}  # --loss gist: gist-s13-e1/, ...
SETS = ("long", "long_useful", "short", "short2")
TUNED = {name: ALL_TUNED[name] for name in ("a", "b")}  # main() narrows it to --variants (and --retrain)
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
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--variants", nargs="+", choices=sorted(ALL_TUNED), default=["a", "b"])
    parser.add_argument("--retrain", nargs="*", metavar="CHECKPOINT",
                        help="also the retrained checkpoints (all, or these names, e.g. s13-e2)")
    parser.add_argument("--retrain-repo", choices=sorted(RETRAIN_REPOS), default="b2")
    parser.add_argument("--sets", nargs="+", choices=SETS, default=["long", "long_useful", "short"])
    parser.add_argument("--short-split", nargs="+", choices=["dev", "holdout", "holdout2"],
                        help="only these short questions (emergency_signs.json split); default all 120")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    TUNED.clear()
    TUNED.update({name: ALL_TUNED[name] for name in args.variants})
    from dotenv import load_dotenv
    from huggingface_hub import snapshot_download
    from langchain_core.documents import Document
    from relevance_set import judge, judge_model
    from sentence_transformers import SentenceTransformer

    from src import resources
    from src.health_answers import attach_health_answers
    from src.hybrid_retrieval import reciprocal_rank_fusion

    load_dotenv(PROJECT_DIR / ".env")
    token = os.environ["HF_TOKEN"]
    if args.retrain is not None:
        repo = RETRAIN_REPOS[args.retrain_repo]
        root = Path(snapshot_download(repo, token=token, allow_patterns=["results.json"]))
        names = args.retrain or [run["name"] for run in json.loads((root / "results.json").read_text())["runs"]]
        prefix = "b2-" if args.retrain_repo == "b2" else ""  # gist names already start with gist-
        TUNED.update({f"{prefix}{name}": (repo, name) for name in names})

    def model_path(repo) -> Path:
        if isinstance(repo, tuple):  # (repo, checkpoint folder); plain files, since the cache's symlinks fail on Windows here
            local = PROJECT_DIR / "output" / "models" / repo[0].split("/")[1]
            return Path(snapshot_download(repo[0], token=token, allow_patterns=[f"{repo[1]}/*"], local_dir=local)) / repo[1]
        return Path(snapshot_download(repo, token=token))

    paths = {v: model_path(repo) for v, repo in TUNED.items()}
    base_path = Path(snapshot_download(ALL_TUNED["a"], token=token))  # the base model's vectors live in -a
    ids = json.loads((base_path / "corpus_ids.json").read_text())
    for v in TUNED:  # every repo's vectors follow the same df.csv row order
        assert json.loads((paths[v] / "corpus_ids.json").read_text()) == ids, f"{v}: corpus order differs"
    vectors = {"base": np.load(base_path / "base_corpus_embeddings.npy"),
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
    report = {"sets": args.sets, "short_split": args.short_split or "all"}

    def versus(scores: dict[str, list[bool]]) -> dict:
        out = {"vs_base": {v: mcnemar(scores["base"], scores[v]) for v in TUNED}}
        if "b" in TUNED:
            out["vs_b"] = {v: mcnemar(scores["b"], scores[v]) for v in TUNED if v != "b"}
        return out

    # long: hit@3 on 561 validation consultations
    with open(PROJECT_DIR / "data" / "df_val.csv", encoding="utf-8", newline="") as f:
        val = list(csv.DictReader(f))
    if "long" in args.sets:
        hits = {}
        for name in names:
            top3 = rank(name, [row["qa.input"] for row in val])
            hits[name] = [any(all(d.metadata[k] == row[k] for k in FIELDS) for d in docs) for row, docs in zip(val, top3)]
            print("long hit@3", name, round(sum(hits[name]) / len(val), 4), flush=True)
        report["long_hit@3"] = {name: round(sum(h) / len(val), 4) for name, h in hits.items()}
        tests = versus(hits)
        report["long_hit@3_vs_base"] = tests["vs_base"]
        if "vs_b" in tests:
            report["long_hit@3_vs_b"] = tests["vs_b"]

    # useful@3 sets: grade what was never graded
    model = judge_model()
    extra = json.loads(EXTRA_GRADES.read_text(encoding="utf-8")) if EXTRA_GRADES.exists() else {}

    useful_by_set: dict[str, dict[str, list[bool]]] = {}

    def useful_for(set_name: str, questions: list[str], saved: list[dict], index: list[int] | None = None) -> None:
        """index: each question's position in the full set, so the grade cache keys stay the same."""
        index = index or list(range(len(questions)))
        tops = {name: rank(name, questions) for name in names}
        jobs = []
        for i, question in enumerate(questions):
            known = {**saved[i], **extra.get(f"{set_name}:{index[i]}", {})}
            missing = {d.id: d for name in names for d in tops[name][i] if d.id not in known}
            if missing:
                docs = list(missing.values())
                attach_health_answers(docs, answers)
                jobs.append((i, question, docs))
        from cost_guard import confirm

        # One judge call per question with new candidates; the earlier runs' grades are reused.
        if jobs and not confirm(f"evaluate_finetuned_embedding {set_name}", len(jobs), "one judge call per question"):
            raise SystemExit(1)
        with ThreadPoolExecutor(8) as pool:
            for (i, _, _), grades in zip(jobs, pool.map(lambda job: judge(model, job[1], job[2]), jobs)):
                extra.setdefault(f"{set_name}:{index[i]}", {}).update(grades)
        EXTRA_GRADES.write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
        useful, relevant = {}, {}
        for name in names:
            useful[name], relevant[name] = [], []
            for i in range(len(questions)):
                grades = {**saved[i], **extra.get(f"{set_name}:{index[i]}", {})}
                got = [grades.get(d.id) for d in tops[name][i]]
                useful[name].append(any(g == 2 for g in got))
                relevant[name].append(any(g is not None and g >= 1 for g in got))
        n = len(questions)
        report[set_name] = {name: {"useful@3": round(sum(useful[name]) / n, 3),
                                   "relevant@3": round(sum(relevant[name]) / n, 3)} for name in names}
        useful_by_set[set_name] = useful
        tests = versus(useful)
        report[f"{set_name}_useful_vs_base"] = tests["vs_base"]
        if "vs_b" in tests:
            report[f"{set_name}_useful_vs_b"] = tests["vs_b"]
        print(set_name, json.dumps(report[set_name], ensure_ascii=False), tests, flush=True)

    relevance = json.loads((PROJECT_DIR / "tests" / "data" / "health_relevance_100.json").read_text(encoding="utf-8"))["items"]
    if "long_useful" in args.sets:
        useful_for("long_useful", [val[item["row"]]["qa.input"] for item in relevance], [item["grades"] for item in relevance])
    if "short" in args.sets:
        short = json.loads((PROJECT_DIR / "tests" / "data" / "emergency_signs.json").read_text(encoding="utf-8"))["items"]
        keep = [i for i, item in enumerate(short) if not args.short_split or item.get("split") in args.short_split]
        assert keep, f"no short questions in {args.short_split}"
        useful_for("short", [short[i]["question"] for i in keep], [{} for _ in keep], keep)
    if "short2" in args.sets:
        short2 = json.loads((PROJECT_DIR / "tests" / "data" / "short_questions_2.json").read_text(encoding="utf-8"))["items"]
        useful_for("short2", [item["question"] for item in short2], [{} for _ in short2])
    if "short" in useful_by_set and "short2" in useful_by_set:
        both = {name: useful_by_set["short"][name] + useful_by_set["short2"][name] for name in names}
        report["short+short2"] = {name: {"useful@3": round(sum(v) / len(v), 3), "n": len(v)} for name, v in both.items()}
        tests = versus(both)
        report["short+short2_useful_vs_base"] = tests["vs_base"]
        if "vs_b" in tests:
            report["short+short2_useful_vs_b"] = tests["vs_b"]
        print("short+short2", json.dumps(report["short+short2"], ensure_ascii=False), tests, flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
