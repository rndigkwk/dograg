"""The pet-places database (data/places.db): place kinds, region names, distance ranking.

`scripts/build_places_db.py` builds one `place` table from public data. Coordinates are
stored as WGS84 latitude/longitude, converted and range-checked at build time, so the
app needs no coordinate library at runtime.
"""

from __future__ import annotations

import json
import re
from math import asin, cos, isfinite, radians, sin, sqrt

KIND_LABELS = {
    "hospital": "동물병원",
    "pharmacy": "동물약국",
    "pet_friendly": "반려동물 동반 시설",
    "grooming": "동물미용업체",
    "boarding": "위탁관리업체",
    "funeral": "장묘업체",
}
# Sources whose places are stored under another kind: 한국관광공사's pet travel places are pet_friendly
# places with companion conditions (one `source` row each, so both sources keep their counts).
SOURCE_KINDS = {"pet_travel": "pet_friendly"}
# Sources without coordinates: searched by region only.
NO_LOCATION_KINDS = frozenset({"funeral", "grooming", "boarding"})
# `info` JSON keys -> labels shown to people (pet_friendly from both sources, boarding).
INFO_LABELS = {
    "zone": "동반 구역", "allowed": "동반 가능 반려견", "needs": "동반 시 필요", "other": "기타 안내",
    "facilities": "반려동물 시설",
    "hours": "운영시간", "closed": "휴무일", "size": "입장 가능 크기", "restrictions": "제한사항",
    "extra_fee": "추가 요금", "parking": "주차", "other_licenses": "함께 등록된 업종", "written": "정보 작성일",
}
# An empty 관광공사 condition is not "no restriction" (the source just did not say).
UNKNOWN_CONDITION = "정보 부족, 확인 필요"
# Condition filters: the info value each one requires. A place without the value never matches, so
# the 문화정보원 places (no zone, size rule or carrier) are left out of a filtered search.
CONDITION_FILTERS = {
    "all_areas": ("all_areas", True),
    "large_dog": ("size_rule", "all"),
    "no_carrier": ("carrier", False),
}
_SIZE_LIMITS = ("소형", "중형", "kg", "㎏", "cm", "이동장", "켄넬", "안내견")
_LARGE_EXCLUDED = re.compile(r"대형견\S{0,3}(?:제외|불가|여름)")  # '대형견 제외', '대형견은 여름에만'
# '전 견동', '전 경종', '상관업이' are typos in the source.
_ALL_SIZES = ("전견종", "전견동", "전경종", "모든견종", "모든반려견", "견종제한없", "견종무관", "상관없", "상관업", "제한없음")
_CARRIERS = ("이동장", "켄넬", "유모차")
_PARTIAL_AREA = re.compile(r"(?:실내|내부|객실|건물|매장|전시관)[^.·/]{0,8}?(?:불가|금지|제한|안\s?됨)|(?:야외|실외)[^.·/]{0,10}?만")
_CARRIER_RULE = re.compile(r"(?:이동장|켄넬|케이지|유모차)[^.·/]{0,8}?(?:필수|필요|사용|이용|탑승|넣)")


def _limits_size(text: str) -> bool:
    compact = "".join(text.split()).lower()
    return any(word in compact for word in _SIZE_LIMITS) or bool(_LARGE_EXCLUDED.search(compact))


def size_rule(allowed: str | None, other: str | None = None) -> str | None:
    """'all' when every size may come (e.g. '전 견종 동반 가능', '맹견 제외 전 견종'), 'limited' for a size,
    weight, carrier or guide-dog rule, None when the text does not say. A rule wins over '전 견종':
    '이동장(켄넬)에 들어가는 전 견종' is a small-dog rule. Without `allowed`, a rule in the extra notes
    ('객실 당 5kg미만 소형견 2마리') still makes it 'limited'; they never make it 'all'."""
    if not allowed:
        return "limited" if other and _limits_size(other) else None
    if _limits_size(allowed):
        return "limited"
    compact = "".join(allowed.split()).lower()
    return "all" if any(word in compact for word in _ALL_SIZES) else None


