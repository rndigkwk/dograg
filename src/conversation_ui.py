"""Sidebar for stored conversations and the pet profile, shown on every page.

main.py calls `sync_conversations()` and the sidebar renderers before running the
current page, so the browser bridge runs once per script run on every page and the
conversation list sits right under the page navigation.
"""

from __future__ import annotations

import streamlit as st

from src.conversation_session import LOADING, UNAVAILABLE, ConversationSession
from src.local_store_component import sync_local_store

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
