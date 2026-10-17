"""POST /memory/note: a consultation note for a signed-in guardian to save (ADR-0009, 2026-10-17).

    POST /memory/note   {question, answer}  ->  {note, date}

Signed-in only (a verified Supabase token, src/auth.py): notes live in the account
(ragdog_user_notes), which the browser writes itself; this route only writes the text and stores
nothing. One model call, counted like a question (src/rate_limit.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from api.chat import client_network
from src import auth, rate_limit
from src.storage.models import MAX_ANSWER_CHARS, MAX_QUESTION_CHARS

router = APIRouter(prefix="/memory", tags=["memory"])


class NoteRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    answer: str = Field(min_length=1, max_length=MAX_ANSWER_CHARS)


@router.post("/note")
def note(body: NoteRequest, request: Request, authorization: str | None = Header(default=None)) -> dict:
    from src.tools import notes

    user = auth.user_id(authorization)
    if not user:
        raise HTTPException(401, "로그인한 경우에만 상담을 기억할 수 있습니다.")
    decision = rate_limit.check(f"user:{user}", client_network(request))
    if not decision.allowed:
        raise HTTPException(429, rate_limit.message(decision))
    text = notes.make_note(body.question, body.answer)
    if not text:
        raise HTTPException(503, "지금은 기록을 만들 수 없습니다. 잠시 뒤 다시 시도해 주세요.")
    return {"note": text, "date": notes.today().isoformat()}
