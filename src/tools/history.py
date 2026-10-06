"""Short-term conversation history shared by the router and the answer prompts."""

from __future__ import annotations

SHORT_TERM_MEMORY_TURNS = 6


def get_recent_chat_history(messages, max_turns=SHORT_TERM_MEMORY_TURNS):
    """세션에 저장된 대화에서 최근 사용자-AI 대화만 반환합니다."""
    if not messages:
        return []
    return list(messages[-max_turns * 2:])


def format_chat_history(messages):
    """대화 이력을 RAG 프롬프트에 넣을 문자열로 변환합니다."""
    role_labels = {"user": "사용자", "assistant": "AI"}
    return "\n".join(
        f"{role_labels.get(message.get('role'), message.get('role', '대화'))}: "
        f"{message.get('content', '')}"
        for message in messages or []
    ) or "이전 대화 없음"


def build_rag_search_query(question, chat_history=None):
    """현재 질문과 이전 사용자 질문을 합쳐 후속 질문 검색을 보강합니다."""
    previous_questions = [
        message.get("content", "")
        for message in get_recent_chat_history(chat_history)
        if message.get("role") == "user" and message.get("content")
    ]
    return "\n".join(dict.fromkeys(previous_questions + [question]))
