"""Pet places (data/places.db): build, kind detection, search per kind, routing, page."""

import json
import sqlite3
import sys
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import pandas as pd
from langchain_core.runnables import RunnableLambda
from streamlit.testing.v1 import AppTest

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

import build_places_db

from src import resources
from src.places_data import (
    SCHEMA,
    describe_info,
    normalize_address,
    province_of,
)
from src.tools import places, router

CAFE_INFO = json.dumps({"hours": "매일 10:00~22:00", "size": "소형", "restrictions": "목줄", "extra_fee": "5,000원"}, ensure_ascii=False)
PLACES = [
    # id, kind, name, road_address, lot_address, phone, homepage, category, info, latitude, longitude
    ("boarding-1", "boarding", "강남펫호텔", "서울특별시 강남구 역삼동", None, None, None, None, None, None, None),
    ("funeral-1", "funeral", "하늘장례식장", "경기도 김포시 대곶면", None, "031-000-0000", "http://example.com", "화장", None, None, None),
    ("grooming-1", "grooming", "강남미용", "서울특별시 강남구 역삼동", None, "02-333-3333", None, "일반 미용", None, None, None),
    ("hospital-1", "hospital", "강남동물병원", "서울특별시 강남구 테헤란로 1", None, "02-111-1111", None, None, None, 37.50, 127.03),
    ("hospital-2", "hospital", "마포동물병원", "서울특별시 마포구 월드컵로 2", None, None, None, None, None, 37.56, 126.90),
    ("pet_friendly-1", "pet_friendly", "멍멍카페", "서울특별시 강남구 도산대로 4", None, None, None, "카페", CAFE_INFO, 37.52, 127.03),
    ("pharmacy-1", "pharmacy", "강남약국", "서울특별시 강남구 역삼로 3", None, "02-222-2222", None, None, None, 37.49, 127.04),
]


def make_db(directory: str) -> Path:
    path = Path(directory) / "places.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(SCHEMA)
        connection.executemany(f"INSERT INTO place VALUES ({', '.join('?' * 11)})", PLACES)
        connection.executemany(
            "INSERT INTO source VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(kind, kind, "https://example.com", f"{kind}.csv", 2, 1, 1, 1, "2026-10-02", '["정제 단계"]')
             for kind in ("hospital", "pharmacy", "pet_friendly", "grooming", "boarding", "funeral")],
        )
        connection.commit()
    return path


class AddressTests(unittest.TestCase):
    def test_short_and_old_province_names_become_current_ones(self):
        self.assertEqual(normalize_address("경기 김포시 대곶면 null"), "경기도 김포시 대곶면")
        self.assertEqual(normalize_address("전라남도 목포시"), "전남광주통합특별시 목포시")
        self.assertEqual(normalize_address("세종시 부강로"), "세종특별자치시 부강로")
        self.assertEqual(normalize_address("안산시 단원구"), "경기도 안산시 단원구")
        self.assertIsNone(normalize_address("null"))
        self.assertEqual(province_of("서울특별시 강남구"), "서울특별시")
        self.assertIsNone(province_of("어딘가 1번지"))

    def test_info_lines_follow_the_label_order(self):
        self.assertEqual(describe_info(CAFE_INFO), ["운영시간: 매일 10:00~22:00", "입장 가능 크기: 소형", "제한사항: 목줄", "추가 요금: 5,000원"])
        self.assertEqual(describe_info(None), [])


