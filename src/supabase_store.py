"""Vector and keyword search in Postgres (Supabase): pgvector + PGroonga, nothing held in app memory.

An alternative to the in-memory store (ADR-0003) that also moves the keyword search out of the app,
so neither Kiwi nor the BM25 index is loaded. Each collection is one table:
    id text primary key, body text, metadata jsonb, embedding halfvec(d)
with an HNSW index (cosine) on embedding and a PGroonga index on body; scripts/export_supabase_store.py
fills them. The two classes have what the app uses from Chroma and from HealthBM25Index:
- PgVectorStore.similarity_search(query, k, filter) and .embeddings (the question is embedded in the
  app as before; only the search runs in the database). HNSW with pgvector 0.8's iterative scan, so a
  filter still fills k rows (filtered recall 0.938 -> 0.987, docs/adr/0003).
- PgroongaIndex.search(query, top_k, where): PGroonga similar search (&@*). Alone it is weaker than
  Kiwi BM25 (useful@3 0.418 vs 0.595); merged with Dense as the app does it matches (0.818 vs 0.809).
Filters use Chroma's where shape ({"key": value}, $and, $or, $in) and become jsonb conditions.
Vectors are stored as float16 (halfvec): the same top 12 for all 220 health questions and the same
report pages as float32, at half the space (docs/adr/0007). The column type is read from the table,
so a float32 (vector) table still works.

When the database fails (connection, timeout), FallbackVectorStore and FallbackIndex answer from the
local stores (Chroma + Kiwi BM25, loaded only then) and keep doing so for a cooldown before trying
the database again; one Breaker per process is shared by all four, so an outage costs one timeout.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

from langchain_core.documents import Document

ROW_COLUMNS = "id, body, metadata"
CONNECT_TIMEOUT_SECONDS = 3
STATEMENT_TIMEOUT_MS = 3000

logger = logging.getLogger(__name__)


def where_sql(where: dict | None) -> tuple[str, list]:
    """Chroma's where dict as a SQL condition on the metadata column, with parameters."""
    if not where:
        return "true", []
    parts, params = [], []
    for key, value in where.items():
        if key in ("$and", "$or"):
            sub = [where_sql(item) for item in value]
            parts.append("(" + f" {key[1:]} ".join(sql for sql, _ in sub) + ")")
            for _, sub_params in sub:
                params += sub_params
        elif isinstance(value, dict) and "$in" in value:
            parts.append("metadata ->> %s = any(%s)")
            params += [key, [str(v) for v in value["$in"]]]
        else:
            if isinstance(value, dict):
                value = value.get("$eq")
            parts.append("metadata ->> %s = %s")
            params += [key, str(value)]
    return " and ".join(parts), params


def _document(row) -> Document:
    return Document(id=row[0], page_content=row[1], metadata=dict(row[2] or {}))


class _Table:
    """One connection per table object, used by one thread at a time; a failed connection is
    dropped so the next call reconnects."""

    session_settings: tuple[str, ...] = ()

    def __init__(self, connect, table: str):
        self._connect, self.table = connect, table
        self._conn = None
        self._lock = threading.Lock()

    @property
    def conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = self._connect()
            # Session settings once per connection: each search is then a single round trip
            # (about 60 ms each from Korea to Seoul's pooler; five per search before).
            for setting in self.session_settings:
                self._conn.execute(setting)
        return self._conn

    def _run(self, work: Callable[[Any], Any]):
        with self._lock:
            try:
                return work(self.conn)
            except Exception:
                if self._conn is not None:
                    self._conn.close()
                self._conn = None
                raise


class PgVectorStore(_Table):
    def __init__(self, connect, table: str, embeddings: Any, ef_search: int = 40):
        super().__init__(connect, table)
        self.embeddings = embeddings
        self.session_settings = (f"set hnsw.ef_search = {int(ef_search)}", "set hnsw.iterative_scan = relaxed_order")
        self._vector_type: str | None = None

    def _column_type(self, conn) -> str:
        """vector or halfvec, read once from the table."""
        if self._vector_type is None:
            kind = conn.execute("select format_type(atttypid, atttypmod) from pg_attribute "
                                "where attrelid = %s::regclass and attname = 'embedding'", [self.table]).fetchone()[0]
            self._vector_type = "halfvec" if kind.startswith("halfvec") else "vector"
        return self._vector_type

    def similarity_search(self, query: str, k: int = 4, filter: dict | None = None) -> list[Document]:  # noqa: A002 - Chroma's name
        vector = "[" + ",".join(f"{x:.6f}" for x in self.embeddings.embed_query(query)) + "]"
        condition, params = where_sql(filter)

        def work(conn):
            cast = self._column_type(conn)
            return conn.execute(
                f"select {ROW_COLUMNS} from {self.table} where {condition} order by embedding <=> %s::{cast} limit %s",
                [*params, vector, k]).fetchall()

        return [_document(row) for row in self._run(work)]


class PgroongaIndex(_Table):
    def search(self, query: str, top_k: int, where: dict | None = None) -> list[Document]:
        condition, params = where_sql(where)
        rows = self._run(lambda conn: conn.execute(
            f"select {ROW_COLUMNS} from {self.table} where body &@* %s and {condition} "
            f"order by pgroonga_score(tableoid, ctid) desc limit %s",
            [query, *params, top_k]).fetchall())
        return [_document(row) for row in rows]


