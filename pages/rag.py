import json
import os
import re
import sqlite3
import tomllib
from datetime import date
from pathlib import Path
from typing import Any, Literal

import streamlit as st
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from src.ui import apply_app_theme, render_page_header

PROJECT_DIR = Path(__file__).resolve().parents[1]
CHROMA_DIR = PROJECT_DIR / "data" / "chroma_db"
DB_PATH = PROJECT_DIR / "data" / "hospital.db"
REPORT_COLLECTION_NAME = "pet_analysis_1024"

ALL_FILTER = "전체"
ETC_DISEASE = "기타"
NONE_DISEASE = "None"
DEPARTMENT_OPTIONS = [ALL_FILTER, "내과", "외과", "안과", "치과", "피부과"]
SHORT_TERM_MEMORY_TURNS = 6
DEFAULT_RAG_TOP_K = 3
MIN_RAG_TOP_K = 1
MAX_RAG_TOP_K = 5
REPORT_ANALYSIS_TOP_K = 6
SINGLE_HOSPITAL_LIMIT = 1
DEFAULT_HOSPITAL_LIMIT = 10
PUPPY_MAX_MONTHS = 12
PUPPY_MAX_YEARS = 1
ADULT_MIN_YEARS = 2
ADULT_MAX_YEARS = 6
CHAT_MESSAGES_STATE_KEY = "fixing_messages"
HOSPITAL_ROWS_STATE_KEY = "hospital_rows"
SELECTED_HOSPITAL_ID_STATE_KEY = "selected_hospital_id"
RAG_TOP_K_SLIDER_KEY = "rag_top_k"


load_dotenv(PROJECT_DIR / ".env")


RAG_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """아래 [검색 데이터]를 근거로 사용자의 질문에 답하세요.
검색된 데이터에 근거해서만 간결하게 답하고, 데이터에 없는 내용은 추측하지 마세요.

[대화 이력]
{chat_history}

[선택 조건]
{filters}

[검색 데이터]
{context}
"""),
    ("human", "{question}"),
])


@st.cache_resource(show_spinner=False)
def create_embedding_model():
    return HuggingFaceEmbeddings(
        model_name="BAAI/bge-m3",
        encode_kwargs={"normalize_embeddings": True},
    )


@st.cache_resource(show_spinner=False)
def load_vector_db():
    return Chroma(
        collection_name="pet_care",
        embedding_function=HuggingFaceEmbeddings(
            model_name="jhgan/ko-sroberta-multitask",
            encode_kwargs={"normalize_embeddings": True},
        ),
        persist_directory=str(CHROMA_DIR),
    )


@st.cache_resource(
    show_spinner="건강 Q&A BM25 색인을 준비합니다. 최초 실행은 수 분 걸릴 수 있습니다."
)
def load_health_bm25_index():
    from src.hybrid_retrieval import HealthBM25Index
    from kiwipiepy import Kiwi

    kiwi = Kiwi()

    def tokenize(text):
        normalized = text.replace("･", "·")
        return [
            token.form.lower()
            for token in kiwi.tokenize(normalized)
            if token.tag.startswith("N") or token.tag in {"SL", "SN"}
        ]

    return HealthBM25Index.from_chroma(load_vector_db(), tokenize)


@st.cache_resource(show_spinner=False)
def load_report_vector_db():
    return Chroma(
        collection_name=REPORT_COLLECTION_NAME,
        embedding_function=create_embedding_model(),
        persist_directory=str(CHROMA_DIR),
    )


def get_openai_api_key():
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        return api_key

    secrets_path = PROJECT_DIR / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        return None
    with secrets_path.open("rb") as file:
        secrets = tomllib.load(file)
    return secrets.get("OPENAI_API_KEY")


@st.cache_resource(show_spinner=False)
def load_rag_chain():
    api_key = get_openai_api_key()
    if not api_key:
        return None
    return RAG_PROMPT | ChatOpenAI(
        model="gpt-5.6-luna",
        temperature=0,
        api_key=api_key,
    ) | StrOutputParser()


