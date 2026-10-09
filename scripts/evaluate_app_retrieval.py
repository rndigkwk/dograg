"""The health search as the app runs it, before and after the fine-tuned model.

    uv run python scripts/evaluate_app_retrieval.py

"before" = the base model's int8 ONNX + the Chroma database kept by
scripts/rebuild_health_collection.py (output/chroma_db_before_finetune); "after" = the current
settings (fine-tuned model's int8 ONNX + data/chroma_db). Both go through src/tools/health.py
retrieve_health (approximate Chroma search, BM25, RRF, top 3), i.e. exactly what the app does,
unlike scripts/evaluate_finetuned_embedding.py (PyTorch, exact search). Same sets and judge:
short 120 (useful@3), long 100 (useful@3), long 561 (label hit@3); grades are shared with that
script's local grade file. Results: output/experiments/app_retrieval.json.
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

from evaluate_finetuned_embedding import EXTRA_GRADES, FIELDS, mcnemar  # noqa: E402

BEFORE_DB = PROJECT_DIR / "output" / "chroma_db_before_finetune"
BASE_MODEL, BASE_ONNX = "jhgan/ko-sroberta-multitask", "onnx/model_qint8_avx512_vnni.onnx"
OUT = PROJECT_DIR / "output" / "experiments" / "app_retrieval.json"


def run(setting: str, questions: dict[str, list[str]]) -> dict[str, list[list]]:
    from src import resources
    from src.tools import health

    with tempfile.TemporaryDirectory(prefix="ragdog-app-eval-", ignore_cleanup_errors=True) as directory:
        source = BEFORE_DB if setting == "before" else PROJECT_DIR / "data" / "chroma_db"
        shutil.copytree(source, Path(directory) / "chroma_db")
        resources.CHROMA_DIR = Path(directory) / "chroma_db"  # a copy: Chroma writes even when reading
        model, onnx = resources.HEALTH_EMBEDDING_MODEL_NAME, resources.HEALTH_ONNX_FILE
        if setting == "before":
            resources.HEALTH_EMBEDDING_MODEL_NAME, resources.HEALTH_ONNX_FILE = BASE_MODEL, BASE_ONNX
        resources.load_vector_db.clear()
        health.initialize_rag.clear()
        try:
            return {name: [health.retrieve_health(q, k=3) for q in qs] for name, qs in questions.items()}
        finally:
            resources.HEALTH_EMBEDDING_MODEL_NAME, resources.HEALTH_ONNX_FILE = model, onnx
            resources.load_vector_db.clear()
            health.initialize_rag.clear()
            resources.CHROMA_DIR = resources.SOURCE_CHROMA_DIR


def main() -> int:
    from relevance_set import judge, judge_model

    csv.field_size_limit(10**8)
    with open(PROJECT_DIR / "data" / "df_val.csv", encoding="utf-8", newline="") as f:
        val = list(csv.DictReader(f))
    relevance = json.loads((PROJECT_DIR / "tests" / "data" / "health_relevance_100.json").read_text(encoding="utf-8"))["items"]
    short = json.loads((PROJECT_DIR / "tests" / "data" / "emergency_signs.json").read_text(encoding="utf-8"))["items"]
    questions = {"short": [i["question"] for i in short], "long_useful": [val[i["row"]]["qa.input"] for i in relevance],
                 "long_hit": [row["qa.input"] for row in val]}
    saved = {"short": [{} for _ in short], "long_useful": [i["grades"] for i in relevance]}
    tops = {setting: run(setting, questions) for setting in ("before", "after")}
    print("retrieved", flush=True)

    extra = json.loads(EXTRA_GRADES.read_text(encoding="utf-8")) if EXTRA_GRADES.exists() else {}
    model = judge_model()
    jobs = []
    for set_name in ("short", "long_useful"):
        for i, question in enumerate(questions[set_name]):
            known = {**saved[set_name][i], **extra.get(f"{set_name}:{i}", {})}
            missing = {str(d.id): d for s in tops for d in tops[s][set_name][i] if str(d.id) not in known}
            if missing:
                jobs.append((set_name, i, question, list(missing.values())))
    with ThreadPoolExecutor(8) as pool:
        for (set_name, i, _, _), grades in zip(jobs, pool.map(lambda j: judge(model, j[2], j[3]), jobs)):
            extra.setdefault(f"{set_name}:{i}", {}).update(grades)
    EXTRA_GRADES.write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
    print(f"graded {len(jobs)} questions with new candidates", flush=True)

    report = {}
    for set_name in ("short", "long_useful"):
        useful = {}
        for setting in tops:
            useful[setting] = []
            for i in range(len(questions[set_name])):
                grades = {**saved[set_name][i], **extra.get(f"{set_name}:{i}", {})}
                useful[setting].append(any(grades.get(str(d.id)) == 2 for d in tops[setting][set_name][i]))
        report[set_name] = {s: round(sum(u) / len(u), 3) for s, u in useful.items()}
        report[f"{set_name}_vs_before"] = mcnemar(useful["before"], useful["after"])
    hits = {s: [any(all(str(d.metadata.get(k)) == row[k] for k in FIELDS) for d in docs)
                for row, docs in zip(val, tops[s]["long_hit"])] for s in tops}
    report["long_hit@3"] = {s: round(sum(h) / len(h), 4) for s, h in hits.items()}
    report["long_hit@3_vs_before"] = mcnemar(hits["before"], hits["after"])
    print(json.dumps(report, ensure_ascii=False, indent=1))
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
