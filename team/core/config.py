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
REPEATED_CHECK = "같은 지적 반복: 수의사(사람) 확인 필요"
RESEARCH_HELD = "필수 조사 실패: 수의사(사람) 확인 필요"
# Research the report cannot do without. A failed place or cost task only leaves its section
# out ("degraded"); when every health task fails the team stops before writing ("held").
REQUIRED_KINDS = ("health",)
KIND_LABELS = {"health": "비슷한 상담 사례", "place": "지역 동물병원 목록", "cost": "진료비 통계"}
# Retries live in one layer, the OpenAI SDK (every external call of the team is an OpenAI call:
# models and report embeddings). A LangGraph RetryPolicy on top would multiply the attempts
# (SDK 3 x node 2 = 6); after the SDK gives up, the node records the failure instead.
MODEL_MAX_RETRIES = 2
PASSED = "검수 통과"


@lru_cache(maxsize=1)
def llm() -> ChatOpenAI:
    """Planning, research and review model. gpt-6-luna takes function tools only through the
    Responses API (/v1/chat/completions rejects tools with reasoning)."""
    return ChatOpenAI(model=CHAT_MODEL_NAME, api_key=settings.get_openai_api_key(), use_responses_api=True, timeout=120,
                      max_retries=MODEL_MAX_RETRIES)


# The reviewer lists every claim of a 20-sentence report and checks each one: the slowest step
# (median 23s at the default effort over 12 consultations). Low effort; see README for the comparison.
REVIEW_REASONING_EFFORT = "low"


@lru_cache(maxsize=1)
def review_llm() -> ChatOpenAI:
    return ChatOpenAI(model=CHAT_MODEL_NAME, api_key=settings.get_openai_api_key(), use_responses_api=True, timeout=120,
                      max_retries=MODEL_MAX_RETRIES,
                      reasoning_effort=settings.get_setting("TEAM_REVIEW_REASONING_EFFORT") or REVIEW_REASONING_EFFORT)


@lru_cache(maxsize=1)
def writer_llm() -> ChatOpenAI:
    """Writer model: one tool call per response, so the two handoff tools are never called together."""
    return ChatOpenAI(
        model=CHAT_MODEL_NAME, api_key=settings.get_openai_api_key(), use_responses_api=True, timeout=120,
                      max_retries=MODEL_MAX_RETRIES,
        model_kwargs={"parallel_tool_calls": False},
    )
