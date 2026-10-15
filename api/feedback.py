"""POST /feedback: 👍/👎, why, and (with consent) the question and answer for review (ADR-0008, P1).

    GET  /feedback/reasons          the reasons offered under a 👎 (src/feedback_store.REASONS)
    POST /feedback                  {trace_id, helpful}              -> Langfuse score (overwrites a changed vote)
    POST /feedback/reason           {trace_id, reason}               -> Langfuse score
    POST /feedback/review           {trace_id, question, answer, route?, reason?, evidence_rows?}
                                    the guardian ticked "send": stored masked in ragdog_feedback

The same calls as the chat page (app_pages/rag.py render_feedback). No model calls, but each one
writes to Langfuse or Supabase, so a browser may send FEEDBACK_PER_HOUR of them (in memory).
"""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from api.chat import client_network, person_of
from src import feedback_store, tracing
from src.storage.models import MAX_ANSWER_CHARS, MAX_QUESTION_CHARS

router = APIRouter(prefix="/feedback", tags=["feedback"])

FEEDBACK_PER_HOUR = 60
TRACE_ID = r"^[0-9a-f]{32}$"  # Langfuse trace ids, as /chat returns them
_sent: dict[str, list[float]] = {}
_sent_lock = threading.Lock()


class Vote(BaseModel):
    trace_id: str = Field(pattern=TRACE_ID)
    helpful: bool


class Reason(BaseModel):
    trace_id: str = Field(pattern=TRACE_ID)
    reason: str


class Review(BaseModel):
    trace_id: str = Field(pattern=TRACE_ID)
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    answer: str = Field(min_length=1, max_length=MAX_ANSWER_CHARS)
    route: str | None = Field(default=None, max_length=20)
    reason: str | None = None
    evidence_rows: list[dict] = Field(default_factory=list, max_length=12)


def _allow(request: Request, client_id: str | None) -> None:
    person, now = person_of(client_id, client_network(request)), time.time()
    with _sent_lock:
        recent = [t for t in _sent.get(person, []) if now - t < 3600]
        if len(recent) >= FEEDBACK_PER_HOUR:
            _sent[person] = recent
            raise HTTPException(429, "의견을 너무 많이 보냈습니다. 잠시 뒤 다시 보내 주세요.")
        _sent[person] = [*recent, now]


def _known_reason(reason: str | None) -> None:
    if reason is not None and reason not in feedback_store.REASONS:
        raise HTTPException(422, f"reason은 {', '.join(feedback_store.REASONS)} 중 하나여야 합니다.")


@router.get("/reasons")
def reasons() -> list[str]:
    return list(feedback_store.REASONS)


@router.post("")
def vote(body: Vote, request: Request, x_ragdog_client: str | None = Header(default=None)) -> dict:
    _allow(request, x_ragdog_client)
    return {"recorded": tracing.record_feedback(body.trace_id, helpful=body.helpful)}


@router.post("/reason")
def reason(body: Reason, request: Request, x_ragdog_client: str | None = Header(default=None)) -> dict:
    _known_reason(body.reason)
    _allow(request, x_ragdog_client)
    return {"recorded": tracing.record_feedback_reason(body.trace_id, body.reason)}


@router.post("/review")
def review(body: Review, request: Request, x_ragdog_client: str | None = Header(default=None)) -> dict:
    _known_reason(body.reason)
    if not feedback_store.enabled():
        raise HTTPException(503, "지금은 대화를 저장할 수 없습니다.")
    _allow(request, x_ragdog_client)
    evidence = [feedback_store.evidence_summary(row) for row in body.evidence_rows]
    saved = feedback_store.save_review(question=body.question, answer=body.answer, route=body.route,
                                       reason=body.reason, trace_id=body.trace_id, evidence=evidence)
    return {"saved": saved}
