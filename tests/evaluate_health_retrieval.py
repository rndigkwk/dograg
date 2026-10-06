"""Compare baseline and lexical reranking on an isolated Chroma copy."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.health_retrieval import rerank_candidates, summarize_retrieval

FIELDS = ("meta.lifeCycle", "meta.department", "meta.disease")


def rank_of_match(row, docs) -> int | None:
    for rank, doc in enumerate(docs, 1):
        if all(str(doc.metadata.get(field)) == str(row[field]) for field in FIELDS):
            return rank
    return None


def evaluate(copy_path: Path) -> int:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from src import resources

    validation = pd.read_csv(ROOT / "data" / "df_val.csv").fillna("")
    baseline, candidate = [], []
    with patch.object(resources, "CHROMA_DIR", copy_path):
        db = resources.load_vector_db()
        for index, row in validation.iterrows():
            docs = db.similarity_search(str(row["qa.input"]), k=12)
            group = "기타" if str(row["meta.disease"]).strip() == "기타" else "non_other"
            baseline.append({"group": group, "hit_rank": rank_of_match(row, docs[:3])})
            candidate.append({"group": group, "hit_rank": rank_of_match(row, rerank_candidates(str(row["qa.input"]), docs, 3))})
            if (index + 1) % 100 == 0:
                print(f"evaluated={index + 1}/{len(validation)}", flush=True)
    base_metrics = summarize_retrieval(baseline)
    new_metrics = summarize_retrieval(candidate)
    activate = (new_metrics["overall"]["hit@3"] > base_metrics["overall"]["hit@3"]
                and new_metrics["non_other"]["hit@3"] >= base_metrics["non_other"]["hit@3"])
    result = {"baseline": base_metrics, "candidate": new_metrics, "activate": activate,
              "relevance": "three metadata fields exact-match; not clinical accuracy"}
    target = ROOT / "output" / "health_retrieval_comparison.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-copy", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_copy:
        return evaluate(args.worker_copy)
    with tempfile.TemporaryDirectory(prefix="dograg-health-eval-") as directory:
        copy_path = Path(directory) / "chroma_db"
        shutil.copytree(ROOT / "data" / "chroma_db", copy_path)
        env = os.environ.copy()
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        return subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker-copy", str(copy_path)], cwd=ROOT, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
