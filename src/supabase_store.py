"""Vector and keyword search in Postgres (Supabase): pgvector + PGroonga, nothing held in app memory.

An alternative to the in-memory store (ADR-0003) that also moves the keyword search out of the app,
so neither Kiwi nor the BM25 index is loaded. Each collection is one table:
    id text primary key, body text, metadata jsonb, embedding vector(d)
with an HNSW index (cosine) on embedding and a PGroonga index on body; scripts/export_supabase_store.py
fills them. The two classes have what the app uses from Chroma and from HealthBM25Index:
- PgVectorStore.similarity_search(query, k, filter) and .embeddings (the question is embedded in the
  app as before; only the search runs in the database). HNSW with pgvector 0.8's iterative scan, so a
  filter still fills k rows (filtered recall 0.938 -> 0.987, docs/adr/0003).
- PgroongaIndex.search(query, top_k, where): PGroonga similar search (&@*). Alone it is weaker than
  Kiwi BM25 (useful@3 0.418 vs 0.595); merged with Dense as the app does it matches (0.818 vs 0.809).
Filters use Chroma's where shape ({"key": value}, $and, $or, $in) and become jsonb conditions.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.documents import Document

ROW_COLUMNS = "id, body, metadata"


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
    def __init__(self, connect, table: str):
        self._connect, self.table = connect, table
        self._conn = None

    @property
    def conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = self._connect()
        return self._conn


class PgVectorStore(_Table):
    def __init__(self, connect, table: str, embeddings: Any, ef_search: int = 40):
        super().__init__(connect, table)
        self.embeddings = embeddings
        self.ef_search = ef_search

    def similarity_search(self, query: str, k: int = 4, filter: dict | None = None) -> list[Document]:  # noqa: A002 - Chroma's name
        vector = "[" + ",".join(f"{x:.6f}" for x in self.embeddings.embed_query(query)) + "]"
        condition, params = where_sql(filter)
        with self.conn.transaction():
            self.conn.execute(f"set local hnsw.ef_search = {int(self.ef_search)}")
            self.conn.execute("set local hnsw.iterative_scan = relaxed_order")
            rows = self.conn.execute(
                f"select {ROW_COLUMNS} from {self.table} where {condition} order by embedding <=> %s::vector limit %s",
                [*params, vector, k]).fetchall()
        return [_document(row) for row in rows]


class PgroongaIndex(_Table):
    def search(self, query: str, top_k: int, where: dict | None = None) -> list[Document]:
        condition, params = where_sql(where)
        rows = self.conn.execute(
            f"select {ROW_COLUMNS} from {self.table} where body &@* %s and {condition} "
            f"order by pgroonga_score(tableoid, ctid) desc limit %s",
            [query, *params, top_k]).fetchall()
        return [_document(row) for row in rows]


def connector(url: str):
    """A function that opens a connection (autocommit) to the database at url."""
    import psycopg

    return lambda: psycopg.connect(url, autocommit=True)


def create_tables(conn, table: str, dimension: int) -> None:
    conn.execute("create extension if not exists vector")
    conn.execute("create extension if not exists pgroonga")
    conn.execute(f"drop table if exists {table}")
    conn.execute(f"create table {table} (id text primary key, body text, metadata jsonb, embedding vector({dimension}))")


def load_rows(conn, table: str, ids, texts, metadatas, vectors) -> None:
    with conn.cursor().copy(f"copy {table} (id, body, metadata, embedding) from stdin") as copy:
        for doc_id, text, metadata, vector in zip(ids, texts, metadatas, vectors):
            copy.write_row((doc_id, text, json.dumps(metadata or {}, ensure_ascii=False),
                            "[" + ",".join(f"{x:.6f}" for x in vector) + "]"))
    conn.execute(f"create index on {table} using hnsw (embedding vector_cosine_ops)")
    conn.execute(f"create index on {table} using pgroonga (body)")
