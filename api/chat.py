"""POST /chat: one guardian question answered as a stream of events (ADR-0008, P1).

The same steps as the Streamlit chat page (app_pages/rag.py), in the same order:

1. The question limit (src/rate_limit.py). Over it, no model is called; the emergency rules (no
   model either) still put the warning and the nearest hospitals first.
2. The conversation so far, with older turns folded into a summary (src/tools/history.py). The API
   keeps no state: the frontend sends the turns and the summary it got last time, and gets the
   updated summary back in the result.
3. The emergency check (rules, then one Decisions call), shown before the answer is written.
4. The chat graph (src/chatbot.py), which masks personal data before any model call, streams the
   answer's text and records the material's gaps.

Events (text/event-stream, one JSON object each): step {message} · places {text} · urgent
{notice, hospitals} · token {text} · result {...} · limited {message, wait_minutes} · error {message}.
The frontend reads them with fetch (the request is a POST, which EventSource cannot send).
"""

from __future__ import annotations

import contextvars
import json
import logging
import queue
import re
import threading
from collections.abc import Iterator
from typing import Literal

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from src import data_gaps, rate_limit
from src.chat_events import find_emergency_hospitals, places_first, progress_message
from src.health_safety import detect_urgent_sign
from src.storage.models import MAX_ANSWER_CHARS, MAX_QUESTION_CHARS, PetProfile
from src.tools.health import DEFAULT_RAG_TOP_K, MAX_RAG_TOP_K, MIN_RAG_TOP_K

logger = logging.getLogger(__name__)
router = APIRouter()

CLIENT_ID = re.compile(r"[0-9a-f]{32}")
MAX_TURNS = 40  # 20 questions and answers, the stored conversation's length (src/storage/models.py)
FAILED = "답변을 만드는 중에 문제가 생겼습니다. 잠시 뒤 다시 질문해 주세요."


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=MAX_ANSWER_CHARS)
    route: str | None = None


class Memory(BaseModel):
    """The summary of older turns, as the last result returned it."""
    upto: int = Field(default=0, ge=0)
    summary: str = Field(default="", max_length=MAX_ANSWER_CHARS)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    history: list[Turn] = Field(default_factory=list, max_length=MAX_TURNS)
    memory: Memory = Field(default_factory=Memory)
    profile: PetProfile | None = None
    location: tuple[float, float] | None = None
    top_k: int = Field(default=DEFAULT_RAG_TOP_K, ge=MIN_RAG_TOP_K, le=MAX_RAG_TOP_K)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question is blank")
        return value.strip()

    @field_validator("location")
    @classmethod
    def _on_earth(cls, value):
        if value is not None and not (-90 <= value[0] <= 90 and -180 <= value[1] <= 180):
            raise ValueError("location is out of range")
        return value


def event(kind: str, data: dict) -> str:
    return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def client_network(request: Request) -> str:
    """The first X-Forwarded-For hop (Cloud Run is behind Google's front end), else the peer."""
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "")


def person_of(client_id: str | None, network: str) -> str:
    """This browser's random id (the frontend keeps one in localStorage), else its network address."""
    if client_id and CLIENT_ID.fullmatch(client_id):
        return client_id
    return f"network:{network}"


def urgent_event(notice: str, location) -> str:
    return event("urgent", {"notice": notice, "hospitals": find_emergency_hospitals(location)})


def answer_events(body: ChatRequest, person: str, network: str, agent: str = "") -> Iterator[str]:
    from src.chatbot import chatbot
    from src.tools.history import history_with_summary
    from src.tools.urgency import urgent_notice

    # Set here, in the thread that runs this generator: the deployment check is not counted
    # (rate_limit) and its answers stay out of the data-gap table (data_gaps, in the worker below).
    data_gaps.REQUEST_AGENT.set(agent)
    decision = rate_limit.check(person, network)
    if not decision.allowed:
        if notice := detect_urgent_sign(body.question):
            yield urgent_event(notice, body.location)
        yield event("limited", {"message": rate_limit.message(decision), "wait_minutes": decision.wait_minutes})
        return

    memory = body.memory.model_dump()
    chat_history = history_with_summary([turn.model_dump(exclude_none=True) for turn in body.history], memory)
    if notice := urgent_notice(body.question):
        yield urgent_event(notice, body.location)

    events: queue.Queue = queue.Queue()
    outcome: dict = {}
    streamed: list[str] = []

    def on_token(text: str) -> None:
        streamed.append(text)
        events.put(event("token", {"text": text}))

    def on_step(node: str, update: dict) -> None:
        if text := places_first(node, update):
            events.put(event("places", {"text": text}))
        if not streamed and (message := progress_message(node, update)):
            events.put(event("step", {"message": message}))

    def work() -> None:
        try:
            outcome["result"] = chatbot(body.question, top_k=body.top_k, chat_history=chat_history,
                                        location=body.location, pet_profile=body.profile,
                                        on_token=on_token, on_step=on_step, session_id=person)
        except Exception:  # noqa: BLE001 - reported to the browser as one error event
            logger.exception("chat failed")
            outcome["error"] = True
        finally:
            events.put(None)

    # The worker sees this request's context (data_gaps.REQUEST_AGENT: the deployment check).
    threading.Thread(target=contextvars.copy_context().run, args=(work,), name="chat", daemon=True).start()
    while (item := events.get()) is not None:
        yield item
    if outcome.get("error"):
        yield event("error", {"message": FAILED})
        return
    result = outcome["result"]
    yield event("result", {
        "answer": result["answer"], "route": result["route"],
        "evidence_rows": result.get("evidence_rows", []), "hospital_rows": result.get("hospital_rows", []),
        "safety_notice": result.get("safety_notice") or notice, "abstained": result.get("abstained", False),
        "trace_id": result.get("trace_id"), "memory": memory,
    })


@router.post("/chat")
def chat(body: ChatRequest, request: Request, x_ragdog_client: str | None = Header(default=None)) -> StreamingResponse:
    network = client_network(request)
    agent = request.headers.get("User-Agent") or ""
    return StreamingResponse(answer_events(body, person_of(x_ragdog_client, network), network, agent),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
