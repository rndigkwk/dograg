import unittest

from langchain_core.documents import Document

from scripts.evaluate_hybrid_search import reciprocal_rank_fusion, rank_of_match


class HybridSearchBenchmarkTests(unittest.TestCase):
    def test_rrf_rewards_documents_returned_by_both_retrievers(self):
        dense = [Document(id=item, page_content=item) for item in "ABC"]
        lexical = [Document(id=item, page_content=item) for item in "BDA"]

        ranked = reciprocal_rank_fusion([lexical, dense], top_k=4, c=60)

        self.assertEqual([doc.id for doc in ranked], ["B", "A", "D", "C"])

    def test_gold_match_requires_all_three_metadata_fields(self):
        row = {
            "meta.lifeCycle": "성견",
            "meta.department": "내과",
            "meta.disease": "구토",
        }
        wrong = Document(
            id="wrong",
            page_content="question",
            metadata={**row, "meta.disease": "설사"},
        )
        correct = Document(id="right", page_content="question", metadata=row)

        self.assertEqual(rank_of_match(row, [wrong, correct]), 2)


if __name__ == "__main__":
    unittest.main()
