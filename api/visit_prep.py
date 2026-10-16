"""POST /visit-prep: the visit-prep report as a stream of progress events (ADR-0008, P1).

    POST /visit-prep                      {consultation, region?, profile?} -> step* · paused | result
    POST /visit-prep/{thread_id}/answer   {answer} ("" to skip)              -> step* · result

The same run as the page (src/visit_prep_runs.py): one team at a time on the server, 10-20 model
calls and one to two minutes per report. ADR-0008 planned a job and polling; one streamed request
does the same with less to keep (no job table). A run may stop to ask the guardian; it then ends
with `paused` and its questions, and waits for the answer for 30 minutes in src/visit_prep_store.py
(Supabase on the deployed server since 2026-10-16), so the answer may reach any instance (Cloud Run
max-instances=2). One team at a time is still per instance.

Limits: a report counts as one question for src/rate_limit.py, and each person (browser) gets
REPORTS_PER_DAY reports (the page gave two per browser session). Answering a paused run is not a
new report. Events: urgent {notice} · step {line} · paused {thread_id, questions} · result {...} ·
busy {message} · limited {message, wait_minutes} · error {message}.
"""

from __future__ import annotations

import contextvars
import logging
import queue
import threading
from collections.abc import Iterator

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api.chat import client_network, event, person_of
from src import data_gaps, rate_limit, settings, tracing, visit_prep_runs, visit_prep_store
from src.health_safety import detect_urgent_sign
from team.core.config import MAX_ANSWER_CHARS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/visit-prep", tags=["visit-prep"])

REPORTS_PER_DAY = 2

URGENT = "응급 징후가 의심됩니다. 보고서를 기다리지 말고 지금 가까운 동물병원에 연락하세요."
BUSY = "다른 사용자의 보고서를 만드는 중입니다. 1~2분 뒤에 다시 시도해 주세요."
FAILED = "보고서를 만들지 못했습니다. 잠시 뒤 다시 시도해 주세요."
REPORTS_USED = f"방문 준비 보고서는 하루 {REPORTS_PER_DAY}번까지 만들 수 있습니다. 내일 다시 만들어 주세요."

# Report counts, the runs waiting for an answer and their owners live in src/visit_prep_store.py:
# Supabase when the database is configured (shared by every instance, kept across deploys), else memory.


class StartRequest(BaseModel):
    consultation: str = Field(min_length=1, max_length=visit_prep_runs.MAX_CONSULTATION_CHARS)
    region: str = Field(default="", max_length=30)
    profile: str = Field(default="", max_length=300)
    # The guardian's position (the page's "현재 위치 사용"): the nearest hospitals instead of a region's.
    location: tuple[float, float] | None = None

    @field_validator("location")
    @classmethod
    def _in_korea(cls, value):
        if value is not None and not (33 <= value[0] <= 39 and 124 <= value[1] <= 132):
            raise ValueError("location is outside Korea")
        return value


class AnswerRequest(BaseModel):
    answer: str = Field(default="", max_length=MAX_ANSWER_CHARS)


def _take_report(person: str, now: float) -> bool:
    return visit_prep_store.store().take_report(person, REPORTS_PER_DAY, now)


def _run_team(person: str, location: tuple[float, float] | None = None):
    def run_team(consultation, region, profile, run_dir, on_step, *, thread_id, resume=None):
        from team.main import (
            run,  # imported on use: the chat routes do not need the agents
        )

        # A resumed run keeps the location in its saved state; only a new run passes it.
        return run(consultation, region, profile, location=location, run_dir=run_dir, on_step=on_step,
                   session=tracing.session_id(person), ask=True,
                   checkpointer=visit_prep_runs.team_checkpointer(), thread_id=thread_id, resume=resume)
    return run_team


def _stream(person: str, consultation: str, region: str, profile: str, agent: str,
            pending: dict | None = None, answer: str | None = None,
            location: tuple[float, float] | None = None) -> Iterator[str]:
    data_gaps.REQUEST_AGENT.set(agent)
    if pending is None and detect_urgent_sign(consultation):
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

    def work() -> None:
        try:
            outcome["value"] = visit_prep_runs.generate(
                consultation, region, profile, run_team=_run_team(person, location), prepare=visit_prep_runs.prepare_search,
                on_line=lambda line: events.put(event("step", {"line": line})), pending=pending, answer=answer)
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
        yield event("error", {"message": FAILED})
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
    return _response(_stream(person, consultation, body.region.strip(), body.profile.strip(), agent, location=body.location))


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
    agent = request.headers.get("User-Agent") or ""
    return _response(_stream(person, pending["consultation"], pending["region"], pending["profile"], agent,
                             pending=pending, answer=body.answer.strip()))
