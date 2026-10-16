"""How many questions one person may ask the deployed app (user decision 2026-10-15).

The app has no login and every question costs model calls, so someone asking in a loop spends
the OpenAI budget. A person here is a browser: a random id kept in its localStorage
(src/storage/snapshot.CLIENT_KEY), PERSON_LIMITS per hour and per day. Clearing the browser makes a
new id, so the network (client IP) has its own, looser limits, NETWORK_LIMITS: an academy or an
office shares one address, and a person limit on the IP alone would make them share 10 questions.

Where it is counted: with SUPABASE_DB_URL, in the Supabase table ragdog_rate_limit (salted hashes
and times only, closed to the public REST API, rows older than KEEP_HOURS deleted), so every
instance and restart shares the count. Without it (the Streamlit backup on its own Chroma search,
2026-10-15) or while the database fails, in this process's memory: the same limits, reset when the
app restarts or sleeps, which is enough to stop someone asking in a loop.
Counted: a chat question and a visit-prep report. Not counted: local runs, tests and in-process
evaluation scripts (they call the code, not the page), and requests carrying the check token
(TRUSTED_CHECK: X-RagDog-Check equal to the secret RAGDOG_CHECK_TOKEN, for API evaluations). Until
2026-10-16 a user agent containing "RagDogCheck" skipped the limit; anyone can set a user agent, so
that let any caller ask without limit (docs/security/2026-10-16-pre-login-review.md).

The network is the client address as the proxy saw it: the PROXY_HOPS-th X-Forwarded-For entry from
the right. The leftmost entries are whatever the caller sent, so reading the first one (as this did
until 2026-10-16) let a caller pick a new network per question.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import random
import secrets
import threading
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src import settings

logger = logging.getLogger(__name__)

TABLE = "ragdog_rate_limit"
PERSON_LIMITS = ((timedelta(hours=1), 10), (timedelta(days=1), 30))
NETWORK_LIMITS = ((timedelta(hours=1), 60), (timedelta(days=1), 200))
KEEP_HOURS = 48
CLEAN_EVERY = 20  # delete expired rows on about one check in this many
_ready = False
# The in-memory count: hash -> times, shared by every session of this process.
_memory: dict[str, list[datetime]] = {}
_memory_lock = threading.Lock()
_PROCESS_SALT = secrets.token_hex(16)  # without a database URL: never stored, changes on restart
# Set by the API for this request when it carried the check token (trusted_check).
TRUSTED_CHECK: ContextVar[bool] = ContextVar("ragdog_trusted_check", default=False)


@dataclass
class Decision:
    allowed: bool
    wait_minutes: int = 0
    per_hour: bool = True  # which limit was reached


def enabled() -> bool:
    return settings.deployed()


def trusted_check(token: str | None) -> bool:
    """Whether a request's X-RagDog-Check header is the secret RAGDOG_CHECK_TOKEN (none set: never)."""
    secret = settings.get_setting("RAGDOG_CHECK_TOKEN") or ""
    return bool(secret and token) and hmac.compare_digest(token.encode(), secret.encode())


def proxy_hops() -> int:
    """How many X-Forwarded-For entries the deployment's own proxies add (Cloud Run: 1)."""
    try:
        return max(1, int(settings.get_setting("RAGDOG_PROXY_HOPS") or 1))
    except ValueError:
        return 1


def forwarded_client(header: str | None, peer: str = "") -> str:
    """The client address the proxy saw: the proxy_hops()-th X-Forwarded-For entry from the right.
    Entries to its left came from the caller and are not trusted."""
    entries = [entry.strip() for entry in (header or "").split(",") if entry.strip()]
    hops = proxy_hops()
    if len(entries) >= hops:
        return entries[-hops]
    return peer or (entries[0] if entries else "")


