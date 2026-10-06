"""Sidebar for stored conversations and the pet profile, shown on every page.

main.py calls `sync_conversations()` and the sidebar renderers before running the
current page, so the browser bridge runs once per script run on every page and the
conversation list sits right under the page navigation.
"""

from __future__ import annotations

from datetime import date

import streamlit as st
from pydantic import ValidationError

from src.conversation_session import LOADING, UNAVAILABLE, ConversationSession
from src.local_store_component import sync_local_store
from src.storage.models import PetProfile
from src.tools.profile import profile_summary, today

CHAT_MESSAGES_STATE_KEY = "fixing_messages"
HOSPITAL_ROWS_STATE_KEY = "hospital_rows"
RENDERED_THREAD_STATE_KEY = "rendered_thread"
STORAGE_NOTICE = (
    "대화와 반려견 정보는 이 브라우저에만 저장되며 서버에는 남지 않습니다. "
    "공용 PC라면 사용 후 '이 기기의 기록 모두 지우기'로 지워 주세요."
)


def open_conversation(session: ConversationSession) -> None:
    """Show the open thread's stored turns (text only; evidence is not stored)."""
    st.session_state[CHAT_MESSAGES_STATE_KEY] = session.messages()
    st.session_state[RENDERED_THREAD_STATE_KEY] = session.current_thread
    st.session_state[HOSPITAL_ROWS_STATE_KEY] = []


def sync_conversations() -> ConversationSession:
    """Load the browser's stored conversations once, and write back what changed since."""
    session = ConversationSession(st.session_state)
    values = session.pending_values()
    with st.sidebar:  # the bridge is invisible; keeping it in the sidebar avoids a gap on the page
        report = sync_local_store(
            "rag_local_store", request=session.request, version=session.snapshot.version, values=values
        )
    if values is not None:
        session.mark_sent()
    if session.apply_report(report) and session.pending_values() is not None:
        st.rerun()  # write the merged snapshot back right away
    if st.session_state.get(RENDERED_THREAD_STATE_KEY) != session.current_thread:
        open_conversation(session)
    return session


def _go_to_chat(chat_page) -> None:
    if chat_page is None:
        st.rerun()
    st.switch_page(chat_page)


def render_conversation_sidebar(session: ConversationSession, chat_page=None) -> None:
    """Thread list and controls. Choosing a thread elsewhere opens the chat page on it."""
    with st.sidebar:
        st.markdown("#### 대화 기록")
        if session.status == UNAVAILABLE:
            st.caption("이 브라우저에서는 대화가 저장되지 않습니다.")
        elif session.status == LOADING:
            st.caption("저장된 대화를 불러오는 중입니다…")
        if session.take_notice():
            st.info(STORAGE_NOTICE)
        if st.button("새 대화", key="thread_new", icon=":material/add:", width="stretch"):
            session.open_thread(None)
            open_conversation(session)
            _go_to_chat(chat_page)
        current = session.current_thread
        for summary in session.threads():
            if st.button(
                summary.title,
                key=f"thread_{summary.id}",
                type="primary" if summary.id == current else "secondary",
                width="stretch",
            ):
                session.open_thread(summary.id)
                open_conversation(session)
                _go_to_chat(chat_page)
        if current is not None and st.button("이 대화 삭제", key="thread_delete", icon=":material/delete:", width="stretch"):
            session.delete_current()
            open_conversation(session)
            st.rerun()
        with st.popover("이 기기의 기록 모두 지우기", width="stretch"):
            st.caption("이 브라우저에 저장된 대화와 반려견 정보를 모두 지웁니다. 되돌릴 수 없습니다.")
            if st.button("모두 지우기", key="clear_device", type="primary"):
                session.clear_device()
                open_conversation(session)
                st.rerun()


def _split_items(text: str) -> list[str]:
    return [item.strip() for item in (text or "").replace("\n", ",").split(",") if item.strip()]


NEUTERED_OPTIONS = ("모름", "함", "안 함")


def render_profile_sidebar(session: ConversationSession) -> None:
    """Long-term memory about the dog (design doc phase 4), kept in this browser only."""
    profile = session.profiles.get()
    current = profile or PetProfile()
    with st.sidebar, st.expander("우리 아이 정보", icon=":material/pets:"):
        st.caption(profile_summary(profile) if profile else "입력하면 질문에 나이가 없어도 나이에 맞는 상담 자료를 먼저 찾습니다.")
        with st.form("pet_profile_form", border=False):
            name = st.text_input("이름", value=current.name or "", max_chars=30)
            breed = st.text_input("견종", value=current.breed or "", max_chars=30)
            birth = st.date_input(
                "태어난 달 (대략)", value=current.birth_month, min_value=date(1990, 1, 1), max_value=today(),
            )
            weight = st.number_input("체중 (kg, 모르면 0)", min_value=0.0, max_value=149.9, value=float(current.weight_kg or 0.0), step=0.1)
            neutered = st.radio(
                "중성화", NEUTERED_OPTIONS, horizontal=True,
                index=0 if current.neutered is None else (1 if current.neutered else 2),
            )
            conditions = st.text_input("지병 (쉼표로 구분)", value=", ".join(current.conditions))
            medications = st.text_input("복용약 (쉼표로 구분)", value=", ".join(current.medications))
            allergies = st.text_input("알레르기 (쉼표로 구분)", value=", ".join(current.allergies))
            if st.form_submit_button("저장", type="primary"):
                try:
                    updated = PetProfile(
                        name=name or None, breed=breed or None, birth_month=birth, weight_kg=weight or None,
                        neutered=None if neutered == "모름" else neutered == "함",
                        conditions=_split_items(conditions), medications=_split_items(medications),
                        allergies=_split_items(allergies),
                    )
                except ValidationError:
                    st.error("입력값을 확인해 주세요.")
                else:
                    session.profiles.save(updated)
                    st.rerun()
        if profile is not None and st.button("정보 지우기", key="profile_clear"):
            session.profiles.clear()
            st.rerun()
