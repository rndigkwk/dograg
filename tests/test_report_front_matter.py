"""src/tools/report.py: contents and reference-list chunks never reach a report answer (2026-10-17)."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.tools import report


def chunk(text, title="반려동물+장묘서비스+이용+실태조사_온라인거래조사팀", page=2):
    return SimpleNamespace(page_content=text, metadata={"title": title, "page": page})


class FrontBackMatterTests(unittest.TestCase):
    def test_contents_and_reference_lists_are_recognised(self):
        contents = chunk("Ⅲ. 반려동물 장묘 관련 소비자 불만 현황··········· 14 1. 소비자 불만 현황··········· 14 "
                         "2. 불만 유형··········· 15")
        references = chunk("반려동물 장묘서비스 이용 실태조사 참 고 문 헌 김현희, 「반려동물관련산업법 제정을 위한 기반마련 연구」", page=69)
        welfare_refs = chunk("참고문헌 김도훈(2022), “민사집행법상 반려동물의 압류금지에 관한 소고”", title="반려동물 복지실태와 개선과제", page=268)
        self.assertTrue(report.is_front_or_back_matter(contents))
        self.assertTrue(report.is_front_or_back_matter(references))
        self.assertTrue(report.is_front_or_back_matter(welfare_refs))

    def test_findings_stay_even_when_they_cite_sources(self):
        table = chunk("【표 3-2】 반려동물 장묘 관련 불만 유형별 현황 (단위 : 건, %) 과다 비용 청구 8 (44.4)", page=20)
        body = chunk("동물복지는 개별동물의 감정(feelings)과 신체적 안녕을 의미하며 (참고문헌의 정의를 따름) …",
                     title="반려동물 복지실태와 개선과제", page=43)
        self.assertFalse(report.is_front_or_back_matter(table))
        self.assertFalse(report.is_front_or_back_matter(body))

    def test_the_search_skips_them_and_still_returns_k(self):
        docs = [chunk("목차··· a··· b··· c"), *[chunk(f"본문 {i}", page=i + 10) for i in range(8)]]
        with patch.object(report.resources, "load_report_vector_db", return_value=object()), \
                patch.object(report.resources, "load_report_bm25_index", return_value=object()), \
                patch("src.hybrid_retrieval.retrieve_hybrid", return_value=docs) as search:
            found = report.search_reports_hybrid("장묘 불만 유형", k=6)
        self.assertEqual([doc.metadata["page"] for doc in found], [10, 11, 12, 13, 14, 15])
        self.assertEqual(search.call_args.kwargs["top_k"], 10)


if __name__ == "__main__":
    unittest.main()
