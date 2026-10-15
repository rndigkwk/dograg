"""Did the deployments' searches reach Supabase? (keep-alive.yml, after the deployed-app checks)

    SUPABASE_DB_URL=... uv run --with "psycopg[binary]" python scripts/check_supabase_search.py [--minutes 40]

scripts/check_deployed_app.py asks each deployment a health question. On Supabase (docs/adr/0007)
that search uses the HNSW index of ragdog_health, so the index's last use (pg_stat_user_indexes)
must fall within this run. If it is older, the deployments answered from the local fallback, i.e.
Supabase failed for them, and the answer check alone would not show it. The query itself is also
database activity, which keeps the free project from pausing (a few requests a week are enough).
Prints one summary row; never prints the database URL.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

import eval_history

INDEX = "ragdog_health_embedding_idx"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=40, help="how recent the last index use must be")
    args = parser.parse_args()
    import psycopg

    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        print("SUPABASE_DB_URL is not set")
        return 1
    with psycopg.connect(url, autocommit=True, connect_timeout=10) as conn:
        scans, last = conn.execute(
            "select idx_scan, last_idx_scan from pg_stat_user_indexes where indexrelname = %s", [INDEX]).fetchone()
        rows = conn.execute("select count(*) from ragdog_health").fetchone()[0]
        size_mb = conn.execute("select pg_database_size(current_database())").fetchone()[0] / 1e6
    now = datetime.now(timezone.utc)
    age = None if last is None else now - last
    fresh = age is not None and age <= timedelta(minutes=args.minutes)
    age_text = "-" if age is None else f"{age.total_seconds() / 60:.0f}분 전"
    line = (f"| Supabase | 건강 문서 {rows:,}건 | 벡터 색인 마지막 사용 {age_text} (누적 {scans:,}회) | "
            f"DB {size_mb:.0f}MB / 500MB | {'ok' if fresh else 'search did not reach Supabase in this run'} |")
    print(line)
    eval_history.record("database", "supabase", fresh, {"documents": rows, "db_mb": round(size_mb), "index_scans": scans,
                                                        "index_last_use_min": None if age is None else round(age.total_seconds() / 60)})
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as file:
            file.write("| DB | 문서 | 검색 사용 | 용량 | 결과 |\n| --- | --- | --- | --- | --- |\n" + line + "\n")
    return 0 if fresh else 1


if __name__ == "__main__":
    sys.exit(main())
