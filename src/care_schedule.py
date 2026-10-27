"""The care schedule's next dates, on the server: the same items and intervals as the web page
(web/src/lib/careSchedule.ts, tests/test_care_schedule.py checks they match), from the
동물사랑배움터 behaviour-guidance ethics guideline pp.39-40 (src/tools/care_guides.py).

The visit report gets the items that are due or overdue (api/visit_prep.py): the browser sends only
the last-done dates, and the dates and states are worked out here, so the report never repeats a
number the browser made up. A next date the guardian set with the vet (2026-10-27) is the one
exception the browser sends: it wins over the guide's while it is ahead of the last-done date, as on
the page (scheduleFor).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

CARE_HEADING = ("[보호자가 기록한 관리 일정: 동물사랑배움터 「건강한 반려문화 조성을 위한 행동지도 윤리 가이드라인」의 주기로 계산한 다음 날짜,"
                " 또는 보호자가 수의사와 정한 다음 날짜]")


@dataclass(frozen=True)
class CareItem:
    id: str
    label: str
    unit: str  # "day" or "month"
    min: int
    max: int
    wording: str
    page: int


CARE_ITEMS = (
    CareItem("heartworm", "심장사상충 예방약", "month", 1, 1, "매달", 40),
    CareItem("external", "외부 기생충 예방약", "month", 1, 1, "매달", 40),
    CareItem("deworming", "내부 기생충 구충제", "month", 3, 6, "3~6개월 간격", 40),
    CareItem("vaccine", "종합백신(DHPPL) 추가접종", "month", 12, 12, "매년 1회", 39),
    CareItem("rabies", "광견병 추가접종", "month", 12, 12, "매년 1회", 39),
    CareItem("checkup", "정기 건강검진", "month", 12, 12, "1년에 한 번 이상", 39),
    CareItem("nails", "발톱 손질", "day", 14, 21, "2~3주 주기", 39),
)
ITEMS_BY_ID = {item.id: item for item in CARE_ITEMS}


def _add(day: date, unit: str, amount: int) -> date:
    if unit == "day":
        return day + timedelta(days=amount)
    month = day.month - 1 + amount
    year, month = day.year + month // 12, month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))  # month ends stay month ends


def next_due(item: CareItem, last: date, today: date) -> tuple[date, date, str]:
    """(earliest, latest, state): overdue after the latest date, due between the two, later before."""
    earliest, latest = _add(last, item.unit, item.min), _add(last, item.unit, item.max)
    state = "overdue" if today > latest else "due" if today >= earliest else "later"
    return earliest, latest, state


def clean_record(raw: dict | None, today: date | None) -> dict[str, date]:
    """Known items with a real date, not in the future unless `today` is None (the set dates);
    anything else is dropped."""
    record = {}
    for item_id, value in (raw or {}).items():
        if item_id not in ITEMS_BY_ID or not isinstance(value, str):
            continue
        try:
            day = date.fromisoformat(value)
        except ValueError:
            continue
        if today is None or day <= today:
            record[item_id] = day
    return record


def due_lines(raw: dict | None, today: date | None = None, planned: dict | None = None) -> list[str]:
    """One line per item that is overdue or due now, for the report; nothing for the rest."""
    today = today or date.today()
    record = clean_record(raw, today)
    set_dates = clean_record(planned, None)
    lines = []
    for item in CARE_ITEMS:
        last, set_day = record.get(item.id), set_dates.get(item.id)
        if set_day and (last is None or set_day > last):
            if set_day > today:
                continue
            status = "기한이 지났음" if set_day < today else "지금 할 때"
            done = f"마지막 {last.isoformat()}, " if last else ""
            lines.append(f"- {item.label}: {done}수의사와 정한 날 {set_day.isoformat()} — {status}")
            continue
        if last is None:
            continue
        earliest, latest, state = next_due(item, last, today)
        if state == "later":
            continue
        window = earliest.isoformat() if earliest == latest else f"{earliest.isoformat()} ~ {latest.isoformat()}"
        status = "기한이 지났음" if state == "overdue" else "지금 할 때"
        lines.append(f"- {item.label}: 마지막 {last.isoformat()}, 다음 예정 {window} ({item.wording}, 지침 {item.page}쪽) — {status}")
    return lines


def care_section(raw: dict | None, today: date | None = None, planned: dict | None = None) -> str:
    lines = due_lines(raw, today, planned)
    return f"{CARE_HEADING}\n" + "\n".join(lines) if lines else ""
