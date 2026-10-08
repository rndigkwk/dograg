"""Report analysis over the pet-industry report collection (OpenAI embeddings)."""

from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src import resources
from src.crag import merge_documents
from src.report_evidence import report_evidence_from_docs

REPORT_ANALYSIS_TOP_K = 6
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
    "상관관계",  # "상관"만 쓰면 "상관없는" 질문이 보고서로 갔다
    "세대별",
    "장묘",
    "동물복지",
    "복지실태",
    "반려동물 산업",
    "시장 규모",
    "실태조사",
    "펫보험",
    "연도별",
)
REPORT_ANALYSIS_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """반려동물 관련 보고서(2025 한국 반려동물 보고서, 복지실태, 산업 실태조사, 의료보험, 장묘서비스)의
검색 자료만 근거로 분석 결과를 작성하세요. 아래 분석 항목은 2025 한국 반려동물 보고서의 목차 기준입니다.
분석 항목에 해당하는 수치, 차이, 추이를 우선 정리하고, 자료에 없는 수치나 원인은 추측하지 마세요.
검색 자료가 부족하면 부족한 부분을 명시하세요. 답변에는 분석 대상, 핵심 결과, 근거 보고서명과 페이지를 포함하세요.
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
        f"[{doc.metadata.get('title', '보고서')} · 페이지 {doc.metadata.get('page', '?')}] {doc.page_content}"
        for doc in report_docs
    )


def analyze_report(question: str) -> dict:
    report_db = resources.load_report_vector_db()
    if report_db is None:
        return {"answer": "보고서 검색에는 OPENAI_API_KEY가 필요합니다.", "evidence_rows": []}
    # 목차 항목은 답변 프롬프트에만 씁니다. 검색어에 붙이면 KB 목차 페이지가 근거를 차지했습니다
    # (정답 페이지 적중 상위 6건 7/18 → 질문만으로 12/18, docs/wiki/retrieval-experiments.md).
    report_docs = search_reports_hybrid(question)
    evidence_rows = report_evidence_from_docs(report_docs)
    if not report_docs:
        return {"answer": "검색된 보고서 근거가 부족해 분석할 수 없습니다.", "evidence_rows": []}
    return {"answer": generate_report_answer(question, report_docs), "evidence_rows": evidence_rows}


REPORT_CANDIDATE_K = 20


def search_reports_hybrid(question: str, k: int = REPORT_ANALYSIS_TOP_K) -> list:
    """Day47: Dense + BM25 over the report chunks, merged by RRF. Report questions name exact
    terms (보고서 이름, 항목, 연도) that a keyword index matches where embeddings drift.
    18 report questions: gold page in the top 6 12/18 -> 16/18, correct answers 23/36 -> 30/36
    (docs/wiki/retrieval-experiments.md, experiment 13)."""
    from src.hybrid_retrieval import retrieve_hybrid

    report_db = resources.load_report_vector_db()
    if report_db is None:
        return []
    return retrieve_hybrid(report_db, resources.load_report_bm25_index(), question, top_k=k,
                           candidate_k=REPORT_CANDIDATE_K)


def search_reports(question: str, queries: list[str] | None = None) -> list:
    """Search the report collection once per (sub)query and merge results by chunk id."""
    report_db = resources.load_report_vector_db()
    if report_db is None:
        return []
    found = []
    for query in queries or [question]:
        found = merge_documents(found, search_reports_hybrid(query))
    return found


def generate_report_answer(question: str, report_docs: list) -> str:
    model = resources.load_chat_model()
    if model is None:
        return "분석 자동화에는 OPENAI_API_KEY가 필요합니다."
    try:
        return (REPORT_ANALYSIS_PROMPT | model | StrOutputParser()).invoke({
            "topics": "\n".join(get_report_analysis_topics(question)),
            "context": format_report_context(report_docs),
            "question": question,
        })
    except Exception:
        return "모델 연결에 실패해 분석 답변을 생성하지 못했습니다. 아래 검색 근거만 확인해 주세요."
