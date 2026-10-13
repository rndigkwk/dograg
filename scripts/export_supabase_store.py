"""Fill the Supabase tables for src/supabase_store.py from the exact store's files (ADR-0003 alternative).

    uv run python scripts/export_vector_store.py            # once: data/vector_store from Chroma
    uv run --with "psycopg[binary]" python scripts/export_supabase_store.py [--drop | --to-halfvec]

Tables ragdog_health and ragdog_report on SUPABASE_DB_URL: id, body (the text), metadata (jsonb),
embedding (pgvector halfvec, float16), with HNSW and PGroonga indexes. Consultation text goes into
the database; it is the project owner's private Supabase project. --drop removes the tables instead;
--to-halfvec converts tables made as float32 (vector) in place (docs/adr/0007).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

TABLES = {"health": "ragdog_health", "report": "ragdog_report"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drop", action="store_true")
    parser.add_argument("--to-halfvec", action="store_true")
    args = parser.parse_args()
    from dotenv import dotenv_values

    from src.supabase_store import connector, create_tables, load_rows, to_halfvec
    from src.vector_store import ExactVectorStore

    conn = connector(dotenv_values(PROJECT_DIR / ".env")["SUPABASE_DB_URL"])()
    def database_mb() -> float:
        return conn.execute("select pg_database_size(current_database())").fetchone()[0] / 1e6

    with conn:
        conn.execute("set statement_timeout = 0")  # index builds take longer than the app's limit
        for name, table in TABLES.items():
            if args.to_halfvec:
                started = time.perf_counter()
                changed = to_halfvec(conn, table)
                size = conn.execute(f"select pg_total_relation_size('{table}')").fetchone()[0]
                print(f"{table}: {'converted' if changed else 'already halfvec'}, {size / 1e6:.1f} MB, "
                      f"database {database_mb():.1f} MB, {time.perf_counter() - started:.0f}s")
                continue
            if args.drop:
                conn.execute(f"drop table if exists {table}")
                print("dropped", table)
                continue
            store = ExactVectorStore.load(PROJECT_DIR / "data" / "vector_store" / name, embeddings=None)
            started = time.perf_counter()
            create_tables(conn, table, store.vectors.shape[1])
            load_rows(conn, table, store.ids, store.texts, store.metadatas, store.vectors)
            size = conn.execute(f"select pg_total_relation_size('{table}')").fetchone()[0]
            print(f"{table}: {len(store.ids)} rows, {size / 2**20:.1f} MB, {time.perf_counter() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
