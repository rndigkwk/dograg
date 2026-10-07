"""The pet-places database (data/places.db): place kinds, region names, distance ranking.

`scripts/build_places_db.py` builds one `place` table from public data. Coordinates are
stored as WGS84 latitude/longitude, converted and range-checked at build time, so the
app needs no coordinate library at runtime.
"""

from __future__ import annotations

import json
from math import asin, cos, isfinite, radians, sin, sqrt

KIND_LABELS = {
    "hospital": "동물병원",
    "pharmacy": "동물약국",
    "pet_friendly": "반려동물 동반 시설",
    "grooming": "동물미용업체",
    "boarding": "위탁관리업체",
    "funeral": "장묘업체",
}
# Sources without coordinates: searched by region only.
NO_LOCATION_KINDS = frozenset({"funeral", "grooming", "boarding"})
# pet_friendly `info` JSON keys -> labels shown to people.
INFO_LABELS = {
    "hours": "운영시간", "closed": "휴무일", "size": "입장 가능 크기", "restrictions": "제한사항",
    "extra_fee": "추가 요금", "parking": "주차", "other_licenses": "함께 등록된 업종", "written": "정보 작성일",
}
SCHEMA = """
CREATE TABLE place (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    road_address TEXT,
    lot_address TEXT,
    phone TEXT,
    homepage TEXT,
    category TEXT,
    info TEXT,          -- JSON object, keys in INFO_LABELS
    latitude REAL,
    longitude REAL
);
CREATE INDEX place_kind ON place(kind);
CREATE TABLE source (
    kind TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    file TEXT NOT NULL,
    source_rows INTEGER NOT NULL,
    rows INTEGER NOT NULL,
    with_location INTEGER NOT NULL,
    with_phone INTEGER NOT NULL,
    updated TEXT,
    notes TEXT          -- JSON list of the cleaning steps and their counts
);
"""


def describe_info(info: str | None) -> list[str]:
    """'운영시간: 매일 10:00~22:00' lines from the `info` JSON column."""
    if not info:
        return []
    values = json.loads(info)
    return [f"{label}: {values[key]}" for key, label in INFO_LABELS.items() if values.get(key)]

# Short and pre-2026 province names in the sources -> the names the current data uses.
SIDO_ALIASES = {
    "서울": "서울특별시", "서울시": "서울특별시",
    "부산": "부산광역시", "부산시": "부산광역시",
    "대구": "대구광역시", "대구시": "대구광역시",
    "인천": "인천광역시", "인천시": "인천광역시",
    "대전": "대전광역시", "대전시": "대전광역시",
    "울산": "울산광역시", "울산시": "울산광역시",
    "세종": "세종특별자치시", "세종시": "세종특별자치시",
    "경기": "경기도",
    "강원": "강원특별자치도", "강원도": "강원특별자치도",
    "충북": "충청북도", "충남": "충청남도",
    "전북": "전북특별자치도", "전라북도": "전북특별자치도",
    "전남": "전남광주통합특별시", "전라남도": "전남광주통합특별시", "광주광역시": "전남광주통합특별시",
    "경북": "경상북도", "경남": "경상남도",
    "제주": "제주특별자치도", "제주도": "제주특별자치도",
}
SIDO_NAMES = frozenset(SIDO_ALIASES.values())
# A source address that starts with a city instead of a province.
CITY_PROVINCES = {"안산시": "경기도"}


def normalize_address(address: str | None) -> str | None:
    """Full province name first, placeholder words removed; None for an empty address."""
    if address is None:
        return None
    words = [word for word in str(address).split() if word.lower() not in {"null", "nan", "none"}]
    if not words:
        return None
    first = words[0]
    if first in SIDO_ALIASES:
        words[0] = SIDO_ALIASES[first]
    elif first in CITY_PROVINCES:
        words.insert(0, CITY_PROVINCES[first])
    return " ".join(words)


def province_of(address: str | None) -> str | None:
    if not address:
        return None
    first = address.split()[0]
    return first if first in SIDO_NAMES else None


def in_korea(latitude, longitude) -> bool:
    try:
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return False
    return isfinite(latitude) and isfinite(longitude) and 33 <= latitude <= 39 and 124 <= longitude <= 132


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 6371.0088 * 2 * asin(min(1, sqrt(a)))


def nearest_places(rows: list[dict], latitude: float, longitude: float, limit: int = 10) -> list[dict]:
    """Rows with valid coordinates by straight-line distance, then id; adds `distance_km`."""
    try:
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError) as exc:
        raise ValueError("유효하지 않은 위치입니다.") from exc
    if not in_korea(latitude, longitude):
        raise ValueError("위치는 대한민국 범위의 위도/경도여야 합니다.")
    ranked = [
        {**row, "distance_km": distance_km(latitude, longitude, float(row["latitude"]), float(row["longitude"]))}
        for row in rows
        if in_korea(row.get("latitude"), row.get("longitude"))
    ]
    return sorted(ranked, key=lambda row: (row["distance_km"], str(row.get("id"))))[:max(0, limit)]
