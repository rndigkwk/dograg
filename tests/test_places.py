"""Pet places (data/places.db): build, kind detection, search per kind, routing, page."""

import json
import sqlite3
import sys
import time
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
    all_areas,
    describe_info,
    format_phone,
    matches_conditions,
    needs_carrier,
    normalize_address,
    province_of,
    size_rule,
    with_area_code,
)
from src.private_data import needs_private_data
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

    def test_phone_numbers_get_hyphens_by_prefix(self):
        cases = {
            "025434037": "02-543-4037",
            "0236728441": "02-3672-8441",
            "0316583500": "031-658-3500",
            "01012345678": "010-1234-5678",
            "07012345678": "070-1234-5678",
            "050714049333": "0507-1404-9333",
            "15882888": "1588-2888",
            "36728441": "3672-8441",
            "7449098": "744-9098",
            "031-658-3500": "031-658-3500",
            " 02 543 4037 ": "02-543-4037",
            "02022088": "02022088",  # fits no numbering rule: left as written
        }
        for raw, expected in cases.items():
            self.assertEqual(format_phone(raw), expected, raw)
        self.assertIsNone(format_phone("-"))
        self.assertIsNone(format_phone(None))

    def test_local_numbers_get_the_province_area_code(self):
        cases = [
            ("3672-8441", "서울특별시 종로구 창경궁로 261", "02-3672-8441"),
            ("744-9098", "경기도 수원시 팔달구 1", "031-744-9098"),
            ("943-4567", "전남광주통합특별시 광산구 1", "062-943-4567"),
            ("723-4567", "전남광주통합특별시 순천시 1", "061-723-4567"),
            ("02-543-4037", "부산광역시 해운대구 1", "02-543-4037"),  # already has one
            ("1588-1234", "서울특별시 중구 1", "1588-1234"),  # nationwide number
            ("3672-8441", None, "3672-8441"),  # no address: unknown province
        ]
        for phone, address, expected in cases:
            self.assertEqual(with_area_code(phone, address), expected, (phone, address))
        self.assertIsNone(with_area_code(None, "서울특별시 중구 1"))

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
            merged_cafe = {"시설명": "합칠카페", "카테고리2": "반려동물식당카페", "카테고리3": "카페", "반려동물 동반 가능정보": "Y",
                           "도로명주소": "서울 마포구 9", "지번주소": None, "전화번호": "02-7", "홈페이지": "http://cafe",
                           "위도": "37.55", "경도": "126.9", "운영시간": "매일 9:00~18:00", "휴무일": "월요일",
                           "입장 가능 동물 크기": "모두", "반려동물 제한사항": "목줄", "애견 동반 추가 요금": "없음",
                           "주차 가능여부": "Y", "최종작성일": "2022-01-01"}
            for column, value in merged_cafe.items():
                facility[column].append(value)
            pd.DataFrame(facility).to_csv(inputs["pet_friendly"], index=False, encoding="utf-8-sig")
            pd.DataFrame({  # 한국관광공사: a shop, no conditions, the cafe ~60 m away, a far 멍카페, notes only
                "contentid": ["1", "2", "3", "4", "5"], "contenttypeid": ["38", "12", "39", "39", "12"],
                "title": ["약국", "빈공원", "합칠 카페", "멍카페", "바다공원"],
                "도로명주소": ["서울 마포구 5", "서울 마포구 6", "서울 마포구 9", "부산 해운대구 1", "강원 강릉시 1"],
                "전화번호": [None] * 5, "업종": ["쇼핑", "관광지", "음식점", "음식점", "관광지"],
                "acmpyTypeCd": ["전구역 동반가능"] * 4 + [None],
                "acmpyPsblCpam": ["전 견종 동반 가능", None, "전 견종 동반 가능", "10kg 이하", None],
                "acmpyNeedMtr": ["목줄 착용", None, "목줄 착용", "이동장(켄넬)사용", None],
                "etcAcmpyInfo": [None, None, "- 실내는 동반불가- 배변봉투 지참", None, "- 소형견만 입장"],
                "relaPosesFclty": [None, None, "운동장", None, None],
                "modifiedtime": ["20260101000000"] * 4 + ["20260301120000"],
                "위도": ["37.55", "37.55", "37.5505", "35.16", "37.75"], "경도": ["126.9", "126.9", "126.9", "129.16", "128.9"],
            }).to_csv(inputs["pet_travel"], index=False, encoding="utf-8-sig")
            output = root / "places.db"
            counts = build_places_db.build(output, inputs)
            with closing(sqlite3.connect(output)) as connection:
                rows = {row[0]: row for row in connection.execute("SELECT * FROM place")}
                sources = {row[0]: row for row in connection.execute("SELECT * FROM source")}

        self.assertEqual(counts, {"boarding": 2, "funeral": 1, "grooming": 2, "hospital": 1, "pet_friendly": 1,
                                  "pet_travel": 3, "pharmacy": 2})
        hospital = rows["hospital-1"]
        self.assertEqual(hospital[1:6], ("hospital", "영업병원", "서울특별시 종로구 창경궁로 261", None, "02-1"))
        self.assertAlmostEqual(hospital[9], 37.5846, places=3)  # EPSG:5174 -> WGS84
        self.assertAlmostEqual(hospital[10], 127.0002, places=3)
        self.assertIsNone(rows["pharmacy-a:1"][5])  # masked phone dropped
        self.assertIsNone(rows["pharmacy-a:2"][9])  # (0, 0) is not a location
        self.assertEqual(rows["funeral-1"][3], "경기도 김포시")
        self.assertEqual(rows["grooming-L1"][7], "출장(자동차) 미용")
        self.assertEqual(json.loads(rows["boarding-L1"][8]), {"other_licenses": "미용"})
        [cafe] = [row for key, row in rows.items() if key.startswith("pet_friendly-")]
        self.assertEqual((cafe[2], cafe[6], cafe[7]), ("멍카페", None, "카페"))  # "정보없음" homepage dropped
        self.assertEqual(json.loads(cafe[8])["size"], "소형")
        self.assertEqual(sources["hospital"][4:9], (2, 1, 1, 1, "2026-08-11 22:02:01"))
        self.assertIn("1건 제외", json.loads(sources["hospital"][9])[0])
        notes = json.loads(sources["pet_friendly"][9])
        self.assertTrue(any("동반 불가(N) 1건" in note for note in notes))
        self.assertTrue(any("중복 1건" in note for note in notes))
        self.assertEqual(sources["grooming"][8], "2026-10-02")  # date in the file name
        travel = {key: json.loads(row[8]) for key, row in rows.items() if key.startswith("pet_travel-")}
        self.assertEqual(set(travel), {"pet_travel-3", "pet_travel-4", "pet_travel-5"})  # no shop, no empty one
        merged = rows["pet_travel-3"]
        self.assertEqual((merged[1], merged[5], merged[6], merged[7]), ("pet_friendly", "02-7", "http://cafe", "식당"))
        self.assertEqual(travel["pet_travel-3"], {
            "zone": "전구역", "allowed": "전 견종 동반 가능", "needs": "목줄 착용", "other": "실내는 동반불가 · 배변봉투 지참",
            "facilities": "운동장", "written": "2026-01-01", "size_rule": "all", "carrier": False, "all_areas": False,
            "hours": "매일 9:00~18:00", "closed": "월요일", "extra_fee": "없음", "parking": "Y"})  # 문화정보원's details kept
        self.assertEqual((travel["pet_travel-4"]["size_rule"], travel["pet_travel-4"]["carrier"]), ("limited", True))
        self.assertNotIn("hours", travel["pet_travel-4"])  # same name, 400 km away: another place
        self.assertEqual({key: travel["pet_travel-5"][key] for key in ("zone", "allowed", "needs", "size_rule")},
                         {"zone": "정보 부족, 확인 필요", "allowed": "정보 부족, 확인 필요", "needs": "정보 부족, 확인 필요",
                          "size_rule": "limited"})
        self.assertNotIn("carrier", travel["pet_travel-5"])  # unknown, not "no carrier"
        self.assertEqual(sources["pet_travel"][4:6], (5, 3))
        self.assertTrue(any("같은 곳 1건" in note for note in json.loads(sources["pet_friendly"][9])))