def _hash(kind: str, value: str) -> str:
    url = settings.get_setting("SUPABASE_DB_URL")
    salt = hashlib.sha256(url.encode()).hexdigest() if url else _PROCESS_SALT
    return hashlib.sha256(f"{salt}:{kind}:{value}".encode()).hexdigest()[:32]


def _decide(counts, now: datetime) -> Decision | None:
    """counts: ((window, limit), (questions in it, oldest time)) pairs; the refusal, or None to allow."""
    for (window, limit), (count, oldest) in counts:
        if count >= limit:
            wait = max(1, math.ceil((oldest + window - now).total_seconds() / 60))
            return Decision(False, wait, window <= timedelta(hours=1))
    return None


def _check_memory(person_key: str, network_key: str, now: datetime) -> Decision:
    with _memory_lock:
        for key in list(_memory):
            _memory[key] = [t for t in _memory[key] if t > now - timedelta(hours=KEEP_HOURS)]
            if not _memory[key]:
                del _memory[key]
        counts = []
        for key, limits in ((person_key, PERSON_LIMITS), (network_key, NETWORK_LIMITS if network_key else ())):
            for window, limit in limits:
                inside = [t for t in _memory.get(key, []) if t > now - window]
                counts.append(((window, limit), (len(inside), min(inside) if inside else None)))
        if refused := _decide(counts, now):
            return refused
        for key in (person_key, network_key):
            if key:
                _memory.setdefault(key, []).append(now)
        return Decision(True)


def client_network() -> str:
    """The client's address in a Streamlit session (forwarded_client); empty outside one."""
    try:
        import streamlit as st

        return forwarded_client(st.context.headers.get("X-Forwarded-For"), st.context.ip_address or "")
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
    if not enabled() or TRUSTED_CHECK.get():
        return Decision(True)
    network = client_network() if network is None else network
    person_key, network_key = _hash("person", person), _hash("network", network) if network else ""
    now = datetime.now(timezone.utc)
    if not settings.get_setting("SUPABASE_DB_URL"):
        return _check_memory(person_key, network_key, now)
    try:
        from src.supabase_store import connector, lock_from_data_api, table_exists

        with connector(settings.get_setting("SUPABASE_DB_URL"))() as conn:
            if not _ready:
                if not table_exists(conn, TABLE):
                    conn.execute(f"""create table {TABLE} (
                        id bigint generated always as identity primary key,
                        at timestamptz not null default now(), person text not null, network text not null)""")
                    conn.execute(f"create index {TABLE}_person_at on {TABLE} (person, at)")
                    conn.execute(f"create index {TABLE}_network_at on {TABLE} (network, at)")
                    lock_from_data_api(conn, TABLE)
                _ready = True
            if random.randrange(CLEAN_EVERY) == 0:
                conn.execute(f"delete from {TABLE} where at < %s", [now - timedelta(hours=KEEP_HOURS)])
            limits = [*PERSON_LIMITS, *(NETWORK_LIMITS if network_key else ())]
            if refused := _decide(zip(limits, _counts(conn, person_key, network_key, now)), now):
                return refused
            conn.execute(f"insert into {TABLE} (person, network) values (%s, %s)", [person_key, network_key])
        return Decision(True)
    except Exception:  # noqa: BLE001 - a broken database must not stop the app: count in memory
        logger.warning("rate limit table unavailable; counting in memory", exc_info=True)
        return _check_memory(person_key, network_key, now)


def message(decision: Decision) -> str:
    (_, hourly), (_, daily) = PERSON_LIMITS
    when = f"약 {decision.wait_minutes}분 뒤" if decision.wait_minutes < 90 else f"약 {math.ceil(decision.wait_minutes / 60)}시간 뒤"
    return (f"질문이 많아 잠시 쉬어 갈게요. 한 사람이 한 시간에 {hourly}번, 하루에 {daily}번까지 물어볼 수 있어요. "
            f"{when}에 다시 질문해 주세요. 응급 증상이라면 기다리지 말고 가까운 동물병원에 바로 연락하세요.")
