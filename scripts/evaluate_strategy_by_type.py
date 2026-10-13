"""Is a different search strategy per question type worth a router? (Day 58 lesson 02, section 3-3)

    uv run python scripts/evaluate_strategy_by_type.py

The app searches every health question one way: Dense + BM25 merged by RRF (ADR-0002). This
measures Dense only, BM25 only and the hybrid, each as the app runs it (fine-tuned int8 model,
Chroma, BM25 over Kiwi nouns, 12 candidates each, top 3 shown), on two judged sets:
- short: the 120 short guardian questions of tests/data/emergency_signs.json
- long: the 100 consultations of tests/data/health_relevance_100.json
Types are fixed before measuring: length (short / long) x whether the question names a disease,
medicine, test or procedure (NAMED_TERMS, written before the results were seen).
Metric: useful@3 (a grade-2 document in the top 3). Grades come from the earlier judged files
plus output/experiments/finetuned_embedding_grades.json; top-3 documents never graded are graded
now by the same judge (scripts/relevance_set.py) and added to that file.
"Per type" = the best strategy for each type, i.e. a router that never mistakes a type (upper bound).
Results: output/experiments/strategy_by_type.json.
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from math import comb
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

GRADES = PROJECT_DIR / "output" / "experiments" / "finetuned_embedding_grades.json"
CANDIDATES = 12
STRATEGIES = ("dense", "bm25", "hybrid")
# Disease, medicine, test and procedure names. "암" and "옴" are left out: they are parts of other
# words (암컷, 옮겨). Written before measuring.
NAMED_TERMS = (
    "심장사상충", "파보", "홍역", "디스템퍼", "코로나", "켄넬", "췌장염", "신부전", "당뇨", "쿠싱", "갑상선",
    "간염", "간수치", "슬개골", "탈구", "디스크", "고관절", "백내장", "녹내장", "결막염", "각막", "외이염",
    "피부염", "아토피", "습진", "농피", "곰팡이", "링웜", "모낭충", "진드기", "벼룩", "회충", "구충",
    "기생충", "종양", "자궁축농증", "방광염", "결석", "장염", "위염", "폐렴", "기관지", "기관허탈",
    "심장병", "심부전", "폐수종", "빈혈", "황달", "뇌수두증", "간질", "치주염", "치석", "탈장",
    "중성화", "예방접종", "백신", "광견병", "항생제", "스테로이드", "소염제", "진통제", "타이레놀",
    "아세트아미노펜", "이부프로펜", "아스피린", "아포퀠", "넥스가드", "하트가드", "레볼루션", "브라벡토",
    "이뇨제", "인슐린", "엑스레이", "초음파", "혈액검사", "CT", "MRI", "수술", "마취", "스케일링",
)


def named(question: str) -> bool:
    return any(term in question for term in NAMED_TERMS)


def mcnemar(a: list[bool], b: list[bool]) -> float:
    only_a = sum(x and not y for x, y in zip(a, b))
    only_b = sum(y and not x for x, y in zip(a, b))
    n = only_a + only_b
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, k) for k in range(min(only_a, only_b) + 1)) / 2**n)


def main() -> int:
    from relevance_set import judge, judge_model

    from src import resources
    from src.health_answers import attach_health_answers
    from src.hybrid_retrieval import reciprocal_rank_fusion

    with open(PROJECT_DIR / "data" / "df_val.csv", encoding="utf-8", newline="") as f:
        val = list(csv.DictReader(f))
    relevance = json.loads((PROJECT_DIR / "tests" / "data" / "health_relevance_100.json").read_text(encoding="utf-8"))["items"]
    short = json.loads((PROJECT_DIR / "tests" / "data" / "emergency_signs.json").read_text(encoding="utf-8"))["items"]
    sets = {
        "short": ([item["question"] for item in short], [{} for _ in short]),
        "long_useful": ([val[int(item["row"])]["qa.input"] for item in relevance], [item["grades"] for item in relevance]),
    }
    extra = json.loads(GRADES.read_text(encoding="utf-8")) if GRADES.exists() else {}
    answers = resources.load_health_answer_table()
    rows = []
    with tempfile.TemporaryDirectory(prefix="ragdog-types-", ignore_cleanup_errors=True) as directory:
        resources.CHROMA_DIR = Path(directory) / "chroma_db"
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", resources.CHROMA_DIR)
        db, bm25 = resources.load_vector_db(), resources.load_health_bm25_index()
        model = judge_model()
        for set_name, (questions, saved) in sets.items():
            tops = []
            for question in questions:
                dense = db.similarity_search(question, k=CANDIDATES)
                lexical = bm25.search(question, CANDIDATES)
                tops.append({"dense": dense[:3], "bm25": lexical[:3],
                             "hybrid": reciprocal_rank_fusion([dense, lexical], top_k=3)})
            jobs = []
            for i, question in enumerate(questions):
                known = {**saved[i], **extra.get(f"{set_name}:{i}", {})}
                missing = {d.id: d for s in STRATEGIES for d in tops[i][s] if d.id not in known}
                if missing:
                    docs = attach_health_answers(list(missing.values()), answers)
                    jobs.append((i, question, docs))
            print(f"{set_name}: grading {sum(len(j[2]) for j in jobs)} new documents for {len(jobs)} questions", flush=True)
            with ThreadPoolExecutor(8) as pool:
                for (i, _, _), grades in zip(jobs, pool.map(lambda job: judge(model, job[1], job[2]), jobs)):
                    extra.setdefault(f"{set_name}:{i}", {}).update(grades)
            GRADES.write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
            for i, question in enumerate(questions):
                grades = {**saved[i], **extra.get(f"{set_name}:{i}", {})}
                row = {"set": set_name, "i": i, "type": f"{'짧은' if set_name == 'short' else '긴'}·{'이름 있음' if named(question) else '이름 없음'}"}
                for s in STRATEGIES:
                    row[s] = any(grades.get(d.id) == 2 for d in tops[i][s])
                rows.append(row)

    types = sorted({r["type"] for r in rows})
    table = {t: {"questions": sum(r["type"] == t for r in rows),
                 **{s: round(sum(r[s] for r in rows if r["type"] == t) / sum(r["type"] == t for r in rows), 3) for s in STRATEGIES}}
             for t in types}
    best = {t: max(STRATEGIES, key=lambda s: (table[t][s], s == "hybrid")) for t in types}  # ties go to hybrid
    routed = [r[best[r["type"]]] for r in rows]
    overall = {s: round(sum(r[s] for r in rows) / len(rows), 3) for s in STRATEGIES}
    overall["per_type"] = round(sum(routed) / len(rows), 3)
    report = {"table": table, "best_per_type": best, "overall": overall,
              "per_type_vs_hybrid_p": round(mcnemar([r["hybrid"] for r in rows], routed), 3),
              "gain_questions": sum(x and not r["hybrid"] for x, r in zip(routed, rows)),
              "loss_questions": sum(r["hybrid"] and not x for x, r in zip(routed, rows))}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    out = PROJECT_DIR / "output" / "experiments" / "strategy_by_type.json"
    out.write_text(json.dumps({**report, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