class ConditionTests(unittest.TestCase):
    def test_size_rule(self):
        for text, rule in (("전 견종 동반 가능", "all"), ("맹견 제외 전 견종 동반 가능", "all"), ("전 견동 동반 가능", "all"),
                           ("이동장(켄넬)에 들어가는 전 견종 동반 가능", "limited"), ("대형견 제외 전 견종 동반 가능", "limited"),
                           ("대형견은 여름에만 동반 가능", "limited"), ("20㎏ 미만 동반 가능", "limited"), ("소형견", "limited"),
                           ("시각 장애인 안내견", "limited"), ("반려견", None), ("전화문의", None), (None, None)):
            with self.subTest(text):
                self.assertEqual(size_rule(text), rule)
        self.assertEqual(size_rule(None, "객실 당 5kg미만 소형견 2마리"), "limited")
        self.assertIsNone(size_rule(None, "전 견종 가능"))  # the notes never make it "all"

    def test_carrier(self):
        self.assertTrue(needs_carrier("목줄 착용,이동장(켄넬)사용"))
        self.assertTrue(needs_carrier("목줄 착용", "식당이용시 이동장 이용 필수"))
        self.assertTrue(needs_carrier(None, None, "케이지나 반려견 유모차 이용"))
        self.assertFalse(needs_carrier("목줄 착용", "계단이 많아 이동장은 어려울것"))
        self.assertIsNone(needs_carrier(None))

    def test_all_areas(self):
        self.assertTrue(all_areas("전구역 동반가능", "배변봉투 지참"))
        self.assertFalse(all_areas("전구역 동반가능", "실내는 동반불가"))
        self.assertFalse(all_areas("전구역 동반가능", "야외 공간만 동반 가능"))
        self.assertFalse(all_areas("일부구역 동반가능"))
        self.assertIsNone(all_areas(None))

    def test_a_missing_condition_never_matches(self):
        info = {"size_rule": "all", "carrier": False, "all_areas": True}
        self.assertTrue(matches_conditions(info, large_dog=True, no_carrier=True, all_areas=True))
        self.assertTrue(matches_conditions({}, large_dog=False))
        self.assertFalse(matches_conditions({"carrier": None}, no_carrier=True))
        self.assertFalse(matches_conditions(json.dumps({"size": "모두 가능"}), large_dog=True))  # 문화정보원 place


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

    def test_a_count_without_man_and_in_korean_number_words(self):
        # "마포구 동물병원 3곳 알려줘" listed 10 places (2026-10-12): the count needed "만".
        for question, count in (("마포구 동물병원 3곳 알려줘", 3), ("해운대구 동물병원 세 곳 추천해줘", 3),
                                ("수원 애견미용 두 군데 알려줘", 2), ("강동구 동물병원 4개 찾아줘", 4),
                                ("성남시 애견호텔 다섯 곳 보여줘", 5), ("마포구 동물병원 7군데 목록", 7)):
            with self.subTest(question):
                self.assertEqual(places.get_hospital_result_limit(question), count)
        for question in ("3개월 된 강아지 데려갈 마포구 동물병원 알려줘", "24시 동물병원 강남구 알려줘",
                         "2층에 있는 강남구 동물병원 알려줘", "강아지 두 마리 데려갈 수 있는 송파구 동물병원 알려줘",
                         "1살 강아지 강남구 동물병원 알려줘", "서초구 동물병원 알려줘"):
            with self.subTest(question):
                self.assertEqual(places.get_hospital_result_limit(question), 10)


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

    def add_places(self, *rows):
        with closing(sqlite3.connect(resources.DB_PATH)) as connection:
            connection.executemany(
                "INSERT INTO place (id, kind, name, road_address, category) VALUES (?, ?, ?, ?, ?)", rows)
            connection.commit()

    def test_short_region_names_use_the_fixed_sql(self):
        model = Mock(side_effect=AssertionError("the model must not write this SQL"))
        with patch.object(resources, "load_chat_model", model):
            for question, name in (("강남 동물병원 알려줘", "강남동물병원"), ("마포에 있는 동물병원", "마포동물병원"),
                                   ("김포 장례식장 찾아줘", "하늘장례식장"), ("서울 동물약국", "강남약국")):
                with self.subTest(question):
                    _, rows = places.run_sql_search(question)
                    self.assertEqual([row["name"] for row in rows], [name])

    def test_words_that_only_look_like_regions(self):
        self.add_places(("hospital-g", "hospital", "고양동물병원", "경기도 고양시 덕양구 1", None),
                        ("hospital-k", "hospital", "공주동물병원", "충청남도 공주시 1", None),
                        ("hospital-n", "hospital", "남양주동물병원", "경기도 남양주시 1", None))
        for cache in (places.known_region_words, places.short_region_names, places._short_region_pattern):
            cache.cache_clear()
        self.assertEqual(places.extract_search_parameters("고양 동물병원"), ["고양시"])
        self.assertEqual(places.extract_search_parameters("고양이 진료 잘하는 동물병원"), [])
        self.assertEqual(places.extract_search_parameters("우리 공주 다니던 동물병원"), [])  # a pet, not 공주시
        self.assertEqual(places.extract_search_parameters("남양주 동물병원"), ["남양주시"])
        self.assertEqual(router.symptom_part("설사하는데 강남 동물병원 알려줘"), "설사하는데")

    def test_a_city_split_into_gus_by_direction_goes_by_its_shared_name(self):
        self.add_places(("hospital-e", "hospital", "일산동물병원", "경기도 고양시 일산동구 1", None),
                        ("hospital-w", "hospital", "호수동물병원", "경기도 고양시 일산서구 1", None),
                        ("hospital-d", "hospital", "강동동물병원", "서울특별시 강동구 1", None))
        for cache in (places.known_region_words, places.short_region_names, places._short_region_pattern):
            cache.cache_clear()
        self.assertEqual(places.extract_search_parameters("일산 동물병원"), ["일산동구", "일산서구"])
        self.assertEqual(places.extract_search_parameters("강동 동물병원"), ["강동구"])  # not "강" from 강동구

    def test_pet_friendly_category_is_kept(self):
        self.add_places(("pet_friendly-2", "pet_friendly", "멍멍공원", "서울특별시 강남구 공원로 1", "여행지"))
        _, rows = self.search("강남구 애견동반 카페 알려줘")
        self.assertEqual([row["name"] for row in rows], ["멍멍카페"])
        _, rows = self.search("강남구 반려견 동반 가능한 곳 알려줘")
        self.assertEqual({row["name"] for row in rows}, {"멍멍카페", "멍멍공원"})

    def test_condition_words_filter_the_places_with_stated_conditions(self):
        with closing(sqlite3.connect(resources.DB_PATH)) as connection:
            connection.execute(
                "INSERT INTO place (id, kind, name, road_address, category, info) VALUES (?, ?, ?, ?, ?, ?)",
                ("pet_travel-1", "pet_friendly", "넓은공원", "서울특별시 강남구 공원로 2", "여행지",
                 json.dumps({"zone": "전구역", "allowed": "전 견종 동반 가능", "needs": "목줄 착용",
                             "size_rule": "all", "carrier": False, "all_areas": True}, ensure_ascii=False)))
            connection.commit()
        answer, rows = self.search("강남구 대형견 동반 가능한 곳 알려줘")
        self.assertEqual([row["name"] for row in rows], ["넓은공원"])  # 멍멍카페 has no stated conditions
        self.assertTrue(answer.startswith(places.CONDITION_NOTICE))
        self.assertIn("동반 가능 반려견: 전 견종 동반 가능", answer)
        _, rows = self.search("강남구 애견동반 이동장 없이 갈 수 있는 곳")
        self.assertEqual([row["name"] for row in rows], ["넓은공원"])
        self.assertEqual(places.extract_search_parameters("강남구 이동장 없이"), ["강남구"])  # 이동장 holds 이동
        _, rows = self.search("강남구 반려견 동반 가능한 곳 알려줘")
        self.assertEqual({row["name"] for row in rows}, {"멍멍카페", "넓은공원"})

    def test_count_per_kind(self):
        answer, _ = self.search("서울특별시 동물병원 몇 곳이야?")
        self.assertEqual(answer.splitlines()[0], "조건에 맞는 동물병원은 2곳입니다.")
        self.assertIn("동물병원 알려줘", answer)  # how to see the list
        self.assertIn("기준", answer)  # the source and its date
        answer, _ = self.search("김포시 장례식장 몇 곳이야?")
        self.assertEqual(answer.splitlines()[0], "조건에 맞는 장묘업체는 1곳입니다.")

    def test_nearest_needs_coordinates(self):
        answer, rows = self.search("가까운 약국 찾아줘", location=(37.49, 127.04))
        self.assertEqual(rows[0]["name"], "강남약국")
        self.assertIn("동물약국", answer)
        for question in ("가까운 장례식장 찾아줘", "근처 애견미용 찾아줘"):
            answer, rows = self.search(question, location=(37.49, 127.04))
            self.assertEqual(rows, [])
            self.assertIn("좌표가 없어", answer)

    def test_earlier_questions_give_only_the_missing_kind_or_region(self):
        # The graph passes recent user questions joined by newlines, the current one last.
        _, rows = self.search("애견동반 펜션 1곳만 추천해줘\n강남구 동물병원 알려줘")
        self.assertEqual([row["name"] for row in rows], ["강남동물병원"])  # no "1곳만", no pet_friendly
        _, rows = self.search("강남구 동물병원 알려줘\n동물약국은?")
        self.assertEqual([row["name"] for row in rows], ["강남약국"])  # region from the earlier question
        _, rows = self.search("강남구 동물병원 알려줘\n마포구는?")
        self.assertEqual([row["name"] for row in rows], ["마포동물병원"])  # kind from the earlier question

    def test_emergency_lists_nearest_and_24h_named_hospitals(self):
        with closing(sqlite3.connect(resources.DB_PATH)) as connection:
            connection.execute(
                "INSERT INTO place (id, kind, name, road_address, phone, latitude, longitude) "
                "VALUES ('hospital-3', 'hospital', '24시 하늘동물의료센터', '서울특별시 송파구 1', '02-999-9999', 37.51, 127.10)"
            )
            connection.commit()
        found = places.emergency_hospitals((37.50, 127.03), nearest=1, named=2)
        self.assertEqual([row["name"] for row in found["nearest"]], ["강남동물병원"])
        self.assertEqual([row["name"] for row in found["night"]], ["24시 하늘동물의료센터"])
        self.assertGreater(found["night"][0]["distance_km"], 5)

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
            app = AppTest.from_file(str(PROJECT_DIR / "app_pages" / "hospital.py"), default_timeout=30).run()
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

    @needs_private_data
    def test_data_page_shows_the_cleaning_steps(self):
        with TemporaryDirectory() as directory, patch.object(resources, "DB_PATH", make_db(directory)):
            app = AppTest.from_file(str(PROJECT_DIR / "app_pages" / "data.py"), default_timeout=30).run()
            self.assertEqual([e.message for e in app.exception], [])
            self.assertTrue(any("정제 단계" in markdown.value for markdown in app.markdown))


