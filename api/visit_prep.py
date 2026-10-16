"""POST /visit-prep: the visit-prep report as a stream of progress events (ADR-0008, P1).

    POST /visit-prep                      {consultation, region?, profile?} -> step* · paused | result
    POST /visit-prep/{thread_id}/answer   {answer} ("" to skip)              -> step* · result

The same run as the page (src/visit_prep_runs.py): one team at a time on the server, 10-20 model
calls and one to two minutes per report. ADR-0008 planned a job and polling; one streamed request
does the same with less to keep (no job table). A run may stop to ask the guardian; it then ends
with `paused` and its questions, and waits in this server's memory for the answer (30 minutes).
So the API service must run as one instance (Cloud Run max-instances=1): the answer has to reach
the server holding the paused run.

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
import time
from collections.abc import Iterator

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.chat import client_network, event, person_of
from src import data_gaps, rate_limit, settings, tracing, visit_prep_runs
from src.health_safety import detect_urgent_sign
from team.core.config import MAX_ANSWER_CHARS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/visit-prep", tags=["visit-prep"])

REPORTS_PER_DAY = 2

URGENT = "응급 징후가 의심됩니다. 보고서를 기다리지 말고 지금 가까운 동물병원에 연락하세요."
BUSY = "다른 사용자의 보고서를 만드는 중입니다. 1~2분 뒤에 다시 시도해 주세요."
FAILED = "보고서를 만들지 못했습니다. 잠시 뒤 다시 시도해 주세요."
REPORTS_USED = f"방문 준비 보고서는 하루 {REPORTS_PER_DAY}번까지 만들 수 있습니다. 내일 다시 만들어 주세요."

# person -> times a report was started; {thread_id: who started it, to resume it}. In memory, like the paused runs.
_reports: dict[str, list[float]] = {}
_owners: dict[str, str] = {}
_pending: dict[str, dict] = {}
_bookkeeping = threading.Lock()


class StartRequest(BaseModel):
    consultation: str = Field(min_length=1, max_length=visit_prep_runs.MAX_CONSULTATION_CHARS)
    region: str = Field(default="", max_length=30)
    profile: str = Field(default="", max_length=300)


class AnswerRequest(BaseModel):
    answer: str = Field(default="", max_length=MAX_ANSWER_CHARS)


def _take_report(person: str, now: float) -> bool:
    with _bookkeeping:
        recent = [t for t in _reports.get(person, []) if now - t < 24 * 3600]
        if len(recent) >= REPORTS_PER_DAY:
            _reports[person] = recent
            return False
        _reports[person] = [*recent, now]
        return True


def _run_team(person: str):
    def run_team(consultation, region, profile, run_dir, on_step, *, thread_id, resume=None):
        from team.main import (
            run,  # imported on use: the chat routes do not need the agents
        )

        return run(consultation, region, profile, run_dir=run_dir, on_step=on_step,
                   session=tracing.session_id(person), ask=True,
                   checkpointer=visit_prep_runs.team_checkpointer(), thread_id=thread_id, resume=resume)
    return run_team


def _stream(person: str, consultation: str, region: str, profile: str, agent: str,
            pending: dict | None = None, answer: str | None = None) -> Iterator[str]:
    data_gaps.REQUEST_AGENT.set(agent)
    if pending is None and detect_urgent_sign(consultation):
        yield event("urgent", {"notice": URGENT})
    if not visit_prep_runs.team_lock().acquire(blocking=False):
        with _bookkeeping:
            if pending is not None:  # still waiting: the guardian can send the answer again
                _pending[pending["thread_id"]] = pending
            elif _reports.get(person):  # not run, so not used up
                _reports[person].pop()
        yield event("busy", {"message": BUSY})
        return
    events: queue.Queue = queue.Queue()
    outcome: dict = {}

    def work() -> None:
        try:
            outcome["value"] = visit_prep_runs.generate(
                consultation, region, profile, run_team=_run_team(person), prepare=visit_prep_runs.prepare_search,
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
        with _bookkeeping:
            _owners[value["thread_id"]] = person
            _pending[value["thread_id"]] = value
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
    if not _take_report(person, time.time()):
        return _refused("limited", {"message": REPORTS_USED, "wait_minutes": None})
    return _response(_stream(person, consultation, body.region.strip(), body.profile.strip(), agent))


@router.post("/{thread_id}/answer")
def answer(thread_id: str, body: AnswerRequest, request: Request, x_ragdog_client: str | None = Header(default=None),
           authorization: str | None = Header(default=None)) -> StreamingResponse:
    visit_prep_runs.forget_expired_runs()
    person = person_of(x_ragdog_client, client_network(request), authorization)
    with _bookkeeping:
        for stale in [key for key in _pending if key not in visit_prep_runs.paused_runs()]:
            _pending.pop(stale, None)
            _owners.pop(stale, None)
        pending = _pending.get(thread_id) if _owners.get(thread_id) == person else None
        if pending is not None:
            _pending.pop(thread_id)
    if pending is None:  # unknown, expired (30 minutes), already answered, or someone else's run
        raise HTTPException(404, "답변을 기다리는 보고서가 없습니다. 다시 만들어 주세요.")
    agent = request.headers.get("User-Agent") or ""
    return _response(_stream(person, pending["consultation"], pending["region"], pending["profile"], agent,
                             pending=pending, answer=body.answer.strip()))
