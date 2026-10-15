"""What the chat shows while an answer is made, shared by the Streamlit page and the API (ADR-0008).

Moved from app_pages/rag.py unchanged so api/chat.py can send the same progress lines, the
early place list and the emergency hospitals without importing the Streamlit page.
"""

from __future__ import annotations

import logging

from src.chat_graph import HEALTH_PART_HEADING
from src.tools.places import emergency_hospitals

ROUTE_PROGRESS = {
    "rag": "건강 상담 자료에서 근거를 찾고 있습니다…",
    "analysis": "보고서에서 근거를 찾고 있습니다…",
    "sql": "동물병원을 찾고 있습니다…",
    "fee": "진료비 조사 자료를 찾고 있습니다…",
    "none": "답변을 작성하고 있습니다…",
}


def progress_message(node: str, update: dict) -> str | None:
    """그래프 노드가 끝날 때마다 다음 단계를 사용자에게 알려 줄 문구를 고릅니다."""
    if node == "classify":
        return ROUTE_PROGRESS.get(update.get("route"))
    if node == "hospital" and update.get("also_health"):
        return "증상에 대한 상담 자료를 찾고 있습니다…"
    if node in {"health_retrieve", "report_retrieve"}:
        return "찾은 근거가 질문에 맞는지 확인하고 있습니다…"
    if node in {"health_grade", "report_grade"}:
        if update.get("documents"):
            return "근거를 바탕으로 답변을 작성하고 있습니다…"
        return "맞는 근거가 없어 검색어를 바꿔 다시 찾고 있습니다…" if node == "health_grade" else None
    return None


def places_first(node: str, update: dict) -> str | None:
    """A symptom + place request: the place list, to show while the symptom answer is written.

    The places are ready in well under a second (fixed SQL) and the health path takes 4-8 s
    more; before this the list the user asked for appeared only with the finished answer."""
    if node == "hospital" and update.get("place_answer"):
        return update["place_answer"] + HEALTH_PART_HEADING
    return None


def find_emergency_hospitals(location) -> dict:
    """Hospitals to show next to an urgent warning; empty when the location was not shared."""
    if location is None:
        return {}
    try:
        return emergency_hospitals(location)
    except Exception:
        logging.getLogger(__name__).warning("Emergency hospital lookup failed", exc_info=True)
        return {}