@st.cache_resource(show_spinner=False)
def initialize_rag():
    db = load_vector_db()
    return db, load_rag_chain()


def build_filter_context(filters):
    labels = {
        "life_cycle": "나이 단계",
        "department": "진료과",
        "disease": "질병 종류",
    }
    items = [
        f"{labels[key]}: {value}"
        for key, value in (filters or {}).items()
        if value and value != ALL_FILTER and key in labels
    ]
    return "\n".join(items) if items else "선택 조건 없음"


def build_metadata_filter(filters):
    key_map = {
        "life_cycle": "meta.lifeCycle",
        "department": "meta.department",
        "disease": "meta.disease",
    }
    conditions = []
    for key, value in (filters or {}).items():
        if key not in key_map or not value or value == ALL_FILTER:
            continue
        if key == "disease" and value == ETC_DISEASE:
            conditions.append({"$or": [
                {"meta.disease": ETC_DISEASE},
                {"meta.disease": NONE_DISEASE},
            ]})
        else:
            conditions.append({key_map[key]: value})
    if not conditions:
        return None
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


def get_recent_chat_history(messages, max_turns=SHORT_TERM_MEMORY_TURNS):
    """세션에 저장된 대화에서 최근 사용자-AI 대화만 반환합니다."""
    if not messages:
        return []
    return list(messages[-max_turns * 2:])


def format_chat_history(messages):
    """대화 이력을 RAG 프롬프트에 넣을 문자열로 변환합니다."""
    role_labels = {"user": "사용자", "assistant": "AI"}
    return "\n".join(
        f"{role_labels.get(message.get('role'), message.get('role', '대화'))}: "
        f"{message.get('content', '')}"
        for message in messages or []
    ) or "이전 대화 없음"


def build_rag_search_query(question, chat_history=None):
    """현재 질문과 이전 사용자 질문을 합쳐 후속 질문 검색을 보강합니다."""
    previous_questions = [
        message.get("content", "")
        for message in get_recent_chat_history(chat_history)
        if message.get("role") == "user" and message.get("content")
    ]
    return "\n".join(dict.fromkeys(previous_questions + [question]))


def format_rag_context(retrieved_docs):
    return "\n\n".join(
        f"질문: {doc.page_content}\n답변: {doc.metadata.get('qa.output', '')}"
        for doc in retrieved_docs
    )


def ask_rag(question, k=DEFAULT_RAG_TOP_K, filters=None, chat_history=None):
    from src.hybrid_retrieval import retrieve_hybrid

    if not question or not question.strip():
        raise ValueError("질문을 입력해 주세요.")
    db, rag_chain = initialize_rag()
    search_query = build_rag_search_query(question, chat_history)
    retrieved_docs = retrieve_hybrid(
        db,
        load_health_bm25_index(),
        search_query,
        top_k=k,
        where=build_metadata_filter(filters),
    )
    prompt_context = format_rag_context(retrieved_docs)
    if rag_chain is None:
        answer = "유사도 검색은 성공했습니다. 답변 생성에는 OPENAI_API_KEY가 필요합니다."
    else:
        answer = rag_chain.invoke({
            "context": prompt_context,
            "chat_history": format_chat_history(chat_history),
            "filters": build_filter_context(filters),
            "question": question,
        })
    return {
        "answer": answer,
        "evidence_rows": [doc.metadata for doc in retrieved_docs],
    }


