"""Check the signed-in users' tables and account deletion (scripts/sql/user_records.sql,
delete_my_account.sql, user_notes.sql) with their tests.

    uv run python scripts/check_user_records.py            # tables applied: run the test only
    uv run python scripts/check_user_records.py --dry-run  # create the tables and test them, then roll back

Uses SUPABASE_DB_URL (the admin connection in .env). Everything the test writes is rolled back; it
prints "all passed" and the number of checks, or the names of the checks that failed (exit 1).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import settings  # noqa: E402

SQL_DIR = Path(__file__).resolve().parent / "sql"


def statements(name: str) -> str:
    """The file without its own begin/commit/rollback: this script owns the transaction."""
    return re.sub(r"^(begin|commit|rollback);\s*$", "", (SQL_DIR / name).read_text(encoding="utf-8"), flags=re.M)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="create the tables and functions inside the rolled-back transaction")
    args = parser.parse_args(argv)
    failed = False
    # Each pair: what to apply in a dry run, its test, and the object that shows it was applied.
    pairs = (("user_records.sql", "user_records_test.sql", "select to_regclass('public.ragdog_user_threads')::text"),
             ("delete_my_account.sql", "delete_my_account_test.sql", "select to_regprocedure('public.delete_my_account()')::text"),
             ("user_notes.sql", "user_notes_test.sql", "select to_regclass('public.ragdog_user_notes')::text"))
    for applied, test, exists in pairs:
        with psycopg.connect(settings.get_setting("SUPABASE_DB_URL"), autocommit=False) as conn:
            try:
                if args.dry_run:
                    conn.execute(statements("user_records.sql"))
                    if applied != "user_records.sql":
                        conn.execute(statements(applied))
                elif conn.execute(exists).fetchone()[0] is None:
                    print(f"{applied}가 아직 적용되지 않았습니다. 먼저 적용하거나 --dry-run으로 확인하세요.")
                    failed = True
                    continue
                setup, report = statements(test).rsplit("select case", 1)
                conn.execute(setup)
                result, checks = conn.execute("select case" + report).fetchone()
            finally:
                conn.rollback()
        print(f"{test}: {result} ({checks} checks)")
        failed |= result != "all passed"
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
