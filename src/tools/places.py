"""Pet-place search over SQLite (data/places.db): hospitals, pharmacies, dog-friendly
places, grooming and boarding businesses, funeral businesses.

Region keywords and counts use fixed SQL; other questions get LLM-written read-only SQL
that must stay on the asked kind; "nearest" ranks by straight-line distance.
"""

from __future__ import annotations

import json
import re
import sqlite3
from functools import lru_cache

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src import resources
from src.places_data import (
    KIND_LABELS,
    NO_LOCATION_KINDS,
    SIDO_ALIASES,
    describe_info,
    nearest_places,
)

SINGLE_HOSPITAL_LIMIT = 1
DEFAULT_HOSPITAL_LIMIT = 10
RESULT_COLUMNS = "id, kind, name, road_address, lot_address, phone, category, info, latitude, longitude"
PLACE_NOTICE = "공공데이터 기준이라 실제 영업 여부·영업시간·이용 조건과 다를 수 있으니 방문 전 전화로 확인해 주세요."

SQL_GENERATION_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """사용자의 반려동물 시설 검색 질문을 SQLite SQL로 변환하세요.
사용할 수 있는 테이블은 place 하나뿐이며 컬럼은 다음과 같습니다.
id, kind, name, road_address, lot_address, phone, category, info, latitude, longitude
kind 값: hospital(동물병원), pharmacy(동물약국), pet_friendly(반려동물 동반 가능 시설), grooming(동물미용업), boarding(위탁관리업·펫호텔), funeral(장묘업체)
category: pet_friendly는 여행지·카페·펜션·박물관·미술관·식당·문예회관·호텔, grooming은 일반 미용·출장(자동차) 미용
info: 운영시간(hours), 휴무일(closed), 입장 가능 크기(size), 제한사항(restrictions), 추가 요금(extra_fee), 주차(parking)를 담은 JSON 문자열
반드시 WHERE 절에 kind = '{kind}' 조건을 넣고, id, kind, name, road_address, lot_address, phone, category, info, latitude, longitude를 고르는 읽기 전용 SELECT 문 하나만 출력하세요.
주소 검색은 road_address와 lot_address를 LIKE로 함께 고려하고, 결과는 최대 10개로 제한하세요.
이용 조건은 info를 LIKE로 거르세요. 예: 대형견 → (info LIKE '%대형%' OR info LIKE '%모두 가능%')
SQL 코드 블록이나 설명 없이 SQL만 출력하세요.""",
    ),
    ("human", "{question}"),
])

SQL_ANSWER_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "검색된 {label} 데이터만 근거로 간결하게 답하세요. 검색 결과가 없으면 찾지 못했다고 말하세요. 데이터에 없는 영업 여부, 영업시간, 이용 조건은 추측하지 마세요.",
    ),
    ("human", "질문: {question}\n검색 결과: {rows}"),
])

COUNT_QUERY_KEYWORDS = ("몇개", "몇 개", "개수", "몇곳", "몇 곳", "몇군데", "몇 군데")
SINGLE_HOSPITAL_KEYWORDS = (
    "하나만",
    "한개만",
    "한 개만",
    "한곳만",
    "한 곳만",
    "한병원만",
    "병원하나만",
    "병원1개만",
    "하나의",
)
NEAREST_HOSPITAL_KEYWORDS = ("가장 가까운", "가까운 병원", "근처 병원", "근처에")
HOSPITAL_QUERY_KEYWORDS = ("동물병원", "병원 주소", "병원 목록", "병원 검색")
# Words that name a kind of place. "약국", "미용", "카페", "펜션" alone are ambiguous
# ("약국에서 산 약 먹여도 돼?", "미용 후 피부가 빨개요"), so they count only with a search word.
# "장례"/"장묘" alone are report topics (장묘 서비스 실태) and stay out.
KIND_KEYWORDS = (
    ("funeral", ("장례식장", "장례업체", "장묘업체", "장묘업", "장묘시설", "화장장", "화장터")),
    ("pharmacy", ("동물약국",)),
    ("boarding", ("애견호텔", "펫호텔", "강아지호텔", "반려견호텔", "애견유치원", "강아지유치원", "반려견유치원", "위탁관리", "맡길곳", "맡길데")),
    ("grooming", ("애견미용", "강아지미용", "반려견미용", "동물미용", "펫미용", "미용실", "미용업")),
    ("pet_friendly", (
        "애견동반", "반려견동반", "반려동물동반", "강아지동반", "동반가능", "같이갈수", "함께갈수", "데려갈수",
        "애견카페", "강아지카페", "애견펜션", "반려견펜션", "강아지펜션",
    )),
)
AMBIGUOUS_KIND_WORDS = (("pharmacy", "약국"), ("grooming", "미용"), ("pet_friendly", "카페"), ("pet_friendly", "펜션"))
PLACE_SEARCH_WORDS = ("근처", "가까운", "어디", "찾아", "목록", "주소", "위치", "몇곳", "몇군데", "몇개", "추천")
LOCATION_ALIASES = {alias: name for alias, name in SIDO_ALIASES.items() if alias.endswith(("시", "도"))}
REQUESTED_COUNT = re.compile(r"(\d+)\s*(?:곳|개|군데)\s*만")


