"""Chat page: renders the conversation and calls src.chatbot. Tools live in src/tools/."""

import logging
import os
import sys

import streamlit as st
from streamlit.errors import StreamlitAPIException

from src import resources
from src.chatbot import chatbot
from src.health_safety import detect_urgent_sign
from src.location_component import render_location_control
from src.memory_limits import release_free_memory
from src.report_evidence import render_pdf_page, resolve_report_pdf
from src.settings import PROJECT_DIR
from src.tools.health import DEFAULT_RAG_TOP_K, MAX_RAG_TOP_K, MIN_RAG_TOP_K
from src.tools.history import get_recent_chat_history
from src.ui import apply_app_theme, render_page_header

CHAT_MESSAGES_STATE_KEY = "fixing_messages"
HOSPITAL_ROWS_STATE_KEY = "hospital_rows"
SELECTED_HOSPITAL_ID_STATE_KEY = "selected_hospital_id"
RAG_TOP_K_SLIDER_KEY = "rag_top_k"


def format_evidence_row(row, index):
    life_cycle = row.get("meta.lifeCycle") or row.get("lifeCycle") or "-"
    department = row.get("meta.department") or row.get("department") or "-"
    disease = row.get("meta.disease") or row.get("disease") or "-"
    answer = row.get("qa.output") or row.get("answer") or ""
    return {
        "title": f"{index + 1}. {life_cycle} / {department} / {disease}",
        "body": f"**답변**\n\n{answer}",
    }


ROUTE_PROGRESS = {
    "rag": "건강 상담 자료에서 근거를 찾고 있습니다…",
    "analysis": "보고서에서 근거를 찾고 있습니다…",
    "sql": "동물병원을 찾고 있습니다…",
    "none": "답변을 작성하고 있습니다…",
}


def progress_message(node: str, update: dict) -> str | None:
    """그래프 노드가 끝날 때마다 다음 단계를 사용자에게 알려 줄 문구를 고릅니다."""
    if node == "classify":
        return ROUTE_PROGRESS.get(update.get("route"))
    if node in {"health_retrieve", "report_retrieve"}:
        return "찾은 근거가 질문에 맞는지 확인하고 있습니다…"
    if node in {"health_grade", "report_grade"}:
        if update.get("documents"):
            return "근거를 바탕으로 답변을 작성하고 있습니다…"
        return "맞는 근거가 없어 검색어를 바꿔 다시 찾고 있습니다…" if node == "health_grade" else None
    return None


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


def render_assistant_message(message: dict, *, show_notice: bool = True) -> None:
    if show_notice and message.get("safety_notice"):
        st.warning(message["safety_notice"])
    st.write(message["content"])
    if message.get("abstained") and message.get("route") == "rag":
        try:
            st.page_link("pages/hospital.py", label="가까운 동물병원 찾기", icon=":material/local_hospital:")
        except StreamlitAPIException:  # 내비게이션 밖(테스트 등)에서는 링크 대신 안내만 표시합니다.
            st.caption("왼쪽 메뉴의 '병원 찾기'에서 가까운 동물병원을 찾을 수 있습니다.")
    evidence_rows = message.get("evidence_rows", [])
    if not evidence_rows:
        return
    if message.get("route") == "analysis":
        st.markdown("#### 보고서 근거")
        previewed = set()
        for index, row in enumerate(evidence_rows, start=1):
            page = row.get("page")
            title = row.get("title") or "2025 한국 반려동물 보고서"
            st.markdown(f"**근거 {index} · {title} · 페이지 {page if page else '확인 불가'}**")
            st.write(row.get("excerpt", ""))
            pdf_path = resolve_report_pdf(PROJECT_DIR, row.get("source"))
            if page and pdf_path and (pdf_path, page) not in previewed:
                previewed.add((pdf_path, page))
                png = render_pdf_page(pdf_path, page)
                if png:
                    st.image(png, caption=f"{title} · {page}페이지")
                else:
                    st.caption("이 페이지의 PDF 미리보기를 열 수 없습니다.")
    else:
        st.markdown("#### 검색 근거")
        for index, row in enumerate(evidence_rows):
            evidence = format_evidence_row(row, index)
            with st.expander(evidence["title"]):
                st.markdown(evidence["body"])


