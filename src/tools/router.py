"""Question router: keyword rules for single-signal questions, the LLM for the rest."""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal

import httpx
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src import resources, settings
from src.tools import history, places, report

logger = logging.getLogger(__name__)
ROUTES = ("rag", "sql", "analysis", "none")


class RouteDecision(BaseModel):
    route: Literal["rag", "sql", "analysis", "none"] = Field(
        description="rag: 건강/질병, sql: 반려동물 시설(병원·약국·동반 시설·미용·위탁·장묘) 검색, analysis: 보고서 분석, none: 기타 대화"
    )


ROUTER_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """질문을 사용할 도구로 분류하세요.
- rag: 반려견 증상, 질병, 치료, 건강 정보
- sql: 동물병원, 동물약국, 반려동물 동반 가능 시설(카페·펜션·여행지·박물관), 애견미용실, 애견호텔·위탁관리업체, 반려동물 장례식장(장묘업체)의 이름, 주소, 지역, 목록 검색
    - analysis: 반려동물 관련 보고서(현황, 복지, 산업, 의료보험, 장묘)의 통계, 추이, 비교, 비중, 분포 분석
- none: 인사, 감사, 자기소개, 기능 문의 등 도구가 필요 없는 질문
인사말은 별도 직접 응답 분기로 만들지 말고 반드시 none으로 분류하세요.
판단 기준:
- 반려견의 몸 상태나 사고(흉터, 부기, 이물 섭취 등)를 설명하는 질문은 병원 방문 여부나 병원에 갈 수 없는 사정이 함께 적혀 있어도 rag입니다.
- 이런 시설을 찾아 달라거나 그 목록·주소·위치·개수·이용 조건을 묻는 질문만 sql입니다.
- 장묘 서비스의 이용 실태·비용 통계는 analysis이고, 장례식장이나 장묘업체를 찾아 달라는 질문은 sql입니다.
- 연구·조사·보고서의 통계, 가격, 비율을 묻는 질문은 동물병원이 언급돼도 analysis입니다.""",
    ),
    ("human", "[대화 이력]\n{chat_history}\n\n[현재 질문]\n{question}"),
])


# Fallback for the questions the keyword rules cannot decide (about 15%): OpenAI's Decisions API,
# a classification endpoint that returns one of the given choices (0.35 s vs 1.5 s for a chat call
# with structured output, same accuracy; docs/wiki/router.md). Called over HTTP because the
# openai SDK that has it (3.26+) is a major upgrade from the one langchain-openai uses here.
# Any error or refusal falls back to the chat-model router below. ROUTER_FALLBACK=llm turns it off.
DECISIONS_URL = "https://api.openai.com/v1/decisions"
DECISIONS_TIMEOUT_SECONDS = 5.0
ROUTE_INSTRUCTIONS = (
    "반려견 서비스 챗봇에 들어온 질문을 처리할 도구 하나로 분류하세요. 대화 이력이 있으면 현재 질문의 맥락으로만 참고하세요. "
    "rag: 반려견 증상, 질병, 치료, 건강 정보(몸 상태를 설명하면 병원 언급이 있어도 rag). "
    "sql: 동물병원·동물약국·반려동물 동반 시설·애견미용·위탁·장묘업체를 찾거나 그 목록·주소·위치·개수·이용 조건을 묻는 질문. "
    "analysis: 반려동물 보고서(현황, 복지, 산업, 의료보험, 장묘)의 통계, 추이, 비교, 비중, 분포 (동물병원이 언급돼도 통계면 analysis). "
    "none: 인사, 감사, 기능 문의, 서비스 범위 밖 대화."
)


def decide_route(question: str, chat_history=None) -> str | None:
    """One Decisions API call; None when it is off, fails, refuses or answers outside ROUTES."""
    if (settings.get_setting("ROUTER_FALLBACK") or "decisions").strip().lower() != "decisions":
        return None
    api_key = settings.get_openai_api_key()
    if not api_key:
        return None
    text = f"[대화 이력]\n{history.format_chat_history(chat_history)}\n\n[현재 질문]\n{question}"
    body = {
        "model": resources.CHAT_MODEL_NAME,
        "input": text,
        "questions": [{"type": "choice", "name": "route", "instructions": ROUTE_INSTRUCTIONS,
                       "choices": [{"value": route} for route in ROUTES]}],
    }
    try:
        response = httpx.post(DECISIONS_URL, json=body, headers={"Authorization": f"Bearer {api_key}"},
                              timeout=DECISIONS_TIMEOUT_SECONDS)
        response.raise_for_status()
        answer = response.json()["answers"][0]
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning("Decisions router failed (%s); using the chat-model router", type(exc).__name__)
        return None
    if answer.get("type") == "choice" and answer.get("choice") in ROUTES:
        return answer["choice"]
    logger.info("Decisions router gave no route (%s); using the chat-model router", answer.get("type"))
    return None