REPORT_ANALYSIS_TOPICS = {
    "한국 반려동물 현황": [
        "한국 반려동물 양육 현황",
        "향후 양육 희망 반려동물",
        "선호 품종과 입양처",
        "관련 법·제도 강화 의견",
        "펫티켓 성숙도",
    ],
    "반려동물의 생활 웰니스": [
        "반려동물 웰니스 인식",
        "반려동물의 영양 관리",
        "반려동물의 운동과 놀이",
        "‘나홀로 집에’ 반려동물 케어",
        "반려동물과의 여가활동",
        "반려동물을 위한 건강검진",
    ],
    "반려가구의 반려동물 양육 경험": [
        "반려가구의 양육 관심사",
        "반려가구의 양육 만족도",
        "반려가구의 양육 지속 의향",
    ],
    "반려가구의 반려동물 생애 지출": [
        "반려동물 입양비",
        "반려동물 양육비",
        "반려동물 치료비",
        "반려동물 장례비",
    ],
    "반려동물 생애자금 관리": [
        "반려동물 생활비 마련",
        "반려동물 보험",
    ],
    "[이슈1] 반려가구의 펫로스 관리": [
        "펫로스 경험",
        "펫로스증후군 경험",
        "펫로스증후군 극복 방법",
    ],
    "[이슈2] 반려동물 비만 관리": [
        "반려동물 비만 진단",
        "반려동물 비만 관리의 중요성",
        "반려동물 비만 대응",
    ],
}
REPORT_ANALYSIS_KEYWORDS = (
    "보고서",
    "현황",
    "양육",
    "양육 관심사",
    "양육 만족도",
    "양육 지속 의향",
    "생애 지출",
    "생애자금",
    "입양비",
    "양육비",
    "치료비",
    "생활비",
    "보험",
    "웰니스",
    "펫로스",
    "펫로스증후군",
    "장례",
    "펫티켓",
    "입양처",
    "비만",
    "건강검진",
    "분석",
    "통계",
    "추이",
    "비교",
    "비중",
    "비율",
    "증감",
    "분포",
    "상관",
    "세대별",
    "연도별",
)
REPORT_ANALYSIS_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """2025 한국 반려동물 보고서 8~9페이지의 목차 항목을 분석 기준으로 삼고,
보고서 검색 자료만 근거로 분석 결과를 작성하세요.
분석 항목에 해당하는 수치, 차이, 추이를 우선 정리하고, 자료에 없는 수치나 원인은 추측하지 마세요.
검색 자료가 부족하면 부족한 부분을 명시하세요. 답변에는 분석 대상, 핵심 결과, 근거 페이지를 포함하세요.
검색 데이터 밖 내용은 말하지 마세요.

[분석 항목]
{topics}

[검색 자료]
{context}""",
    ),
    ("human", "{question}"),
])


def get_report_analysis_topics(question: str) -> list[str]:
    normalized_question = question.replace(" ", "")
    selected_topics = []
    for section, topics in REPORT_ANALYSIS_TOPICS.items():
        if section.replace(" ", "") in normalized_question:
            selected_topics.append(f"{section}: {', '.join(topics)}")
            continue
        matched_topics = [
            topic for topic in topics if topic.replace(" ", "") in normalized_question
        ]
        if matched_topics:
            selected_topics.append(f"{section}: {', '.join(matched_topics)}")
    if selected_topics:
        return selected_topics
    return [f"{section}: {', '.join(topics)}" for section, topics in REPORT_ANALYSIS_TOPICS.items()]


def format_report_context(report_docs):
    return "\n\n".join(
        f"[페이지 {doc.metadata.get('page', '?')}] {doc.page_content}"
        for doc in report_docs
    )


def run_report_analysis(question: str) -> str:
    report_db = load_report_vector_db()
    topics = get_report_analysis_topics(question)
    search_query = f"{' '.join(topics)}\n{question}"
    report_docs = report_db.similarity_search(search_query, k=REPORT_ANALYSIS_TOP_K)
    prompt_context = format_report_context(report_docs)
    model = load_chat_model()
    if model is None:
        return "분석 자동화에는 OPENAI_API_KEY가 필요합니다."
    return (REPORT_ANALYSIS_PROMPT | model | StrOutputParser()).invoke({
        "topics": "\n".join(topics),
        "context": prompt_context or "검색된 보고서 자료가 없습니다.",
        "question": question,
    })


@tool
def report_analysis_tool(question: str) -> str:
    """2025 한국 반려동물 보고서의 목차 항목을 근거로 통계와 추이를 분석합니다."""
    return run_report_analysis(question)