def with_particle(word: str, after_consonant: str, after_vowel: str) -> str:
    """'동물병원은', '장묘업체는': the particle depends on the last syllable's final consonant."""
    code = ord(word[-1]) - 0xAC00
    has_final = 0 <= code <= 11171 and code % 28 != 0
    return word + (after_consonant if has_final else after_vowel)


def _compact(question: str) -> str:
    return "".join(question.lower().split())


def place_kind(question: str) -> str | None:
    """The kind of place the question looks for (a KIND_LABELS key), or None."""
    compact = _compact(question)
    for kind, keywords in KIND_KEYWORDS:
        if any(keyword in compact for keyword in keywords):
            return kind
    if "동물병원" in compact or any(keyword in " ".join(question.lower().split()) for keyword in HOSPITAL_QUERY_KEYWORDS):
        return "hospital"
    if any(word in compact for word in PLACE_SEARCH_WORDS):
        for kind, word in AMBIGUOUS_KIND_WORDS:
            if word in compact:
                return kind
    return None


def is_place_question(question: str) -> bool:
    return place_kind(question) is not None


def validate_sql(sql: str) -> str:
    cleaned = sql.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()
    if cleaned.lower().startswith("sql"):
        cleaned = cleaned[3:].strip()

    cleaned = cleaned.rstrip(";").strip()
    normalized = cleaned.lower()
    if not normalized.startswith("select"):
        raise ValueError("읽기 전용 SELECT 문만 실행할 수 있습니다.")
    if ";" in cleaned or "--" in cleaned or "/*" in cleaned:
        raise ValueError("여러 문장이나 주석이 포함된 SQL은 실행할 수 없습니다.")
    referenced_tables = re.findall(
        r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)",
        normalized,
    )
    if not referenced_tables or any(table != "place" for table in referenced_tables):
        raise ValueError("place 테이블만 조회할 수 있습니다.")
    return cleaned


def stays_on_kind(sql: str, kind: str) -> bool:
    return re.search(rf"\bkind\s*=\s*'{kind}'", sql, flags=re.IGNORECASE) is not None


def build_location_conditions(location_keywords: list[str]) -> str:
    return " OR ".join(
        "road_address LIKE ? OR lot_address LIKE ?"
        for _ in location_keywords
    )


def should_limit_to_one_hospital(question: str) -> bool:
    return (
        not is_count_query(question)
        and (
            is_single_hospital_query(question)
            or is_nearest_hospital_query(question)
        )
    )


def get_hospital_result_limit(question: str) -> int:
    if should_limit_to_one_hospital(question):
        return SINGLE_HOSPITAL_LIMIT
    return requested_count(question)


def requested_count(question: str) -> int:
    """'3곳만' -> 3, at most DEFAULT_HOSPITAL_LIMIT; otherwise the default."""
    if match := REQUESTED_COUNT.search(question):
        return min(max(int(match.group(1)), 1), DEFAULT_HOSPITAL_LIMIT)
    return DEFAULT_HOSPITAL_LIMIT


def force_sql_limit(sql: str, limit: int) -> str:
    if re.search(r"\blimit\s+\d+", sql, flags=re.IGNORECASE):
        return re.sub(r"\blimit\s+\d+", f"LIMIT {limit}", sql, flags=re.IGNORECASE)
    return f"{sql} LIMIT {limit}"


