"""Create the `visit_prep` schema that keeps visit-prep runs between API requests (src/visit_prep_store.py).

    uv run python scripts/setup_visit_prep_store.py          # once, with the admin SUPABASE_DB_URL in .env
    uv run python scripts/setup_visit_prep_store.py --check  # what exists and who may use it

Makes, idempotently:
- schema visit_prep, with LangGraph's PostgresSaver tables (its own migrations, run here as admin);
- visit_prep.paused (thread_id, owner hash, pending json, paused_at) and
  visit_prep.report_starts (owner hash, at): hashes and times, plus the paused consultation for at
  most 30 minutes;
- row level security on every table, nothing for anon/authenticated (the public REST API does not
  even expose the schema), and the app role ragdog_app allowed to read and write them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import settings  # noqa: E402
from src.visit_prep_store import SCHEMA  # noqa: E402

OWN_TABLES = """
create table if not exists paused (
    thread_id text primary key check (thread_id ~ '^[0-9a-f]{32}$'),
    owner text not null,
    pending jsonb not null,
    paused_at timestamptz not null default now()
);
create table if not exists report_starts (
    id bigint generated always as identity primary key,
    owner text not null,
    at timestamptz not null default now()
);
create index if not exists report_starts_owner_at on report_starts (owner, at);
"""


def check(conn, schema: str = SCHEMA) -> None:
    rows = conn.execute("""select c.relname, c.relrowsecurity,
                                  has_table_privilege('ragdog_app', c.oid, 'select,insert,update,delete') as app,
                                  has_table_privilege('anon', c.oid, 'select') as anon,
                                  has_table_privilege('authenticated', c.oid, 'select') as authenticated
                           from pg_class c join pg_namespace n on n.oid = c.relnamespace
                           where n.nspname = %s and c.relkind = 'r' order by 1""", [schema]).fetchall()
    for row in rows:
        print(row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--schema", default=SCHEMA, help="another schema name, for scripts/check_visit_prep_store.py")
    args = parser.parse_args(argv)
    return setup(settings.get_setting("SUPABASE_DB_URL"), args.schema, check_only=args.check)


def setup(url: str, schema: str = SCHEMA, *, check_only: bool = False) -> int:
    with psycopg.connect(url, autocommit=True, row_factory=dict_row, prepare_threshold=None,
                         options=f"-c search_path={schema}") as conn:
        if not check_only:
            from langgraph.checkpoint.postgres import PostgresSaver

            conn.execute(f"create schema if not exists {schema}")
            PostgresSaver(conn).setup()  # LangGraph's tables, in visit_prep (first on the search path)
            conn.execute(OWN_TABLES)
            tables = [r["relname"] for r in conn.execute(
                "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = %s and c.relkind = 'r'",
                [schema]).fetchall()]
            conn.execute(f"revoke all on schema {schema} from public, anon, authenticated")
            conn.execute(f"grant usage on schema {schema} to ragdog_app")
            for table in tables:
                conn.execute(f"alter table {schema}.{table} enable row level security")
                conn.execute(f"revoke all on {schema}.{table} from public, anon, authenticated")
                conn.execute(f"grant select, insert, update, delete on {schema}.{table} to ragdog_app")
                conn.execute(f"drop policy if exists ragdog_app_all on {schema}.{table}")
                conn.execute(f"create policy ragdog_app_all on {schema}.{table} for all to ragdog_app using (true) with check (true)")
            conn.execute(f"grant usage on all sequences in schema {schema} to ragdog_app")
            print("set up:", ", ".join(sorted(tables)))
        check(conn, schema)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
