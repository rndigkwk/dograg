import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.vector_store import ExactVectorStore, write_store


class FakeEmbeddings:
    def __init__(self, vectors):
        self.vectors = vectors

    def embed_query(self, text):
        return self.vectors[text]


class ExactVectorStoreTests(unittest.TestCase):
    """The in-memory exact store that replaces Chroma (ADR-0003): same results, same interface."""

    def setUp(self):
        vectors = np.array([[1, 0], [0.8, 0.6], [0, 1]], dtype=np.float32)
        metadatas = [{"meta.lifeCycle": "성견"}, {"meta.lifeCycle": "자견"}, {"meta.lifeCycle": "성견"}]
        self.directory = Path(tempfile.mkdtemp())
        write_store(self.directory, ["a", "b", "c"], ["가", "나", "다"], metadatas, vectors)
        self.store = ExactVectorStore.load(self.directory, FakeEmbeddings({"q": [2.0, 0.1]}))

    def test_ranks_by_cosine_and_returns_documents(self):
        found = self.store.similarity_search("q", k=2)
        self.assertEqual([d.id for d in found], ["a", "b"])
        self.assertEqual(found[0].page_content, "가")
        self.assertEqual(found[0].metadata, {"meta.lifeCycle": "성견"})

    def test_filter_uses_the_chroma_where_shape(self):
        self.assertEqual([d.id for d in self.store.similarity_search("q", k=3, filter={"meta.lifeCycle": "성견"})], ["a", "c"])
        both = {"$or": [{"meta.lifeCycle": "자견"}, {"meta.lifeCycle": "노령견"}]}
        self.assertEqual([d.id for d in self.store.similarity_search("q", k=3, filter=both)], ["b"])

    def test_get_gives_what_the_bm25_index_reads(self):
        stored = self.store.get(include=["documents", "metadatas"])
        self.assertEqual(stored["ids"], ["a", "b", "c"])
        self.assertEqual(stored["documents"], ["가", "나", "다"])
        self.assertEqual(len(stored["metadatas"]), 3)


if __name__ == "__main__":
    unittest.main()
