"""When the model provider stops answering for a while: say so, and show what the search still finds.

On 2026-10-19 the OpenAI project reached its spend limit (429 insufficient_quota,
project_spend_limit_exceeded) and every question, a greeting included, got "답변을 만드는 중에 문제가
생겼습니다". Nothing was wrong with the app, and the health search does not need the provider: the
question vector comes from the ko-sroberta model in this process and the consultations from Supabase
(src/resources.py), the care guides from memory (src/tools/care_guides.py). So for such an error the
chat shows the closest consultations and guides as they are, with no written answer, and says plainly
that answers are paused. A question far from the material gets the notice alone.

Only quota errors took this path at first. Since 2026-10-23 the model calls have time limits
(src/resources.py), and a provider that does not answer in time or cannot be reached takes it too,
with its own notice ("unavailable"). Other failures stay one error event, as before (api/chat.py).

Since 2026-10-27 such a call goes to Claude first (src/resources.py with_claude_fallback, ADR-0012);
this path is what is left when Claude fails too, or when there is no Anthropic key. After such a
failure the next calls skip OpenAI for a while (the breaker, OPENAI_BREAKER_SECONDS), so Claude's
error alone can arrive here; it counts as "unavailable".
"""

from __future__ import annotations

import logging

from src.health_answers import evidence_row
from src.health_safety import detect_urgent_sign

logger = logging.getLogger(__name__)

# What still works differs by screen: the web app has fees and the care schedule, the Streamlit backup not.
STILL_WORKS = {
    "web": "그동안 시설 찾기, 지역별 진료비, 관리 일정은 그대로 쓸 수 있어요.",
    "streamlit": "그동안 시설 찾기와 데이터 소개는 그대로 쓸 수 있어요.",
}
PAUSED_ONLY = "지금은 답변을 만드는 AI 서비스의 이용 한도가 다 되어 답변을 쓰지 못합니다. 보통 하루 안에 다시 열립니다."
PAUSED = f"{PAUSED_ONLY}\n\n{STILL_WORKS['web']}"
FOUND = "대신 질문과 가까운 자료를 아래 '검색 근거'에 그대로 보여 드립니다. 답변이 아니라 비슷한 상담 사례와 공공 지침이니, 지금 반려견에게 맞는지는 동물병원에 확인해 주세요."
QUOTA_MARKERS = ("insufficient_quota", "spend_limit", "quota")
UNAVAILABLE_ONLY = "지금 답변을 만드는 AI 서비스가 제때 응답하지 않아 답변을 쓰지 못했습니다. 잠시 뒤 다시 물어봐 주세요."
# The OpenAI client's errors for a request that timed out, could not connect, failed on the
# provider's side (5xx) or stayed rate limited after the retry; matched by name, as LangChain wraps them.
UNAVAILABLE_ERRORS = ("APITimeoutError", "APIConnectionError", "InternalServerError", "RateLimitError")


def _chain(error: BaseException | None):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        yield error
        error = error.__cause__ or error.__context__


def is_quota_error(error: BaseException | None) -> bool:
    """A provider's "out of quota" error, anywhere in the exception chain (LangChain wraps them)."""
    return any(type(e).__name__ == "RateLimitError" and any(marker in str(e) for marker in QUOTA_MARKERS)
               for e in _chain(error))


def outage_kind(error: BaseException | None) -> str | None:
    """"quota", "unavailable" (timed out, unreachable, the provider's own failure) or None (a bug of ours)."""
    if is_quota_error(error):
        return "quota"
    chain = list(_chain(error))
    if any(type(e).__name__ in UNAVAILABLE_ERRORS for e in chain):
        return "unavailable"
    # Claude's own error (a bad key included) reaches here only while the OpenAI breaker sends calls
    # to Claude alone (src/resources.py): OpenAI failed moments ago and Claude now, an outage.
    return "unavailable" if any(type(e).__module__.split(".")[0] == "anthropic" for e in chain) else None


def paused(screen: str = "web", kind: str = "quota") -> str:
    return f"{UNAVAILABLE_ONLY if kind == 'unavailable' else PAUSED_ONLY}\n\n{STILL_WORKS[screen]}"


def search_only_result(question: str, top_k: int, screen: str = "web", kind: str = "quota") -> dict:
    """The closest consultations (if near enough) and care guides, shown as evidence without an answer."""
    from src.tools import care_guides, health

    rows = []
    try:
        if not health.other_species(question):
            guides = care_guides.retrieve_care_guides(question)
            similarity = health.health_top_similarity(question)
            cases = (health.retrieve_health(question, k=top_k)
                     if isinstance(similarity, float) and similarity >= health.HEALTH_SIMILARITY_FLOOR else [])
            rows = [evidence_row(doc) for doc in [*guides, *cases]]
    except Exception:  # noqa: BLE001 - the notice still goes out without the search
        logger.warning("search-only answer failed", exc_info=True)
    return {
        "answer": f"{paused(screen, kind)}\n\n{FOUND}" if rows else paused(screen, kind),
        "route": "rag" if rows else "none",
        "evidence_rows": rows,
        "hospital_rows": [],
        "safety_notice": detect_urgent_sign(question),
        "abstained": False,
        "trace_id": None,
        "degraded": True,
    }
