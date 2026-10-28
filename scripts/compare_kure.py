"""KURE-v1 for the health search: is it better than the app's fine-tuned ko-sroberta?

    uv run --group tools python scripts/compare_kure.py                         # KURE-v1 as published
    uv run --group tools python scripts/compare_kure.py --finetuned --dry-run   # judge calls it would need
    uv run --group tools python scripts/compare_kure.py --finetuned             # + notebooks/kure_finetune_colab.ipynb
    uv run --group tools python scripts/compare_kure.py --bge-m3 --dry-run      # + notebooks/bge_m3_embed_colab.ipynb

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

--finetuned (2026-10-16) compares KURE-v1 fine-tuned on the app's synthetic queries instead
(notebooks/kure_finetune_colab.ipynb): the private model blanden77/kure-v1-dograg and its document
vectors from the private dataset's experiments branch (downloaded when missing). Grades are cached
(finetuned_embedding_grades.json), so only top-3 documents never graded cost a judge call: the
script counts those questions first and asks scripts/cost_guard.py; --dry-run stops there. The
results go to MLflow on DagsHub (experiment health-embedding, scripts/mlflow_tracking.py) unless
--no-mlflow, and to output/experiments/kure_v1_ft.json.

--bge-m3 (2026-10-28) compares BAAI/bge-m3 as published, the model KURE-v1 was trained from
(open-questions: the health collection was never measured with it). Document vectors from
notebooks/bge_m3_embed_colab.ipynb (1,024 tokens, as KURE-v1), downloaded from the experiments
branch when missing; otherwise as --finetuned. The health search has used the embedding alone since
2026-10-20, so Dense is the row to read; the hybrid is kept to compare with the earlier runs.
"""

from __future__ import annotations

import argparse
import csv
import json
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
DATA_REPO = "blanden77/dograg-data"
FINETUNED = {"model": "blanden77/kure-v1-dograg", "rows": PROJECT_DIR / "output" / "experiments" / "kure_v1_ft_rows.npy",
             "remote_rows": "kure/kure_v1_ft_rows.npy", "out": PROJECT_DIR / "output" / "experiments" / "kure_v1_ft.json",
             "run": "kure-v1 ft-b"}
BGE_M3 = {"model": "BAAI/bge-m3", "rows": PROJECT_DIR / "output" / "experiments" / "bge_m3_rows.npy",
          "remote_rows": "bgem3/bge_m3_rows.npy", "out": PROJECT_DIR / "output" / "experiments" / "bge_m3.json",
          "run": "bge-m3 base"}


def mcnemar(a: list[bool], b: list[bool]) -> float:
    from math import comb

    only_a = sum(x and not y for x, y in zip(a, b))
    only_b = sum(y and not x for x, y in zip(a, b))
    n = only_a + only_b
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, k) for k in range(min(only_a, only_b) + 1)) / 2**n)


def rss_mb() -> int:
    import psutil

    return round(psutil.Process().memory_info().rss / 2**20)


def rows_file(path: Path, remote: str) -> Path:
    if not path.exists():
        from huggingface_hub import hf_hub_download

        from src import settings

        downloaded = hf_hub_download(DATA_REPO, remote, repo_type="dataset", revision="experiments",
                                     token=settings.get_setting("HF_TOKEN"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Path(downloaded).read_bytes())
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--finetuned", action="store_true", help="KURE-v1 fine-tuned on our synthetic queries")
    which.add_argument("--bge-m3", action="store_true", help="BAAI/bge-m3 as published")
    parser.add_argument("--dry-run", action="store_true", help="count the judge calls and stop")
    parser.add_argument("--yes", action="store_true", help="go on above scripts/cost_guard.py's threshold")
    parser.add_argument("--no-mlflow", action="store_true")
    args = parser.parse_args(argv)
    other = FINETUNED if args.finetuned else BGE_M3 if args.bge_m3 else None
    if other:
        model_name, rows, out, run = other["model"], rows_file(other["rows"], other["remote_rows"]), other["out"], other["run"]
    else:
        model_name, rows, out, run = "nlpai-lab/KURE-v1", KURE_ROWS, OUT, "kure-v1 base"

    import torch
    from sentence_transformers import SentenceTransformer

    from cost_guard import confirm

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
    kure_vectors = np.load(rows)[[int(doc_id) for doc_id in app.ids]]  # app order
    bm25 = HealthBM25Index.from_chroma(app, resources.make_health_tokenizer(), token_cache=resources.BM25_TOKEN_CACHE,
                                       tokenizer_version=resources.HEALTH_TOKENIZER_VERSION)
    documents = {d.id: d for d in bm25.documents}

    before = rss_mb()
    from src import settings

    kure = SentenceTransformer(model_name, device="cpu", token=settings.get_setting("HF_TOKEN"))
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

    answers = resources.load_health_answer_table()
    jobs_by_set: dict = {}
    for set_name, (questions, saved) in sets.items():
        jobs_by_set[set_name] = []
        for i, question in enumerate(questions):
            known = {**saved[i], **extra.get(f"{set_name}:{i}", {})}
            missing = {d.id: d for docs in tops[set_name][i].values() for d in docs if d.id not in known}
            if missing:
                jobs_by_set[set_name].append((i, question, attach_health_answers(list(missing.values()), answers)))
    calls = sum(len(jobs) for jobs in jobs_by_set.values())  # one judge call per question with new documents
    detail = ", ".join(f"{s} {len(j)} questions / {sum(len(x[2]) for x in j)} documents" for s, j in jobs_by_set.items())
    if args.dry_run:
        print(f"[dry run] judge calls needed: {calls} ({detail})")
        return 0
    if calls and not confirm(f"compare_kure {run} judge", calls=calls,
                             detail=detail, yes=args.yes):
        return 1
    judge_llm = judge_model() if calls else None
    hits: dict = {}
    for set_name, (questions, saved) in sets.items():
        jobs = jobs_by_set[set_name]
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
    report["model"] = model_name
    print(json.dumps(report, ensure_ascii=False, indent=1))
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.no_mlflow:
        log_to_mlflow(report, out, run=run, judge_calls=calls)
    return 0


def log_to_mlflow(report: dict, out: Path, *, run: str, judge_calls: int) -> None:
    """The comparison as a parent run with one child per system, named like the baselines that
    scripts/mlflow_backfill_embeddings.py logged (the training run is separate)."""
    from mlflow_tracking import log_comparison, system_metrics

    kure = run
    systems = {}
    for key, name in (("app", "ko-sroberta ft-b (app)"), ("kure", kure)):
        systems[name] = {**system_metrics(report["useful@3"], "dense", key),
                         **system_metrics(report["useful@3"], "hybrid", key),
                         "query_ms_p50": report["query_ms_p50"][key]}
    systems[kure]["float_model_mb"] = report["kure_float_model_mb"]
    log_comparison("health-embedding", f"compare {kure} vs app", systems, artifact=out,
                   params={"questions": "short 120, long 100, all 220", "reference": "ko-sroberta ft-b (app)",
                           "candidates": CANDIDATES, "fusion": "RRF dense+BM25, top 3", "judge_calls": judge_calls},
                   tags={"model": report["model"], "script": "scripts/compare_kure.py"})

if __name__ == "__main__":
    raise SystemExit(main())