def force_sql_limit_one(sql: str) -> str:
    return force_sql_limit(sql, SINGLE_HOSPITAL_LIMIT)


def fallback_sql(question: str, kind: str = "hospital", location_keywords: list[str] | None = None) -> tuple[str, list[str]]:
    """Fixed SQL for region and count questions (and when no LLM key is set)."""
    if location_keywords is None:
        location_keywords = extract_search_parameters(question)
    parameters = [kind] + [f"%{keyword}%" for keyword in location_keywords for _ in range(2)]
    where = "kind = ?"
    if location_keywords:
        where += f" AND ({build_location_conditions(location_keywords)})"
    if is_count_query(question):
        return f"SELECT COUNT(*) AS count FROM place WHERE {where}", parameters
    limit = get_hospital_result_limit(question)
    return f"SELECT {RESULT_COLUMNS} FROM place WHERE {where} ORDER BY id LIMIT {limit}", parameters


def is_count_query(question: str) -> bool:
    compact_question = _compact(question)
    return any("".join(keyword.split()) in compact_question for keyword in COUNT_QUERY_KEYWORDS)


def is_single_hospital_query(question: str) -> bool:
    compact_question = _compact(question)
    return any("".join(keyword.split()) in compact_question for keyword in SINGLE_HOSPITAL_KEYWORDS)


def is_nearest_hospital_query(question: str) -> bool:
    compact_question = _compact(question)
    return any("".join(keyword.split()) in compact_question for keyword in NEAREST_HOSPITAL_KEYWORDS)


def wants_nearest(question: str) -> bool:
    """'가까운 약국', '근처 장례식장': rank by distance, unless a region is named."""
    compact_question = _compact(question)
    return any(word in compact_question for word in ("가까운", "근처")) and not extract_search_parameters(question)


REGION_WORD = re.compile(r"[가-힣]+(?:특별시|광역시|특별자치시|특별자치도|도|시|군|구|동|읍|면)")


@lru_cache(maxsize=4)
def known_region_words(db_path: str) -> frozenset[str]:
    """Region names that occur in the stored addresses, so '대형견도' or '애견동(반)' are not regions."""
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        addresses = connection.execute("SELECT road_address, lot_address FROM place").fetchall()
    finally:
        connection.close()
    return frozenset(
        word for pair in addresses for address in pair if address
        for word in address.split() if REGION_WORD.fullmatch(word)
    )


def extract_search_parameters(question: str) -> list[str]:
    candidates = [LOCATION_ALIASES.get(word, word) for word in REGION_WORD.findall(question)]
    try:
        known = known_region_words(resources.DB_PATH.as_posix())
    except sqlite3.Error:
        known = None
    locations = [word for word in candidates if known is None or word in known]
    if len(locations) > 1:
        specific_locations = [
            location
            for location in locations
            if not location.endswith(("특별시", "광역시", "특별자치시", "도", "시"))
        ]
        if specific_locations:
            locations = specific_locations
    return list(dict.fromkeys(locations))


