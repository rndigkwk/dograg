"""Where the API keeps visit-prep runs between requests (2026-10-16, docs/wiki/lecture-review.md re-review).

A run may pause to ask the guardian (Day 51 interrupt) and resume on a later request. Until now the
paused graph (InMemorySaver), the run waiting for its answer, its owner and each person's report
count lived in one server's memory, so the API had to run as a single Cloud Run instance and a
deploy lost every paused run. With SUPABASE_DB_URL they live in Postgres instead, in the schema
`visit_prep` (not exposed by the public REST API; scripts/setup_visit_prep_store.py makes it):

- the graph checkpoints (LangGraph PostgresSaver tables), deleted when a run finishes or expires;
- `paused`: the run waiting for an answer, its owner (a salted hash, never the browser id) and when;
- `report_starts`: who started a report when (hashes and times only), for REPORTS_PER_DAY.

A paused run holds the consultation text, so nothing is kept past PAUSED_RUN_TTL_SECONDS: expired
pauses and their checkpoints are deleted on the next request, and checkpoints of runs that crashed
are dropped after STALE_CHECKPOINT_SECONDS. Without a database URL (local runs, tests, the Streamlit
backup) the same interface keeps everything in this process's memory, as before.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

from src import rate_limit, settings

logger = logging.getLogger(__name__)

SCHEMA = "visit_prep"
PAUSED_RUN_TTL_SECONDS = 30 * 60
STALE_CHECKPOINT_SECONDS = 60 * 60  # a run lasts 1-2 minutes; older checkpoints with no pause belong to a crash
DAY_SECONDS = 24 * 3600


def owner_key(person: str) -> str:
    """The person as stored: a salted hash (src/rate_limit.py), never the browser id or account id."""
    return rate_limit._hash("visit-prep", person)


class Store(Protocol):
    def checkpointer(self): ...
    def take_report(self, person: str, limit: int, now: float) -> bool: ...
    def refund_report(self, person: str) -> None: ...
    def save_paused(self, thread_id: str, person: str, pending: dict, now: float) -> None: ...
    def take_paused(self, thread_id: str, person: str, now: float) -> dict | None: ...
    def put_back(self, thread_id: str, person: str, pending: dict, paused_at: float) -> None: ...
    def expire(self, now: float) -> list[str]: ...


@dataclass
class MemoryStore:
    """One process's memory: the behaviour before 2026-10-16 (a single API instance)."""
    _reports: dict[str, list[float]] = field(default_factory=dict)
    _paused: dict[str, tuple[str, dict, float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _saver: object = None

    def checkpointer(self):
        if self._saver is None:
            from langgraph.checkpoint.memory import InMemorySaver

            self._saver = InMemorySaver()
        return self._saver

    def take_report(self, person, limit, now):
        key = owner_key(person)
        with self._lock:
            recent = [t for t in self._reports.get(key, []) if now - t < DAY_SECONDS]
            if len(recent) >= limit:
                self._reports[key] = recent
                return False
            self._reports[key] = [*recent, now]
            return True

    def refund_report(self, person):
        with self._lock:
            if self._reports.get(owner_key(person)):
                self._reports[owner_key(person)].pop()

    def save_paused(self, thread_id, person, pending, now):
        with self._lock:
            self._paused[thread_id] = (owner_key(person), pending, now)

    def take_paused(self, thread_id, person, now):
        with self._lock:
            owner, pending, paused_at = self._paused.get(thread_id, (None, None, 0.0))
            if owner != owner_key(person) or now - paused_at > PAUSED_RUN_TTL_SECONDS:
                return None
            del self._paused[thread_id]
            return {**pending, "paused_at": paused_at}

    def put_back(self, thread_id, person, pending, paused_at):
        with self._lock:
            self._paused[thread_id] = (owner_key(person), {k: v for k, v in pending.items() if k != "paused_at"}, paused_at)

    def expire(self, now):
        with self._lock:
            gone = [tid for tid, (_, _, at) in self._paused.items() if now - at > PAUSED_RUN_TTL_SECONDS]
            for tid in gone:
                del self._paused[tid]
        for tid in gone:
            self.checkpointer().delete_thread(tid)
        return gone


class PostgresStore:
    """The same in Supabase, shared by every API instance (see the module docstring)."""

    def __init__(self, url: str, schema: str = SCHEMA):
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        # Session pooler: no server-side prepared statements; the schema first on the search path,
        # so LangGraph's unqualified table names land in visit_prep.
        self._pool = ConnectionPool(url, min_size=0, max_size=4, open=True, kwargs={
            "autocommit": True, "prepare_threshold": None, "row_factory": dict_row,
            "options": f"-c search_path={schema}"})
        self._saver = None

    def probe(self) -> None:
        """Fail now, not on the first report, if the database or the schema is missing."""
        with self._pool.connection() as conn:
            conn.execute("select 1 from paused, report_starts, checkpoints limit 0")

    def checkpointer(self):
        if self._saver is None:
            from langgraph.checkpoint.postgres import PostgresSaver

            self._saver = PostgresSaver(self._pool)
        return self._saver

    def take_report(self, person, limit, now):
        key = owner_key(person)
        with self._pool.connection() as conn, conn.transaction():
            conn.execute("select pg_advisory_xact_lock(hashtext(%s))", [key])  # one count per person at a time
            count = conn.execute("select count(*) as n from report_starts where owner = %s and at > to_timestamp(%s)",
                                 [key, now - DAY_SECONDS]).fetchone()["n"]
            if count >= limit:
                return False
            conn.execute("insert into report_starts (owner, at) values (%s, to_timestamp(%s))", [key, now])
            return True

    def refund_report(self, person):
        with self._pool.connection() as conn:
            conn.execute("""delete from report_starts where id = (
                select id from report_starts where owner = %s order by at desc limit 1)""", [owner_key(person)])

    def save_paused(self, thread_id, person, pending, now):
        with self._pool.connection() as conn:
            conn.execute("""insert into paused (thread_id, owner, pending, paused_at) values (%s, %s, %s, to_timestamp(%s))
                            on conflict (thread_id) do update set owner = excluded.owner, pending = excluded.pending,
                            paused_at = excluded.paused_at""", [thread_id, owner_key(person), json.dumps(pending, ensure_ascii=False), now])

    def take_paused(self, thread_id, person, now):
        # Deleted as it is taken: one answer per pause, even with two requests at once.
        with self._pool.connection() as conn:
            row = conn.execute("""delete from paused where thread_id = %s and owner = %s and paused_at > to_timestamp(%s)
                                  returning pending, extract(epoch from paused_at) as paused_at""",
                               [thread_id, owner_key(person), now - PAUSED_RUN_TTL_SECONDS]).fetchone()
        return None if row is None else {**row["pending"], "paused_at": float(row["paused_at"])}

    def put_back(self, thread_id, person, pending, paused_at):
        with self._pool.connection() as conn:
            conn.execute("""insert into paused (thread_id, owner, pending, paused_at) values (%s, %s, %s, to_timestamp(%s))
                            on conflict (thread_id) do nothing""",
                         [thread_id, owner_key(person), json.dumps({k: v for k, v in pending.items() if k != "paused_at"},
                                                                   ensure_ascii=False), paused_at])

    def expire(self, now):
        with self._pool.connection() as conn:
            gone = [row["thread_id"] for row in conn.execute(
                "delete from paused where paused_at < to_timestamp(%s) returning thread_id",
                [now - PAUSED_RUN_TTL_SECONDS]).fetchall()]
            # Checkpoints with no pause row: finished runs are deleted as they finish, so these are crashes.
            stale = [row["thread_id"] for row in conn.execute(
                """select distinct thread_id from checkpoints c where not exists (select 1 from paused p where p.thread_id = c.thread_id)
                   and (c.checkpoint->>'ts')::timestamptz < to_timestamp(%s)""", [now - STALE_CHECKPOINT_SECONDS]).fetchall()]
            conn.execute("delete from report_starts where at < to_timestamp(%s)", [now - DAY_SECONDS])
        for thread_id in {*gone, *stale}:
            self.checkpointer().delete_thread(thread_id)
        return gone


_store: Store | None = None
_store_lock = threading.Lock()


def store() -> Store:
    """Postgres on the deployed server with SUPABASE_DB_URL (memory if it cannot connect or the schema
    from scripts/setup_visit_prep_store.py is missing), else memory.
    Local runs and tests use memory even though .env has the database URL: they must not write there."""
    global _store
    with _store_lock:
        if _store is None:
            url = settings.get_setting("SUPABASE_DB_URL") if settings.deployed() else None
            if url:
                try:
                    _store = PostgresStore(url)
                    _store.probe()
                except Exception:  # noqa: BLE001 - a missing schema or a down database must not stop reports
                    logger.warning("visit-prep store unavailable; keeping runs in memory", exc_info=True)
                    _store = MemoryStore()
            else:
                _store = MemoryStore()
        return _store


def _reset_for_tests(new: Store | None = None) -> None:
    global _store
    _store = new


def now() -> float:
    return time.time()