def all_areas(zone: str | None, other: str | None = None, allowed: str | None = None) -> bool | None:
    """Whether the whole place, indoors too, is open to dogs. The source's '전구역' is not enough: some of
    those places write '실내는 동반불가' or '야외 공간만' in the notes (2026-10-29 sample)."""
    if not zone:
        return None
    if "일부" in zone:
        return False
    return not _PARTIAL_AREA.search(" ".join(text for text in (other, allowed) if text))


def needs_carrier(needs: str | None, other: str | None = None, allowed: str | None = None) -> bool | None:
    """Whether a carrier or a stroller is required: from the listed needs, or a rule in the notes or the
    allowed text ('식당이용시 이동장 이용 필수', '케이지나 반려견 유모차 이용'). '이동장은 어려울것' is not
    a rule. None when the needs are empty and no rule is written."""
    if needs and any(word in needs for word in _CARRIERS):
        return True
    if _CARRIER_RULE.search(" ".join(text for text in (other, allowed) if text)):
        return True
    return False if needs else None


def matches_conditions(info: str | dict | None, **wanted: bool) -> bool:
    """Whether a place's info meets every requested CONDITION_FILTERS entry (False ones are ignored)."""
    values = json.loads(info) if isinstance(info, str) else (info or {})
    return all(values.get(CONDITION_FILTERS[name][0]) == CONDITION_FILTERS[name][1]
               for name, on in wanted.items() if on)


def name_key(name: str | None) -> str:
    """A place name without spaces, punctuation and case, to compare names across sources."""
    return re.sub(r"[\W_]+", "", name or "").lower()
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


def format_phone(raw: str | None) -> str | None:
    """'025434037' -> '02-543-4037', '050714049333' -> '0507-1404-9333'.

    Re-splits the digits by the Korean numbering plan: 02 (Seoul), 050X (safe numbers),
    1XXX-XXXX (nationwide), 0XX area and mobile codes, and local numbers without an area
    code. A number that fits none of these is returned as it was written.
    """
    if raw is None:
        return None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    size = len(digits)
    if digits.startswith("02") and size in (9, 10):
        return f"02-{digits[2:-4]}-{digits[-4:]}"
    if digits.startswith("050") and size == 12:
        return f"{digits[:4]}-{digits[4:8]}-{digits[8:]}"
    if digits[0] == "1" and size == 8:
        return f"{digits[:4]}-{digits[4:]}"
    if digits[0] == "0" and size in (10, 11):
        return f"{digits[:3]}-{digits[3:-4]}-{digits[-4:]}"
    if digits[0] != "0" and size in (7, 8):
        return f"{digits[:-4]}-{digits[-4:]}"
    return raw.strip()


# The landline area code of each province (after normalize_address). The merged 전남광주통합특별시
# keeps two codes: its 구 are the former 광주광역시 (062), its 시·군 the former 전라남도 (061).
AREA_CODES = {
    "서울특별시": "02", "부산광역시": "051", "대구광역시": "053", "인천광역시": "032", "대전광역시": "042",
    "울산광역시": "052", "세종특별자치시": "044", "경기도": "031", "강원특별자치도": "033", "충청북도": "043",
    "충청남도": "041", "전북특별자치도": "063", "경상북도": "054", "경상남도": "055", "제주특별자치도": "064",
}
_LOCAL_NUMBER = re.compile(r"[2-9]\d{2,3}-\d{4}")


def with_area_code(phone: str | None, address: str | None) -> str | None:
    """'3672-8441' at a 서울특별시 address -> '02-3672-8441'. Some sources write landlines without the
    area code, which a phone cannot dial from elsewhere. Only a local number (first digit 2-9, as
    local numbers are) with a known province changes."""
    if not phone or not address or not _LOCAL_NUMBER.fullmatch(phone):
        return phone
    words = address.split()
    if words[0] == "전남광주통합특별시":
        code = "062" if len(words) > 1 and words[1].endswith("구") else "061"
    else:
        code = AREA_CODES.get(words[0])
    return f"{code}-{phone}" if code else phone


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
