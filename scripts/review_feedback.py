"""Answers guardians marked 👎 and chose to send (src/feedback_store.py): read them, then turn the
ones worth keeping into evaluation candidates (Day 59: grow the golden set from real failures).

    uv run --with "psycopg[binary]" python scripts/review_feedback.py               # counts and rows
    uv run --with "psycopg[binary]" python scripts/review_feedback.py export        # candidates file

show: rows per reason and route, then each row (newest first): reason, route, the masked question
and the start of the answer.
export: output/feedback/candidates.json, one item per row not exported before, in the shape the
evaluation sets use (id, question, route) plus what a person needs to write the expected answer
(the app's answer, the reason, the evidence labels). Nothing is added to tests/data by itself: a
person reads each candidate, writes `expected` (and the reference answer for a health question),
and moves the good ones into the matching set. No model calls.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
OUT = PROJECT_DIR / "output" / "feedback" / "candidates.json"
TABLE = "ragdog_feedback"


def database_url() -> str | None:
    from dotenv import dotenv_values

    return os.environ.get("SUPABASE_DB_URL") or dotenv_values(PROJECT_DIR / ".env").get("SUPABASE_DB_URL")


def load_rows(days: int) -> list[dict]:
    import psycopg

    with psycopg.connect(database_url()) as conn:
        exists = conn.execute("select to_regclass(%s)", [f"public.{TABLE}"]).fetchone()[0]
        if exists is None:
            return []
        rows = conn.execute(f"select id, created_at, trace_id, route, reason, question, answer, evidence from {TABLE} "
                            "where created_at > now() - make_interval(days => %s) order by created_at desc", [days]).fetchall()
    names = ("id", "created_at", "trace_id", "route", "reason", "question", "answer", "evidence")
    return [dict(zip(names, row)) for row in rows]


def show(rows: list[dict]) -> None:
    print(f"{len(rows)} rows")
    for (reason, route), count in Counter((r["reason"] or "이유 없음", r["route"] or "-") for r in rows).most_common():
        print(f"  {reason} · {route}: {count}")
    for row in rows:
        answer = " ".join(str(row["answer"]).split())[:120]
        print(f"\n#{row['id']} {row['created_at']:%Y-%m-%d %H:%M} · {row['reason'] or '이유 없음'} · {row['route']}")
        print(f"  질문: {row['question']}")
        print(f"  답변: {answer}…")


def candidates(rows: list[dict], known: set[str]) -> list[dict]:
    items = []
    for row in rows:
        item_id = f"fb-{row['id']}"
        if item_id in known:
            continue
        items.append({"id": item_id, "question": row["question"], "route": row["route"], "reason": row["reason"],
                      "app_answer": row["answer"], "evidence": row["evidence"] or [], "trace_id": row["trace_id"],
                      "created_at": row["created_at"].isoformat(),
                      "expected": "", "reference": "",
                      "note": "사람이 expected(보류/답변/경로)와, 건강 질문이면 reference(수의사 답 수준의 기준 답변)를 적은 뒤 "
                              "맞는 평가 세트로 옮긴다"})
    return items


def export(rows: list[dict]) -> Path:
    existing = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"items": []}
    known = {item["id"] for item in existing["items"]}
    new = candidates(rows, known)
    existing["items"] = new + existing["items"]
    existing["description"] = ("👎 answers sent with consent (ragdog_feedback), as evaluation candidates. Questions are "
                               "masked as stored. Fill expected/reference, then move the good ones to tests/data.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(existing, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"{len(new)} new candidates, {len(existing['items'])} in {OUT}")
    return OUT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", choices=("show", "export"), default="show")
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if not database_url():
        print("SUPABASE_DB_URL is not set")
        return 1
    rows = load_rows(args.days)
    show(rows) if args.command == "show" else export(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
