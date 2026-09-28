import importlib
import importlib.util
import unittest
from unittest.mock import Mock, patch

from langchain_core.documents import Document


class HybridRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.find_spec("src.hybrid_retrieval")
        cls.hybrid = importlib.import_module("src.hybrid_retrieval") if spec else None

    def test_runtime_hybrid_retrieval_module_exists(self):
        self.assertIsNotNone(self.hybrid, "runtime hybrid retrieval module is not implemented")

    def test_rrf_combines_rankings_and_returns_requested_count(self):
        if self.hybrid is None:
            self.skipTest("runtime hybrid retrieval module is not implemented")
        dense = [Document(id=key, page_content=key) for key in ["a", "b", "c"]]
        lexical = [Document(id=key, page_content=key) for key in ["b", "d", "a"]]

        fused = self.hybrid.reciprocal_rank_fusion(
            [dense, lexical], top_k=3, c=60
        )

        self.assertEqual([document.id for document in fused], ["b", "a", "d"])

    def test_metadata_filter_supports_nested_and_or_conditions(self):
        if self.hybrid is None:
            self.skipTest("runtime hybrid retrieval module is not implemented")
        metadata = {
            "meta.lifeCycle": "성견",
            "meta.department": "내과",
            "meta.disease": "None",
        }
        where = {"$and": [
            {"meta.lifeCycle": "성견"},
            {"$or": [
                {"meta.disease": "기타"},
                {"meta.disease": "None"},
            ]},
        ]}

        self.assertTrue(self.hybrid.matches_metadata_filter(metadata, where))
        self.assertFalse(self.hybrid.matches_metadata_filter(
            {**metadata, "meta.lifeCycle": "자견"}, where
        ))

    def test_bm25_candidates_apply_the_same_metadata_filter_as_dense(self):
        if self.hybrid is None:
            self.skipTest("runtime hybrid retrieval module is not implemented")
        documents = [
            Document(id="wrong", page_content="구토 증상", metadata={"meta.department": "외과"}),
            Document(id="right", page_content="구토 증상", metadata={"meta.department": "내과"}),
        ]

        candidates = self.hybrid.select_bm25_candidates(
            documents,
            scores=[100.0, 1.0],
            where={"meta.department": "내과"},
            top_k=2,
        )

        self.assertEqual([document.id for document in candidates], ["right"])

    def test_bm25_index_tokenizes_query_and_searches_ranked_documents(self):
        class Scores:
            def get_scores(self, tokens):
                self.tokens = tokens
                return [1.0, 5.0]

        documents = [
            Document(id="less", page_content="구토 원인"),
            Document(id="more", page_content="구토 치료 방법"),
        ]
        scorer = Scores()
        index = self.hybrid.HealthBM25Index(
            documents, scorer, lambda text: text.split()
        )

        found = index.search("구토 치료", top_k=1)

        self.assertEqual(scorer.tokens, ["구토", "치료"])
        self.assertEqual([document.id for document in found], ["more"])

    def test_health_rag_uses_hybrid_candidates_and_preserves_selected_filters(self):
        from pages import rag

        dense_doc = Document(
            id="dense", page_content="구토", metadata={"meta.department": "내과"}
        )
        lexical_doc = Document(
            id="lexical", page_content="구토 원인", metadata={"meta.department": "내과"}
        )
        db = Mock()
        db.similarity_search.return_value = [dense_doc]
        index = Mock()
        index.search.return_value = [lexical_doc]
        where = {"meta.department": "내과"}
        filters = {"department": "내과"}

        with patch.object(rag, "initialize_rag", return_value=(db, None)), patch.object(
            rag, "load_health_bm25_index", return_value=index
        ), patch.object(rag, "build_metadata_filter", return_value=where):
            result = rag.ask_rag("강아지 구토", k=2, filters=filters)

        db.similarity_search.assert_called_once_with("강아지 구토", k=12, filter=where)
        index.search.assert_called_once_with("강아지 구토", 12, where=where)
        self.assertEqual(len(result["evidence_rows"]), 2)


if __name__ == "__main__":
    unittest.main()