def format_evidence_row(row, index):
    life_cycle = row.get("meta.lifeCycle") or row.get("lifeCycle") or "-"
    department = row.get("meta.department") or row.get("department") or "-"
    disease = row.get("meta.disease") or row.get("disease") or "-"
    answer = row.get("qa.output") or row.get("answer") or ""
    return {
        "title": f"{index + 1}. {life_cycle} / {department} / {disease}",
        "body": f"**답변**\n\n{answer}",
    }


@tool
def rag_tool(question: str) -> str:
    """반려견의 증상, 질병, 치료 등 건강 관련 질문에 학습 데이터를 검색해 답합니다."""
    result = ask_rag(question, k=DEFAULT_RAG_TOP_K)
    return result["answer"]


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


@st.cache_resource(show_spinner=False)
def load_chat_model():
    api_key = get_openai_api_key()
    if not api_key:
        return None
    return ChatOpenAI(model="gpt-5.6-luna", temperature=0, api_key=api_key)


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
    connection = sqlite3.connect(DB_PATH)
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


def run_sql_search(question: str) -> tuple[str, list[dict]]:
    """지역, 주소, 병원명으로 동물병원 SQLite 데이터를 검색합니다."""
    location_keywords = extract_search_parameters(question)

    # 지역 조건은 정해진 SQL로 처리해 SQL 생성·답변용 LLM 호출을 줄입니다.
    use_fallback = bool(location_keywords) or is_count_query(question)
    model = None if use_fallback else load_chat_model()
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


@tool
def sql_tool(question: str) -> str:
    """지역, 주소, 병원명으로 동물병원 SQLite 데이터를 검색해 답합니다."""
    answer, _ = run_sql_search(question)
    return answer


class RouteDecision(BaseModel):
    route: Literal["rag", "sql", "analysis", "none"] = Field(
        description="rag: 건강/질병, sql: 병원 검색, analysis: 보고서 분석, none: 기타 대화"
    )


ROUTER_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """질문을 사용할 도구로 분류하세요.
- rag: 반려견 증상, 질병, 치료, 건강 정보
- sql: 동물병원 이름, 주소, 지역, 병원 목록 검색
    - analysis: 2025 한국 반려동물 보고서의 현황, 통계, 추이, 비교, 비중, 분포 분석
- none: 인사, 감사, 자기소개, 기능 문의 등 도구가 필요 없는 질문
인사말은 별도 직접 응답 분기로 만들지 말고 반드시 none으로 분류하세요.""",
    ),
    ("human", "[대화 이력]\n{chat_history}\n\n[현재 질문]\n{question}"),
])


OUT_OF_SCOPE_KEYWORDS = ("날씨", "기온", "미세먼지", "뉴스", "주식", "환율")
AGE_PATTERN = re.compile(r"(\d+)\s*(개월|살|세)")
DEPARTMENT_KEYWORDS = {
    "내과": (
        "내과",
        "구토",
        "토해",
        "설사",
        "소화",
        "식욕",
        "복통",
        "복부",
        "기침",
        "호흡",
        "열",
        "발열",
        "당뇨",
        "간",
        "신장",
    ),
    "외과": ("외과", "골절", "절뚝", "파행", "상처", "수술", "탈구", "다리"),
    "안과": ("안과", "눈", "눈곱", "충혈", "결막", "각막", "백내장"),
    "치과": ("치과", "치아", "잇몸", "구강", "입냄새", "치석"),
    "피부과": ("피부과", "피부", "가려", "긁", "털", "탈모", "발진", "귀"),
}


def is_date_question(question: str) -> bool:
    normalized = "".join(question.lower().split())
    return "날짜" in normalized or "며칠" in normalized or "몇일" in normalized


def current_date_answer() -> str:
    today = date.today()
    return f"오늘은 {today.year}년 {today.month}월 {today.day}일입니다."


