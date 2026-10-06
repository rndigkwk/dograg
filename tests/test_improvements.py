import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pymupdf
from streamlit.testing.v1 import AppTest

from pages import rag
from src import resources
from src.health_quality import audit_health_data, normalize_label
from src.health_retrieval import rerank_candidates, summarize_retrieval
from src.health_safety import detect_urgent_sign, has_usable_evidence
from src.hospital_distance import nearest_hospitals
from src.location_component import parse_location_result
from src.report_evidence import render_pdf_page, report_evidence_from_docs
from src.tools import health, places, report


def render_saved_message_for_test(message):
    from pages import rag as page
    page.render_assistant_message(message)


class HealthQualityTests(unittest.TestCase):
    def test_audit_preserves_other_and_counts_missing(self):
        train = pd.DataFrame({"meta.disease": [" 기타 ", "기타", None], "meta.department": [" 내과 ", "내과", None], "qa.input": ["a", "a", "b"]})
        val = pd.DataFrame({"meta.disease": ["기타"], "meta.department": ["내과"], "qa.input": ["a"]})
        result = audit_health_data(train, val)
        self.assertEqual(result["train"]["rows"], 3)
        self.assertEqual(result["train"]["missing"]["meta.disease"], 1)
        self.assertEqual(result["train"]["duplicate_questions"], 1)
        self.assertEqual(result["train"]["normalized_labels"]["기타"], 2)
        self.assertEqual(result["train"]["normalized_departments"]["내과"], 2)
        self.assertEqual(result["question_overlap"], 1)
        self.assertEqual(normalize_label("  관절  질환  "), "관절 질환")

    def test_lexical_rerank_and_empty_subgroup_metrics(self):
        docs = [SimpleNamespace(page_content="고양이 사료", metadata={}), SimpleNamespace(page_content="강아지 기침", metadata={})]
        self.assertIs(rerank_candidates("강아지 기침", docs, 1)[0], docs[1])
        summary = summarize_retrieval([{"group": "기타", "hit_rank": 2}])
        self.assertEqual(summary["overall"]["hit@3"], 1.0)
        self.assertEqual(summary["non_other"]["count"], 0)


class SafetyTests(unittest.TestCase):
    def test_urgent_and_negated_signs(self):
        self.assertIsNotNone(detect_urgent_sign("강아지가 숨을 못 쉬어요"))
        self.assertIsNotNone(detect_urgent_sign("계속 헛구역질만 해요"))
        self.assertIsNone(detect_urgent_sign("호흡곤란은 없어요"))
        self.assertIsNone(detect_urgent_sign("초콜릿은 안 먹었어요"))
        self.assertIsNotNone(detect_urgent_sign("숨을 못 쉬고 구토는 없어요"))
        self.assertIsNone(detect_urgent_sign("구토했어요"))
        self.assertFalse(has_usable_evidence([], None))

    def test_empty_rag_skips_model_and_returns_notice(self):
        db = SimpleNamespace(similarity_search=lambda *args, **kwargs: [])
        index = SimpleNamespace(search=lambda *args, **kwargs: [])
        with patch.object(health, "initialize_rag", return_value=(db, object())), patch.object(
            resources, "load_health_bm25_index", return_value=index
        ):
            result = health.ask_rag("강아지가 숨을 못 쉬어요")
        self.assertIn("근거", result["answer"])
        self.assertIn("동물병원", result["safety_notice"])


