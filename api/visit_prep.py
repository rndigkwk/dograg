"""POST /visit-prep: the visit-prep report as a stream of progress events (ADR-0008, P1).

    POST /visit-prep                      {consultation, region?, profile?, notes?} -> step* · paused | result
    POST /visit-prep/{thread_id}/answer   {answer} ("" to skip)              -> step* · result
    POST /visit-prep/{thread_id}/retry    {}                                  -> step* · paused | result

The same run as the page (src/visit_prep_runs.py): one team at a time on the server, 10-20 model
calls and one to two minutes per report. ADR-0008 planned a job and polling; one streamed request
does the same with less to keep (no job table). A run may stop to ask the guardian; it then ends
with `paused` and its questions, and waits for the answer for 30 minutes in src/visit_prep_store.py
(Supabase on the deployed server since 2026-10-16), so the answer may reach any instance (Cloud Run
max-instances=2). One team at a time is still per instance.

Limits: a report counts as one question for src/rate_limit.py, and each person (browser) gets
REPORTS_PER_DAY reports (the page gave two per browser session). Answering a paused run is not a
new report. Events: urgent {notice} · step {line} · paused {thread_id, questions} · result {...} ·
busy {message} · limited {message, wait_minutes} · error {message, thread_id?}.

A run that fails (a model or search error mid-run) keeps its checkpoints: the error event carries
its thread_id, and POST .../retry goes on from the last finished step (team/main.py retry), for
MAX_RETRIES tries within the same 30 minutes as a pause. A retry is not a new report.
"""

from __future__ import annotations

import contextvars
import logging
import queue
import threading
import uuid
from collections.abc import Iterator

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api.chat import Note, client_network, event, person_of
from src import (
    data_gaps,
    rate_limit,
    settings,
    tracing,
    visit_prep_runs,
    visit_prep_store,
)
from src.health_safety import SAVED_NOTES_HEADING, detect_urgent_sign, todays_text
from src.pii import mask_pii
from src.tools.health import notes_context
from team.core.config import MAX_ANSWER_CHARS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/visit-prep", tags=["visit-prep"])

REPORTS_PER_DAY = 2

URGENT = "응급 징후가 의심됩니다. 보고서를 기다리지 말고 지금 가까운 동물병원에 연락하세요."
BUSY = "다른 사용자의 보고서를 만드는 중입니다. 1~2분 뒤에 다시 시도해 주세요."
FAILED = "보고서를 만들지 못했습니다. 잠시 뒤 다시 시도해 주세요."
FAILED_RETRY = "보고서를 만들다 멈췄습니다. 30분 안에 '이어서 만들기'를 누르면 끝낸 단계부터 이어서 만듭니다."
NOT_FAILED = "이어서 만들 보고서가 없습니다. 다시 만들어 주세요."
MAX_RETRIES = 2  # each try is 10-20 model calls that the report limit does not count
REPORTS_USED = f"방문 준비 보고서는 하루 {REPORTS_PER_DAY}번까지 만들 수 있습니다. 내일 다시 만들어 주세요."

# Report counts, the runs waiting for an answer and their owners live in src/visit_prep_store.py:
# Supabase when the database is configured (shared by every instance, kept across deploys), else memory.


class StartRequest(BaseModel):
    consultation: str = Field(min_length=1, max_length=visit_prep_runs.MAX_CONSULTATION_CHARS)
    region: str = Field(default="", max_length=30)
    profile: str = Field(default="", max_length=300)
    # The guardian's position (the page's "현재 위치 사용"): the nearest hospitals instead of a region's.
    location: tuple[float, float] | None = None
    # Saved consultation notes the guardian ticked for this report (ADR-0009; none unless chosen).
    notes: list[Note] = Field(default_factory=list, max_length=5)

    @field_validator("location")
    @classmethod
    def _in_korea(cls, value):
        if value is not None and not (33 <= value[0] <= 39 and 124 <= value[1] <= 132):
            raise ValueError("location is outside Korea")
        return value


