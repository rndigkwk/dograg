import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from src.hybrid_retrieval import (
    HealthBM25Index,
    corpus_fingerprint,
    load_token_cache,
    write_token_cache,
)


def fake_db(ids, texts):
    db = Mock()
    db.get.return_value = {"ids": ids, "documents": texts, "metadatas": [{} for _ in ids]}
    return db


def counting_tokenizer():
    calls = []

    def tokenize(text):
        calls.append(text)
        return text.split()

    return tokenize, calls


class BM25TokenCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = Path(self.directory.name) / "tokens.json.gz"
        # Three documents: with two, BM25 IDF is zero for every term and all scores tie.
        self.ids, self.texts = ["1", "0", "2"], ["설사 구토", "기침 발열", "식욕 부진"]

    def build(self, ids=None, texts=None, version="v1"):
        tokenize, calls = counting_tokenizer()
        index = HealthBM25Index.from_chroma(
            fake_db(ids or self.ids, texts or self.texts), tokenize,
            token_cache=self.cache, tokenizer_version=version,
        )
        return index, calls

    def test_cache_hit_skips_corpus_tokenization(self):
        _, calls = self.build()
        self.assertEqual(len(calls), 3)  # no cache file yet: every document is tokenized
        self.assertFalse(self.cache.exists())  # building never writes the cache
        write_token_cache(self.cache, self.ids, [t.split() for t in self.texts], self.texts, "v1")
        index, calls = self.build()
        self.assertEqual(calls, [])
        self.assertEqual(index.search("구토", top_k=1)[0].id, "1")
        self.assertEqual(calls, ["구토"])  # only the query is tokenized

    def test_cached_tokens_follow_document_ids_not_file_order(self):
        write_token_cache(
            self.cache, ["2", "0", "1"], [["식욕", "부진"], ["기침", "발열"], ["설사", "구토"]],
            ["식욕 부진", "기침 발열", "설사 구토"], "v1",
        )
        index, calls = self.build()
        self.assertEqual(calls, [])
        self.assertEqual(index.search("기침", top_k=1)[0].id, "0")

    def test_changed_corpus_or_tokenizer_falls_back_to_tokenizing(self):
        write_token_cache(self.cache, self.ids, [t.split() for t in self.texts], self.texts, "v1")
        _, calls = self.build(texts=["설사 구토 혈변", "기침 발열", "식욕 부진"])
        self.assertEqual(len(calls), 3)
        _, calls = self.build(version="v2")
        self.assertEqual(len(calls), 3)

    def test_corrupt_cache_falls_back_to_tokenizing(self):
        self.cache.write_bytes(b"not gzip")
        _, calls = self.build()
        self.assertEqual(len(calls), 3)
        self.assertIsNone(load_token_cache(self.cache, "anything", "v1"))

    def test_fingerprint_depends_on_ids_and_texts(self):
        base = corpus_fingerprint(["1"], ["a"])
        self.assertNotEqual(base, corpus_fingerprint(["2"], ["a"]))
        self.assertNotEqual(base, corpus_fingerprint(["1"], ["b"]))

    def test_cache_file_is_compact_json(self):
        write_token_cache(self.cache, self.ids, [["설사"], ["기침"], ["식욕"]], self.texts, "v1")
        payload = json.loads(gzip.decompress(self.cache.read_bytes()))
        self.assertEqual(set(payload), {"format", "tokenizer", "corpus_sha256", "tokens"})
        self.assertEqual(payload["tokens"], {"1": ["설사"], "0": ["기침"], "2": ["식욕"]})


class ProjectCacheTests(unittest.TestCase):
    def test_committed_cache_matches_the_health_collection_size(self):
        from src import resources

        payload = json.loads(gzip.decompress(resources.BM25_TOKEN_CACHE.read_bytes()))
        self.assertEqual(payload["tokenizer"], resources.HEALTH_TOKENIZER_VERSION)
        self.assertEqual(len(payload["tokens"]), 19206)


class WarmupDecisionTests(unittest.TestCase):
    def test_only_a_real_server_warms_up(self):
        from app_pages import rag

        self.assertTrue(rag.warmup_wanted({}, {}, runtime_exists=True))
        self.assertFalse(rag.warmup_wanted({}, {"streamlit.testing.v1": object()}, runtime_exists=True))
        self.assertFalse(rag.warmup_wanted({}, {}, runtime_exists=False))

    def test_environment_override_wins(self):
        from app_pages import rag

        self.assertFalse(rag.warmup_wanted({"DOGRAG_WARMUP": "0"}, {}, runtime_exists=True))
        self.assertTrue(rag.warmup_wanted({"DOGRAG_WARMUP": "1"}, {}, runtime_exists=False))


if __name__ == "__main__":
    unittest.main()
