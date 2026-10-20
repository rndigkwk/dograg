"""Add the production search's top 3 (SEARCH_BACKEND=supabase) to the saved relevance sets.

    uv run python scripts/add_supabase_rankings.py      # needs SUPABASE_DB_URL in .env; no model calls

The sets (scripts/relevance_set.py) grade the candidate pools of the local search (Chroma + Kiwi
BM25), but the app searches Supabase (pgvector + PGroonga), which ranks differently. This stores
each question's production ranking as rankings["supabase"], so a reranker or any other change is
compared with what guardians get (notebooks/rerank_colab.ipynb). A training question's own document
and same-question documents are left out, as relevance_set.py does for --train sets.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

SETS = {  # file -> (question rows, training rows)
    "health_relevance_100.json": ("df_val.csv", False),
    "health_relevance_dental.json": ("df_val.csv", False),
    "health_relevance_train_etc.json": ("df.csv", True),
    "health_relevance_train_labeled.json": ("df.csv", True),
}
TOP = 12  # enough for a reranker over the production list, too


def main() -> int:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ["SEARCH_BACKEND"] = "supabase"
    import pandas as pd
    import relevance_set

    from src import resources
    from src.hybrid_retrieval import retrieve_hybrid

    if resources.search_backend() != "supabase":
        print("SUPABASE_DB_URL is not set", file=sys.stderr)
        return 1
    db, index = resources.load_vector_db(), resources.load_health_bm25_index()
    corpus = pd.read_csv(PROJECT_DIR / "data" / "df.csv").fillna("")
    for name, (source, training) in SETS.items():
        path = PROJECT_DIR / "tests" / "data" / name
        saved = json.loads(path.read_text(encoding="utf-8"))
        rows = corpus if source == "df.csv" else pd.read_csv(PROJECT_DIR / "data" / source).fillna("")
        for item in saved["items"]:
            question = str(rows.loc[item["row"], "qa.input"])
            skip = relevance_set.same_question(rows, item["row"]) if training else set()
            found = retrieve_hybrid(db, index, question, top_k=TOP + len(skip))
            item["rankings"]["supabase"] = [str(doc.id) for doc in found if str(doc.id) not in skip][:TOP]
        if resources.load_search_breaker().failures:
            print("the database failed during the run; nothing saved", file=sys.stderr)
            return 1
        path.write_text(json.dumps(saved, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        judged = relevance_set.metrics(saved["items"], lambda item: item["rankings"]["supabase"])
        print(name, judged)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
