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

    def test_a_pages_pdf_and_ocr_chunks_share_one_slot(self):
        kb = "반려동물 보고서"
        docs = [chunk("77쪽 PDF", kb, 77), chunk("77쪽 OCR 12.8%", kb, 77), chunk("78쪽", kb, 78), chunk("79쪽", kb, 79)]
        kept = report.by_page(docs, 2)
        self.assertEqual([d.page_content for d in kept], ["77쪽 PDF", "77쪽 OCR 12.8%", "78쪽"])

    def test_reports_named_in_a_question(self):
        self.assertEqual(len(report.named_reports("KB 2025와 2024 복지실태 보고서에서 혼자 있는 시간은?")), 2)
        self.assertEqual(len(report.named_reports("장묘서비스 불만 유형은?")), 1)
        self.assertEqual(report.named_reports("반려동물 월평균 양육비는?"), [])

    def test_a_question_naming_two_reports_gets_pages_from_each(self):
        kb, welfare = list(report.REPORT_NAMES)[:2]

        def search(db, index, query, top_k, candidate_k, where):
            name = "KB" if where["source"] == kb else "복지"
            pages = range(10, 18) if name == "KB" else (170, 169, 1, 2)
            return [chunk(f"{name} {n}", name, n) for n in pages]

        with patch.object(report.resources, "load_report_vector_db", return_value=object()), \
                patch.object(report.resources, "load_report_bm25_index", return_value=object()), \
                patch("src.hybrid_retrieval.retrieve_hybrid", side_effect=search) as hybrid:
            found = report.search_reports_hybrid("KB 2025와 2024 복지실태 보고서에서 혼자 있는 시간을 각각 알려주세요", k=6)
        self.assertEqual([d.page_content for d in found], ["KB 10", "KB 11", "KB 12", "복지 170", "복지 169", "복지 1"])
        self.assertEqual({c.kwargs["where"]["source"] for c in hybrid.call_args_list}, {kb, welfare})
        self.assertEqual(hybrid.call_args.args[2], "혼자 있는 시간을")  # the topic, not the report names

    def test_a_question_asking_reports_apart_without_names(self):
        self.assertTrue(report.asks_several_reports("펫보험 가입률은 보고서마다 몇 %로 나오나요?"))
        self.assertTrue(report.asks_several_reports("혼자 있는 시간을 보고서들에서 찾아 비교해 주세요."))
        self.assertTrue(report.asks_several_reports("여러 보고서의 양육비를 정리해 줘"))
        self.assertFalse(report.asks_several_reports("KB 2025 보고서에서 반려가구 수는?"))
        self.assertEqual(report.report_topic("혼자 있는 하루 평균 시간을 보고서들에서 찾아 비교해 주세요."),
                         "혼자 있는 하루 평균 시간을")
        self.assertEqual(report.report_topic("펫보험 가입률은 보고서마다 몇 %로 나오나요?"), "펫보험 가입률은 몇 %로 나오나요?")

    def test_unnamed_reports_are_the_leading_four_of_the_overall_ranking(self):
        kb, welfare, industry, medical, funeral = report.REPORT_NAMES

        def search(db, index, query, top_k, candidate_k, where=None):
            if where is None:  # the overall ranking picks the reports
                return [chunk("목차··· a··· b··· c", page=2)] + [
                    SimpleNamespace(page_content=f"{s} {n}", metadata={"source": s, "page": n, "title": ""})
                    for s, n in ((industry, 179), (kb, 77), (industry, 180), (medical, 61), (welfare, 1), (funeral, 6))]
            return [SimpleNamespace(page_content=f"{where['source']} {n}", metadata={"source": where["source"], "page": n,
                                                                                      "title": ""}) for n in (1, 2, 3)]

        with patch.object(report.resources, "load_report_vector_db", return_value=object()), \
                patch.object(report.resources, "load_report_bm25_index", return_value=object()), \
                patch("src.hybrid_retrieval.retrieve_hybrid", side_effect=search) as hybrid:
            found = report.search_reports_hybrid("펫보험 가입률은 보고서마다 몇 %로 나오나요?", k=6)
        searched = [c.kwargs["where"]["source"] for c in hybrid.call_args_list if c.kwargs.get("where")]
        self.assertEqual(searched, [industry, kb, medical, welfare])
        self.assertEqual(len(found), 8)  # two pages each
        self.assertEqual(hybrid.call_args_list[0].args[2], "펫보험 가입률은 몇 %로 나오나요?")

    def test_guardians_words_gain_the_reports_word(self):
        self.assertEqual(report.with_report_terms("직접 땅에 묻은 비율"), "직접 땅에 묻은 비율 매장")
        self.assertIn("양육 희망", report.with_report_terms("반려묘를 키우고 싶은 비반려가구"))
        self.assertEqual(report.with_report_terms("반려가구 수는?"), "반려가구 수는?")

    def test_one_named_report_is_searched_alone_without_its_name(self):
        self.assertEqual(report.without_report_name("장묘 실태조사에서 등록된 동물장묘업체 수는 2013년과 2022년에 각각 몇 곳인가요?"),
                         "등록된 동물장묘업체 수는 2013년과 2022년에 각각")  # the question ending goes too
        self.assertEqual(report.without_report_name("산업 조사체계 보고서에서 앞으로의 장례 방법은?"), "앞으로의 장례 방법은?")
        kb = next(iter(report.REPORT_NAMES))
        with patch.object(report.resources, "load_report_vector_db", return_value=object()), \
                patch.object(report.resources, "load_report_bm25_index", return_value=object()), \
                patch("src.hybrid_retrieval.retrieve_hybrid", return_value=[chunk("KB 16", "KB", 16)]) as hybrid:
            report.search_reports_hybrid("KB 2025 보고서에서 반려묘를 키우고 싶은 비율은?", k=6)
        self.assertEqual(hybrid.call_args.kwargs["where"], {"source": kb})
        self.assertEqual(hybrid.call_args.args[2], "반려묘를 키우고 싶은 비율은? 양육 희망 양육 계획")

    def test_supabase_report_keywords_come_from_the_in_memory_bm25(self):
        bm25 = object()
        report.resources.load_report_bm25_index.clear()
        try:
            with patch.object(report.resources, "search_backend", return_value="supabase"), \
                    patch.object(report.resources, "create_embedding_model", return_value=object()), \
                    patch.object(report.resources, "load_fallback_report_index", return_value=bm25):
                self.assertIs(report.resources.load_report_bm25_index(), bm25)
        finally:
            report.resources.load_report_bm25_index.clear()

    def test_the_topic_drops_names_years_and_asks(self):
        self.assertEqual(report.report_topic("KB 2025와 2024 복지실태 보고서에서 반려동물이 혼자 있는 하루 평균 시간을 각각 알려주세요."),
                         "반려동물이 혼자 있는 하루 평균 시간을")
        self.assertIn("동물병원 소비자", report.report_topic("동물병원 소비자가 낸 가격과 KB 2025의 펫보험 가입률을 정리해 줘"))

    def test_the_search_skips_them_and_still_returns_k(self):
        docs = [chunk("목차··· a··· b··· c"), *[chunk(f"본문 {i}", page=i + 10) for i in range(8)]]
        with patch.object(report.resources, "load_report_vector_db", return_value=object()), \
                patch.object(report.resources, "load_report_bm25_index", return_value=object()), \
                patch("src.hybrid_retrieval.retrieve_hybrid", return_value=docs) as search:
            found = report.search_reports_hybrid("장묘 불만 유형", k=6)
        self.assertEqual([doc.metadata["page"] for doc in found], [10, 11, 12, 13, 14, 15])
        self.assertEqual(search.call_args.kwargs["top_k"], 14)


if __name__ == "__main__":
    unittest.main()
