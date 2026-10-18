"""Report analysis over the pet-industry report collection (OpenAI embeddings)."""

from __future__ import annotations

import re

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
페이지는 각 검색 자료 머리표의 "페이지 N"을 그대로 쓰세요. 본문에 인쇄된 쪽 번호나 목차의 숫자는 화면의 근거 목록과 달라 쓰지 마세요.
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
# A table of contents line ends in a dot leader ("소비자 불만 현황······· 14"); three or more in a
# chunk make it a contents page. A reference list opens with its heading.
_DOT_LEADER = re.compile(r"[·…]{3,}|\.{5,}")
_REFERENCES_HEADING = re.compile(r"참\s*고\s*문\s*헌")


def is_front_or_back_matter(doc) -> bool:
    """Contents and reference-list chunks: they name every topic, so the keyword search ranks them
    high, but they hold no figures, and the model then cites a contents page's page numbers
    (2026-10-17: "p.14" from 장묘 보고서 page 2, a reference page among the evidence). 76 of the
    1,193 report chunks (docs/wiki/retrieval-experiments.md)."""
    text = doc.page_content
    title = str(doc.metadata.get("title") or "").replace("+", " ").split("_")[0]
    head = " ".join(text.split())[:120].replace(title, "", 1)
    return len(_DOT_LEADER.findall(text)) >= 3 or bool(_REFERENCES_HEADING.search(head[:40]))


