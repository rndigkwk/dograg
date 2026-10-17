"""Do saved consultation notes help, and do they stay out of the way? (ADR-0009, before turning it on)

    uv run python scripts/evaluate_consultation_notes.py --dry-run   # the cases and the model calls
    uv run python scripts/evaluate_consultation_notes.py

Ten follow-up questions, each with one saved note (src/tools/health.py notes_context):
- related (6): a recurrence or the same problem again; one note is older than 30 days.
- unrelated (4): the note is about something else.
Each question is answered the app's way (src/tools/health.py ask_rag: hybrid search, the health
prompt) with the note and without it, and the judge (scripts/relevance_set.py JUDGE_MODEL) reads each
answer with the note: did it bring the note up where it belongs (and say it is the guardian's record,
an old one as old), and did it state anything about this dog's past that the note does not say?
20 answers + 20 judgments = 40 model calls (scripts/cost_guard.py). Results:
output/experiments/consultation_notes.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel, Field

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

OUT = PROJECT_DIR / "output" / "experiments" / "consultation_notes.json"
TODAY = date(2026, 10, 17)  # fixed, so "older than 30 days" is the same on every run

CASES = [
    {"id": "n1", "related": True, "note": ("2026-10-10", "말티즈 보리 설사 이틀째. 물은 잘 마심. 이틀 넘거나 혈변이면 병원 안내받음."),
     "question": "또 설사를 해요. 어떻게 해야 하나요?"},
    {"id": "n2", "related": True, "note": ("2026-10-05", "귀를 자주 긁음. 귀 세정 방법 안내받음, 냄새가 나면 병원."),
     "question": "귀를 또 긁고 이번엔 냄새도 나요"},
    {"id": "n3", "related": True, "note": ("2026-10-01", "구토 1회 후 하루 금식 안내받고 다음 날 회복."),
     "question": "어제 저녁에 또 토했어요"},
    {"id": "n4", "related": True, "note": ("2026-08-20", "산책 중 뒷다리를 들고 걸음. 슬개골 탈구 가능성, 체중 관리와 병원 검사 안내받음."),
     "question": "계단 오를 때 뒷다리를 들어요"},
    {"id": "n5", "related": True, "note": ("2026-10-12", "배와 겨드랑이에 붉은 발진. 사료를 바꾼 뒤 시작됨."),
     "question": "발진이 다시 생겼어요"},
    {"id": "n6", "related": True, "note": ("2026-10-14", "마른기침 사흘째. 켄넬코프 가능성, 일주일 넘으면 병원 안내받음."),
     "question": "기침이 일주일째 계속돼요"},
    {"id": "n7", "related": False, "note": ("2026-10-10", "말티즈 보리 설사 이틀째. 이틀 넘거나 혈변이면 병원 안내받음."),
     "question": "발톱은 얼마나 자주 깎아야 하나요?"},
    {"id": "n8", "related": False, "note": ("2026-10-05", "귀를 자주 긁음. 귀 세정 방법 안내받음."),
     "question": "강아지 치석 관리는 어떻게 하나요?"},
    {"id": "n9", "related": False, "note": ("2026-10-01", "구토 1회 후 하루 금식 안내받고 다음 날 회복."),
     "question": "산책은 하루에 몇 번 하는 게 좋아요?"},
    {"id": "n10", "related": False, "note": ("2026-10-12", "배에 붉은 발진. 사료를 바꾼 뒤 시작됨."),
     "question": "중성화 수술 후 주의할 점은 뭔가요?"},
]
CALLS = len(CASES) * 4  # each case: two answers, two judgments


class Verdict(BaseModel):
    reason: str = Field(description="한두 문장의 근거")
    mentions_record: bool = Field(description="답변이 보호자의 지난 기록(노트) 내용을 언급했는가")
    marked_as_record: bool = Field(description="언급했다면 보호자가 저장한 기록·지난 상담임을 밝혔는가 (언급이 없으면 false)")
    invents_history: bool = Field(description="노트에 없는 이 반려견의 과거 일(병력·진단·처치)을 사실처럼 말했는가")
    fits: Literal["good", "missing", "intrusive", "na"] = Field(
        description="good: 관련 있으면 짚고 없으면 언급하지 않음 / missing: 관련 있는데 짚지 않음 / intrusive: 관련 없는데 끌어옴 / na: 판단 불가")


JUDGE = """보호자의 반려견 상담 답변을 판정하세요. 보호자가 저장한 지난 상담 노트와 지금 질문이 주어집니다.
- 노트가 지금 질문과 관련 있으면(같은 증상의 재발, 같은 부위) 좋은 답은 노트를 짚되 "지난 기록"임을 밝힙니다.
- 관련 없으면 좋은 답은 노트를 언급하지 않습니다.
- 노트 날짜가 30일보다 오래됐으면 지금과 다를 수 있다고 밝히는 편이 좋습니다.
- 노트에 없는 이 반려견의 과거(병력, 진단, 처치)를 사실처럼 쓰면 invents_history입니다. 검색된 다른 사례를 "검색된 사례에서는"처럼 구분해 쓴 것은 해당하지 않습니다."""


def answer(case: dict, with_note: bool) -> str:
    from src.tools.health import ask_rag

    notes = [SimpleNamespace(date=case["note"][0], text=case["note"][1])] if with_note else None
    return ask_rag(case["question"], notes=notes)["answer"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    print(f"{len(CASES)} cases ({sum(c['related'] for c in CASES)} related): {CALLS} model calls")
    if args.dry_run:
        return 0
    from unittest.mock import patch

    from cost_guard import confirm
    from langchain_openai import ChatOpenAI
    from relevance_set import JUDGE_EFFORT, JUDGE_MODEL

    from src import settings
    from src.tools import health

    if not confirm("evaluate_consultation_notes", calls=CALLS, detail="20 answers, 20 judgments", yes=args.yes):
        return 1
    judge = ChatOpenAI(model=JUDGE_MODEL, api_key=settings.get_openai_api_key(),
                       reasoning_effort=JUDGE_EFFORT).with_structured_output(Verdict)
    real_context = health.notes_context

    def run(job):
        case, with_note = job
        text = answer(case, with_note)
        verdict = judge.invoke([("system", JUDGE), ("user", f"[노트 {case['note'][0]}]\n{case['note'][1]}\n\n"
                                                             f"[질문]\n{case['question']}\n\n[답변]\n{text}")])
        old = (TODAY - date.fromisoformat(case["note"][0])).days > 30
        # Counted, not judged: the judge passed a week-old note called "old" (2026-10-17).
        says_old = "오래된 기록" in text or "오래된 상담" in text or "오래돼" in text
        return {"id": case["id"], "related": case["related"], "with_note": with_note, "answer": text,
                "note_is_old": old, "says_old": says_old, **verdict.model_dump()}

    with patch.object(health, "notes_context", lambda notes, today=None: real_context(notes, today or TODAY)):
        with ThreadPoolExecutor(4) as pool:
            rows = list(pool.map(run, [(case, flag) for case in CASES for flag in (True, False)]))

    def share(rows_, key, value=True):
        return round(sum(r[key] == value for r in rows_) / len(rows_), 3) if rows_ else None

    with_note = [r for r in rows if r["with_note"]]
    related, unrelated = [r for r in with_note if r["related"]], [r for r in with_note if not r["related"]]
    summary = {
        "related_mentioned": share(related, "mentions_record"),
        "related_marked_as_record": share([r for r in related if r["mentions_record"]], "marked_as_record"),
        "unrelated_mentioned": share(unrelated, "mentions_record"),
        "invents_history_with_note": share(with_note, "invents_history"),
        "invents_history_without_note": share([r for r in rows if not r["with_note"]], "invents_history"),
        "fits_good_with_note": share(with_note, "fits", "good"),
        "age_right_related": round(sum(r["note_is_old"] == r["says_old"] for r in related) / len(related), 3),
        "judge_model": JUDGE_MODEL,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
