"""Answers a guardian marked 👎 and chose to send, kept for review (Day 59: grow the golden set).

The app sends no question or answer text to Langfuse (src/tracing.py), so a 👎 alone says nothing about
what went wrong. Under a 👎 the guardian can pick a reason (REASONS, a Langfuse score) and, only if they
tick the consent box, send this question and answer. The question is stored masked (src/pii.py), as the
model saw it. Rows go to the Supabase table ragdog_feedback, closed to the public REST API like the
search tables (supabase_store.lock_from_data_api). Without SUPABASE_DB_URL nothing is stored and the
page does not offer to send.
"""

from __future__ import annotations

import json
import logging
import threading

from src import settings
from src.pii import mask_pii

logger = logging.getLogger(__name__)

TABLE = "ragdog_feedback"
REASONS = ("틀린 정보", "질문과 다른 답", "근거가 부족해요", "너무 길어요", "기타")
MAX_TEXT = 4000
_ready = threading.Event()


def enabled() -> bool:
    return bool(settings.get_setting("SUPABASE_DB_URL"))


def _connect():
    from src.supabase_store import connector, lock_from_data_api

    conn = connector(settings.get_setting("SUPABASE_DB_URL"))()
    if not _ready.is_set():
        conn.execute(f"""create table if not exists {TABLE} (
            id bigint generated always as identity primary key,
            created_at timestamptz not null default now(),
            trace_id text, route text, reason text,
            question text not null, answer text not null, evidence jsonb)""")
        lock_from_data_api(conn, TABLE)
        _ready.set()
    return conn


def evidence_summary(row: dict) -> dict:
    """What identifies an evidence row (labels, source, page), without its long texts (the
    consultation and the vet answer stay in the private data, not in this table)."""
    return {key: value for key, value in row.items()
            if isinstance(value, (int, float)) or (isinstance(value, str) and len(value) <= 80)}


def save_review(*, question: str, answer: str, reason: str | None, route: str | None,
                trace_id: str | None, evidence: list | None = None) -> bool:
    """Store one consented 👎 answer; False (logged) when the database is not there or fails."""
    if not enabled():
        return False
    try:
        with _connect() as conn:
            conn.execute(
                f"insert into {TABLE} (trace_id, route, reason, question, answer, evidence) values (%s, %s, %s, %s, %s, %s)",
                [trace_id, route, reason, mask_pii(question)[:MAX_TEXT], str(answer)[:MAX_TEXT],
                 json.dumps(evidence or [], ensure_ascii=False)])
        return True
    except Exception:  # noqa: BLE001 - feedback must never break the chat page
        logger.warning("feedback review not saved", exc_info=True)
        return False
