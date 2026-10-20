"""Chat page: renders the conversation and calls src.chatbot. Tools live in src/tools/."""

import logging
import os
import sys

import streamlit as st
from streamlit.errors import StreamlitAPIException
from streamlit.runtime.scriptrunner_utils.exceptions import ScriptControlException

from src import feedback_store, model_outage, rate_limit, resources
from src.chat_events import (  # noqa: F401
    ROUTE_PROGRESS,
    find_emergency_hospitals,
    places_first,
    progress_message,
)
from src.chat_graph import HEALTH_ABSTAIN, HEALTH_PART_HEADING
from src.chatbot import chatbot
from src.conversation_session import LOADING, ConversationSession
from src.conversation_ui import (
    CHAT_MESSAGES_STATE_KEY,
    HOSPITAL_ROWS_STATE_KEY,
    RENDERED_THREAD_STATE_KEY,
)
from src.health_safety import detect_urgent_sign
from src.location_component import render_location_control
from src.memory_limits import release_free_memory
from src.report_evidence import render_pdf_page, resolve_report_pdf
from src.settings import PROJECT_DIR
from src.storage.models import PetProfile
from src.tools.health import DEFAULT_RAG_TOP_K, MAX_RAG_TOP_K, MIN_RAG_TOP_K
from src.tools.history import history_with_summary, summary_due
from src.tools.profile import profile_summary, suggest_memory
from src.tools.urgency import urgent_notice as find_urgent_notice
from src.tracing import record_feedback, record_feedback_reason
from src.ui import apply_app_theme, plain_tildes, render_page_header

SELECTED_PLACE_ID_STATE_KEY = "selected_place_id"
RAG_TOP_K_SLIDER_KEY = "rag_top_k"
# The question being answered. A rerun mid-answer (a widget changed, or the browser location
# arrived) stops the run that holds it; the next run finds it here and answers it then.
IN_FLIGHT_STATE_KEY = "answer_in_flight"
# An error from the last answer, shown once after the rerun that opens the input again
CHAT_ERROR_STATE_KEY = "chat_error"
PROFILE_SUGGESTION_KEY = "profile_suggestion"
# {thread id: {"upto", "summary"}}: the running summary of each conversation's older turns
HISTORY_SUMMARY_STATE_KEY = "history_summaries"
PROFILE_DISMISSED_KEY = "profile_detection_dismissed"
# New facts the user chose not to remember this session (their summaries): not offered again
MEMORY_DECLINED_KEY = "memory_declined"


def format_evidence_row(row, index):
    if row.get("kind") == "care_guide":  # src/tools/care_guides.py
        source = f"출처: {row.get('organization', '')} · [원문 보기]({row.get('url', '')})"
        return {
            "title": f"{index + 1}. 지침 · {row.get('title', '')} · {row.get('page', '?')}쪽",
            "body": f"{row.get('piece', '')}\n\n{source}",
        }
    life_cycle = row.get("meta.lifeCycle") or row.get("lifeCycle") or "-"
    department = row.get("meta.department") or row.get("department") or "-"
    disease = row.get("meta.disease") or row.get("disease") or "-"
    answer = row.get("qa.output") or row.get("answer") or ""
    return {
        "title": f"{index + 1}. {life_cycle} / {department} / {disease}",
        "body": f"**답변**\n\n{answer}",
    }


def render_hospital_links(rows):
    rows = [row for row in rows if row.get("id") and row.get("latitude") is not None]
    if not rows:
        return
    st.markdown("#### 지도에서 위치 보기")
    for row in rows:
        if st.button(
            f"{row.get('name', '장소')} - {row.get('road_address') or row.get('lot_address') or ''}",
            key=f"hospital_link_{row['id']}",
        ):
            st.session_state[SELECTED_PLACE_ID_STATE_KEY] = row["id"]
            st.switch_page("app_pages/hospital.py")


def _hospital_line(row: dict) -> str:
    phone = row.get("phone")
    call = f"[{phone}](tel:{''.join(ch for ch in phone if ch.isdigit())})" if phone else "전화번호 없음"
    address = row.get("road_address") or row.get("lot_address") or ""
    return f"- **{row['name']}** · {row['distance_km']:.1f}km · {call}  \n  {address}"


