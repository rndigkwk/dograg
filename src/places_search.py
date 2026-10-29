"""Finding pet places in data/places.db: by region, nearest to a location, one by id. Shared by the
facility page (app_pages/hospital.py) and the API (api/places.py, ADR-0008). No model calls.

The queries are the page's own (moved here unchanged): a region matches the start of the road or
lot address for the province and anywhere in it for the city, county or district.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing

from src import resources
from src.places_data import (
    KIND_LABELS,
    NO_LOCATION_KINDS,
    SOURCE_KINDS,
    describe_info,
    matches_conditions,
    nearest_places,
)

COLUMNS = "id, kind, name, road_address, lot_address, phone, homepage, category, info, latitude, longitude"

# Province -> cities, counties and districts offered for the region search (moved from the page).
REGIONS = {

    "서울특별시": [
            "종로구", "중구", "용산구", "성동구", "광진구", "동대문구",
            "중랑구", "성북구", "강북구", "도봉구", "노원구", "은평구",
            "서대문구", "마포구", "양천구", "강서구", "구로구", "금천구",
            "영등포구", "동작구", "관악구", "서초구", "강남구", "송파구",
            "강동구"
        ],

    "경기도": [
        "수원시", "성남시", "의정부시", "안양시", "부천시", "광명시",
        "평택시", "동두천시", "안산시", "고양시", "과천시", "구리시",
        "남양주시", "오산시", "시흥시", "군포시", "의왕시", "하남시",
        "용인시", "파주시", "이천시", "안성시", "김포시", "연천군",
        "가평군", "양평군", "화성시", "광주시", "양주시", "포천시",
        "여주시"
    ],

    "부산광역시": [
        "중구", "서구", "동구", "영도구", "부산진구", "동래구",
        "남구", "북구", "해운대구", "사하구", "금정구", "강서구",
        "연제구", "수영구", "사상구", "기장군"
    ],

    "경상남도": [
        "진주시", "통영시", "사천시", "김해시", "밀양시", "거제시",
        "양산시", "의령군", "함안군", "창녕군", "고성군", "남해군",
        "하동군", "산청군", "함양군", "거창군", "합천군", "창원시"
    ],

    "전남광주통합특별시": [
        "목포시", "여수시", "순천시", "나주시", "광양시",
        "동구", "서구", "남구", "북구", "광산구",
        "담양군", "곡성군", "구례군", "고흥군", "보성군",
        "화순군", "장흥군", "강진군", "해남군", "영암군",
        "무안군", "함평군", "영광군", "장성군", "완도군",
        "진도군", "신안군"
    ],

    "인천광역시": [
        "중구", "영종구", "제물포구", "미추홀구", "연수구",
        "남동구", "부평구", "계양구", "서해구", "검단구", "강화군"
    ],

    "경상북도": [
        "포항시", "경주시", "김천시", "안동시", "구미시", "영주시",
        "영천시", "상주시", "문경시", "경산시", "의성군", "청송군",
        "영양군", "영덕군", "청도군", "고령군", "성주군", "칠곡군",
        "예천군", "봉화군", "울진군", "울릉군"
    ],

    "대구광역시": [
        "중구", "동구", "서구", "남구", "북구",
        "수성구", "달서구", "달성군", "군위군"
    ],

    "충청남도": [
        "천안시", "공주시", "보령시", "아산시", "서산시",
        "논산시", "금산군", "부여군", "서천군", "청양군",
        "홍성군", "예산군", "태안군", "계룡시", "당진시"
    ],

    "전북특별자치도": [
        "전주시", "군산시", "익산시", "정읍시", "남원시",
        "김제시", "완주군", "진안군", "무주군", "장수군",
        "임실군", "순창군", "고창군", "부안군"
    ],

    "충청북도": [
        "충주시", "제천시", "보은군", "옥천군", "영동군",
        "진천군", "괴산군", "음성군", "단양군", "증평군",
        "청주시"
    ],

    "강원특별자치도": [
        "춘천시", "원주시", "강릉시", "동해시", "태백시", "속초시",
        "삼척시", "홍천군", "횡성군", "영월군", "평창군", "정선군",
        "철원군", "화천군", "양구군", "인제군", "고성군", "양양군"
    ],

    "대전광역시": [
        "동구", "중구", "서구", "유성구", "대덕구"
    ],

    "울산광역시": [
        "중구", "남구", "동구", "북구", "울주군"
    ],

    "제주특별자치도": [
        "제주시", "서귀포시"
    ],

    "세종특별자치시": [
        "한누리대로", "새롬중앙로", "조치원읍", "마음로", "다정중앙로",
        "장군면", "나성로", "보람로", "집현북로", "해밀3로", "금남면",
        "아름서1길", "도움3로", "보듬3로", "연서면", "다정1길", "노을1로"
    ]
}


def _rows(sql: str, parameters=()) -> list[dict]:
    with closing(sqlite3.connect(f"file:{resources.DB_PATH.as_posix()}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(sql, list(parameters))]


def public(row: dict) -> dict:
    """A place as the API returns it: the info JSON parsed and its readable lines, one address."""
    info = row.get("info")
    return {**{key: row.get(key) for key in COLUMNS.split(", ") if key != "info"},
            "address": row.get("road_address") or row.get("lot_address") or None,
            "info": json.loads(info) if isinstance(info, str) and info else {},
            "info_lines": describe_info(info),
            **({"distance_km": round(row["distance_km"], 3)} if "distance_km" in row else {})}


def sources() -> dict[str, dict]:
    """Where each kind's data comes from: title, url, rows, updated. A source stored under another kind
    (SOURCE_KINDS) is listed in that kind's `more`, and its rows count in the kind's total."""
    found = {row["kind"]: row for row in _rows("SELECT kind, title, url, rows, updated FROM source")}
    for extra, kind in SOURCE_KINDS.items():
        if extra in found and kind in found:
            more = found.pop(extra)
            found[kind] = {**found[kind], "rows": found[kind]["rows"] + more["rows"],
                           "more": [*found[kind].get("more", []), more]}
    return found


def in_region(kind: str, province: str, city: str | None = None, **wanted: bool) -> list[dict]:
    """`wanted`: CONDITION_FILTERS names (all_areas, large_dog, no_carrier) the places must meet."""
    conditions = ["kind = ?", "(road_address LIKE ? OR lot_address LIKE ?)"]
    parameters = [kind, f"{province}%", f"{province}%"]
    if city:
        conditions.append("(road_address LIKE ? OR lot_address LIKE ?)")
        parameters += [f"%{city}%", f"%{city}%"]
    rows = _rows(f"SELECT {COLUMNS} FROM place WHERE {' AND '.join(conditions)} ORDER BY name", parameters)
    return [row for row in rows if matches_conditions(row["info"], **wanted)]


def nearest(kind: str, latitude: float, longitude: float, limit: int = 10, **wanted: bool) -> list[dict]:
    """Raises ValueError for a kind without coordinates or a location outside Korea."""
    if kind in NO_LOCATION_KINDS:
        raise ValueError(f"{KIND_LABELS[kind]} 목록에는 좌표가 없어 지역으로만 찾을 수 있습니다.")
    rows = _rows(f"SELECT {COLUMNS} FROM place WHERE kind = ? AND latitude IS NOT NULL", [kind])
    rows = [row for row in rows if matches_conditions(row["info"], **wanted)]
    return nearest_places(rows, latitude, longitude, limit=limit)


def by_id(place_id: str) -> dict | None:
    rows = _rows(f"SELECT {COLUMNS} FROM place WHERE id = ?", [place_id])
    return rows[0] if rows else None
