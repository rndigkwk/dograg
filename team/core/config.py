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
# Fallback (day56): when an optional research task fails or finds nothing, the report still gets
# a fixed, checked guide for that section instead of a gap. It is evidence like any other (the
# reviewer checks the report against it), carries its own id, and the run stays "degraded".
FALLBACK_EVIDENCE = {
    "cost": [
        {"evidence_id": "guide-cost-1",
         "fact": "진료비는 병원과 검사·처치 항목에 따라 다르므로, 방문 전에 병원에 전화해 진찰료와 예상 검사 비용을 물어보는 것이 좋다."},
        {"evidence_id": "guide-cost-2",
         "fact": "동물병원은 진찰료·입원비·예방접종비 등 주요 진료비를 병원 안에 게시해야 한다(수의사법 진료비 게시제, 2024년부터 모든 동물병원)."},
    ],
}
FALLBACK_SUMMARY = "{label}를 찾지 못해 기본 안내로 대신함 (실제 통계 아님)"
# Retries live in one layer, the OpenAI SDK (every external call of the team is an OpenAI call:
# models and report embeddings). A LangGraph RetryPolicy on top would multiply the attempts
# (SDK 3 x node 2 = 6); after the SDK gives up, the node records the failure instead.
MODEL_MAX_RETRIES = 2
PASSED = "검수 통과"
# Node visits a normal run stays within (Day 56: count top-level visits to spot loops). Above
# these the run is a "repeat suspect": a second research round, a second rewrite, or more
# researchers than the plan allows. The hard stops (MAX_ROUNDS, the ping-pong check) sit higher.
VISIT_LIMITS = {
    "planner": 2,                                # first plan + one extra research round
    "researcher": MAX_TASKS + MAX_EXTRA_TASKS,   # one per task
    "writer": 2,                                 # first draft + one rewrite
    "reviewer": 2,
}


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
