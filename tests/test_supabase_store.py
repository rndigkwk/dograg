import os
import unittest
from unittest.mock import patch

from src.supabase_store import Breaker, FallbackIndex, FallbackVectorStore, where_sql


class WhereSqlTests(unittest.TestCase):
    """Chroma's where dicts become jsonb conditions for the Supabase store (ADR-0007)."""

    def test_shapes_the_app_sends(self):
        self.assertEqual(where_sql(None), ("true", []))
        self.assertEqual(where_sql({"meta.lifeCycle": "성견"}), ("metadata ->> %s = %s", ["meta.lifeCycle", "성견"]))
        sql, params = where_sql({"$or": [{"meta.disease": "기타"}, {"meta.disease": "해당없음"}]})
        self.assertEqual(sql, "(metadata ->> %s = %s or metadata ->> %s = %s)")
        self.assertEqual(params, ["meta.disease", "기타", "meta.disease", "해당없음"])
        sql, params = where_sql({"$and": [{"meta.department": "내과"}, {"meta.lifeCycle": {"$in": ["성견", "노령견"]}}]})
        self.assertEqual(sql, "(metadata ->> %s = %s and metadata ->> %s = any(%s))")
        self.assertEqual(params, ["meta.department", "내과", "meta.lifeCycle", ["성견", "노령견"]])


class Unavailable(Exception):
    pass


class FakeStore:
    def __init__(self, name, error=None):
        self.name, self.error, self.calls, self.embeddings = name, error, 0, "embedder"

    def similarity_search(self, query, k=4, filter=None):  # noqa: A002 - Chroma's name
        self.calls += 1
        if self.error:
            raise self.error
        return [f"{self.name}:{query}:{k}:{filter}"]

    search = lambda self, query, top_k, where=None: self.similarity_search(query, top_k, where)  # noqa: E731


class FallbackTests(unittest.TestCase):
    """When Supabase fails, search answers from the local stores and stays there for a cooldown."""

    def setUp(self):
        self.now = 0.0
        self.breaker = Breaker(cooldown=300, clock=lambda: self.now)
        self.local_loads = 0

    def load_local(self):
        self.local_loads += 1
        return FakeStore("local")

    def store(self, primary):
        return FallbackVectorStore(primary, self.load_local, self.breaker, errors=(Unavailable,))

    def test_healthy_database_never_loads_the_local_store(self):
        store = self.store(FakeStore("db"))
        self.assertEqual(store.similarity_search("구토", k=3, filter={"a": "b"}), ["db:구토:3:{'a': 'b'}"])
        self.assertEqual(store.embeddings, "embedder")
        self.assertEqual(self.local_loads, 0)

    def test_outage_falls_back_then_retries_after_the_cooldown(self):
        primary = FakeStore("db", error=Unavailable("timeout"))
        store = self.store(primary)
        with self.assertLogs("src.supabase_store", level="WARNING"):
            self.assertEqual(store.similarity_search("구토", k=3), ["local:구토:3:None"])
        self.now = 299
        store.similarity_search("설사", k=3)
        self.assertEqual(primary.calls, 1)  # no second timeout while the breaker is open
        primary.error = None
        self.now = 301
        self.assertEqual(store.similarity_search("설사", k=3), ["db:설사:3:None"])

    def test_one_breaker_covers_the_keyword_index_too(self):
        with self.assertLogs("src.supabase_store", level="WARNING"):
            self.store(FakeStore("db", error=Unavailable("down"))).similarity_search("구토")
        primary = FakeStore("db")
        index = FallbackIndex(primary, self.load_local, self.breaker, errors=(Unavailable,))
        self.assertEqual(index.search("구토", 12), ["local:구토:12:None"])
        self.assertEqual(primary.calls, 0)

    def test_a_bug_in_the_query_is_not_hidden(self):
        store = self.store(FakeStore("db", error=ValueError("bad sql")))
        with self.assertRaises(ValueError):
            store.similarity_search("구토")
        self.assertFalse(self.breaker.open)


class SearchBackendTests(unittest.TestCase):
    def test_supabase_needs_both_settings(self):
        from src import resources

        with patch.dict(os.environ, {"SEARCH_BACKEND": "supabase", "SUPABASE_DB_URL": ""}):
            self.assertEqual(resources.search_backend(), "local")
        with patch.dict(os.environ, {"SEARCH_BACKEND": "Supabase ", "SUPABASE_DB_URL": "postgresql://x"}):
            self.assertEqual(resources.search_backend(), "supabase")
        with patch.dict(os.environ, {"SEARCH_BACKEND": "local", "SUPABASE_DB_URL": "postgresql://x"}):
            self.assertEqual(resources.search_backend(), "local")


if __name__ == "__main__":
    unittest.main()
