"""Emergency warning: the rules first, then one OpenAI Decisions call for what they miss.

The rules (src/health_safety.py) catch 9 of 20 urgent questions worded in ways they were not
written from (tests/data/emergency_signs.json, holdout). When they find nothing, one Decisions
call (the classification API the router uses, about 0.3 s) asks whether the guardian should go
to a hospital now. Off with URGENT_SECOND_CHECK=off, and skipped without an API key; any
failure or refusal leaves the rules' answer (no warning). Measured with
scripts/evaluate_emergency.py --second-check.

The same call's middle answer, see_vet_soon, became the answer's "진료 권장" badge (2026-11-06;
urgency_level): no extra call. Measured with scripts/evaluate_care_level.py. "새로 생기거나 커지는
혹·멍울" joined its examples on 2026-11-07: both lump questions of the holdout
(tests/data/urgency_holdout_questions.json) got no badge.
"""

from __future__ import annotations

import logging

import httpx

from src import resources, settings
from src.health_safety import URGENT_NOTICE, detect_urgent_sign
from src.tools import places, router

logger = logging.getLogger(__name__)

URGENT_INSTRUCTIONS = """보호자가 반려동물의 상태를 적은 글입니다. 얼마나 서둘러 동물병원에 가야 하는지 고르세요.

emergency_now: 몇 시간 안에 목숨이 위험할 수 있어 지금 바로 병원에 연락하거나 가야 하는 상황. 예: 숨쉬기 힘들어함·혀나 잇몸이 파랗거나 하얌, 쓰러짐·의식이나 반응이 떨어짐, 경련·발작이 이어짐, 독성 물질이나 사람 약을 먹음, 배가 부풀고 헛구역질만 함, 멈추지 않는 출혈·피를 토함, 교통사고·추락·깊은 상처, 열사병, 소변을 전혀 못 봄, 난산, 눈 외상, 얼굴이 붓는 심한 알레르기 반응.
see_vet_soon: 진료가 필요하지만 지금 당장 생명이 위험해 보이지는 않는 상황. 예: 며칠째 이어지는 구토·설사·식욕 부진, 혈변이나 혈뇨, 절뚝거림, 이물을 삼켰지만 지금은 잘 지냄, 새로 생기거나 커지는 혹·멍울, 이미 진단받고 치료 중인 병, 수술 뒤 회복 문제.
not_urgent: 일상적인 증상, 이미 지나가 지금은 괜찮은 일, 없다고 밝힌 증상, 일반 정보·예방·대처법 질문, 증상 설명이 없는 질문(시설 찾기, 보고서, 인사 등).
emergency_now는 위 예처럼 지금 위급한 신호가 글에 적혀 있을 때만 고르세요."""
CHOICES = ("emergency_now", "see_vet_soon", "not_urgent")


def second_check_enabled() -> bool:
    return (settings.get_setting("URGENT_SECOND_CHECK") or "decisions").strip().lower() == "decisions"


def decide_urgency(question: str) -> str | None:
    """One Decisions call: one of CHOICES, or None when off, failed or refused."""
    if not second_check_enabled():
        return None
    api_key = settings.get_openai_api_key()
    if not api_key:
        return None
    body = {
        "model": resources.CHAT_MODEL_NAME,
        "input": question,
        "questions": [{"type": "choice", "name": "urgency", "instructions": URGENT_INSTRUCTIONS,
                       "choices": [{"value": choice} for choice in CHOICES]}],
    }
    try:
        response = router.decisions_post(body, api_key)
        response.raise_for_status()
        answer = response.json()["answers"][0]
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning("Decisions urgency check failed (%s); keeping the rules' answer", type(exc).__name__)
        return None
    if answer.get("type") == "choice" and answer.get("choice") in CHOICES:
        return answer["choice"]
    logger.info("Decisions urgency check gave no choice (%s)", answer.get("type"))
    return None


def decide_urgent(question: str) -> bool | None:
    """True for emergency_now, False for the other two, None when off, failed or refused."""
    choice = decide_urgency(question)
    return None if choice is None else choice == "emergency_now"


def needs_second_check(question: str) -> bool:
    """Not for a date question or a bare place search ("강남구 동물병원 알려줘"): no call there.
    A place search with something before the place words ("입술이 거무스름한데 강남구 …") is checked."""
    if router.is_date_question(question):
        return False
    if not places.is_place_question(question) or router.describes_symptom(question):
        return True
    return router.symptom_part(question) != question


def urgency_level(question: str) -> tuple[str | None, str | None]:
    """(the red warning or None, "see_vet_soon" or None): the rules first, then one Decisions call
    whose middle answer is the "진료 권장" badge. Never both."""
    if notice := detect_urgent_sign(question):
        return notice, None
    if not needs_second_check(question):
        return None, None
    choice = decide_urgency(question)
    if choice == "emergency_now":
        return URGENT_NOTICE, None
    return None, "see_vet_soon" if choice == "see_vet_soon" else None


def urgent_notice(question: str) -> str | None:
    """The warning to show before the answer, or None."""
    return urgency_level(question)[0]
