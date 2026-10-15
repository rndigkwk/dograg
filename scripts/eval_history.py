"""Every weekly regression and deployed-app check, kept in Supabase so the trend can be read.

The results used to live only in the GitHub job summaries and Langfuse (the free plan keeps
data for a limited time); output/ of a CI run is gone when the job ends. The checks now add a row
each to ragdog_eval_history (closed to the public REST API like every RagDog table):

- regression (scripts/check_regression.py): one row per set with its run scores and judge model
- deploy (scripts/check_deployed_app.py): one row per deployment: seconds to the first page, to
  the date and the health answer, the deployed commit, the problems
- database (scripts/check_supabase_search.py): documents, database size, index use

Only when the workflow asks for it (RECORD_FLAG=1, plus SUPABASE_DB_URL). The database URL alone
is not enough: src/settings.py loads it from .env into the environment, and on 2026-10-15 the unit
tests of check_regression.py wrote their made-up scores into the table that way. Local runs, tests
and the PR quality check record nothing. A failed insert never fails the check.

    uv run --with "psycopg[binary]" python scripts/eval_history.py [--days 60] [--kind deploy]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
TABLE = "ragdog_eval_history"
RECORD_FLAG = "RAGDOG_EVAL_HISTORY"
# Same statements as src/supabase_store.lock_from_data_api (that module needs langchain; these
# scripts run with psycopg only). tests/test_eval_history.py keeps the two the same.
LOCK = (f"alter table {TABLE} enable row level security", f"revoke all on {TABLE} from anon, authenticated")
CREATE = f"""create table if not exists {TABLE} (
    id bigint generated always as identity primary key,
    created_at timestamptz not null default now(),
    kind text not null, target text not null, run text, commit text,
    ok boolean not null, metrics jsonb not null default '{{}}')"""


def record(kind: str, target: str, ok: bool, metrics: dict, run: str | None = None,
           commit: str | None = None) -> bool:
    """Add one row; False (with a note) when there is no database or the insert fails."""
    url = os.environ.get("SUPABASE_DB_URL")
    if not url or os.environ.get(RECORD_FLAG) != "1":
        return False
    try:
        import psycopg

        with psycopg.connect(url, autocommit=True, connect_timeout=10) as conn:
            conn.execute(CREATE)
            for statement in LOCK:
                conn.execute(statement)
            conn.execute(f"insert into {TABLE} (kind, target, run, commit, ok, metrics) values (%s, %s, %s, %s, %s, %s)",
                         [kind, target, run, commit or os.environ.get("GITHUB_SHA"), ok,
                          json.dumps(metrics, ensure_ascii=False, default=str)])
        return True
    except Exception as error:  # noqa: BLE001 - the history must never fail the check it records
        print(f"history not recorded: {type(error).__name__}", flush=True)
        return False


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:.3f}" if abs(value) < 10 else f"{value:.0f}"
    if isinstance(value, list):
        return f"{len(value)}건" if value else "-"
    return "-" if value is None else str(value)


def show(days: int, kind: str | None) -> None:
    import psycopg
    from dotenv import dotenv_values

    url = os.environ.get("SUPABASE_DB_URL") or dotenv_values(PROJECT_DIR / ".env").get("SUPABASE_DB_URL")
    if not url:
        print("SUPABASE_DB_URL is not set")
        return
    query = (f"select created_at, kind, target, run, commit, ok, metrics from {TABLE} "
             "where created_at > now() - make_interval(days => %s)" + (" and kind = %s" if kind else "")
             + " order by kind, target, created_at")
    with psycopg.connect(url) as conn:
        rows = conn.execute(query, [days, kind] if kind else [days]).fetchall()
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"last {days} days: {len(rows)} rows")
    groups: dict[tuple[str, str], list] = {}
    for row in rows:
        groups.setdefault((row[1], row[2]), []).append(row)
    for (group_kind, target), items in groups.items():
        names = sorted({name for item in items for name in item[6]})
        print(f"\n## {group_kind} · {target}\n")
        print("| 시각 (UTC) | 커밋 | 결과 | " + " | ".join(names) + " |")
        print("| --- | --- | --- | " + " | ".join("---:" for _ in names) + " |")
        for created, _, _, _, commit, ok, metrics in items:
            print(f"| {created:%m-%d %H:%M} | {(commit or '-')[:7]} | {'✅' if ok else '❌'} | "
                  + " | ".join(_fmt(metrics.get(name)) for name in names) + " |")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--kind", choices=("regression", "deploy", "database"))
    args = parser.parse_args()
    show(args.days, args.kind)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
