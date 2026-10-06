"""Hospital search over SQLite: region keywords, LLM-written read-only SQL, or distance."""

from __future__ import annotations

import json
import re
import sqlite3

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src import resources
from src.hospital_distance import nearest_hospitals

SINGLE_HOSPITAL_LIMIT = 1
DEFAULT_HOSPITAL_LIMIT = 10

SQL_GENERATION_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """사용자의 병원 검색 질문을 SQLite SQL로 변환하세요.
사용할 수 있는 테이블은 hospital 하나뿐이며 컬럼은 다음과 같습니다.
ids, name, new_address, x_coor, y_coor, old_address
반드시 ids, name, new_address, x_coor, y_coor를 포함한 읽기 전용 SELECT 문 하나만 출력하세요.
주소 검색은 new_address와 old_address를 LIKE로 함께 고려하고, 결과는 최대 10개로 제한하세요.
SQL 코드 블록이나 설명 없이 SQL만 출력하세요.""",
    ),
    ("human", "{question}"),
])

SQL_ANSWER_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "검색된 동물병원 데이터만 근거로 간결하게 답하세요. 검색 결과가 없으면 찾지 못했다고 말하세요.",
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
LOCATION_ALIASES = {
    "서울시": "서울특별시",
    "부산시": "부산광역시",
    "대구시": "대구광역시",
    "인천시": "인천광역시",
    "광주시": "광주광역시",
    "대전시": "대전광역시",
    "울산시": "울산광역시",
    "세종시": "세종특별자치시",
}


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
    if not referenced_tables or any(table != "hospital" for table in referenced_tables):
        raise ValueError("hospital 테이블만 조회할 수 있습니다.")
    return cleaned