class Breaker:
    """After a database error, send searches to the local stores for `cooldown` seconds."""

    def __init__(self, cooldown: float = 300.0, clock: Callable[[], float] = time.monotonic):
        self.cooldown, self.clock = cooldown, clock
        self.open_until = 0.0
        self.failures = 0

    @property
    def open(self) -> bool:
        return self.clock() < self.open_until

    def trip(self, error: BaseException) -> None:
        self.failures += 1
        self.open_until = self.clock() + self.cooldown
        logger.warning("Supabase search failed (%s: %s); using local search for %.0fs",
                       type(error).__name__, error, self.cooldown)


def database_errors() -> tuple[type[BaseException], ...]:
    """Errors that mean the database is unavailable, not a bug in the query."""
    import psycopg

    return (psycopg.OperationalError, psycopg.errors.QueryCanceled, psycopg.errors.AdminShutdown, OSError, TimeoutError)


class _Fallback:
    def __init__(self, primary, load_local: Callable[[], Any], breaker: Breaker, errors=None):
        self.primary, self._load_local, self.breaker = primary, load_local, breaker
        self._errors = errors

    def _call(self, method: str, *args, **kwargs):
        errors = self._errors or database_errors()
        if not self.breaker.open:
            try:
                return getattr(self.primary, method)(*args, **kwargs)
            except errors as error:
                self.breaker.trip(error)
        return getattr(self._load_local(), method)(*args, **kwargs)


class FallbackVectorStore(_Fallback):
    @property
    def embeddings(self):
        return self.primary.embeddings

    def similarity_search(self, query: str, k: int = 4, filter: dict | None = None) -> list[Document]:  # noqa: A002 - Chroma's name
        return self._call("similarity_search", query, k=k, filter=filter)


class FallbackIndex(_Fallback):
    def search(self, query: str, top_k: int, where: dict | None = None) -> list[Document]:
        return self._call("search", query, top_k, where=where)


def connector(url: str):
    """A function that opens a connection (autocommit) to the database at url, failing fast: a
    3-second connect timeout and a 3-second statement timeout, so an outage falls back quickly."""
    import psycopg

    def connect():
        conn = psycopg.connect(url, autocommit=True, connect_timeout=CONNECT_TIMEOUT_SECONDS)
        conn.execute(f"set statement_timeout = {STATEMENT_TIMEOUT_MS}")
        return conn

    return connect


def create_tables(conn, table: str, dimension: int, vector_type: str = "halfvec") -> None:
    conn.execute("create extension if not exists vector")
    conn.execute("create extension if not exists pgroonga")
    conn.execute(f"drop table if exists {table}")
    conn.execute(f"create table {table} (id text primary key, body text, metadata jsonb, embedding {vector_type}({dimension}))")
    lock_from_data_api(conn, table)


def table_exists(conn, table: str) -> bool:
    """Whether the table is there. The app connects as ragdog_app (2026-10-15), which may read and
    write its tables but not create, alter or lock them: those run only where the table is missing,
    that is with the admin connection (a fresh project, tests)."""
    return conn.execute("select to_regclass(%s)", [f"public.{table}"]).fetchone()[0] is not None


def lock_from_data_api(conn, table: str) -> None:
    """Keep a table out of Supabase's public REST API. Tables in the public schema are granted to
    the anon and authenticated roles by default, and without row level security anyone with the
    project URL and its publishable key could read or delete them (AI Hub text must not be shared).
    The app connects as the table owner, which row level security does not restrict."""
    conn.execute(f"alter table {table} enable row level security")
    conn.execute(f"revoke all on {table} from anon, authenticated")


def load_rows(conn, table: str, ids, texts, metadatas, vectors, vector_type: str = "halfvec") -> None:
    with conn.cursor().copy(f"copy {table} (id, body, metadata, embedding) from stdin") as copy:
        for doc_id, text, metadata, vector in zip(ids, texts, metadatas, vectors):
            copy.write_row((doc_id, text, json.dumps(metadata or {}, ensure_ascii=False),
                            "[" + ",".join(f"{x:.6f}" for x in vector) + "]"))
    conn.execute(f"create index {table}_embedding_idx on {table} using hnsw (embedding {vector_type}_cosine_ops)")
    conn.execute(f"create index {table}_body_idx on {table} using pgroonga (body)")


def to_halfvec(conn, table: str) -> bool:
    """Convert a float32 (vector) table in place. The HNSW index is dropped first so the database
    never holds two copies of it (the free plan stops at 500 MB). False if already halfvec."""
    kind = conn.execute("select format_type(atttypid, atttypmod) from pg_attribute "
                        "where attrelid = %s::regclass and attname = 'embedding'", [table]).fetchone()[0]
    if kind.startswith("halfvec"):
        return False
    dimension = int(kind[kind.index("(") + 1:-1])
    conn.execute(f"drop index if exists {table}_embedding_idx")
    conn.execute(f"alter table {table} alter column embedding type halfvec({dimension}) using embedding::halfvec({dimension})")
    conn.execute(f"create index {table}_embedding_idx on {table} using hnsw (embedding halfvec_cosine_ops)")
    conn.execute(f"analyze {table}")
    return True
