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
from src.private_data import needs_private_data


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
    @needs_private_data
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

    def test_a_rerun_stopping_the_warmup_ends_it_quietly(self):
        # Streamlit's StopException is a BaseException: `except Exception` let it kill the
        # warm-up thread with a traceback on the deployed app (2026-10-09).
        from unittest.mock import patch

        from streamlit.runtime.scriptrunner_utils.exceptions import StopException

        from app_pages import rag

        with patch.object(rag.resources, "load_vector_db", side_effect=StopException()), \
                self.assertLogs("app_pages.rag", level="INFO") as logs:
            rag._warm_up_health_search()
        self.assertIn("stopped by a rerun", logs.output[0])

    def test_loaders_called_from_background_threads_show_no_spinner(self):
        # A spinner sends messages through the attached script run: NoSessionContext without one
        # (#47), StopException when that run is stopped. Neither can happen without a spinner.
        from src import resources

        for loader in (resources.load_vector_db, resources.load_health_bm25_index, resources.load_health_answer_table,
                       resources.load_report_vector_db, resources.load_report_bm25_index):
            self.assertFalse(loader._info.show_spinner, loader.__name__)


if __name__ == "__main__":
    unittest.main()