def build_location_conditions(location_keywords: list[str]) -> str:
    return " OR ".join(
        "new_address LIKE ? OR old_address LIKE ?"
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
    return DEFAULT_HOSPITAL_LIMIT


def force_sql_limit_one(sql: str) -> str:
    if re.search(r"\blimit\s+\d+", sql, flags=re.IGNORECASE):
        return re.sub(
            r"\blimit\s+\d+",
            f"LIMIT {SINGLE_HOSPITAL_LIMIT}",
            sql,
            flags=re.IGNORECASE,
        )
    return f"{sql} LIMIT {SINGLE_HOSPITAL_LIMIT}"


def fallback_sql(question: str) -> str:
    """LLM 키가 없을 때도 기본적인 지역 병원 검색은 수행합니다."""
    location_keywords = extract_search_parameters(question)
    if is_count_query(question):
        if not location_keywords:
            return "SELECT COUNT(*) AS count FROM hospital"
        conditions = build_location_conditions(location_keywords)
        return f"SELECT COUNT(*) AS count FROM hospital WHERE {conditions}"

    limit = get_hospital_result_limit(question)
    if not location_keywords:
        return f"SELECT ids, name, new_address, x_coor, y_coor, old_address FROM hospital LIMIT {limit}"
    conditions = build_location_conditions(location_keywords)
    return f"SELECT ids, name, new_address, x_coor, y_coor, old_address FROM hospital WHERE {conditions} LIMIT {limit}"


def is_count_query(question: str) -> bool:
    compact_question = "".join(question.lower().split())
    return any("".join(keyword.split()) in compact_question for keyword in COUNT_QUERY_KEYWORDS)


def is_single_hospital_query(question: str) -> bool:
    compact_question = "".join(question.lower().split())
    return any("".join(keyword.split()) in compact_question for keyword in SINGLE_HOSPITAL_KEYWORDS)


def is_nearest_hospital_query(question: str) -> bool:
    compact_question = "".join(question.lower().split())
    return any("".join(keyword.split()) in compact_question for keyword in NEAREST_HOSPITAL_KEYWORDS)


def is_hospital_question(question: str) -> bool:
    normalized_question = " ".join(question.lower().split())
    compact_question = "".join(normalized_question.split())
    if "동물병원" in compact_question:
        return True
    return any(keyword in normalized_question for keyword in HOSPITAL_QUERY_KEYWORDS)


def extract_search_parameters(question: str) -> list[str]:
    locations = re.findall(
        r"[가-힣]+(?:특별시|광역시|특별자치시|특별자치도|도|시|군|구|동|읍|면)",
        question,
    )
    if len(locations) > 1:
        specific_locations = [
            location
            for location in locations
            if not location.endswith(("특별시", "광역시", "특별자치시", "도", "시"))
        ]
        if specific_locations:
            locations = specific_locations
    return list(dict.fromkeys(LOCATION_ALIASES.get(location, location) for location in locations))


def format_sql_result(hospital_rows: list[dict]) -> str:
    if len(hospital_rows) == 1 and "count" in hospital_rows[0]:
        return f"조건에 맞는 동물병원은 {hospital_rows[0]['count']}개입니다."
    if not hospital_rows:
        return "조건에 맞는 동물병원을 찾지 못했습니다."

    lines = [f"조건에 맞는 동물병원 {len(hospital_rows)}곳입니다."]
    for index, row in enumerate(hospital_rows, start=1):
        lines.append(f"{index}. {row.get('name', '이름 없음')}")
        address = row.get("new_address") or row.get("old_address") or "주소 없음"
        lines.append(f"   주소: {address}")
    return "\n".join(lines)


def execute_hospital_sql(sql: str, location_keywords: list[str]) -> list[dict]:
    connection = sqlite3.connect(resources.DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        if location_keywords and "?" in sql:
            sql_parameters = [
                f"%{keyword}%"
                for keyword in location_keywords
                for _ in range(2)
            ]
            rows = connection.execute(sql, sql_parameters).fetchall()
        else:
            rows = connection.execute(sql).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def run_sql_search(question: str, location: tuple[float, float] | None = None) -> tuple[str, list[dict]]:
    """지역, 주소, 병원명으로 동물병원 SQLite 데이터를 검색합니다."""
    if is_nearest_hospital_query(question):
        if location is None:
            return "가까운 병원을 찾으려면 현재 위치 사용 버튼을 누르거나 지역을 지정해 검색해 주세요.", []
        connection = sqlite3.connect(f"file:{resources.DB_PATH.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = [dict(row) for row in connection.execute(
                "SELECT ids, name, new_address, old_address, x_coor, y_coor FROM hospital"
            )]
        finally:
            connection.close()
        limit = SINGLE_HOSPITAL_LIMIT if is_single_hospital_query(question) else DEFAULT_HOSPITAL_LIMIT
        ranked = nearest_hospitals(rows, *location, limit=limit)
        if not ranked:
            return "위치 좌표가 유효한 동물병원을 찾지 못했습니다.", []
        lines = ["현재 위치 기준 가까운 동물병원입니다. 거리는 직선거리이며 이동거리·소요시간과 다릅니다."]
        for index, row in enumerate(ranked, start=1):
            lines.append(f"{index}. {row['name']} — {row.get('new_address') or row.get('old_address') or '주소 없음'} ({row['distance_km']:.2f} km)")
        return "\n".join(lines), ranked
    location_keywords = extract_search_parameters(question)

    # 지역 조건은 정해진 SQL로 처리해 SQL 생성·답변용 LLM 호출을 줄입니다.
    use_fallback = bool(location_keywords) or is_count_query(question)
    model = None if use_fallback else resources.load_chat_model()
    if model is None:
        sql = fallback_sql(question)
    else:
        sql = (SQL_GENERATION_PROMPT | model | StrOutputParser()).invoke(
            {"question": question}
        )

    sql = validate_sql(sql)
    if should_limit_to_one_hospital(question):
        sql = force_sql_limit_one(sql)
    hospital_rows = execute_hospital_sql(sql, location_keywords)
    if model is None:
        return format_sql_result(hospital_rows), hospital_rows
    answer = (SQL_ANSWER_PROMPT | model | StrOutputParser()).invoke(
        {"question": question, "rows": json.dumps(hospital_rows, ensure_ascii=False)}
    )
    return answer, hospital_rows