class AnswerRequest(BaseModel):
    answer: str = Field(default="", max_length=MAX_ANSWER_CHARS)


def with_notes(consultation: str, notes: list[Note]) -> str:
    """The consultation the team reads: the guardian's text, then the notes they chose, with each
    note's age written out (src/tools/health.notes_context) and personal details masked as in chat.
    The urgent-sign check reads the guardian's own text only."""
    if not notes:
        return consultation
    masked = [Note(date=note.date, text=mask_pii(note.text)) for note in notes]
    return f"{consultation}\n\n{SAVED_NOTES_HEADING}\n{notes_context(masked)}"


def _take_report(person: str, now: float) -> bool:
    return visit_prep_store.store().take_report(person, REPORTS_PER_DAY, now)


def _run_team(person: str, location: tuple[float, float] | None = None):
    def run_team(consultation, region, profile, run_dir, on_step, *, thread_id, resume=None, retry=False):
        from team.main import (
            run,  # imported on use: the chat routes do not need the agents
        )

        # A resumed run keeps the location in its saved state; only a new run passes it.
        return run(consultation, region, profile, location=location, run_dir=run_dir, on_step=on_step,
                   session=tracing.session_id(person), ask=True,
                   checkpointer=visit_prep_runs.team_checkpointer(), thread_id=thread_id, resume=resume, retry=retry)
    return run_team


def _stream(person: str, consultation: str, region: str, profile: str, agent: str,
            pending: dict | None = None, answer: str | None = None,
            location: tuple[float, float] | None = None, retry: bool = False) -> Iterator[str]:
    data_gaps.REQUEST_AGENT.set(agent)
    if pending is None and detect_urgent_sign(todays_text(consultation)):
        yield event("urgent", {"notice": URGENT})
    if not visit_prep_runs.team_lock().acquire(blocking=False):
        if pending is not None:  # still waiting: the guardian can send the answer again
            visit_prep_store.store().put_back(pending["thread_id"], person, pending, pending["paused_at"])
        else:  # not run, so not used up
            visit_prep_store.store().refund_report(person)
        yield event("busy", {"message": BUSY})
        return
    events: queue.Queue = queue.Queue()
    outcome: dict = {}
    thread_id = pending["thread_id"] if pending else uuid.uuid4().hex
    lines: list[str] = []  # this try's progress, kept with a failed run

    def on_line(line: str) -> None:
        lines.append(line)
        events.put(event("step", {"line": line}))

    def work() -> None:
        try:
            outcome["value"] = visit_prep_runs.generate(
                consultation, region, profile, run_team=_run_team(person, location), prepare=visit_prep_runs.prepare_search,
                on_line=on_line, pending=pending, answer=answer, retry=retry, thread_id=thread_id)
        except Exception:  # noqa: BLE001 - reported as one error event
            logger.exception("visit-prep run failed")
        finally:
            visit_prep_runs.team_lock().release()
            events.put(None)

    threading.Thread(target=contextvars.copy_context().run, args=(work,), name="visit-prep", daemon=True).start()
    while (item := events.get()) is not None:
        yield item
    value = outcome.get("value")
    if value is None:
        tries = (pending or {}).get("retries", 0) + (1 if retry else 0)
        if tries >= MAX_RETRIES:
            visit_prep_store.store().checkpointer().delete_thread(thread_id)  # no more tries: its checkpoints go now
            yield event("error", {"message": FAILED})
            return
        steps = [*(pending or {}).get("steps", []), *lines] or [visit_prep_runs.PREPARED]
        failed = {"failed": True, "thread_id": thread_id, "consultation": consultation, "region": region,
                  "profile": profile, "steps": steps, "seconds": (pending or {}).get("seconds", 0), "retries": tries}
        visit_prep_store.store().save_paused(thread_id, person, failed, visit_prep_store.now())
        yield event("error", {"message": FAILED_RETRY, "thread_id": thread_id})
    elif value["paused"]:
        visit_prep_store.store().save_paused(value["thread_id"], person, value, visit_prep_store.now())
        yield event("paused", {"thread_id": value["thread_id"], "questions": value["questions"]})
    else:
        yield event("result", {key: value[key] for key in
                               ("report", "passed", "status", "round", "steps", "urgent", "seconds", "answered")})