def is_out_of_scope_question(question: str) -> bool:
    normalized = "".join(question.lower().split())
    return any(keyword in normalized for keyword in OUT_OF_SCOPE_KEYWORDS)


def classify_question(question: str, chat_history=None) -> str:
    if is_out_of_scope_question(question):
        return "none"
    if is_hospital_question(question):
        return "sql"
    normalized_question = "".join(question.lower().split())
    has_report_topic = any(
        keyword.replace(" ", "") in normalized_question
        for keyword in REPORT_ANALYSIS_KEYWORDS
    )
    if has_report_topic:
        return "analysis"

    model = load_chat_model()
    if model is not None:
        decision = (ROUTER_PROMPT | model.with_structured_output(RouteDecision)).invoke(
            {
                "chat_history": format_chat_history(chat_history),
                "question": question,
            }
        )
        return decision.route

    contextual_question = build_rag_search_query(question, chat_history).lower()
    if any(word in contextual_question for word in ("병원", "주소", "지역", "동물병원")):
        return "sql"
    if any(word in contextual_question for word in ("증상", "질병", "아파", "구토", "치료")):
        return "rag"
    if any(
        keyword.replace(" ", "") in contextual_question
        for keyword in REPORT_ANALYSIS_KEYWORDS
    ):
        return "analysis"
    return "none"


def answer_without_tool(question: str, chat_history=None) -> str:
    model = load_chat_model()
    if model is None:
        return "안녕하세요. 반려견 건강이나 동물병원에 관해 질문해 주세요."
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "도구가 필요하지 않은 일반 대화에 짧고 자연스럽게 답하세요. 의료 정보를 추측해서 답하지 마세요.",
        ),
        ("human", "[대화 이력]\n{chat_history}\n\n[현재 질문]\n{question}"),
    ])
    return (prompt | model | StrOutputParser()).invoke({
        "chat_history": format_chat_history(chat_history),
        "question": question,
    })


def infer_life_cycle_filter(question: str) -> str | None:
    for age_text, unit in AGE_PATTERN.findall(question):
        age = int(age_text)
        if unit == "개월":
            return "자견" if age <= PUPPY_MAX_MONTHS else "성견"
        if age <= PUPPY_MAX_YEARS:
            return "자견"
        if ADULT_MIN_YEARS <= age <= ADULT_MAX_YEARS:
            return "성견"
        return "노령견"
    return None


def infer_department_filter(question: str) -> str | None:
    normalized_question = question.lower()
    for department in DEPARTMENT_OPTIONS:
        if department != "전체" and department in normalized_question:
            return department

    compact_question = "".join(normalized_question.split())
    for department, keywords in DEPARTMENT_KEYWORDS.items():
        if any(keyword in compact_question for keyword in keywords):
            return department
    return None


def infer_rag_filters(question: str) -> dict[str, str]:
    filters = {}
    life_cycle = infer_life_cycle_filter(question)
    department = infer_department_filter(question)
    if life_cycle:
        filters["life_cycle"] = life_cycle
    if department:
        filters["department"] = department
    return filters


def chatbot(
    question: str,
    *,
    top_k: int = DEFAULT_RAG_TOP_K,
    chat_history=None,
) -> dict[str, Any]:
    """질문을 분류한 뒤 rag, sql, 또는 도구 없는 일반 응답을 실행합니다."""
    if not question or not question.strip():
        raise ValueError("질문을 입력해 주세요.")

    if is_date_question(question):
        return {"route": "none", "answer": current_date_answer()}

    contextual_question = build_rag_search_query(question, chat_history)
    route = classify_question(question, chat_history=chat_history)
    if route == "rag":
        rag_result = ask_rag(
            question,
            k=top_k,
            filters=infer_rag_filters(contextual_question),
            chat_history=chat_history,
        )
        return {
            "route": route,
            "answer": rag_result["answer"],
            "evidence_rows": rag_result["evidence_rows"],
        }
    elif route == "analysis":
        return {
            "route": route,
            "answer": report_analysis_tool.invoke({"question": question}),
            "evidence_rows": [],
        }
    elif route == "sql":
        answer, hospital_rows = run_sql_search(contextual_question)
    else:
        answer = answer_without_tool(question, chat_history=chat_history)
        hospital_rows = []
    return {"route": route, "answer": answer, "hospital_rows": hospital_rows}


