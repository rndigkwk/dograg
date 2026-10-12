"""Small talk and questions outside the service: fixed replies, no model call.

A model used to answer these as a general assistant: it said it was ChatGPT, offered coding and
translation, and did out-of-scope tasks (code, math, recommendations; guardrail baseline #103).
Only about 3% of deployed questions came here. Now a short rule picks one of four replies that
say what this service does (tests/data/general_questions.json, docs/curriculum-fit.md).
"""

from __future__ import annotations

SERVICE_GUIDE = (
    "라그도그는 반려견 건강 상담 서비스예요. 이런 것을 물어볼 수 있어요.\n"
    "- **건강·증상:** \"강아지가 이틀째 설사를 해요\"\n"
    "- **동물병원·약국·미용·동반 시설 찾기:** \"강남구 24시 동물병원 알려줘\"\n"
    "- **지역별 진료비:** \"강남구 엑스레이 비용 얼마야?\"\n"
    "- **반려동물 통계:** \"반려견 보험 가입률 알려줘\""
)
GREETING_REPLY = "안녕하세요! " + SERVICE_GUIDE
THANKS_REPLY = "도움이 됐다니 다행이에요. 반려견에 대해 더 궁금한 점이 있으면 물어봐 주세요."
OUT_OF_SCOPE_REPLY = "그 질문은 제가 도와드릴 수 있는 범위 밖이에요. " + SERVICE_GUIDE

GREETING_WORDS = ("안녕", "반가", "처음", "hello", "hi")
THANKS_WORDS = ("고마", "감사", "thank")
CAPABILITY_WORDS = ("기능", "할수있", "이름", "누구", "소개", "사용법", "물어볼")


def answer_without_tool(question: str, chat_history=None) -> str:
    """The reply for a question routed to none (chat_history is kept for the graph's call)."""
    normalized = "".join(question.lower().split())
    if any(word in normalized for word in THANKS_WORDS):
        return THANKS_REPLY
    if any(word in normalized for word in CAPABILITY_WORDS):
        return SERVICE_GUIDE
    if any(word in normalized for word in GREETING_WORDS):
        return GREETING_REPLY
    return OUT_OF_SCOPE_REPLY
