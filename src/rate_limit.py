"""How many questions one person may ask the deployed app (user decision 2026-10-15).

The app has no login and every question costs model calls, so someone asking in a loop spends
the OpenAI budget. A person here is a browser: a random id kept in its localStorage
(src/storage/snapshot.CLIENT_KEY), PERSON_LIMITS per hour and per day. Clearing the browser makes a
new id, so the network (client IP) has its own, looser limits, NETWORK_LIMITS: an academy or an
office shares one address, and a person limit on the IP alone would make them share 10 questions.

Only hashes are stored (salted with the database URL, a secret), with the time, in the Supabase
table ragdog_rate_limit, closed to the public REST API; rows older than KEEP_HOURS are deleted.
Counted: a chat question and a visit-prep report. Not counted: local runs, tests and evaluation
scripts (they call the code, not the page), and the deployment check (src/data_gaps.from_check).
When the database fails the question is allowed: the limit must never stop the app.
"""

from __future__ import annotations

import hashlib
import logging
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src import data_gaps, settings

logger = logging.getLogger(__name__)

TABLE = "ragdog_rate_limit"
PERSON_LIMITS = ((timedelta(hours=1), 10), (timedelta(days=1), 30))
NETWORK_LIMITS = ((timedelta(hours=1), 60), (timedelta(days=1), 200))
KEEP_HOURS = 48
CLEAN_EVERY = 20  # delete expired rows on about one check in this many
_ready = False


@dataclass
class Decision:
    allowed: bool
    wait_minutes: int = 0
    per_hour: bool = True  # which limit was reached


def enabled() -> bool:
    return settings.deployed() and bool(settings.get_setting("SUPABASE_DB_URL"))


def _hash(kind: str, value: str) -> str:
    salt = hashlib.sha256((settings.get_setting("SUPABASE_DB_URL") or "").encode()).hexdigest()
    return hashlib.sha256(f"{salt}:{kind}:{value}".encode()).hexdigest()[:32]


def client_network() -> str:
    """The client's address: the first X-Forwarded-For hop (both deployments sit behind a proxy),
    else Streamlit's peer address; empty outside a Streamlit session."""
    try:
        import streamlit as st

        forwarded = (st.context.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        return forwarded or (st.context.ip_address or "")
    except Exception:  # noqa: BLE001 - no Streamlit session
        return ""


def _counts(conn, person: str, network: str, now: datetime) -> list[tuple[int, datetime | None]]:
    """For each (key, window) of PERSON_LIMITS then NETWORK_LIMITS: questions in it and the oldest one's
    time, in one query (one round trip; the check runs before every answer)."""
    parts, params = [], []
    for column, key, limits in (("person", person, PERSON_LIMITS), ("network", network, NETWORK_LIMITS)):
        for window, _ in limits:
            condition = f"{column} = %s and at > %s"
            parts += [f"count(*) filter (where {condition})", f"min(at) filter (where {condition})"]
            params += [key, now - window, key, now - window]
    row = conn.execute(f"select {', '.join(parts)} from {TABLE} where person = %s or network = %s",
                       [*params, person, network]).fetchone()
    return [(row[i], row[i + 1]) for i in range(0, len(row), 2)]


def check(person: str, network: str | None = None) -> Decision:
    """Count one question for this person and network, or refuse it with the wait."""
    global _ready
    if not enabled() or data_gaps.from_check():
        return Decision(True)
    network = client_network() if network is None else network
    person_key, network_key = _hash("person", person), _hash("network", network) if network else ""
    try:
        from src.supabase_store import connector, lock_from_data_api

        with connector(settings.get_setting("SUPABASE_DB_URL"))() as conn:
            if not _ready:
                conn.execute(f"""create table if not exists {TABLE} (
                    id bigint generated always as identity primary key,
                    at timestamptz not null default now(), person text not null, network text not null)""")
                conn.execute(f"create index if not exists {TABLE}_person_at on {TABLE} (person, at)")
                conn.execute(f"create index if not exists {TABLE}_network_at on {TABLE} (network, at)")
                lock_from_data_api(conn, TABLE)
                _ready = True
            now = datetime.now(timezone.utc)
            if random.randrange(CLEAN_EVERY) == 0:
                conn.execute(f"delete from {TABLE} where at < %s", [now - timedelta(hours=KEEP_HOURS)])
            limits = [*PERSON_LIMITS, *(NETWORK_LIMITS if network_key else ())]
            for (window, limit), (count, oldest) in zip(limits, _counts(conn, person_key, network_key, now)):
                if count >= limit:
                    wait = max(1, math.ceil((oldest + window - now).total_seconds() / 60))
                    return Decision(False, wait, window <= timedelta(hours=1))
            conn.execute(f"insert into {TABLE} (person, network) values (%s, %s)", [person_key, network_key])
        return Decision(True)
    except Exception:  # noqa: BLE001 - a broken limit must not stop the app
        logger.warning("rate limit check failed; question allowed", exc_info=True)
        return Decision(True)


def message(decision: Decision) -> str:
    (_, hourly), (_, daily) = PERSON_LIMITS
    when = f"약 {decision.wait_minutes}분 뒤" if decision.wait_minutes < 90 else f"약 {math.ceil(decision.wait_minutes / 60)}시간 뒤"
    return (f"질문이 많아 잠시 쉬어 갈게요. 한 사람이 한 시간에 {hourly}번, 하루에 {daily}번까지 물어볼 수 있어요. "
            f"{when}에 다시 질문해 주세요. 응급 증상이라면 기다리지 말고 가까운 동물병원에 바로 연락하세요.")