def render_hospital_links(rows):
    if not rows:
        return
    st.markdown("#### 지도에서 병원 보기")
    for row in rows:
        hospital_id = row.get("ids")
        if hospital_id is None:
            continue
        if st.button(
            f"{row.get('name', '병원')} - {row.get('new_address', '')}",
            key=f"hospital_link_{hospital_id}",
        ):
            st.session_state[SELECTED_HOSPITAL_ID_STATE_KEY] = hospital_id
            st.switch_page("pages/hospital.py")


def render_page():
    apply_app_theme()
    render_page_header(
        "반려견 AI 상담",
        eyebrow="반려동물 건강 정보",
        description=(
            "건강 질문은 RAG로, 병원 검색은 SQLite로, 보고서 분석은 분석 도구로 처리합니다.\n"
            "분석 추천 항목: 한국 반려동물 현황, 웰니스, 양육 경험, 생애 지출, 자금 관리, 펫로스, 비만"
        ),
        accent="검증된 정보로 함께 살펴봐요",
    )

    top_k = st.slider(
        "참고할 근거 수",
        min_value=MIN_RAG_TOP_K,
        max_value=MAX_RAG_TOP_K,
        value=DEFAULT_RAG_TOP_K,
        key=RAG_TOP_K_SLIDER_KEY,
    )

    if CHAT_MESSAGES_STATE_KEY not in st.session_state:
        st.session_state[CHAT_MESSAGES_STATE_KEY] = []
    for message in st.session_state[CHAT_MESSAGES_STATE_KEY]:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    question = st.chat_input(
        "예: 강아지가 계속 구토해요 / 강남구 병원을 알려주세요."
    )
    st.markdown(
        """
        <style>
        textarea[data-testid="stChatInputTextArea"] {
            color: #17233f !important;
            -webkit-text-fill-color: #17233f !important;
            caret-color: #5943d8 !important;
        }
        textarea[data-testid="stChatInputTextArea"]::placeholder {
            color: #66728d !important;
            -webkit-text-fill-color: #66728d !important;
            opacity: 1 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if not question:
        render_hospital_links(st.session_state.get(HOSPITAL_ROWS_STATE_KEY, []))
        return

    chat_history = get_recent_chat_history(st.session_state[CHAT_MESSAGES_STATE_KEY])
    st.session_state[CHAT_MESSAGES_STATE_KEY].append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        try:
            with st.spinner(
                " 답변을 생성하는 중입니다. 잠시만 기다리세요"
            ):
                result = chatbot(
                    question,
                    top_k=top_k,
                    chat_history=chat_history,
                )

            st.write(result["answer"])
            st.session_state[CHAT_MESSAGES_STATE_KEY].append(
                {"role": "assistant", "content": result["answer"]}
            )
            st.session_state[CHAT_MESSAGES_STATE_KEY] = get_recent_chat_history(
                st.session_state[CHAT_MESSAGES_STATE_KEY]
            )

            st.session_state[HOSPITAL_ROWS_STATE_KEY] = result.get("hospital_rows", [])
            render_hospital_links(st.session_state[HOSPITAL_ROWS_STATE_KEY])

            evidence_rows = result.get("evidence_rows", [])
            if evidence_rows:
                st.markdown("#### 검색 근거")
                for index, row in enumerate(evidence_rows):
                    evidence = format_evidence_row(row, index)
                    with st.expander(evidence["title"]):
                        st.markdown(evidence["body"])
        except Exception as exc:
            st.error(f"실행 중 오류가 발생했습니다: {exc}")


def is_streamlit_runtime():
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except Exception:
        return False
    return get_script_run_ctx(suppress_warning=True) is not None


if is_streamlit_runtime():
    render_page()
