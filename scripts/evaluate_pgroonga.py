"""Can PGroonga on Supabase replace the in-app Kiwi BM25? (keyword search quality and time)

    uv run --with "psycopg[binary]" python scripts/evaluate_pgroonga.py [--keep]

The app's keyword search is BM25 over Kiwi nouns in memory (about 320 MB with Kiwi). Moving it to
Postgres would free that memory. Supabase has PGroonga (no Korean morphological dictionary, so it
indexes character n-grams). The 19,206 health consultation questions (id + text) and the 1,193
report chunks go into tables with a PGroonga index on SUPABASE_DB_URL; two query styles:
- or:      the question's words joined with OR (Groonga query syntax), ranked by pgroonga_score
- similar: PGroonga similar search (&@*), the closest to BM25's term weighting
Health: useful@3 on the 220 judged questions (short 120, long 100) for the keyword search alone and
for the app's hybrid (the app's Dense, 12 candidates each, RRF), against the Kiwi BM25 runs.
Top-3 documents never graded are graded by the same judge and added to the grade file.
Reports: the gold page in the top 6 of the hybrid (as the app answers) for the 18 report questions
of tests/data/crag_eval_questions.json. Also the time per keyword query from this PC.
The tables are dropped afterwards unless --keep. Results: output/experiments/pgroonga.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

GRADES = PROJECT_DIR / "output" / "experiments" / "finetuned_embedding_grades.json"
HEALTH_TABLE, REPORT_TABLE = "ragdog_health_text_eval", "ragdog_report_text_eval"
CANDIDATES, REPORT_CANDIDATES, REPORT_TOP = 12, 20, 6
STYLES = ("or", "similar")
WORD = re.compile(r"[0-9A-Za-z가-힣]{2,}")


def or_query(question: str) -> str:
    words = list(dict.fromkeys(WORD.findall(question)))[:32]
    return " OR ".join(words) if words else question


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    import psycopg
    from dotenv import dotenv_values

    from evaluate_strategy_by_type import mcnemar
    from relevance_set import judge, judge_model
    from src import resources
    from src.health_answers import attach_health_answers
    from src.hybrid_retrieval import reciprocal_rank_fusion
    from src.tools import report

    with open(PROJECT_DIR / "data" / "df_val.csv", encoding="utf-8", newline="") as f:
        val = list(csv.DictReader(f))
    relevance = json.loads((PROJECT_DIR / "tests" / "data" / "health_relevance_100.json").read_text(encoding="utf-8"))["items"]
    short = json.loads((PROJECT_DIR / "tests" / "data" / "emergency_signs.json").read_text(encoding="utf-8"))["items"]
    sets = {"short": ([i["question"] for i in short], [{} for _ in short]),
            "long_useful": ([val[int(i["row"])]["qa.input"] for i in relevance], [i["grades"] for i in relevance])}
    report_items = [i for i in json.loads((PROJECT_DIR / "tests" / "data" / "crag_eval_questions.json").read_text(encoding="utf-8"))["items"]
                    if i["group"] == "report_answerable" and i.get("gold_pages")]
    extra = json.loads(GRADES.read_text(encoding="utf-8")) if GRADES.exists() else {}
    url = dotenv_values(PROJECT_DIR / ".env")["SUPABASE_DB_URL"]
    result: dict = {}
    with tempfile.TemporaryDirectory(prefix="ragdog-pgroonga-", ignore_cleanup_errors=True) as directory, \
            psycopg.connect(url, autocommit=True) as conn:
        resources.CHROMA_DIR = Path(directory) / "chroma_db"
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", resources.CHROMA_DIR)
        db, bm25 = resources.load_vector_db(), resources.load_health_bm25_index()
        report_db, report_bm25 = resources.load_report_vector_db(), resources.load_report_bm25_index()
        by_id = {d.id: d for d in bm25.documents}
        report_by_id = {d.id: d for d in report_bm25.documents}

        conn.execute("create extension if not exists pgroonga")
        started = time.perf_counter()
        for table, docs in ((HEALTH_TABLE, bm25.documents), (REPORT_TABLE, report_bm25.documents)):
            conn.execute(f"drop table if exists {table}")
            conn.execute(f"create table {table} (id text primary key, body text)")
            with conn.cursor().copy(f"copy {table} (id, body) from stdin") as copy:
                for d in docs:
                    copy.write_row((d.id, d.page_content))
            conn.execute(f"create index on {table} using pgroonga (body)")
        result["upload_and_index_s"] = round(time.perf_counter() - started, 1)
        result["storage_mb"] = {t: round(conn.execute(f"select pg_total_relation_size('{t}')").fetchone()[0] / 2**20, 1)
                                for t in (HEALTH_TABLE, REPORT_TABLE)}

        def keyword(table, question, k, style):
            if style == "or":
                sql = (f"select id from {table} where body &@~ %s "
                       f"order by pgroonga_score(tableoid, ctid) desc limit {k}")
                params = (or_query(question),)
            else:
                sql = (f"select id from {table} where body &@* %s "
                       f"order by pgroonga_score(tableoid, ctid) desc limit {k}")
                params = (question,)
            return [row[0] for row in conn.execute(sql, params)]

        seconds = {s: [] for s in STYLES}
        tops: dict = {}
        for set_name, (questions, _) in sets.items():
            tops[set_name] = []
            for question in questions:
                dense = db.similarity_search(question, k=CANDIDATES)
                row = {"kiwi": bm25.search(question, CANDIDATES)}
                for style in STYLES:
                    started = time.perf_counter()
                    row[style] = [by_id[i] for i in keyword(HEALTH_TABLE, question, CANDIDATES, style) if i in by_id]
                    seconds[style].append(time.perf_counter() - started)
                tops[set_name].append({**{f"{n} only": row[n][:3] for n in ("kiwi", *STYLES)},
                                       **{f"hybrid {n}": reciprocal_rank_fusion([dense, row[n]], top_k=3) for n in ("kiwi", *STYLES)}})
        result["keyword_query_ms_p50"] = {s: round(statistics.median(v) * 1000, 1) for s, v in seconds.items()}

        model, answers = judge_model(), resources.load_health_answer_table()
        hits: dict = {}
        for set_name, (questions, saved) in sets.items():
            jobs = []
            for i, question in enumerate(questions):
                known = {**saved[i], **extra.get(f"{set_name}:{i}", {})}
                missing = {d.id: d for docs in tops[set_name][i].values() for d in docs if d.id not in known}
                if missing:
                    jobs.append((i, question, attach_health_answers(list(missing.values()), answers)))
            print(f"{set_name}: grading {sum(len(j[2]) for j in jobs)} new documents", flush=True)
            with ThreadPoolExecutor(8) as pool:
                for (i, _, _), grades in zip(jobs, pool.map(lambda job: judge(model, job[1], job[2]), jobs)):
                    extra.setdefault(f"{set_name}:{i}", {}).update(grades)
            GRADES.write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
            for i in range(len(questions)):
                grades = {**saved[i], **extra.get(f"{set_name}:{i}", {})}
                for name, docs in tops[set_name][i].items():
                    hits.setdefault(name, []).append(any(grades.get(d.id) == 2 for d in docs))
        result["health_useful@3"] = {name: round(sum(v) / len(v), 3) for name, v in hits.items()}
        result["health_vs_kiwi_p"] = {name: round(mcnemar(hits["hybrid kiwi"] if name.startswith("hybrid") else hits["kiwi only"], v), 3)
                                      for name, v in hits.items() if "kiwi" not in name}

        def gold_hit(item, docs):
            gold = {(name, page) for name, page in item["gold_pages"]}
            return bool(gold & {(Path(d.metadata.get("source", "")).name, d.metadata.get("page")) for d in docs})

        report_hits: dict = {}
        for item in report_items:
            dense = report_db.similarity_search(item["question"], k=REPORT_CANDIDATES)
            runs = {"kiwi": report_bm25.search(item["question"], REPORT_CANDIDATES)}
            for style in STYLES:
                runs[style] = [report_by_id[i] for i in keyword(REPORT_TABLE, item["question"], REPORT_CANDIDATES, style) if i in report_by_id]
            for name, lexical in runs.items():
                report_hits.setdefault(name, []).append(gold_hit(item, reciprocal_rank_fusion([dense, lexical], top_k=REPORT_TOP)))
        result["report_gold_page_top6_hybrid"] = {name: f"{sum(v)}/{len(v)}" for name, v in report_hits.items()}
        if not args.keep:
            conn.execute(f"drop table if exists {HEALTH_TABLE}")
            conn.execute(f"drop table if exists {REPORT_TABLE}")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    (PROJECT_DIR / "output" / "experiments" / "pgroonga.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
