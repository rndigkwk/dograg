import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from langchain_core.documents import Document

from pages import rag
from src.hybrid_retrieval import retrieve_hybrid
from src.report_evidence import (
    DEFAULT_REPORT_SOURCE,
    report_evidence_from_docs,
    resolve_report_pdf,
)


class OpenAIEmbeddingSwitchTests(unittest.TestCase):
    def test_health_local_and_report_openai_collections(self):
        self.assertEqual(rag.HEALTH_COLLECTION_NAME, "pet_care")
        self.assertEqual(rag.HEALTH_EMBEDDING_MODEL_NAME, "jhgan/ko-sroberta-multitask")
        self.assertTrue(rag.REPORT_COLLECTION_NAME.startswith("pet_reports_openai3small_1536_"))
        self.assertEqual(rag.EMBEDDING_MODEL_NAME, "text-embedding-3-small")

    def test_no_api_key_means_no_embedding_model(self):
        rag.create_embedding_model.clear()
        try:
            with patch.object(rag, "get_openai_api_key", return_value=None):
                self.assertIsNone(rag.create_embedding_model())
        finally:
            rag.create_embedding_model.clear()

    def test_hybrid_falls_back_to_bm25_without_embeddings(self):
        db = Mock(embeddings=None)
        lexical = [Document(id="b", page_content="b")]
        index = Mock()
        index.search.return_value = lexical

        result = retrieve_hybrid(db, index, "구토", top_k=1)

        db.similarity_search.assert_not_called()
        self.assertEqual([doc.id for doc in result], ["b"])

    def test_report_search_without_key_explains_requirement(self):
        with patch.object(rag, "load_report_vector_db", return_value=None):
            result = rag.analyze_report("반려동물 장묘 서비스 이용 현황")
        self.assertEqual(result["evidence_rows"], [])
        self.assertIn("OPENAI_API_KEY", result["answer"])


class MultiReportEvidenceTests(unittest.TestCase):
    def test_evidence_keeps_relative_source_and_title(self):
        docs = [SimpleNamespace(
            metadata={"page": 3, "source": "data/source/반려동물 복지실태와 개선과제.pdf", "title": "반려동물 복지실태와 개선과제"},
            page_content="근거",
        )]
        row = report_evidence_from_docs(docs)[0]
        self.assertEqual(row["source"], "data/source/반려동물 복지실태와 개선과제.pdf")
        self.assertEqual(row["title"], "반려동물 복지실태와 개선과제")

    def test_untrusted_source_falls_back_to_default_report(self):
        for source in ("C:/old/private.pdf", "../secrets.pdf", "data/source/../../x.pdf", None):
            docs = [SimpleNamespace(metadata={"page": 1, "source": source}, page_content="근거")]
            self.assertEqual(report_evidence_from_docs(docs)[0]["source"], DEFAULT_REPORT_SOURCE)

    def test_resolve_report_pdf_stays_inside_data_folder(self):
        root = Path(rag.PROJECT_DIR)
        self.assertEqual(resolve_report_pdf(root, DEFAULT_REPORT_SOURCE), root / DEFAULT_REPORT_SOURCE)
        self.assertIsNone(resolve_report_pdf(root, "../outside.pdf"))
        self.assertEqual(resolve_report_pdf(root, None), root / DEFAULT_REPORT_SOURCE)

    def test_default_report_pdf_exists(self):
        self.assertTrue((Path(rag.PROJECT_DIR) / DEFAULT_REPORT_SOURCE).is_file())

    def test_report_context_names_each_report(self):
        docs = [SimpleNamespace(metadata={"page": 7, "title": "반려동물 장묘서비스 이용 실태조사"}, page_content="본문")]
        self.assertIn("반려동물 장묘서비스 이용 실태조사", rag.format_report_context(docs))
        self.assertIn("7", rag.format_report_context(docs))


if __name__ == "__main__":
    unittest.main()