class DistanceTests(unittest.TestCase):
    def test_distance_order_and_invalid_rows(self):
        rows = [
            {"ids": 2, "name": "far", "x_coor": 200000, "y_coor": 600000},
            {"ids": 1, "name": "near", "x_coor": 200000, "y_coor": 500000},
            {"ids": 3, "name": "bad", "x_coor": None, "y_coor": None},
        ]
        from pyproj import Transformer
        lon, lat = Transformer.from_crs(5174, 4326, always_xy=True).transform(200000, 500000)
        result = nearest_hospitals(rows, lat, lon)
        self.assertEqual([row["ids"] for row in result], [1, 2])
        self.assertAlmostEqual(result[0]["distance_km"], 0, places=5)
        with self.assertRaises(ValueError):
            nearest_hospitals(rows, 127, 37)

    def test_equal_distance_uses_numeric_id_order(self):
        from pyproj import Transformer
        lon, lat = Transformer.from_crs(5174, 4326, always_xy=True).transform(200000, 500000)
        rows = [{"ids": 10, "x_coor": 200000, "y_coor": 500000}, {"ids": 2, "x_coor": 200000, "y_coor": 500000}]
        self.assertEqual([row["ids"] for row in nearest_hospitals(rows, lat, lon)], [2, 10])

    def test_nearest_chat_without_location_does_not_claim_first_row(self):
        with patch.object(resources, "load_chat_model", return_value=None):
            answer, rows = places.run_sql_search("가장 가까운 동물병원")
        self.assertEqual(rows, [])
        self.assertIn("위치", answer)

    def test_nearest_chat_ranks_inserted_second_first(self):
        from pyproj import Transformer
        lon, lat = Transformer.from_crs(5174, 4326, always_xy=True).transform(200000, 500000)
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "hospital.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute("CREATE TABLE hospital (ids INTEGER, name TEXT, new_address TEXT, old_address TEXT, x_coor REAL, y_coor REAL)")
                connection.executemany("INSERT INTO hospital VALUES (?, ?, ?, ?, ?, ?)", [(2, "far", "far address", "", 200000, 600000), (1, "near", "near address", "", 200000, 500000)])
                connection.commit()
            finally:
                connection.close()
            with patch.object(resources, "DB_PATH", db_path), patch.object(resources, "load_chat_model", side_effect=AssertionError("nearest should not use SQL model")):
                answer, rows = places.run_sql_search("가장 가까운 동물병원", location=(lat, lon))
                _, one_row = places.run_sql_search("가장 가까운 동물병원 하나만", location=(lat, lon))
        self.assertEqual([row["name"] for row in rows], ["near", "far"])
        self.assertEqual(len(one_row), 1)
        self.assertIn("직선거리", answer)

    def test_location_result_denial_and_validation(self):
        self.assertEqual(parse_location_result({"status": "denied"}), (None, "위치 권한이 거부되었습니다."))
        self.assertEqual(parse_location_result({"latitude": 37.5, "longitude": 127.0}), ((37.5, 127.0), None))
        self.assertEqual(parse_location_result({"latitude": 127, "longitude": 37}), (None, "유효하지 않은 위치입니다."))

    def test_both_pages_mount_location_control(self):
        root = Path(__file__).resolve().parents[1]
        hospital = AppTest.from_file(str(root / "pages" / "hospital.py"), default_timeout=30).run()
        chat = AppTest.from_file(str(root / "pages" / "rag.py"), default_timeout=30).run()
        self.assertEqual([item.message for item in hospital.exception], [])
        self.assertEqual([item.message for item in chat.exception], [])


class ReportEvidenceTests(unittest.TestCase):
    def test_page_metadata_and_render_boundaries(self):
        docs = [SimpleNamespace(metadata={"page": "2", "source_path": "C:/old/private.pdf"}, page_content="sample")]
        self.assertEqual(report_evidence_from_docs(docs)[0]["page"], 2)
        self.assertNotIn("private.pdf", str(report_evidence_from_docs(docs)))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "test.pdf"
            pdf = pymupdf.open()
            pdf.new_page()
            pdf.new_page()
            pdf.save(path)
            pdf.close()
            self.assertIsNotNone(render_pdf_page(path, 2))
            self.assertIsNone(render_pdf_page(path, 0))
            self.assertIsNone(render_pdf_page(path, 3))

    def test_empty_report_skips_model(self):
        db = SimpleNamespace(similarity_search=lambda *args, **kwargs: [])
        with patch.object(resources, "load_report_vector_db", return_value=db):
            result = report.analyze_report("반려동물 보고서의 비만 현황")
        self.assertEqual(result["evidence_rows"], [])
        self.assertIn("근거", result["answer"])

    def test_saved_assistant_message_replays_notice_and_page_evidence(self):
        message = {"role": "assistant", "content": "요약", "route": "analysis", "safety_notice": "진료 권고", "evidence_rows": [{"page": 2, "excerpt": "보고서 근거"}]}
        with patch.object(rag, "render_pdf_page", return_value=None):
            app = AppTest.from_function(render_saved_message_for_test, args=(message,), default_timeout=30).run()
        self.assertEqual([item.message for item in app.exception], [])
        self.assertTrue(any("진료 권고" in item.value for item in app.warning))
        self.assertTrue(any("페이지 2" in item.value for item in app.markdown))


if __name__ == "__main__":
    unittest.main()
