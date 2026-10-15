"""Which kinds of question do the evaluation sets cover, and where is a kind held up by one question?

    uv run python scripts/eval_coverage.py              # the tables, as Markdown
    uv run python scripts/eval_coverage.py --gaps       # also: topics the deployments found missing

Day 60 (lesson 02, 7-1): count the questions per kind; a kind with one question or none rests on
how that one question is worded, so it is the next place to add questions. Three views:

1. Each evaluation set by its own kind field (group, kind, category, route): kinds with <= 1
   question, and which sets run by themselves (weekly regression, PR quality check).
2. Health questions by department of the material: the share of the corpus (data/df.csv) against
   the number of health questions in the sets that use consultation rows. A department with many
   documents and almost no questions is a blind spot of the health numbers.
3. With --gaps: the words that recur in what the deployed answers said was missing
   (ragdog_data_gaps, src/data_gaps.py) and how many evaluation questions mention each.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
DATA = PROJECT_DIR / "tests" / "data"
THIN = 1
KIND_FIELDS = ("group", "kind", "category", "route", "part")
# set file -> how it runs. Weekly: .github/workflows/regression-eval.yml; PR: pr-quality.yml.
AUTOMATED = {
    "crag_eval_questions.json": "주간·PR",
    "place_routing_questions.json": "주간·PR",
    "visit_prep_consultations.json": "주간",
    "health_relevance_100.json": "주간(답변 정확도)",
}
NOT_QUESTIONS = {"judge_validation.json", "region_names.json"}


def items_of(data) -> list[dict]:
    if isinstance(data, list):
        return data
    return data.get("items") or []


def kind_of(name: str, item: dict) -> str:
    if name == "place_routing_questions.json":
        return f"{item['route']}/{item.get('kind') or '-'}"
    if name == "health_relevance_100.json":
        return eval_labels(item).get("meta.department", "?")
    for field in KIND_FIELDS:
        if item.get(field):
            return str(item[field])
    return "(구분 없음)"


def eval_labels(item: dict) -> dict:
    labels = item.get("gold_labels") or item.get("meta") or {}
    return labels if isinstance(labels, dict) else {}


def load_sets() -> dict[str, list[dict]]:
    return {path.name: items_of(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(DATA.glob("*.json")) if path.name not in NOT_QUESTIONS}


def set_table(sets: dict[str, list[dict]]) -> list[str]:
    lines = ["| 평가 세트 | 실행 | 질문 수 | 구분 수 | 1개 이하인 구분 |", "| --- | --- | ---: | ---: | --- |"]
    for name, items in sets.items():
        counts = Counter(kind_of(name, item) for item in items)
        thin = sorted(kind for kind, n in counts.items() if n <= THIN)
        lines.append(f"| {name.removesuffix('.json')} | {AUTOMATED.get(name, '수동')} | {len(items)} | {len(counts)} | "
                     f"{', '.join(thin) if thin else '-'} |")
    return lines


def automated_detail(sets: dict[str, list[dict]]) -> list[str]:
    lines = []
    for name in AUTOMATED:
        counts = Counter(kind_of(name, item) for item in sets.get(name, []))
        cells = ", ".join(f"{kind} {n}" + (" ⚠" if n <= THIN else "") for kind, n in counts.most_common())
        lines.append(f"- **{name.removesuffix('.json')}** ({AUTOMATED[name]}): {cells}")
    return lines


def department_table(sets: dict[str, list[dict]]) -> list[str]:
    import pandas as pd

    corpus = pd.read_csv(PROJECT_DIR / "data" / "df.csv", usecols=["meta.department"])["meta.department"].str.strip().value_counts()
    questions: Counter = Counter()
    for items in sets.values():
        for item in items:
            department = str(eval_labels(item).get("meta.department") or "").strip()
            if department:
                questions[department] += 1
    total = corpus.sum()
    lines = ["| 진료과 | 자료 문서 | 자료 비율 | 평가 질문 | 질문 1개당 문서 |", "| --- | ---: | ---: | ---: | ---: |"]
    for department, docs in corpus.items():
        n = questions.get(department, 0)
        per = f"{docs // n:,}" if n else "질문 없음"
        lines.append(f"| {department} | {docs:,} | {docs / total:.0%} | {n}{' ⚠' if n <= THIN else ''} | {per} |")
    return lines


def gap_table(sets: dict[str, list[dict]], top: int) -> list[str]:
    import psycopg
    from dotenv import dotenv_values

    from report_data_gaps import STOP_WORDS, WORD

    url = dotenv_values(PROJECT_DIR / ".env").get("SUPABASE_DB_URL")
    if not url:
        return ["SUPABASE_DB_URL이 없어 건너뜀"]
    with psycopg.connect(url) as conn:
        rows = conn.execute("select sentence from ragdog_data_gaps where sentence is not null").fetchall()
    words: Counter = Counter()
    for (sentence,) in rows:
        words.update({w for w in WORD.findall(sentence) if w not in STOP_WORDS})
    texts = [json.dumps(item, ensure_ascii=False) for items in sets.values() for item in items]
    lines = [f"모인 빈칸 문장 {len(rows)}개", "", "| 낱말 | 빈칸 문장 | 이 낱말이 든 평가 질문 |", "| --- | ---: | ---: |"]
    for word, count in words.most_common(top):
        stem = re.escape(word[:2])
        lines.append(f"| {word} | {count} | {sum(bool(re.search(stem, t)) for t in texts)} |")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gaps", action="store_true")
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args()
    sys.path.insert(0, str(PROJECT_DIR / "scripts"))
    sys.stdout.reconfigure(encoding="utf-8")
    sets = load_sets()
    print("## 1. 세트별 구분\n")
    print("\n".join(set_table(sets)))
    print("\n자동 실행 세트의 구분별 질문 수 (⚠ = 1개 이하):\n")
    print("\n".join(automated_detail(sets)))
    print("\n## 2. 건강 질문의 진료과\n")
    print("\n".join(department_table(sets)))
    if args.gaps:
        print("\n## 3. 배포 앱이 찾은 자료 빈칸\n")
        print("\n".join(gap_table(sets, args.top)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