def format_sql_result(rows: list[dict], kind: str = "hospital") -> str:
    label = KIND_LABELS[kind]
    if len(rows) == 1 and "count" in rows[0]:
        return f"조건에 맞는 {with_particle(label, '은', '는')} {rows[0]['count']}곳입니다."
    if not rows:
        return f"조건에 맞는 {with_particle(label, '을', '를')} 찾지 못했습니다."

    lines = [f"조건에 맞는 {label} {len(rows)}곳입니다."]
    for index, row in enumerate(rows, start=1):
        category = f" ({row['category']})" if row.get("category") else ""
        lines.append(f"{index}. {row.get('name', '이름 없음')}{category}")
        lines.append(f"   주소: {row.get('road_address') or row.get('lot_address') or '주소 없음'}")
        if row.get("phone"):
            lines.append(f"   전화: {row['phone']}")
        lines.extend(f"   {line}" for line in describe_info(row.get("info")))
    return "\n".join(lines)


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{resources.DB_PATH.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def execute_place_sql(sql: str, parameters: list | tuple = ()) -> list[dict]:
    connection = _connect()
    try:
        return [dict(row) for row in connection.execute(sql, parameters).fetchall()]
    finally:
        connection.close()


def _with_notice(answer: str, rows: list[dict]) -> str:
    return f"{answer}\n\n{PLACE_NOTICE}" if rows else answer


def run_nearest_search(question: str, kind: str, location: tuple[float, float] | None) -> tuple[str, list[dict]]:
    label = KIND_LABELS[kind]
    if kind in NO_LOCATION_KINDS:
        return f"{with_particle(label, '은', '는')} 좌표가 없어 거리순으로 찾을 수 없습니다. 시·도나 시·군·구 이름으로 검색해 주세요.", []
    if location is None:
        return f"가까운 {with_particle(label, '을', '를')} 찾으려면 현재 위치 사용 버튼을 누르거나 지역을 지정해 검색해 주세요.", []
    rows = execute_place_sql(
        f"SELECT {RESULT_COLUMNS} FROM place WHERE kind = ? AND latitude IS NOT NULL", [kind]
    )
    # "가장 가까운" lists several by distance; only "하나만" or "3곳만" shortens the list.
    limit = SINGLE_HOSPITAL_LIMIT if is_single_hospital_query(question) else requested_count(question)
    ranked = nearest_places(rows, *location, limit=limit)
    if not ranked:
        return f"위치 좌표가 유효한 {with_particle(label, '을', '를')} 찾지 못했습니다.", []
    lines = [f"현재 위치 기준 가까운 {label}입니다. 거리는 직선거리이며 이동거리·소요시간과 다릅니다."]
    for index, row in enumerate(ranked, start=1):
        address = row.get("road_address") or row.get("lot_address") or "주소 없음"
        phone = f", {row['phone']}" if row.get("phone") else ""
        lines.append(f"{index}. {row['name']} — {address}{phone} ({row['distance_km']:.2f} km)")
    return _with_notice("\n".join(lines), ranked), ranked


def _from_follow_up(current: str, earlier: list[str], read):
    """What the current question says, else what the latest earlier question said ("거기 약국은?")."""
    for text in [current, *reversed(earlier)]:
        if value := read(text):
            return value
    return None


def run_sql_search(question: str, location: tuple[float, float] | None = None) -> tuple[str, list[dict]]:
    """지역, 주소, 이름으로 반려동물 시설을 검색합니다.

    `question` may carry earlier user questions on the lines before the current one
    (history.build_rag_search_query). Counts, "N곳만" and "nearest" come from the current
    question only; the kind and region fall back to earlier questions for follow-ups.
    """
    *earlier, current = [line for line in question.split("\n") if line.strip()] or [question]
    kind = _from_follow_up(current, earlier, place_kind) or "hospital"
    location_keywords = _from_follow_up(current, earlier, extract_search_parameters) or []
    question = current
    if wants_nearest(question):
        return run_nearest_search(question, kind, location)

    # 지역·개수 질문은 정해진 SQL로 처리해 SQL 생성·답변용 LLM 호출을 줄입니다.
    use_fallback = bool(location_keywords) or is_count_query(question)
    model = None if use_fallback else resources.load_chat_model()
    sql, parameters = fallback_sql(question, kind, location_keywords)
    used_model = False
    if model is not None:
        generated = validate_sql(
            (SQL_GENERATION_PROMPT | model | StrOutputParser()).invoke({"question": question, "kind": kind})
        )
        # Generated SQL that drops the kind filter would mix pharmacies into a hospital search.
        if stays_on_kind(generated, kind):
            sql, parameters, used_model = generated, [], True
    sql = validate_sql(sql)
    if should_limit_to_one_hospital(question):
        sql = force_sql_limit_one(sql)
    elif REQUESTED_COUNT.search(question) and not is_count_query(question):
        sql = force_sql_limit(sql, requested_count(question))  # "3곳만"
    rows = execute_place_sql(sql, parameters)
    if len(rows) == 1 and "count" in rows[0]:
        return format_sql_result(rows, kind), rows
    if not used_model:
        return _with_notice(format_sql_result(rows, kind), rows), rows
    answer = (SQL_ANSWER_PROMPT | model | StrOutputParser()).invoke(
        {"label": KIND_LABELS[kind], "question": question, "rows": json.dumps(rows, ensure_ascii=False)}
    )
    return _with_notice(answer, rows), rows