def search_reports_hybrid(question: str, k: int = REPORT_ANALYSIS_TOP_K) -> list:
    """Day47: Dense + BM25 over the report chunks, merged by RRF. Report questions name exact
    terms (보고서 이름, 항목, 연도) that a keyword index matches where embeddings drift.
    18 report questions: gold page in the top 6 12/18 -> 16/18, correct answers 23/36 -> 30/36
    (docs/wiki/retrieval-experiments.md, experiment 13)."""
    from src.hybrid_retrieval import retrieve_hybrid

    report_db = resources.load_report_vector_db()
    if report_db is None:
        return []
    index = resources.load_report_bm25_index()
    sources = named_reports(question)
    if len(sources) < 2 and asks_several_reports(question):
        sources = leading_reports(report_db, index, with_report_terms(report_topic(question)))
    if sources:
        # A question that names two reports ("KB 2025와 2024 복지실태 보고서에서 …") is searched in
        # each report on its topic words: ranked together one report filled every slot, and the
        # report names, years and "각각 알려주세요" pulled cover pages ahead of the figure (r03:
        # 복지실태 p.169-170 "1일 평균 5.1시간" missed on Supabase until searched this way). No model call.
        # A question naming one report is searched in that report only (h07: KB p.16 out of the top 6
        # among all five reports, 4th within KB on Supabase), on the question without the name.
        topic = with_report_terms(report_topic(question) if len(sources) >= 2 else without_report_name(question))
        share = max(1, k // len(sources))
        found = []
        for source in sources:
            mine = retrieve_hybrid(report_db, index, topic, top_k=k + 8, candidate_k=REPORT_CANDIDATE_K,
                                   where={"source": source})
            found += by_page([doc for doc in mine if not is_front_or_back_matter(doc)], share)
        return found
    found = retrieve_hybrid(report_db, index, with_report_terms(question), top_k=k + 8, candidate_k=REPORT_CANDIDATE_K)
    return by_page([doc for doc in found if not is_front_or_back_matter(doc)], k)


# How guardians name each report in a question; a question naming two or more is searched per report.
REPORT_NAMES = {
    "data/source/2025 한국 반려동물 보고서.pdf": ("KB", "한국 반려동물 보고서"),
    "data/source/반려동물 복지실태와 개선과제.pdf": ("복지실태", "복지 실태"),
    "data/source/반려동물 산업 조사체계 진단 및 실태조사.pdf": ("산업 조사", "조사체계"),
    "data/source/반려동물+의료보험서비스+시장+진단+및+개선방안+연구_고은희_강하영.pdf": (
        "의료·보험", "의료보험", "의료 보험", "보험서비스", "동물병원 소비자"),
    "data/source/반려동물+장묘서비스+이용+실태조사_온라인거래조사팀.pdf": ("장묘",),
}
_TOPIC_NOISE = re.compile(r"\b20\d\d(년)?(와|과|의|에서)?|(보고서|실태조사)(마다|별로?|들)?(와|과|의|에서|을|를)?|각각|"
                          r"비교해 ?(서|줘|주세요)?|비교하고|찾아|묶어서|정리해 ?줘|알려 ?(주세요|줘)")
# "보고서마다", "보고서들에서", "각 보고서", "여러 보고서", "두 보고서": the question asks the reports apart
# without naming them (holdout h01-h04, 2026-10-18).
_SEVERAL_REPORTS = re.compile(r"보고서(마다|별|들)|(각|여러|두|세) ?보고서")
LEADING_REPORTS = 3


def report_topic(question: str) -> str:
    """The question without what names the reports (names, years, "보고서", "각각 알려주세요"): what
    to look for inside each report. A name that is also a topic ("동물병원 소비자") stays."""
    for names in REPORT_NAMES.values():
        for name in sorted(names, key=len, reverse=True):
            if name != "동물병원 소비자":
                question = question.replace(name, " ")
    return " ".join(_TOPIC_NOISE.sub(" ", question).split()).strip(" ,.") or question


# Guardians' words for what the reports call otherwise; the report's word is added to the query, no
# model call. h03 "직접 땅에 묻은" found KB's "직접 매장" (p.68, 70) only with 매장 added; h07
# "키우고 싶은" found "양육 희망" (p.16). Checked beyond those two on five everyday questions (e01-e05).
REPORT_TERMS = [
    (re.compile(r"땅에 묻|묻어 ?주|묻었|묻은"), "매장"),
    (re.compile(r"세상을 떠난|떠나보낸|무지개다리|죽은 (반려|강아지|고양이)"), "장례 펫로스"),
    (re.compile(r"키우고 싶|키울 생각|기르고 싶|입양하고 싶"), "양육 희망 양육 계획"),
    (re.compile(r"키우는 (집|가구|가정)|기르는 (집|가구|가정)"), "반려가구 양육 가구"),
    (re.compile(r"병원비"), "진료비 치료비"),
    (re.compile(r"혼자 (두|남)"), "혼자 있는 시간"),
    (re.compile(r"강아지"), "반려견"),
    (re.compile(r"고양이"), "반려묘"),
    (re.compile(r"보험(을|에)? ?(들|든)"), "보험 가입"),
]


def with_report_terms(query: str) -> str:
    added = [term for pattern, term in REPORT_TERMS if pattern.search(query) and term not in query]
    return " ".join([query, *added])


def asks_several_reports(question: str) -> bool:
    return bool(_SEVERAL_REPORTS.search(question))


def leading_reports(report_db, index, topic: str) -> list[str]:
    """The reports a question that names none is about: the first LEADING_REPORTS reports in the
    overall ranking of its topic words. Five reports split six slots one each left both answers out
    on Supabase (h01, h04); three reports, two pages each, had every asked report on 4/5 local and
    3/5 Supabase questions, from 3/5 and 1/5 ranked together (docs/wiki/retrieval-experiments.md)."""
    from src.hybrid_retrieval import retrieve_hybrid

    order: list[str] = []
    for doc in retrieve_hybrid(report_db, index, topic, top_k=40, candidate_k=REPORT_CANDIDATE_K):
        source = doc.metadata.get("source")
        if source not in order and not is_front_or_back_matter(doc):
            order.append(source)
    return order[:LEADING_REPORTS]


# Longer forms a guardian writes the names in; stripped before REPORT_NAMES' short ones.
_FULL_NAMES = ("산업 조사체계", "의료·보험서비스", "의료보험서비스", "장묘서비스 이용 실태조사", "장묘서비스", "한국 반려동물 보고서")


def without_report_name(question: str) -> str:
    """A question naming one report, without the name and "보고서에서": the report is the search's
    filter. Only whole words go ("장묘 실태조사에서", not the 장묘 in "동물장묘업체"), and years stay
    ("2013년과 2022년에" is what h12 asks for); report_topic drops both, for two-report questions."""
    names = [*_FULL_NAMES, *sorted({n for ns in REPORT_NAMES.values() for n in ns}, key=len, reverse=True)]
    for name in names:
        question = re.sub(rf"(?<![가-힣]){re.escape(name)}(?:\s*20\d\d)?(?:(?:와|과|의|에서|은|는|이|가)(?![가-힣]))?", " ", question)
    question = re.sub(r"(보고서|실태조사)(?:에서|의|와|과)?(?![가-힣])", " ", question)
    return " ".join(question.split()) or question


def named_reports(question: str) -> list[str]:
    """The report sources a question names, in REPORT_NAMES order."""
    return [source for source, names in REPORT_NAMES.items() if any(name in question for name in names)]


def by_page(docs: list, k: int) -> list:
    """The first k pages in rank order, with every found chunk of each. A KB page has a PDF chunk
    (exact wording) and an OCR chunk (its figures, scripts/add_kb_ocr_chunks.py); counted apart,
    the two filled 7 of the 18 questions' top-6 slots and pushed out another report's page (r03)."""
    pages: list = []
    for doc in docs:
        page = (doc.metadata.get("source"), doc.metadata.get("page"))
        if page not in pages:
            pages.append(page)
    keep = set(pages[:k])
    return [doc for doc in docs if (doc.metadata.get("source"), doc.metadata.get("page")) in keep]


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