def warmup_wanted(env: dict | None = None, modules: dict | None = None, runtime_exists=None) -> bool:
    """Warm up on a real Streamlit server, not under AppTest; DOGRAG_WARMUP=0/1 overrides.

    sys.argv cannot tell the two apart: Streamlit replaces it with the app script path.
    AppTest also has a runtime, but it is the only one that imports streamlit.testing.
    """
    env = os.environ if env is None else env
    override = str(env.get("DOGRAG_WARMUP", "")).strip().lower()
    if override in {"0", "false", "off", "no"}:
        return False
    if override in {"1", "true", "on", "yes"}:
        return True
    modules = sys.modules if modules is None else modules
    if runtime_exists is None:
        from streamlit import runtime

        runtime_exists = runtime.exists()
    return bool(runtime_exists) and "streamlit.testing.v1" not in modules


def _warm_up_health_search():
    # 모델(ko-sroberta), BM25 색인, 답변 표를 미리 캐시에 올립니다. 실패해도 첫 질문 때 다시 시도됩니다.
    try:
        resources.load_vector_db()
        resources.load_health_bm25_index()
        resources.load_health_answer_table()
        release_free_memory()  # 로딩 중 잠깐 쓴 메모리를 OS에 돌려줍니다.
    except Exception:  # noqa: BLE001 - warm-up is best effort
        logging.getLogger(__name__).warning("Health search warm-up failed", exc_info=True)


@st.cache_resource(show_spinner=False)
def start_warmup():
    """Start one background warm-up per server process (st.cache_resource runs this once)."""
    import threading

    from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

    thread = threading.Thread(target=_warm_up_health_search, name="dograg-warmup", daemon=True)
    add_script_run_ctx(thread, get_script_run_ctx())
    thread.start()
    return thread


def render_page():
    if warmup_wanted():
        start_warmup()
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
    st.caption("가까운 병원 검색은 위치 사용을 선택한 경우에만 직선거리로 계산합니다.")
    location, location_status = render_location_control("rag_browser_location")
    if location_status:
        st.info(f"{location_status} 지역명으로 병원을 검색할 수 있습니다.")

    if CHAT_MESSAGES_STATE_KEY not in st.session_state:
        st.session_state[CHAT_MESSAGES_STATE_KEY] = []
    for message in st.session_state[CHAT_MESSAGES_STATE_KEY]:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                render_assistant_message(message)
            else:
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
        urgent_notice = detect_urgent_sign(question)
        if urgent_notice:
            st.warning(urgent_notice)
        try:
            # 답변 문장은 모델이 쓰는 대로 보여 주고, 그 전까지는 지금 단계를 알려 줍니다.
            status = st.empty()
            status.caption("⏳ 질문을 확인하고 있습니다…")
            stream_box = st.empty()
            streamed: list[str] = []

            def show_token(text: str) -> None:
                if not streamed:
                    status.empty()
                streamed.append(text)
                stream_box.markdown("".join(streamed) + " ▌")

            def show_step(node: str, update: dict) -> None:
                message = None if streamed else progress_message(node, update)
                if message:
                    status.caption(f"⏳ {message}")

            try:
                result = chatbot(
                    question,
                    top_k=top_k,
                    chat_history=chat_history,
                    location=location,
                    on_token=show_token,
                    on_step=show_step,
                )
            finally:
                status.empty()
                stream_box.empty()

            assistant_message = {
                "role": "assistant", "content": result["answer"], "route": result["route"],
                "evidence_rows": result.get("evidence_rows", []),
                "safety_notice": result.get("safety_notice") or urgent_notice,
                "abstained": result.get("abstained", False),
            }
            render_assistant_message(assistant_message, show_notice=False)
            st.session_state[CHAT_MESSAGES_STATE_KEY].append(assistant_message)
            st.session_state[CHAT_MESSAGES_STATE_KEY] = get_recent_chat_history(
                st.session_state[CHAT_MESSAGES_STATE_KEY]
            )

            st.session_state[HOSPITAL_ROWS_STATE_KEY] = result.get("hospital_rows", [])
            render_hospital_links(st.session_state[HOSPITAL_ROWS_STATE_KEY])
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