def render_emergency(emergency: dict) -> None:
    """Under an urgent warning: the nearest hospitals with phone numbers, or how to get them."""
    with st.container(border=True):
        st.markdown("**🚨 가까운 동물병원**")
        if not emergency.get("nearest"):
            try:
                st.page_link("app_pages/hospital.py", label="시설 찾기에서 가까운 동물병원 찾기", icon=":material/local_hospital:")
            except (StreamlitAPIException, KeyError):  # 내비게이션 밖(AppTest 등)
                st.caption("왼쪽 메뉴의 '시설 찾기'에서 가까운 동물병원을 찾을 수 있습니다.")
            st.caption("위의 '현재 위치 사용'을 누르면 다음부터 가까운 병원을 여기에 바로 보여 줍니다.")
            return
        st.markdown("\n".join(_hospital_line(row) for row in emergency["nearest"]))
        if emergency.get("night"):
            st.markdown("이름에 24시·응급·야간이 들어간 가까운 병원")
            st.markdown("\n".join(_hospital_line(row) for row in emergency["night"]))
        st.caption("거리는 직선거리입니다. 영업 여부와 진료 시간은 데이터에 없으니 출발 전에 전화로 지금 진료가 가능한지 확인하세요.")


def send_feedback(trace_id: str) -> None:
    value = st.session_state.get(f"feedback_{trace_id}")
    if value is not None:  # None: the vote was cleared; the stored score stays
        record_feedback(trace_id, helpful=value == 1)


def send_feedback_reason(trace_id: str) -> None:
    reason = st.session_state.get(f"feedback_reason_{trace_id}")
    if reason:
        record_feedback_reason(trace_id, reason)


def render_feedback(message: dict, question: str | None = None) -> None:
    """👍/👎 under answers of this session that have a Langfuse trace (tracing on). After a 👎: why
    (a Langfuse score) and, with consent, this question and answer for review (src/feedback_store.py)."""
    trace_id = message.get("trace_id")
    if not trace_id:
        return
    st.feedback("thumbs", key=f"feedback_{trace_id}", on_change=send_feedback, args=(trace_id,))
    if st.session_state.get(f"feedback_{trace_id}") != 0:
        return
    st.radio("어떤 점이 아쉬웠나요?", feedback_store.REASONS, index=None, horizontal=True,
             key=f"feedback_reason_{trace_id}", on_change=send_feedback_reason, args=(trace_id,))
    if not (question and feedback_store.enabled()):
        return
    sent_key = f"feedback_sent_{trace_id}"
    if st.session_state.get(sent_key):
        st.caption("보내 주셔서 고맙습니다. 답변을 고치는 데 쓰겠습니다.")
        return
    consent = st.checkbox("이 질문과 답변을 개선에 쓰도록 보내기 (전화번호·주소 같은 개인정보는 가린 뒤 저장합니다)",
                          key=f"feedback_consent_{trace_id}")
    if consent and st.button("보내기", key=f"feedback_send_{trace_id}"):
        st.session_state[sent_key] = feedback_store.save_review(
            question=question, answer=message.get("content", ""), route=message.get("route"),
            reason=st.session_state.get(f"feedback_reason_{trace_id}"), trace_id=trace_id,
            evidence=[feedback_store.evidence_summary(row) for row in message.get("evidence_rows", []) if isinstance(row, dict)])
        st.caption("보내 주셔서 고맙습니다. 답변을 고치는 데 쓰겠습니다." if st.session_state[sent_key]
                   else "지금은 보내지 못했습니다. 잠시 뒤 다시 시도해 주세요.")


EXCERPT_PREVIEW_CHARS = 150  # about 2-3 lines in the chat column


