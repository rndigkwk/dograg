"""Build data/places.db, the pet-places database, from public data.

    uv run python scripts/build_places_db.py

Sources (download them first; they are not kept in the repository):
- hospital: 행정안전부 동물병원 인허가 CSV (`data/source/동물_동물병원.csv`, CP949, EPSG:5174).
  Only rows whose status is 영업/정상 are kept.
- pharmacy: 행정안전부 동물약국 API, operating rows (`data/animal_pharmacy_operating.csv`,
  collected by scripts/collect_public_data.py, WGS84 columns 위도/경도).
- funeral, grooming, boarding: 국가동물보호정보시스템 장묘업·동물미용업·위탁관리업 lists
  (`data/국가동물보호정보시스템_*.csv`). No coordinates: searched by region only.
- pet_friendly: 한국문화정보원 반려동물 동반 가능 문화시설 (`data/source/한국문화정보원_*.csv`).
  Only travel, cafe/restaurant and culture places marked 동반 가능=Y are kept. Its
  medical rows are left out: the official data above covers them, and the culture data
  repeats each pharmacy about 5.5 times.
- pet_travel: 한국관광공사 반려동물 동반여행 서비스 details (`data/pet_travel_complete.csv`, collected by
  scripts/resume_pet_travel_details.py). Stored as pet_friendly places with their companion
  conditions. Shops (contenttypeid 38) and places without any condition text are left out, and a
  문화정보원 place with the same name within 300 m is merged into the 관광공사 one.

Coordinates outside Korea are dropped (the place stays, without a location). Every
step's row counts go to the `source` table, which the data page shows. The database is
written to a temporary file and moved into place when complete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from pyproj import Transformer

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from src.places_data import (
    SCHEMA,
    UNKNOWN_CONDITION,
    all_areas,
    distance_km,
    format_phone,
    in_korea,
    name_key,
    needs_carrier,
    normalize_address,
    size_rule,
    with_area_code,
)

DATA = PROJECT_DIR / "data"
INPUTS = {
    "hospital": DATA / "source" / "동물_동물병원.csv",
    "pharmacy": DATA / "animal_pharmacy_operating.csv",
    "funeral": DATA / "국가동물보호정보시스템_장묘업목록_20261002.csv",
    "grooming": DATA / "국가동물보호정보시스템_동물미용업_20261002.csv",
    "boarding": DATA / "국가동물보호정보시스템_위탁관리업_20261002.csv",
    "pet_friendly": DATA / "source" / "한국문화정보원_전국 반려동물 동반 가능 문화시설 위치 데이터_20250324.csv",
    "pet_travel": DATA / "pet_travel_complete.csv",
}
OUTPUT = DATA / "places.db"

ANIMAL_GO_KR = "https://www.animal.go.kr"  # portal root; the list pages were not recorded at download time
SOURCES = {
    "hospital": ("행정안전부 동물병원 인허가 정보 (공공데이터포털)", "https://www.data.go.kr"),
    "pharmacy": ("행정안전부 동물약국 정보", "https://www.data.go.kr/data/15155272/openapi.do"),
    "funeral": ("국가동물보호정보시스템 동물장묘업 목록", ANIMAL_GO_KR),
    "grooming": ("국가동물보호정보시스템 동물미용업 목록", ANIMAL_GO_KR),
    "boarding": ("국가동물보호정보시스템 동물위탁관리업 목록", ANIMAL_GO_KR),
    "pet_friendly": ("한국문화정보원 전국 반려동물 동반 가능 문화시설 위치 데이터", "https://www.data.go.kr"),
    "pet_travel": ("한국관광공사 반려동물 동반여행 서비스", "https://www.data.go.kr/data/15135102/openapi.do"),
}
SHOP_TYPE = "38"  # 쇼핑: pharmacies, opticians... almost never with condition text
CONDITION_COLUMNS = ("acmpyPsblCpam", "acmpyNeedMtr", "etcAcmpyInfo")
# 관광공사 업종 -> the pet_friendly categories the search and the chat already use.
TRAVEL_CATEGORIES = {"관광지": "여행지", "숙박": "숙박", "레포츠": "레포츠", "음식점": "식당", "문화시설": "문화시설"}
SAME_PLACE_KM = 0.3
# 문화정보원 details kept on the merged place when the 관광공사 one has none.
MERGED_INFO = ("hours", "closed", "extra_fee", "parking")
PET_FRIENDLY_GROUPS = ("반려동반여행", "반려동물식당카페", "반려문화시설")
PET_FRIENDLY_INFO = {
    "운영시간": "hours", "휴무일": "closed", "입장 가능 동물 크기": "size", "반려동물 제한사항": "restrictions",
    "애견 동반 추가 요금": "extra_fee", "주차 가능여부": "parking", "최종작성일": "written",
}
EMPTY_VALUES = {"", "정보없음", "해당없음", "null", "nan", "none"}
_TM_TO_WGS84 = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)


@dataclass
class Loaded:
    rows: list[tuple] = field(default_factory=list)
    source_rows: int = 0
    updated: str | None = None
    notes: list[str] = field(default_factory=list)


def clean(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return None if text.lower() in EMPTY_VALUES else text


def clean_phone(value) -> str | None:
    text = clean(value)
    return None if text is None or "*" in text else format_phone(text)  # "*": masked in the source


def location(latitude, longitude) -> tuple[float | None, float | None]:
    if not in_korea(latitude, longitude):
        return None, None
    return round(float(latitude), 7), round(float(longitude), 7)


def tm_location(x, y) -> tuple[float | None, float | None]:
    try:
        longitude, latitude = _TM_TO_WGS84.transform(float(x), float(y))
    except (TypeError, ValueError):
        return None, None
    return location(latitude, longitude)


def date_in_name(path: Path) -> str | None:
    stamp = path.stem.rsplit("_", 1)[-1]
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}" if stamp.isdigit() and len(stamp) == 8 else None


def place(place_id, kind, name, road, lot=None, phone=None, homepage=None, category=None, info=None, latitude=None, longitude=None):
    info = {key: value for key, value in (info or {}).items() if value is not None}  # keeps carrier False
    road, lot = normalize_address(clean(road)), normalize_address(clean(lot))
    return (
        place_id, kind, clean(name), road, lot,
        with_area_code(phone, road or lot), clean(homepage), category, json.dumps(info, ensure_ascii=False) if info else None, latitude, longitude,
    )


def load_hospitals(path: Path) -> Loaded:
    frame = pd.read_csv(path, encoding="cp949", dtype=str)
    operating = frame[frame["영업상태명"] == "영업/정상"]
    loaded = Loaded(source_rows=len(frame), updated=clean(operating["데이터갱신시점"].max()))
    loaded.notes.append(f"영업/정상만 사용 (폐업·휴업 등 {len(frame) - len(operating):,}건 제외)")
    for record in operating.to_dict("records"):
        loaded.rows.append(place(
            f"hospital-{record['관리번호']}", "hospital", record["사업장명"], record["도로명주소"], record["지번주소"],
            clean_phone(record["전화번호"]), None, None, None, *tm_location(record["좌표정보(X)"], record["좌표정보(Y)"]),
        ))
    loaded.notes.append("좌표 EPSG:5174 → WGS84 변환 후 국내 범위 검사")
    return loaded


def load_pharmacies(path: Path) -> Loaded:
    frame = pd.read_csv(path, dtype=str)
    operating = frame[frame["SALS_STTS_CD"].str.lstrip("0") == "1"]
    loaded = Loaded(source_rows=len(frame), updated=clean(operating["DAT_UPDT_PNT"].max()))
    loaded.notes.append("수집 단계에서 영업/정상(상태코드 01)만 저장된 파일")
    for record in operating.to_dict("records"):
        loaded.rows.append(place(
            f"pharmacy-{record['고유ID']}", "pharmacy", record["사업장명"], record["도로명주소"], record["지번주소"],
            clean_phone(record["전화번호"]), None, None, None, *location(record["위도"], record["경도"]),
        ))
    return loaded


def load_funeral(path: Path) -> Loaded:
    frame = pd.read_csv(path, dtype=str)
    loaded = Loaded(source_rows=len(frame), updated=date_in_name(path), notes=["좌표 없음: 지역 검색만 지원"])
    for record in frame.to_dict("records"):
        loaded.rows.append(place(
            f"funeral-{record['번호']}", "funeral", record["업체명"], record["소재지"], phone=clean_phone(record["전화번호"]),
            homepage=record["홈페이지"], category=clean(record["취급업종"]),
        ))
    return loaded


def load_licensed_business(path: Path, kind: str) -> Loaded:
    """국가동물보호정보시스템 미용업·위탁관리업: license number, name, 시·군·구·동 address, mostly masked phones."""
    frame = pd.read_csv(path, dtype=str)
    loaded = Loaded(source_rows=len(frame), updated=date_in_name(path))
    masked = frame["전화번호"].fillna("*").str.contains(r"\*", regex=True).sum()
    loaded.notes.append(f"주소는 읍·면·동까지만 공개, 좌표 없음 · 전화번호 {masked:,}건 비공개")
    for record in frame.to_dict("records"):
        category = clean(record["구분"])
        if kind == "grooming" and category:
            category = "출장(자동차) 미용" if "자동차" in category else "일반 미용"
        other = clean(record.get("비고"))
        loaded.rows.append(place(
            f"{kind}-{record['인허가 정보']}", kind, record["업체명"], record["소재지"], phone=clean_phone(record["전화번호"]),
            category=category if kind == "grooming" else None,
            info={"other_licenses": " ".join(other.split()) if other else None},
        ))
    return loaded


def load_pet_friendly(path: Path) -> Loaded:
    frame = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    loaded = Loaded(source_rows=len(frame), updated=date_in_name(path))
    kept = frame[frame["카테고리2"].isin(PET_FRIENDLY_GROUPS)]
    allowed = kept[kept["반려동물 동반 가능정보"] == "Y"]
    unique = allowed.drop_duplicates(["시설명", "도로명주소"])
    loaded.notes += [
        f"의료·서비스 분류 {len(frame) - len(kept):,}건 제외 (공식 데이터와 중복)",
        f"동반 불가(N) {len(kept) - len(allowed):,}건 제외",
        f"이름+주소 중복 {len(allowed) - len(unique):,}건 제거",
        f"작성일 2022년 {(unique['최종작성일'].str[:4] == '2022').sum():,}건 · 2025년 {(unique['최종작성일'].str[:4] == '2025').sum():,}건",
    ]
    for record in unique.to_dict("records"):
        key = f"{record['시설명']}|{record['도로명주소']}"
        loaded.rows.append(place(
            f"pet_friendly-{hashlib.sha1(key.encode()).hexdigest()[:12]}", "pet_friendly", record["시설명"],
            record["도로명주소"], record["지번주소"], clean_phone(record["전화번호"]), record["홈페이지"],
            clean(record["카테고리3"]),
            {target: clean(record[source]) for source, target in PET_FRIENDLY_INFO.items()},
            *location(record["위도"], record["경도"]),
        ))
    return loaded


def bullets(text: str | None) -> str | None:
    """'- 맹견은 입마개- 배변봉투 지참' -> '맹견은 입마개 · 배변봉투 지참' (the source's '- ' lists, often unbroken)."""
    if not text:
        return None
    parts = [" ".join(part.split()) for part in re.split(r"(?<!\d)-\s", text)]
    return " · ".join(part for part in parts if part)


def load_pet_travel(path: Path) -> Loaded:
    frame = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    places = frame[frame["contenttypeid"] != SHOP_TYPE]
    stated = places[places[list(CONDITION_COLUMNS)].map(clean).notna().any(axis=1)]
    modified = stated["modifiedtime"].dropna().max()
    loaded = Loaded(source_rows=len(frame), updated=f"{modified[:4]}-{modified[4:6]}-{modified[6:8]}" if modified else None)
    loaded.notes += [
        f"쇼핑(약국·안경점 등) {len(frame) - len(places):,}건 제외: 동반 조건 글이 거의 없음",
        f"동반 조건 글이 없는 {len(places) - len(stated):,}건 제외",
        f"빈 조건은 '{UNKNOWN_CONDITION}'로 표시 (제한 없음으로 읽지 않음)",
    ]
    for record in stated.to_dict("records"):
        allowed, needs, other = (clean(record[column]) for column in CONDITION_COLUMNS)
        zone = clean(record["acmpyTypeCd"])
        written = clean(record["modifiedtime"])
        loaded.rows.append(place(
            f"pet_travel-{record['contentid']}", "pet_friendly", record["title"], record["도로명주소"], None,
            clean_phone(record["전화번호"]), None, TRAVEL_CATEGORIES.get(record["업종"], clean(record["업종"])),
            {
                "zone": zone.replace("동반가능", "").strip() if zone else UNKNOWN_CONDITION,
                "allowed": allowed or UNKNOWN_CONDITION, "needs": needs or UNKNOWN_CONDITION,
                "other": bullets(other), "facilities": clean(record["relaPosesFclty"]),
                "written": f"{written[:4]}-{written[4:6]}-{written[6:8]}" if written else None,
                "size_rule": size_rule(allowed, other), "carrier": needs_carrier(needs, other, allowed),
                "all_areas": all_areas(zone, other, allowed),
            },
            *location(record["위도"], record["경도"]),
        ))
    return loaded


def merge_same_places(travel: Loaded, culture: Loaded) -> None:
    """Drop each 문화정보원 place that a 관광공사 place repeats (same name, within SAME_PLACE_KM) and keep
    its hours, closed days, fee and parking on the 관광공사 place, which has the conditions."""
    by_name: dict[str, list[int]] = {}
    for index, row in enumerate(travel.rows):
        if row[9] is not None:
            by_name.setdefault(name_key(row[2]), []).append(index)
    kept, merged, same_name = [], 0, 0
    for row in culture.rows:
        matches = by_name.get(name_key(row[2]), [])
        same_name += bool(matches)
        near = [i for i in matches if row[9] is not None
                and distance_km(row[9], row[10], travel.rows[i][9], travel.rows[i][10]) <= SAME_PLACE_KM]
        if not near:
            kept.append(row)
            continue
        merged += 1
        target = list(travel.rows[near[0]])
        info = json.loads(target[8])
        info.update({key: value for key, value in json.loads(row[8] or "{}").items() if key in MERGED_INFO and key not in info})
        target[5], target[6] = target[5] or row[5], target[6] or row[6]  # phone, homepage
        target[8] = json.dumps(info, ensure_ascii=False)
        travel.rows[near[0]] = tuple(target)
    culture.rows = kept
    culture.notes.append(f"한국관광공사 데이터와 같은 곳 {merged:,}건은 관광공사 쪽에 합침 (이름이 같고 {SAME_PLACE_KM * 1000:.0f}m 안)")
    travel.notes.append(f"문화정보원 데이터와 같은 곳 {merged:,}건: 운영시간·휴무일·요금·주차·전화를 가져옴 "
                        f"(이름만 같은 {same_name - merged:,}건은 다른 곳으로 봄)")


LOADERS = {
    "hospital": load_hospitals,
    "pharmacy": load_pharmacies,
    "funeral": load_funeral,
    "grooming": lambda path: load_licensed_business(path, "grooming"),
    "boarding": lambda path: load_licensed_business(path, "boarding"),
    "pet_friendly": load_pet_friendly,
    "pet_travel": load_pet_travel,
}


def build(output: Path, inputs: dict[str, Path]) -> dict[str, int]:
    temporary = output.with_suffix(".db.tmp")
    temporary.unlink(missing_ok=True)
    with closing(sqlite3.connect(temporary)) as connection:
        connection.executescript(SCHEMA)
        every = {kind: LOADERS[kind](path) for kind, path in inputs.items()}
        if "pet_travel" in every and "pet_friendly" in every:
            merge_same_places(every["pet_travel"], every["pet_friendly"])
        for kind, loaded in every.items():
            path = inputs[kind]
            rows = sorted({row[0]: row for row in loaded.rows if row[2]}.values())  # a place needs a name; ids unique
            connection.executemany(f"INSERT INTO place VALUES ({', '.join('?' * 11)})", rows)
            title, url = SOURCES[kind]
            connection.execute(
                "INSERT INTO source VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kind, title, url, path.name, loaded.source_rows, len(rows),
                 sum(row[9] is not None for row in rows), sum(row[5] is not None for row in rows),
                 loaded.updated, json.dumps(loaded.notes, ensure_ascii=False)),
            )
        connection.commit()
        connection.execute("VACUUM")
    temporary.replace(output)
    with closing(sqlite3.connect(output)) as connection:
        return dict(connection.execute("SELECT kind, rows FROM source ORDER BY kind").fetchall())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for kind, path in INPUTS.items():
        parser.add_argument(f"--{kind.replace('_', '-')}", type=Path, default=path, dest=kind)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(build(args.output, {kind: getattr(args, kind) for kind in INPUTS}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
