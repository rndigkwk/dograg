"""Core layer: paths, models and limits for the visit-prep team."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from langchain_openai import ChatOpenAI

from src import settings
from src.resources import CHAT_MODEL_NAME

PROJECT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_DIR / "output" / "visit_prep"
REPORT_FILE = "visit_report.md"
RESULT_FILE = "result.json"

# Limits keep cost bounded and stop loops.
MAX_TASKS = 5          # research tasks in the first plan
MAX_EXTRA_TASKS = 2    # tasks added when the supervisor sends the team back to research
MAX_ROUNDS = 2         # times the supervisor sends work back after a rejection; then a person decides
TOOL_CALL_LIMIT = 3    # tool calls per researcher run
AGENT_CALL_LIMIT = 6   # model calls per researcher or writer run
HUMAN_CHECK = "반복 상한 도달: 수의사(사람) 확인 필요"
PASSED = "검수 통과"


@lru_cache(maxsize=1)
def llm() -> ChatOpenAI:
    """Planning, research and review model. gpt-6-luna takes function tools only through the
    Responses API (/v1/chat/completions rejects tools with reasoning)."""
    return ChatOpenAI(model=CHAT_MODEL_NAME, api_key=settings.get_openai_api_key(), use_responses_api=True, timeout=120)


@lru_cache(maxsize=1)
def writer_llm() -> ChatOpenAI:
    """Writer model: one tool call per response, so the two handoff tools are never called together."""
    return ChatOpenAI(
        model=CHAT_MODEL_NAME, api_key=settings.get_openai_api_key(), use_responses_api=True, timeout=120,
        model_kwargs={"parallel_tool_calls": False},
    )