def excerpt_preview(text: str) -> str:
    """The first 2-3 lines of a report excerpt, on one line; the rest is behind 자세히 보기."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= EXCERPT_PREVIEW_CHARS else flat[:EXCERPT_PREVIEW_CHARS].rstrip() + "…"


def render_report_evidence(evidence_rows: list[dict], key: str) -> None:
    """Report evidence: title, page and a short preview; full text and the PDF page on request.
    The page image is rendered only when opened, so long answers stay short and the server
    renders no PDF page nobody looks at."""
    st.markdown("#### 보고서 근거")
    for index, row in enumerate(evidence_rows, start=1):
        page = row.get("page")
        title = row.get("title") or "2025 한국 반려동물 보고서"
        with st.container(border=True):
            scanned = " · 스캔 글(OCR)" if row.get("scanned") else ""
            st.markdown(f"**근거 {index} · {title} · 페이지 {page if page else '확인 불가'}{scanned}**")
            if scanned:
                st.caption("보고서 그림 속 숫자를 스캔(OCR)으로 읽은 글이라 글자가 틀릴 수 있어요. 원문 페이지로 확인하세요.")
            st.caption(excerpt_preview(row.get("excerpt", "")))
            if not st.toggle("자세히 보기", key=f"report_evidence_{key}_{index}"):
                continue
            st.write(plain_tildes(row.get("excerpt", "")))
            pdf_path = resolve_report_pdf(PROJECT_DIR, row.get("source"))
            png = render_pdf_page(pdf_path, page) if page and pdf_path else None
            if png:
                st.image(png, caption=f"{title} · {page}페이지")
            else:
                st.caption("이 페이지의 PDF 미리보기를 열 수 없습니다.")


def render_visit_prep_button(question: str, key: str) -> None:
    """Under a health answer: carry this question to the visit-prep report page."""
    from app_pages.visit_prep import CONSULTATION_KEY, MAX_CONSULTATION_CHARS

    if st.button("이 상담으로 방문 준비 보고서 만들기", key=f"visit_prep_{key}", icon=":material/description:"):
        st.session_state[CONSULTATION_KEY] = question[:MAX_CONSULTATION_CHARS]
        try:
            st.switch_page("app_pages/visit_prep.py")
        except (StreamlitAPIException, KeyError):  # 내비게이션 밖(AppTest 등)
            st.caption("왼쪽 메뉴의 '방문 준비 보고서'에서 이어서 만들 수 있습니다.")


def render_assistant_message(message: dict, *, show_notice: bool = True, key: str = "latest",
                             question: str | None = None) -> None:
    if show_notice and message.get("safety_notice"):
        st.warning(message["safety_notice"])
    if show_notice and message.get("emergency") is not None:
        render_emergency(message["emergency"])
    st.write(plain_tildes(message["content"]))
    render_feedback(message, question)
    # Not under an abstention: there was no evidence, so a report would spend 10-20 model calls
    # on the same empty search. Stored turns keep no "abstained" flag, so the text is checked too.
    abstained = message.get("abstained") or str(message.get("content", "")).startswith(HEALTH_ABSTAIN)
    if question and message.get("route") == "rag" and not abstained:
        render_visit_prep_button(question, key)
    if message.get("abstained") and message.get("route") == "rag":
        try:
            st.page_link("app_pages/hospital.py", label="가까운 동물병원 찾기", icon=":material/local_hospital:")
        except (StreamlitAPIException, KeyError):  # 내비게이션 밖(AppTest 등)에서는 링크 대신 안내만 표시합니다.
            st.caption("왼쪽 메뉴의 '시설 찾기'에서 가까운 동물병원을 찾을 수 있습니다.")
    evidence_rows = message.get("evidence_rows", [])
    if not evidence_rows:
        return
    if message.get("route") == "analysis":
        render_report_evidence(evidence_rows, key)
    else:
        st.markdown("#### 검색 근거")
        for index, row in enumerate(evidence_rows):
            evidence = format_evidence_row(row, index)
            with st.expander(evidence["title"]):
                st.markdown(plain_tildes(evidence["body"]))


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
        resources.load_report_bm25_index()  # report search is hybrid too (needs the API key; None without)
        release_free_memory()  # 로딩 중 잠깐 쓴 메모리를 OS에 돌려줍니다.
    except ScriptControlException:
        # The script run this thread is attached to was stopped (a rerun). Streamlit's control
        # exceptions derive from BaseException; stop quietly instead of a thread traceback.
        logging.getLogger(__name__).info("Health search warm-up stopped by a rerun; the first question loads the rest")
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


def suggest_profile(session: ConversationSession, question: str, route: str) -> None:
    """Profile detection and automatic memory (src/tools/profile.suggest_memory), for health answers.
    An empty profile: offered whole, and not asked again this session once declined. A stored one:
    only new facts (a diagnosis, a medicine, a surgery, a new weight), each set offered once.
    Nothing is saved without a click."""
    # Until the browser reports its stored profile the session holds an empty one: a suggestion
    # then would offer a "new" profile, and saving it would replace the stored one (2026-10-15).
    if route != "rag" or session.status == LOADING:
        return
    current = session.profiles.get()
    if current is None and st.session_state.get(PROFILE_DISMISSED_KEY):
        return
    try:
        suggestion = suggest_memory(current, question)
    except Exception:  # detection is optional; the answer is already shown
        logging.getLogger(__name__).warning("Profile detection failed", exc_info=True)
        return
    if suggestion is None or suggestion.summary in st.session_state.get(MEMORY_DECLINED_KEY, []):
        return
    st.session_state[PROFILE_SUGGESTION_KEY] = {"profile": suggestion.profile.model_dump(mode="json"),
                                                "summary": suggestion.summary, "update": current is not None}


def render_profile_suggestion(session: ConversationSession) -> None:
    suggestion = st.session_state.get(PROFILE_SUGGESTION_KEY)
    if not suggestion:
        return
    profile = PetProfile.model_validate(suggestion["profile"])
    update = suggestion["update"]
    with st.container(border=True):
        if update:
            st.markdown(f"**새로 알게 된 정보를 기억할까요?** {suggestion['summary']}")
            st.caption("기억하면 이 브라우저의 '우리 아이 정보'에 더해지고, 다음 상담부터 답변에 반영됩니다.")
        else:
            st.markdown(f"**대화에서 반려견 정보를 찾았어요.** {profile_summary(profile)}")
            st.caption("저장하면 이 브라우저에만 남고, 다음 상담부터 나이에 맞는 자료를 먼저 찾습니다.")
        save, dismiss = st.columns(2)
        if save.button("기억하기" if update else "우리 아이 정보에 저장", key="profile_suggest_save", type="primary",
                       width="stretch"):
            session.profiles.save(profile)
            st.session_state.pop(PROFILE_SUGGESTION_KEY, None)
            st.rerun()
        if dismiss.button("기억하지 않기" if update else "저장하지 않기", key="profile_suggest_dismiss", width="stretch"):
            st.session_state.pop(PROFILE_SUGGESTION_KEY, None)
            if update:
                st.session_state.setdefault(MEMORY_DECLINED_KEY, []).append(suggestion["summary"])
            else:
                st.session_state[PROFILE_DISMISSED_KEY] = True
            st.rerun()


def conversation_history(session: ConversationSession, messages: list[dict]) -> list[dict]:
    """What the prompts see of this conversation: a summary of older turns + the recent ones.
    The summary lives in this browser session only (like the conversation itself)."""
    memories = st.session_state.setdefault(HISTORY_SUMMARY_STATE_KEY, {})
    memory = memories.setdefault(session.current_thread or "new", {})
    if summary_due(messages, memory):
        with st.spinner("이전 대화를 요약하고 있습니다…"):
            return history_with_summary(messages, memory)
    return history_with_summary(messages, memory)


def interrupted_question(session: ConversationSession, messages: list[dict]) -> dict | None:
    """The question an earlier run was answering when a rerun stopped it, if it still applies:
    same conversation, and its question is still the last message (not a new or other chat)."""
    in_flight = st.session_state.get(IN_FLIGHT_STATE_KEY)
    if not in_flight:
        return None
    last = messages[-1] if messages else {}
    if in_flight["thread"] != session.current_thread or last != {"role": "user", "content": in_flight["question"]}:
        st.session_state.pop(IN_FLIGHT_STATE_KEY, None)
        return None
    return in_flight


def render_page():
    if warmup_wanted():
        start_warmup()
    apply_app_theme()
    # main.py syncs with the browser and draws the conversation sidebar before this page runs.
    session = ConversationSession(st.session_state)
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
    for position, message in enumerate(st.session_state[CHAT_MESSAGES_STATE_KEY]):
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                # Keyed by thread and position, so an opened 자세히 보기 stays open on reruns.
                asked = st.session_state[CHAT_MESSAGES_STATE_KEY][position - 1] if position else None
                render_assistant_message(message, key=f"{session.current_thread}_{position}",
                                         question=asked["content"] if asked and asked["role"] == "user" else None)
            else:
                st.write(plain_tildes(message["content"]))

    render_profile_suggestion(session)
    if error := st.session_state.pop(CHAT_ERROR_STATE_KEY, None):
        st.error(error)

    messages = st.session_state[CHAT_MESSAGES_STATE_KEY]
    in_flight = interrupted_question(session, messages)
    # Closed while a question is being answered: a question sent then stopped the running answer
    # and left the first one unanswered (tests/test_conversation_page.py, scripts/evaluate_chat_input_lock.py).
    question = st.chat_input(
        "예: 강아지가 계속 구토해요 / 강남구 병원을 알려주세요.",
        disabled=in_flight is not None,
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
    if question and not (decision := rate_limit.check(session.person)).allowed:
        # Over the question limit (src/rate_limit.py): no model call. The emergency rules need none,
        # so a dog in danger still gets the hospital first.
        if notice := detect_urgent_sign(question):
            st.warning(notice)
            render_emergency(find_emergency_hospitals(location))
        st.warning(rate_limit.message(decision))
        question = None
    if question:
        # Record the question as in flight and draw the page again, now with the input closed;
        # that run answers it (below). A rerun from another widget mid-answer resumes it the same way.
        chat_history = conversation_history(session, messages)
        messages.append({"role": "user", "content": question})
        st.session_state[IN_FLIGHT_STATE_KEY] = {
            "question": question, "chat_history": chat_history, "thread": session.current_thread,
        }
        st.rerun()
    if in_flight is None:
        render_hospital_links(st.session_state.get(HOSPITAL_ROWS_STATE_KEY, []))
        if session.pending_values() is not None:
            st.rerun()  # e.g. the storage notice was just shown: save "seen" now, not on the next click
        return
    # Its question is already on screen (drawn from the messages above); answer it now.
    question, chat_history = in_flight["question"], in_flight["chat_history"]
    with st.chat_message("assistant"):
        # The rules, then one Decisions call (~0.3 s) for what they miss (src/tools/urgency.py).
        urgent_notice = find_urgent_notice(question)
        emergency = None
        if urgent_notice:
            # Shown before the answer is generated: in an emergency the hospital comes first.
            st.warning(urgent_notice)
            emergency = find_emergency_hospitals(location)
            render_emergency(emergency)
        try:
            # 답변 문장은 모델이 쓰는 대로 보여 주고, 그 전까지는 지금 단계를 알려 줍니다.
            places_box = st.empty()
            status = st.empty()
            status.caption("⏳ 질문을 확인하고 있습니다…")
            stream_box = st.empty()
            streamed: list[str] = []

            def show_token(text: str) -> None:
                if not streamed:
                    status.empty()
                streamed.append(text)
                stream_box.markdown(plain_tildes("".join(streamed)) + " ▌")

            def show_step(node: str, update: dict) -> None:
                if places := places_first(node, update):
                    places_box.markdown(plain_tildes(places))
                message = None if streamed else progress_message(node, update)
                if message:
                    status.caption(f"⏳ {message}")

            try:
                result = chatbot(
                    question,
                    top_k=top_k,
                    chat_history=chat_history,
                    location=location,
                    pet_profile=session.profiles.get(),
                    on_token=show_token,
                    on_step=show_step,
                    session_id=session.request,
                )
            except Exception as error:
                # The model provider out of quota: show what the search finds, as the API does (#238).
                if streamed or not model_outage.is_quota_error(error):
                    raise
                result = model_outage.search_only_result(question, top_k)
            finally:
                places_box.empty()
                status.empty()
                stream_box.empty()

            assistant_message = {
                "role": "assistant", "content": result["answer"], "route": result["route"],
                "evidence_rows": result.get("evidence_rows", []),
                "safety_notice": result.get("safety_notice") or urgent_notice,
                "abstained": result.get("abstained", False),
                "trace_id": result.get("trace_id"),
                "emergency": emergency,
            }
            position = len(st.session_state[CHAT_MESSAGES_STATE_KEY])
            # Record first: a new conversation gets its thread id here, and the widgets below must
            # carry the key the history loop gives them on the next run. Keyed with the old (None)
            # thread, a button clicked before the save-and-rerun finished was gone by the time the
            # click arrived (seen on the deployed app, where the save takes a few seconds).
            thread = session.record_turn(question, result["answer"], route=result["route"])
            st.session_state[CHAT_MESSAGES_STATE_KEY].append(assistant_message)
            st.session_state.pop(IN_FLIGHT_STATE_KEY, None)
            st.session_state[RENDERED_THREAD_STATE_KEY] = thread
            render_assistant_message(assistant_message, show_notice=False, question=question,
                                     key=f"{thread}_{position}")
            suggest_profile(session, question, result["route"])

            st.session_state[HOSPITAL_ROWS_STATE_KEY] = result.get("hospital_rows", [])
            render_hospital_links(st.session_state[HOSPITAL_ROWS_STATE_KEY])
        except Exception as exc:
            # Only errors end the attempt here; a rerun stops the run with Streamlit's
            # StopException (not an Exception), which leaves the question in flight.
            st.session_state.pop(IN_FLIGHT_STATE_KEY, None)
            st.session_state[CHAT_ERROR_STATE_KEY] = f"실행 중 오류가 발생했습니다: {exc}"
    # Draw again with the input open; the browser bridge at the top of the page also saves this turn then.
    st.rerun()


# st.Page and AppTest run this file as "__main__"; importing it (tests) renders nothing.
if __name__ == "__main__":
    render_page()
