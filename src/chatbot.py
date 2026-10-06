"""Entry point the chat page calls: settings + tools + LangGraph run."""

from __future__ import annotations

from typing import Any

from src import resources, settings
from src.chat_graph import build_chat_graph, run_chat
from src.tools.health import DEFAULT_RAG_TOP_K
from src.tools.toolset import TOOLS


def chatbot(
    question: str,
    *,
    top_k: int = DEFAULT_RAG_TOP_K,
    chat_history=None,
    location: tuple[float, float] | None = None,
    pet_profile=None,
    crag: bool | None = None,
    crag_reports: bool | None = None,
    on_token=None,
    on_step=None,
) -> dict[str, Any]:
    """질문을 분류한 뒤 rag, sql, analysis, 또는 도구 없는 일반 응답을 LangGraph로 실행합니다.

    crag(건강 상담)는 ENABLE_CRAG, crag_reports(보고서)는 ENABLE_CRAG_REPORTS 설정을 따릅니다.
    보고서 CRAG는 판정이 정답 근거를 걸러 내서 기본으로 꺼 둡니다(docs/wiki/safety-and-evidence.md).
    채팅 모델(API 키)이 없으면 둘 다 쓰지 않습니다.
    """
    if crag is None:
        crag = settings.crag_enabled()
    if crag_reports is None:
        crag_reports = settings.setting_enabled("ENABLE_CRAG_REPORTS")
    model_ready = resources.load_chat_model() is not None
    return run_chat(
        TOOLS,
        question,
        top_k=top_k,
        chat_history=chat_history,
        location=location,
        pet_profile=pet_profile,
        crag=bool(crag) and model_ready,
        crag_reports=bool(crag_reports) and model_ready,
        graph=build_chat_graph(TOOLS),
        on_token=on_token,
        on_step=on_step,
    )