if __name__ == "__main__":
    unittest.main()


class NightCareTests(unittest.TestCase):
    """"24시간 하는 곳": no opening hours in the data, so names with 24시/응급/야간 are shown."""

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        db_path = Path(directory.name) / "places.sqlite"
        with closing(sqlite3.connect(db_path)) as connection:
            connection.execute(
                "CREATE TABLE place (id TEXT, kind TEXT, name TEXT, road_address TEXT, lot_address TEXT, phone TEXT, "
                "category TEXT, info TEXT, latitude REAL, longitude REAL)")
            rows = [("h1", "hospital", "청담동물병원", "서울 강남구 1", "", "02-1", "", "", 37.5, 127.0),
                    ("h2", "hospital", "강남24시동물메디컬센터", "서울 강남구 2", "", "02-2", "", "", 37.5, 127.01),
                    ("h3", "hospital", "마포야간동물병원", "서울 마포구 3", "", "02-3", "", "", 37.55, 126.9),
                    ("h4", "hospital", "서초동물병원", "서울 서초구 4", "", "02-4", "", "", 37.48, 127.03)]
            connection.executemany("INSERT INTO place VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            connection.commit()
        patcher = patch.object(resources, "DB_PATH", db_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        for cache in (places.known_region_words, places.short_region_names, places._short_region_pattern):
            cache.cache_clear()

    def test_a_follow_up_keeps_the_region_and_shows_only_night_named_hospitals(self):
        with patch.object(resources, "load_chat_model", return_value=None):
            answer, rows = places.run_sql_search("강남구 동물병원 알려줘\n그중에 24시간 하는 곳도 있어?")
        self.assertEqual([row["id"] for row in rows], ["h2"])
        self.assertIn("영업시간 정보가 없어", answer)

    def test_none_found_says_so_instead_of_listing_everything(self):
        with patch.object(resources, "load_chat_model", return_value=None):
            answer, rows = places.run_sql_search("서초구 야간 진료하는 동물병원")
        self.assertEqual(rows, [])
        self.assertIn("찾지 못했습니다", answer)

    def test_nearest_night_hospital_filters_by_name_too(self):
        answer, rows = places.run_sql_search("가장 가까운 24시 동물병원", location=(37.5, 127.0))
        self.assertEqual({row["id"] for row in rows}, {"h2", "h3"})  # h1, h4 are closer but not night-named
        self.assertTrue(answer.startswith("영업시간 정보가 없어"))

    def test_symptom_and_place_requests_are_recognized(self):
        self.assertTrue(router.is_symptom_and_place_request("설사가 이틀째인데 마포구 동물병원 어디 있어?"))
        self.assertFalse(router.is_symptom_and_place_request("설사가 이틀째예요"))
        self.assertFalse(router.is_symptom_and_place_request("마포구 동물병원 어디 있어?"))
        self.assertTrue(router.is_symptom_and_place_request("강아지가 토하는데 강남구 동물병원 알려줘"))
        self.assertEqual(router.symptom_part("설사가 이틀째인데 마포구 동물병원 어디 있어?"), "설사가 이틀째인데")
        self.assertEqual(router.symptom_part("혈변을 봤어요 근처 동물병원 알려줘"), "혈변을 봤어요")
        self.assertEqual(router.symptom_part("기침을 계속 하는데 수원 동물병원 목록 보여줘"), "기침을 계속 하는데")

    def test_other_questions_are_unchanged(self):
        self.assertFalse(places.wants_night_care("강남구 동물병원 알려줘"))
        self.assertTrue(places.wants_night_care("밤에 여는 병원 있어?"))


class StockNoticeTests(unittest.TestCase):
    """The data has no stock: a pharmacy list says so instead of skipping that part of the question."""

    def test_a_stock_request_gets_the_list_and_says_the_stock_is_unknown(self):
        with TemporaryDirectory() as directory, patch.object(resources, "DB_PATH", make_db(directory)), \
                patch.object(resources, "load_chat_model", return_value=None):
            answer, rows = places.run_sql_search("강남구 동물약국과 실시간 약품 재고를 알려주세요")
            self.assertTrue(rows)
            self.assertTrue(answer.startswith(places.STOCK_NOTICE))
            answer, _ = places.run_sql_search("강남구 동물약국 알려줘")
            self.assertNotIn(places.STOCK_NOTICE, answer)

    def test_only_pharmacies_get_the_stock_notice(self):
        self.assertTrue(places.wants_stock("심장사상충약 파는 약국"))
        self.assertEqual(places._with_stock_notice("목록", "grooming", "재고 있어?"), "목록")


class GeneratedSqlLimitTests(unittest.TestCase):
    """A model-written query is shaped by validate_sql but not bounded in cost (2026-10-16 review)."""

    def test_a_runaway_query_is_stopped_and_rows_are_capped(self):
        from src.tools import places

        with patch.object(places, "SQL_SECONDS", 0.2):
            started = time.monotonic()
            with self.assertRaises(sqlite3.OperationalError):
                places.execute_place_sql(places.validate_sql(
                    "SELECT a.id FROM place a JOIN place b JOIN place c WHERE a.name || b.name || c.name = 'x'"))
            self.assertLess(time.monotonic() - started, 5)
        rows = places.execute_place_sql("SELECT id FROM place")
        self.assertEqual(len(rows), places.SQL_MAX_ROWS)