class BuildTests(unittest.TestCase):
    def test_build_cleans_every_source_and_records_the_steps(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = {kind: root / f"{kind}_20261002.csv" for kind in build_places_db.INPUTS}
            pd.DataFrame({
                "관리번호": ["1", "2"], "사업장명": ["영업병원", "폐업병원"], "영업상태명": ["영업/정상", "폐업"],
                "도로명주소": ["서울 종로구 창경궁로 261", "서울특별시 종로구"], "지번주소": [None, None],
                "전화번호": ["02-1", "02-2"], "좌표정보(X)": ["199947.178659", "1"], "좌표정보(Y)": ["453593.826987", "1"],
                "데이터갱신시점": ["2026-08-11 22:02:01", "2026-08-01 00:00:00"],
            }).to_csv(inputs["hospital"], index=False, encoding="cp949")
            pd.DataFrame({
                "고유ID": ["a:1", "a:2"], "사업장명": ["약국", "좌표없는약국"], "SALS_STTS_CD": ["01", "01"],
                "도로명주소": ["경기도 수원시", "부산 해운대구"], "지번주소": [None, None], "전화번호": ["***", "051-1"],
                "위도": ["37.27", "0"], "경도": ["127.01", "0"], "DAT_UPDT_PNT": ["2026-10-01 22:33:00"] * 2,
            }).to_csv(inputs["pharmacy"], index=False, encoding="utf-8-sig")
            pd.DataFrame({
                "번호": ["1"], "취급업종": ["장례, 화장"], "업체명": ["펫장례"], "소재지": ["경기 김포시 null"],
                "전화번호": ["031-1"], "홈페이지": ["http://x"],
            }).to_csv(inputs["funeral"], index=False, encoding="utf-8-sig")
            for kind in ("grooming", "boarding"):
                pd.DataFrame({
                    "번호": ["1", "2"], "구분": ["미용 (자동차이용)", "미용 (일반)"], "업체명": ["출장미용", "동네미용"],
                    "전화번호": ["***********", "02-9"], "소재지": ["서울특별시 종로구 숭인동", "서울특별시 종로구 구기동"],
                    "인허가 정보": ["L1", "L2"], "이전인허가정보": [None, None], "비고": ["  미용", " "],
                }).to_csv(inputs[kind], index=False, encoding="utf-8-sig")
            facility = {
                "시설명": ["멍카페", "멍카페", "동물약국", "금지박물관"],
                "카테고리2": ["반려동물식당카페", "반려동물식당카페", "반려의료", "반려동반여행"],
                "카테고리3": ["카페", "카페", "동물약국", "박물관"], "반려동물 동반 가능정보": ["Y", "Y", "Y", "N"],
                "도로명주소": ["서울 마포구 1"] * 2 + ["서울 마포구 2", "서울 마포구 3"], "지번주소": [None] * 4,
                "전화번호": ["02-5"] * 4, "홈페이지": ["정보없음"] * 4, "위도": ["37.55"] * 4, "경도": ["126.9"] * 4,
                "운영시간": ["매일 10:00~22:00"] * 4, "휴무일": ["정보없음"] * 4, "입장 가능 동물 크기": ["소형"] * 4,
                "반려동물 제한사항": ["목줄"] * 4, "애견 동반 추가 요금": ["없음"] * 4, "주차 가능여부": ["Y"] * 4,
                "최종작성일": ["2025-03-24"] * 4,
            }
            pd.DataFrame(facility).to_csv(inputs["pet_friendly"], index=False, encoding="utf-8-sig")
            output = root / "places.db"
            counts = build_places_db.build(output, inputs)
            with closing(sqlite3.connect(output)) as connection:
                rows = {row[0]: row for row in connection.execute("SELECT * FROM place")}
                sources = {row[0]: row for row in connection.execute("SELECT * FROM source")}

        self.assertEqual(counts, {"boarding": 2, "funeral": 1, "grooming": 2, "hospital": 1, "pet_friendly": 1, "pharmacy": 2})
        hospital = rows["hospital-1"]
        self.assertEqual(hospital[1:6], ("hospital", "영업병원", "서울특별시 종로구 창경궁로 261", None, "02-1"))
        self.assertAlmostEqual(hospital[9], 37.5846, places=3)  # EPSG:5174 -> WGS84
        self.assertAlmostEqual(hospital[10], 127.0002, places=3)
        self.assertIsNone(rows["pharmacy-a:1"][5])  # masked phone dropped
        self.assertIsNone(rows["pharmacy-a:2"][9])  # (0, 0) is not a location
        self.assertEqual(rows["funeral-1"][3], "경기도 김포시")
        self.assertEqual(rows["grooming-L1"][7], "출장(자동차) 미용")
        self.assertEqual(json.loads(rows["boarding-L1"][8]), {"other_licenses": "미용"})
        [cafe] = [row for row in rows.values() if row[1] == "pet_friendly"]
        self.assertEqual((cafe[2], cafe[6], cafe[7]), ("멍카페", None, "카페"))  # "정보없음" homepage dropped
        self.assertEqual(json.loads(cafe[8])["size"], "소형")
        self.assertEqual(sources["hospital"][4:9], (2, 1, 1, 1, "2026-08-11 22:02:01"))
        self.assertIn("1건 제외", json.loads(sources["hospital"][9])[0])
        notes = json.loads(sources["pet_friendly"][9])
        self.assertTrue(any("동반 불가(N) 1건" in note for note in notes))
        self.assertTrue(any("중복 1건" in note for note in notes))
        self.assertEqual(sources["grooming"][8], "2026-10-02")  # date in the file name


class KindTests(unittest.TestCase):
    def test_kind_from_the_question(self):
        cases = {
            "강남구 동물병원 목록 알려줘": "hospital",
            "근처 동물약국 찾아줘": "pharmacy",
            "마포구 약국 어디 있어?": "pharmacy",
            "김포 반려동물 장례식장 알려줘": "funeral",
            "강남구 애견미용 어디야?": "grooming",
            "여행 가는 동안 맡길 곳 찾아줘": "boarding",
            "마포구 애견호텔 목록": "boarding",
            "강아지랑 같이 갈 수 있는 카페 추천해줘": "pet_friendly",
            "제주 애견펜션 찾아줘": "pet_friendly",
            "사람 약국에서 산 해열제 먹여도 돼?": None,
            "미용 후 피부가 빨개요": None,
            "반려동물 장묘 서비스 이용 실태": None,
        }
        for question, kind in cases.items():
            self.assertEqual(places.place_kind(question), kind, question)

    def test_particles_and_requested_count(self):
        self.assertEqual(places.with_particle("동물병원", "을", "를"), "동물병원을")
        self.assertEqual(places.with_particle("장묘업체", "을", "를"), "장묘업체를")
        self.assertEqual(places.get_hospital_result_limit("종로구 동물약국 3곳만 알려줘"), 3)
        self.assertEqual(places.get_hospital_result_limit("종로구 동물약국 50곳만"), 10)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        patcher = patch.object(resources, "DB_PATH", make_db(self.directory.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.directory.cleanup)

    def search(self, question, **kwargs):
        with patch.object(resources, "load_chat_model", return_value=None):
            return places.run_sql_search(question, **kwargs)

    def test_region_search_stays_on_the_kind(self):
        answer, rows = self.search("강남구 동물약국 알려줘")
        self.assertEqual([row["name"] for row in rows], ["강남약국"])
        self.assertIn("전화: 02-222-2222", answer)
        self.assertIn("방문 전 전화로 확인", answer)
        _, rows = self.search("강남구 동물병원 알려줘")
        self.assertEqual([row["name"] for row in rows], ["강남동물병원"])
        _, rows = self.search("강남구 애견호텔 알려줘")
        self.assertEqual([row["name"] for row in rows], ["강남펫호텔"])

    def test_pet_friendly_answer_lists_the_conditions(self):
        answer, rows = self.search("강남구 애견동반 카페 알려줘")
        self.assertEqual([row["name"] for row in rows], ["멍멍카페"])
        self.assertIn("멍멍카페 (카페)", answer)
        self.assertIn("입장 가능 크기: 소형", answer)
        self.assertIn("추가 요금: 5,000원", answer)

    def test_count_per_kind(self):
        answer, _ = self.search("서울특별시 동물병원 몇 곳이야?")
        self.assertEqual(answer, "조건에 맞는 동물병원은 2곳입니다.")
        answer, _ = self.search("김포시 장례식장 몇 곳이야?")
        self.assertEqual(answer, "조건에 맞는 장묘업체는 1곳입니다.")

    def test_nearest_needs_coordinates(self):
        answer, rows = self.search("가까운 약국 찾아줘", location=(37.49, 127.04))
        self.assertEqual(rows[0]["name"], "강남약국")
        self.assertIn("동물약국", answer)
        for question in ("가까운 장례식장 찾아줘", "근처 애견미용 찾아줘"):
            answer, rows = self.search(question, location=(37.49, 127.04))
            self.assertEqual(rows, [])
            self.assertIn("좌표가 없어", answer)

    def test_region_word_wins_over_nearby_word(self):
        _, rows = self.search("마포구 근처에 동물병원 있어?")
        self.assertEqual([row["name"] for row in rows], ["마포동물병원"])

    def test_generated_sql_without_the_kind_filter_is_not_used(self):
        unfiltered = "SELECT id, kind, name, road_address, lot_address, phone, category, info, latitude, longitude FROM place"
        answer_prompt = Mock()
        with patch.object(resources, "load_chat_model", return_value=RunnableLambda(lambda value: value)), \
                patch.object(places, "SQL_GENERATION_PROMPT", RunnableLambda(lambda _: unfiltered)), \
                patch.object(places, "SQL_ANSWER_PROMPT", answer_prompt):
            answer, rows = places.run_sql_search("유명한 동물약국 알려줘")
        self.assertEqual({row["kind"] for row in rows}, {"pharmacy"})  # fixed SQL, not the generated one
        self.assertIn("강남약국", answer)

    def test_sql_must_read_only_the_place_table(self):
        with self.assertRaises(ValueError):
            places.validate_sql("SELECT * FROM sqlite_master")
        self.assertTrue(places.stays_on_kind("SELECT * FROM place WHERE kind = 'pharmacy'", "pharmacy"))
        self.assertFalse(places.stays_on_kind("SELECT * FROM place WHERE kind = 'hospital'", "pharmacy"))


class RoutingTests(unittest.TestCase):
    def test_new_kinds_route_to_sql_without_a_model(self):
        with patch.object(resources, "load_chat_model", return_value=None):
            for question in ("마포구 동물약국 알려줘", "김포 장례식장 찾아줘", "강남구 애견미용 어디야?", "애견동반 카페 추천해줘"):
                self.assertEqual(router.classify_question(question), "sql", question)
            self.assertEqual(router.classify_question("반려동물 장묘 서비스 이용 실태"), "analysis")
            self.assertEqual(router.classify_question("강아지가 기침해요"), "rag")


class PlacePageTests(unittest.TestCase):
    def test_region_search_per_kind_on_the_page(self):
        with TemporaryDirectory() as directory, patch.object(resources, "DB_PATH", make_db(directory)):
            app = AppTest.from_file(str(PROJECT_DIR / "pages" / "hospital.py"), default_timeout=30).run()
            app.radio(key="place_kind").set_value("pharmacy").run()
            app.selectbox[0].set_value("서울특별시").run()
            app.selectbox[1].set_value("강남구").run()
            app.button(key="place_search").click().run()
            self.assertEqual([e.message for e in app.exception], [])
            self.assertIn("동물약국 1곳", app.success[0].value)

            app.radio(key="place_kind").set_value("pet_friendly").run()
            app.button(key="place_search").click().run()
            table = app.dataframe[0].value
            self.assertEqual(table.loc[0, "입장 가능 크기"], "소형")
            self.assertEqual(table.loc[0, "분류"], "카페")

            app.radio(key="place_kind").set_value("funeral").run()
            self.assertEqual(len(app.selectbox), 1)  # funeral: province only
            self.assertEqual([e.message for e in app.exception], [])

    def test_data_page_shows_the_cleaning_steps(self):
        with TemporaryDirectory() as directory, patch.object(resources, "DB_PATH", make_db(directory)):
            app = AppTest.from_file(str(PROJECT_DIR / "pages" / "data.py"), default_timeout=30).run()
            self.assertEqual([e.message for e in app.exception], [])
            self.assertTrue(any("정제 단계" in markdown.value for markdown in app.markdown))


if __name__ == "__main__":
    unittest.main()
