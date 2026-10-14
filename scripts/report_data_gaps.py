"""What the material did not cover, as collected on the deployments (src/data_gaps.py).

    uv run --with "psycopg[binary]" python scripts/report_data_gaps.py [--days 30] [--top 30]

Reads ragdog_data_gaps on SUPABASE_DB_URL: rows per route and kind (missing / abstained) and the
words that recur in the gap sentences (Hangul and Latin words, without the words every gap sentence
has), with a few sentences for each, so the most asked-about missing topics show first. Decide
from this what to add to the material (a source, a fact sheet), then measure it as usual.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
STOP_WORDS = {"검색된", "자료에는", "자료에", "자료에서는", "없습니다", "없고", "나와", "있지", "않습니다", "내용은", "내용이",
              "정보는", "정보가", "대한", "관한", "구체적인", "또는", "그리고", "다만", "기준은", "방법은", "여부는", "경우의"}
WORD = re.compile(r"[가-힣A-Za-z]{2,}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--top", type=int, default=30)
    args = parser.parse_args()
    import psycopg
    from dotenv import dotenv_values

    url = dotenv_values(PROJECT_DIR / ".env").get("SUPABASE_DB_URL")
    if not url:
        print("SUPABASE_DB_URL is not set in .env")
        return 1
    with psycopg.connect(url) as conn:
        rows = conn.execute("select route, kind, sentence from ragdog_data_gaps "
                            "where created_at > now() - make_interval(days => %s)", [args.days]).fetchall()
    sys.stdout.reconfigure(errors="replace")
    print(f"last {args.days} days: {len(rows)} rows")
    for (route, kind), count in sorted(Counter((r, k) for r, k, _ in rows).items()):
        print(f"  {route} {kind}: {count}")
    examples: dict[str, list[str]] = defaultdict(list)
    words: Counter = Counter()
    for _, _, sentence in rows:
        if not sentence:
            continue
        seen = {word for word in WORD.findall(sentence) if word not in STOP_WORDS}
        words.update(seen)
        for word in seen:
            if len(examples[word]) < 3:
                examples[word].append(sentence)
    print(f"\nmost frequent words in gap sentences (top {args.top}):")
    for word, count in words.most_common(args.top):
        print(f"- {word} ({count})")
        for sentence in examples[word]:
            print(f"    · {sentence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