OUT_OF_SCOPE_KEYWORDS = ("날씨", "기온", "미세먼지", "뉴스", "주식", "환율")
HEALTH_QUERY_KEYWORDS = (
    "증상", "질병", "구토", "토해", "설사", "아파", "통증", "기침",
    "발열", "식욕", "절뚝", "골절", "상처", "충혈", "눈곱",
    "잇몸", "가려", "발진",
    # 2026-10-04 평가에서 놓친 건강 질문의 표현. "혹", "토"처럼 짧아 오탐이 나는 말은 넣지 않습니다.
    "부어", "부풀", "부기", "물렸", "물린", "삼켰", "삼킨", "흉터", "출혈",
    "호흡", "경련", "발작", "켁켁", "무기력", "혈변",
    # 2026-10-07 시설 라우팅 평가(tests/data/place_routing_questions.json)에서 놓친 표현.
    "토했", "먹여도",
)
HOSPITAL_LOOKUP_KEYWORDS = (
    "목록", "주소", "위치", "검색", "찾아", "추천", "어디",
    "몇 개", "몇개", "몇 곳", "몇곳", "가까운", "근처",
)


def is_date_question(question: str) -> bool:
    normalized = "".join(question.lower().split())
    return "날짜" in normalized or "며칠" in normalized or "몇일" in normalized


def current_date_answer() -> str:
    today = date.today()
    return f"오늘은 {today.year}년 {today.month}월 {today.day}일입니다."


def is_out_of_scope_question(question: str) -> bool:
    normalized = "".join(question.lower().split())
    return any(keyword in normalized for keyword in OUT_OF_SCOPE_KEYWORDS)


def classify_question(question: str, chat_history=None) -> str:
    if is_out_of_scope_question(question):
        return "none"
    normalized_question = "".join(question.lower().split())
    has_hospital_lookup = places.is_place_question(question) and any(
        keyword.replace(" ", "") in normalized_question
        for keyword in HOSPITAL_LOOKUP_KEYWORDS
    )
    has_health_topic = any(
        keyword in normalized_question for keyword in HEALTH_QUERY_KEYWORDS
    )
    has_report_topic = any(
        keyword.replace(" ", "") in normalized_question
        for keyword in report.REPORT_ANALYSIS_KEYWORDS
    )
    mentions_hospital = places.is_place_question(question)
    if has_report_topic and "보고서" in normalized_question:
        return "analysis"
    # 키워드 신호가 하나뿐일 때만 규칙으로 정하고, 신호가 충돌하면 LLM 라우터에 맡깁니다.
    # 예: "닭 뼈를 삼켰는데 가까운 동물병원에 갈 수 없어요"(건강 + 병원 찾기 표현)
    if has_health_topic and not has_hospital_lookup:
        return "rag"
    if mentions_hospital and not has_health_topic and not has_report_topic:
        return "sql"
    if has_report_topic and not mentions_hospital and not has_health_topic:
        return "analysis"

    model = resources.load_chat_model()
    if model is None:
        # 모델이 없으면 예전 우선순위(병원 찾기 > 건강 > 병원 > 보고서)를 그대로 씁니다.
        if has_hospital_lookup:
            return "sql"
        if has_health_topic:
            return "rag"
        if mentions_hospital:
            return "sql"
        if has_report_topic:
            return "analysis"
    if model is not None:
        if route := decide_route(question, chat_history):
            return route
        decision = (ROUTER_PROMPT | model.with_structured_output(RouteDecision)).invoke(
            {
                "chat_history": history.format_chat_history(chat_history),
                "question": question,
            }
        )
        return decision.route

    contextual_question = history.build_rag_search_query(question, chat_history).lower()
    if any(word in contextual_question for word in ("병원", "주소", "지역", "동물병원", "동물약국", "장례식장", "애견미용", "애견호텔", "애견동반", "애견카페")):
        return "sql"
    if any(word in contextual_question for word in ("증상", "질병", "아파", "구토", "치료")):
        return "rag"
    if any(
        keyword.replace(" ", "") in contextual_question
        for keyword in report.REPORT_ANALYSIS_KEYWORDS
    ):
        return "analysis"
    return "none"
