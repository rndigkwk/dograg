import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from src import resources
from src.tools import health, places, report


class RagRefactorHelpersTest(unittest.TestCase):
    def test_formats_health_rag_documents_for_prompt_context(self):
        docs = [
            SimpleNamespace(
                page_content="강아지가 계속 구토해요.",
                metadata={"qa.output": "반복 구토는 진료가 필요할 수 있습니다."},
            ),
            SimpleNamespace(
                page_content="식욕이 없어요.",
                metadata={"qa.output": "식욕 저하는 관찰이 필요합니다."},
            ),
        ]

        self.assertEqual(
            health.format_rag_context(docs),
            "질문: 강아지가 계속 구토해요.\n"
            "답변: 반복 구토는 진료가 필요할 수 있습니다.\n\n"
            "질문: 식욕이 없어요.\n"
            "답변: 식욕 저하는 관찰이 필요합니다.",
        )

    def test_formats_report_documents_with_page_metadata(self):
        docs = [
            SimpleNamespace(
                page_content="반려동물 양육 현황은 전년 대비 증가했다.",
                metadata={"page": 12},
            )
        ]

        self.assertEqual(
            report.format_report_context(docs),
            "[보고서 · 페이지 12] 반려동물 양육 현황은 전년 대비 증가했다.",
        )

    def test_executes_place_sql_and_returns_dict_rows(self):
        from src.places_data import SCHEMA

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "places.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.executescript(SCHEMA)
                connection.execute(
                    "INSERT INTO place (id, kind, name, road_address, latitude, longitude) "
                    "VALUES ('hospital-1', 'hospital', '테스트동물병원', '서울특별시 강남구 테헤란로', 37.0, 127.0)"
                )
                connection.commit()
            finally:
                connection.close()

            with patch.object(resources, "DB_PATH", db_path):
                rows = places.execute_place_sql(
                    "SELECT id, name, road_address, latitude, longitude FROM place WHERE road_address LIKE ?",
                    ["%강남구%"],
                )

        self.assertEqual(
            rows,
            [{"id": "hospital-1", "name": "테스트동물병원", "road_address": "서울특별시 강남구 테헤란로", "latitude": 37.0, "longitude": 127.0}],
        )

    def test_detects_questions_that_should_limit_hospital_results_to_one(self):
        self.assertTrue(places.should_limit_to_one_hospital("강남구 동물병원 하나만 알려줘"))
        self.assertTrue(places.should_limit_to_one_hospital("근처 병원 알려줘"))
        self.assertFalse(places.should_limit_to_one_hospital("강남구 동물병원이 몇 개야?"))

    def test_forces_sql_limit_one_without_duplicating_limit_clause(self):
        self.assertEqual(
            places.force_sql_limit_one("SELECT * FROM hospital LIMIT 10"),
            "SELECT * FROM hospital LIMIT 1",
        )
        self.assertEqual(
            places.force_sql_limit_one("SELECT * FROM hospital"),
            "SELECT * FROM hospital LIMIT 1",
        )


if __name__ == "__main__":
    unittest.main()
