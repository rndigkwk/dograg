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

5. After the result, for a health answer: new facts about the dog to offer for saving
   (src/tools/profile.suggest_memory), when the frontend asks (suggest_memory: its stored profile is
   loaded) and the guardian has not declined the same facts. Sent last, so it never delays the answer.

Events (text/event-stream, one JSON object each): step {message} · places {text} · urgent
{notice, hospitals} · token {text} · result {...} · memory {profile, new_facts, summary, update} ·
limited {message, wait_minutes} · error {message}.
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

from src import auth, data_gaps, rate_limit
from src.chat_events import find_emergency_hospitals, places_first, progress_message
from src.health_safety import detect_urgent_sign
from src.pii import mask_pii
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


class Note(BaseModel):
    """A consultation note the guardian saved in their account (ADR-0009), as the browser sends it."""
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    text: str = Field(min_length=1, max_length=300)

    @field_validator("date")
    @classmethod
    def _a_real_date(cls, value: str) -> str:
        from datetime import date

        date.fromisoformat(value)  # ValueError -> 422
        return value


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    history: list[Turn] = Field(default_factory=list, max_length=MAX_TURNS)
    memory: Memory = Field(default_factory=Memory)
    profile: PetProfile | None = None
    location: tuple[float, float] | None = None
    top_k: int = Field(default=DEFAULT_RAG_TOP_K, ge=MIN_RAG_TOP_K, le=MAX_RAG_TOP_K)
    # The frontend asks for a memory suggestion only once its stored profile is loaded (a suggestion
    # against an empty stand-in would replace the stored profile, 2026-10-15), and lists the facts the
    # guardian declined this session so they are not offered again.
    suggest_memory: bool = False
    declined_memory: list[str] = Field(default_factory=list, max_length=20)
    # "report": the report page (web /reports) asks the five PDF reports directly, without the
    # classification call; anything else is classified as usual.
    route: Literal["report"] | None = None
    # The latest notes, sent only when a signed-in guardian turned "지난 상담 기억" on (ADR-0009).
    notes: list[Note] = Field(default_factory=list, max_length=5)

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
    """The client address Cloud Run's front end saw (src/rate_limit.forwarded_client), else the peer."""
    return rate_limit.forwarded_client(request.headers.get("X-Forwarded-For"), request.client.host if request.client else "")


def person_of(client_id: str | None, network: str, authorization: str | None = None) -> str:
    """Who is asking: the signed-in account (a verified Supabase token, src/auth.py), else this
    browser's random id (the frontend keeps one in localStorage), else its network address."""
    if user := auth.user_id(authorization):
        return f"user:{user}"
    if client_id and CLIENT_ID.fullmatch(client_id):
        return client_id
    return f"network:{network}"


def urgent_event(notice: str, location) -> str:
    return event("urgent", {"notice": notice, "hospitals": find_emergency_hospitals(location)})


def answer_events(body: ChatRequest, person: str, network: str, agent: str = "", trusted: bool = False) -> Iterator[str]:
    from src.chatbot import chatbot
    from src.tools.history import history_with_summary
    from src.tools.urgency import urgent_notice

    # Set here, in the thread that runs this generator: the deployment check is not counted
    # (rate_limit) and its answers stay out of the data-gap table (data_gaps, in the worker below).
    data_gaps.REQUEST_AGENT.set(agent)
    rate_limit.TRUSTED_CHECK.set(trusted)  # the check token, verified by the route
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
                                        on_token=on_token, on_step=on_step, session_id=person,
                                        force_route="analysis" if body.route == "report" else None,
                                        notes=[Note(date=n.date, text=mask_pii(n.text)) for n in body.notes])
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
    if body.suggest_memory and result["route"] == "rag":
        yield from memory_event(body)


def memory_event(body: ChatRequest) -> Iterator[str]:
    from src.tools.profile import suggest_memory

    try:
        suggestion = suggest_memory(body.profile, body.question)
    except Exception:  # noqa: BLE001 - optional: the answer is already out
        logger.warning("memory suggestion failed", exc_info=True)
        return
    if suggestion is not None and suggestion.summary not in body.declined_memory:
        yield event("memory", {"profile": suggestion.profile.model_dump(mode="json", exclude_defaults=True),
                               "new_facts": suggestion.new_facts, "summary": suggestion.summary,
                               "update": body.profile is not None and not body.profile.is_empty()})


@router.post("/chat")
def chat(body: ChatRequest, request: Request, x_ragdog_client: str | None = Header(default=None),
         x_ragdog_check: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> StreamingResponse:
    network = client_network(request)
    agent = request.headers.get("User-Agent") or ""
    trusted = rate_limit.trusted_check(x_ragdog_check)
    person = person_of(x_ragdog_client, network, authorization)
    return StreamingResponse(answer_events(body, person, network, agent, trusted),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