def _response(stream: Iterator[str]) -> StreamingResponse:
    return StreamingResponse(stream, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _refused(kind: str, data: dict) -> StreamingResponse:
    return _response(iter([event(kind, data)]))


@router.post("")
def start(body: StartRequest, request: Request, x_ragdog_client: str | None = Header(default=None),
          x_ragdog_check: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> StreamingResponse:
    if not settings.get_openai_api_key():
        raise HTTPException(503, "OpenAI API 키가 없어 보고서를 만들 수 없습니다.")
    network = client_network(request)
    person = person_of(x_ragdog_client, network, authorization)
    consultation = body.consultation.strip()
    if not consultation:
        raise HTTPException(422, "상담 내용을 적어 주세요.")
    agent = request.headers.get("User-Agent") or ""
    data_gaps.REQUEST_AGENT.set(agent)
    rate_limit.TRUSTED_CHECK.set(rate_limit.trusted_check(x_ragdog_check))
    decision = rate_limit.check(person, network)
    if not decision.allowed:
        return _refused("limited", {"message": rate_limit.message(decision), "wait_minutes": decision.wait_minutes})
    visit_prep_store.store().expire(visit_prep_store.now())
    if not _take_report(person, visit_prep_store.now()):
        return _refused("limited", {"message": REPORTS_USED, "wait_minutes": None})
    return _response(_stream(person, with_notes(consultation, body.notes), body.region.strip(), body.profile.strip(), agent,
                             location=body.location))


@router.post("/{thread_id}/answer")
def answer(thread_id: str, body: AnswerRequest, request: Request, x_ragdog_client: str | None = Header(default=None),
           authorization: str | None = Header(default=None)) -> StreamingResponse:
    # This server's own list only: the store owns the checkpoints, and another instance may be
    # resuming a run that paused here.
    visit_prep_runs.forget_expired_runs(delete=False)
    store, now = visit_prep_store.store(), visit_prep_store.now()
    store.expire(now)  # paused runs nobody answered within 30 minutes, with their checkpoints
    person = person_of(x_ragdog_client, client_network(request), authorization)
    pending = store.take_paused(thread_id, person, now)  # the owner's, once
    if pending is None:  # unknown, expired (30 minutes), already answered, or someone else's run
        raise HTTPException(404, "답변을 기다리는 보고서가 없습니다. 다시 만들어 주세요.")
    if pending.get("failed"):  # a failed run is continued, not answered
        store.put_back(thread_id, person, pending, pending.get("paused_at", now))
        raise HTTPException(409, "멈춘 보고서입니다. '이어서 만들기'를 눌러 주세요.")
    agent = request.headers.get("User-Agent") or ""
    return _response(_stream(person, pending["consultation"], pending["region"], pending["profile"], agent,
                             pending=pending, answer=body.answer.strip()))


@router.post("/{thread_id}/retry")
def retry(thread_id: str, request: Request, x_ragdog_client: str | None = Header(default=None),
          authorization: str | None = Header(default=None)) -> StreamingResponse:
    """Go on with the owner's failed run from its last finished step."""
    visit_prep_runs.forget_expired_runs(delete=False)
    store, now = visit_prep_store.store(), visit_prep_store.now()
    store.expire(now)
    person = person_of(x_ragdog_client, client_network(request), authorization)
    pending = store.take_paused(thread_id, person, now)
    if pending is None or not pending.get("failed"):
        if pending is not None:  # a pause waiting for its answer: leave it
            store.put_back(thread_id, person, pending, pending.get("paused_at", now))
        raise HTTPException(404, NOT_FAILED)
    agent = request.headers.get("User-Agent") or ""
    return _response(_stream(person, pending["consultation"], pending["region"], pending["profile"], agent,
                             pending=pending, retry=True))
