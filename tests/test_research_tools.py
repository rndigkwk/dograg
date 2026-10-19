"""team/tools/research.py search_health_qa: consultations and care guides, graded together."""

import json
import unittest
from unittest.mock import patch

from langchain_core.documents import Document

from src.crag import RetrievalReview
from team.tools import research


def case(doc_id):
    return Document(id=doc_id, page_content="노견이 계단을 못 올라요", metadata={"qa.output": "관절을 확인하세요",
                                                                          "meta.lifeCycle": "노령견"})


GUIDE = Document(id="leaflet-p2-0", page_content="미끄럼 방지 및 물·식기·잠자리에 쉽게 접근할 수 있는 환경", metadata={
    "kind": "care_guide", "source_id": "leaflet-p2-0", "title": "반려동물과의 이별, 미리 알고 함께 준비합니다", "page": 2,
    "organization": "동물사랑배움터", "piece": "미끄럼 방지"})


class SearchHealthQaTests(unittest.TestCase):
    def run_tool(self, kept_ids, guides=(GUIDE,)):
        seen = {}

        def review(kind, question, context):
            seen["context"] = context
            return RetrievalReview(feedback="", useful_ids=kept_ids, sufficient=True)

        with patch.object(research.health, "infer_rag_filters", return_value={}), \
                patch.object(research.health, "retrieve_health", return_value=[case("17")]), \
                patch.object(research.care_guides, "retrieve_care_guides", return_value=list(guides)), \
                patch.object(research, "review_evidence", side_effect=review):
            items = json.loads(research.search_health_qa.invoke({"query": "노견 계단 돌봄"}))
        return items, seen["context"]

    def test_a_kept_guide_comes_back_with_its_source_and_a_citable_id(self):
        items, context = self.run_tool(["17", "leaflet-p2-0"])
        self.assertIn("[leaflet-p2-0] 지침 「반려동물과의 이별, 미리 알고 함께 준비합니다」 2쪽: 미끄럼 방지", context)
        self.assertEqual(items[0]["evidence_id"], "qa-17")
        self.assertEqual(items[1], {"evidence_id": "careguide-반려동물과의+이별,+미리+알고+함께+준비합니다-p2",
                                    "source": "동물사랑배움터 「반려동물과의 이별, 미리 알고 함께 준비합니다」 2쪽",
                                    "excerpt": GUIDE.page_content})

    def test_without_a_guide_the_consultations_come_back_as_before(self):
        items, _ = self.run_tool(["17"], guides=())
        self.assertEqual([item["evidence_id"] for item in items], ["qa-17"])


if __name__ == "__main__":
    unittest.main()
