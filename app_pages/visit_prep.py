"""Visit-prep report page: runs the multi-agent team (team/) on one consultation.

Limits keep the deployed app safe: a run makes 10-20 model calls and takes one to two
minutes, so each browser session gets MAX_RUNS_PER_SESSION runs and the server runs one
team at a time. Files go to a temporary folder that is deleted after the run; the report
stays only in this session, like the chat (the server keeps no consultation text).
"""

from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitAPIException

from src import rate_limit, settings, tracing, visit_prep_runs
from src.conversation_session import ConversationSession
from src.conversation_ui import CHAT_MESSAGES_STATE_KEY
from src.health_safety import detect_urgent_sign
from src.tools.profile import profile_summary
from src.ui import apply_app_theme, plain_tildes, render_page_header
from src.visit_prep_runs import MAX_CONSULTATION_CHARS, PAUSED_RUN_TTL_SECONDS  # noqa: F401

MAX_RUNS_PER_SESSION = 2
RUNS_STATE_KEY = "visit_prep_runs"
# The consultation box's widget key. The chat page sets it to an answer's question before
# switching here ("이 상담으로 방문 준비 보고서 만들기").
CONSULTATION_KEY = "visit_prep_consultation"
RESULT_STATE_KEY = "visit_prep_result"
# A run paused at ask_guardian: {"thread_id", "questions", "consultation", "region", "profile", "steps", "seconds"}
PENDING_STATE_KEY = "visit_prep_pending"
# A paused run whose questions are not answered within this time is deleted from the server
# (the guardian closed the tab, or went away); answering after that asks for a new run.
EXPIRED_NOTICE = "질문을 받은 지 30분이 지나 답변 대기가 끝났습니다. 남은 횟수는 그대로이니 다시 만들어 주세요."
ANSWER_KEY = "visit_prep_answer"


team_lock = visit_prep_runs.team_lock
team_checkpointer = visit_prep_runs.team_checkpointer
paused_runs = visit_prep_runs.paused_runs
forget_paused_run = visit_prep_runs.forget_paused_run
forget_expired_runs = visit_prep_runs.forget_expired_runs
step_line = visit_prep_runs.step_line


def run_team(consultation: str, region: str, profile: str, run_dir: Path, on_step, *,
             thread_id: str, resume: str | None = None):
    from team.main import run  # imported on use: the chat pages do not need the agents

    session = tracing.session_id(ConversationSession(st.session_state).request)
    return run(consultation, region, profile, run_dir=run_dir, on_step=on_step, session=session,
               ask=True, checkpointer=team_checkpointer(), thread_id=thread_id, resume=resume)


def last_question() -> str:
    for message in reversed(st.session_state.get(CHAT_MESSAGES_STATE_KEY, [])):
        if message["role"] == "user":
            return message["content"][:MAX_CONSULTATION_CHARS]
    return ""


def prepare_search() -> None:
    """Load the search resources in this page's own script thread before the team starts
    (src/visit_prep_runs.prepare_search: a cached loader first used in a worker thread failed)."""
    visit_prep_runs.prepare_search()


def generate(consultation: str, region: str, profile: str, pending: dict | None = None,
             answer: str | None = None) -> dict:
    """src/visit_prep_runs.generate with the page's progress box."""
    label = "답변을 더해 보고서를 만드는 중입니다. 1~2분 걸립니다." if pending else "보고서를 만드는 중입니다. 1~2분 걸립니다."
    with st.status(label, expanded=True) as status:
        outcome = visit_prep_runs.generate(
            consultation, region, profile, run_team=run_team, prepare=prepare_search,
            on_line=lambda line: status.write(f"✓ {line}"), pending=pending, answer=answer)
        if outcome["paused"]:
            status.update(label="보고서에 필요한 내용을 몇 가지 여쭤볼게요", state="complete", expanded=False)
        else:
            status.update(label="보고서를 만들었습니다" if outcome["passed"] else outcome["status"],
                          state="complete" if outcome["passed"] else "error", expanded=False)
    return outcome


def render_urgent_notice() -> None:
    st.error("응급 징후가 의심됩니다. 보고서를 기다리지 말고 지금 가까운 동물병원에 연락하세요.")
    try:
        st.page_link("app_pages/hospital.py", label="시설 찾기에서 가까운 동물병원 찾기", icon=":material/local_hospital:")
    except (StreamlitAPIException, KeyError):  # 내비게이션 밖(AppTest 등)
        st.caption("왼쪽 메뉴의 '시설 찾기'에서 가까운 동물병원을 찾을 수 있습니다.")


UNCHECKED_NOTICES = {
    "필수 조사 실패: 수의사(사람) 확인 필요":
        "비슷한 상담 사례 조사가 오류로 실패해 보고서를 쓰지 않았습니다. 잠시 뒤 다시 시도하거나 병원에 바로 문의하세요.",
    "같은 지적 반복: 수의사(사람) 확인 필요":
        "다시 써도 같은 문장이 근거 없음으로 지적돼, 수의사(사람)의 확인이 필요한 초안으로 표시했습니다.",
    None: "두 번 고쳐도 근거를 확인하지 못한 문장이 있어, 수의사(사람)의 확인이 필요한 초안으로 표시했습니다.",
}


def render_result(result: dict) -> None:
    if result["urgent"]:
        render_urgent_notice()
    if result["passed"]:
        answered = " · 보호자 답변 반영" if result.get("answered") else ""
        st.success(f"검수 통과 · 다시 쓰기 {result['round']}회 · {result['seconds']}초{answered}")
    else:
        st.warning(UNCHECKED_NOTICES.get(result.get("status"), UNCHECKED_NOTICES[None]))
    with st.expander("진행 과정"):
        st.markdown("\n".join(f"- {line}" for line in result["steps"]))
    with st.container(border=True):
        st.markdown(plain_tildes(result["report"]))
    st.download_button("보고서 내려받기 (.md)", result["report"], file_name="visit_report.md",
                       mime="text/markdown", icon=":material/download:")


def start_or_resume(consultation: str, region: str, profile: str, pending: dict | None = None,
                    answer: str | None = None) -> None:
    """Run (or resume) under the server-wide team lock and keep the outcome in the session."""
    if not team_lock().acquire(blocking=False):
        st.info("다른 사용자의 보고서를 만드는 중입니다. 1~2분 뒤에 다시 눌러 주세요.")
        return
    try:
        outcome = generate(consultation, region, profile, pending, answer)
    except Exception as exc:  # noqa: BLE001 - any failure is shown to the guardian instead of a traceback
        st.error(f"보고서를 만들지 못했습니다: {exc}")
        return
    finally:
        team_lock().release()
    if outcome["paused"]:
        st.session_state[PENDING_STATE_KEY] = outcome
        st.session_state.pop(ANSWER_KEY, None)
    else:
        st.session_state.pop(PENDING_STATE_KEY, None)
        st.session_state[RESULT_STATE_KEY] = outcome
    st.rerun()  # redraw the form with the remaining runs; the result stays in the session


def render_questions(pending: dict) -> None:
    """The paused run's questions. Answering or skipping resumes the same run (no new run counted)."""
    from team.core.config import MAX_ANSWER_CHARS

    with st.container(border=True):
        st.markdown("**보고서를 더 정확하게 만들기 위해 몇 가지 여쭤볼게요**")
        st.markdown("\n".join(f"{number}. {question}" for number, question in enumerate(pending["questions"], start=1)))
        with st.form("visit_prep_answer_form"):
            answer = st.text_area("답변 (아는 것만 적어도 됩니다)", key=ANSWER_KEY, max_chars=MAX_ANSWER_CHARS,
                                  placeholder="예: 어제 저녁부터요. 하루에 세 번 정도 했고 밥은 반만 먹었어요.")
            left, right = st.columns(2)
            answered = left.form_submit_button("답하고 보고서 만들기", icon=":material/send:", type="primary")
            skipped = right.form_submit_button("건너뛰고 바로 만들기", icon=":material/skip_next:")
    if answered or skipped:
        start_or_resume(pending["consultation"], pending["region"], pending["profile"], pending,
                        "" if skipped else answer.strip())


def render_page() -> None:
    apply_app_theme()
    render_page_header(
        "병원 방문 준비 보고서",
        eyebrow="멀티에이전트 팀",
        description=(
            "상담 내용을 증상·병원·비용 조사로 나눠 여러 에이전트가 동시에 조사하고, "
            "작성자가 쓴 보고서를 검수자가 문장마다 근거와 대조합니다. 진단이 아니라 수의사에게 보여 줄 정리입니다."
        ),
        accent="조사 · 작성 · 검수를 나눠 맡아요",
    )
    forget_expired_runs()
    if (pending := st.session_state.get(PENDING_STATE_KEY)) and pending["thread_id"] not in paused_runs():
        st.session_state.pop(PENDING_STATE_KEY, None)  # expired: give the run back before the form shows the count
        st.session_state[RUNS_STATE_KEY] = max(st.session_state.get(RUNS_STATE_KEY, 1) - 1, 0)
        st.info(EXPIRED_NOTICE)
    session = ConversationSession(st.session_state)
    runs = st.session_state.get(RUNS_STATE_KEY, 0)
    saved_profile = session.profiles.get()

    with st.form("visit_prep_form"):
        if CONSULTATION_KEY not in st.session_state:
            # Seeded once, not passed as value=: a default that changes between reruns makes
            # Streamlit treat the box as a new widget and drop what was typed.
            st.session_state[CONSULTATION_KEY] = last_question()
        consultation = st.text_area("상담 내용", key=CONSULTATION_KEY, max_chars=MAX_CONSULTATION_CHARS,
                                    placeholder="예: 4살 말티즈가 어제부터 설사를 하고 오늘 아침에 두 번 토했어요. 병원비도 걱정돼요.")
        left, right = st.columns(2)
        region = left.text_input("근처 동물병원을 찾을 지역 (선택)", placeholder="예: 강남구")
        profile = right.text_input("반려견 정보 (선택)", value=profile_summary(saved_profile) if saved_profile else "",
                                   placeholder="예: 말티즈, 4살, 3.2kg")
        submitted = st.form_submit_button("방문 준비 보고서 만들기", icon=":material/description:",
                                          disabled=runs >= MAX_RUNS_PER_SESSION)
    st.caption(f"한 번에 1\\~2분, 모델 호출 10\\~20회가 들어 세션당 {MAX_RUNS_PER_SESSION}번까지 만들 수 있습니다"
               f"(남은 횟수 {max(MAX_RUNS_PER_SESSION - runs, 0)}번).")

    if submitted:
        consultation = consultation.strip()
        if detect_urgent_sign(consultation):
            render_urgent_notice()  # before the run: in an emergency the hospital comes first
        if runs >= MAX_RUNS_PER_SESSION:  # the disabled button already ignores clicks; kept as a guard
            st.info(f"이 세션에서는 보고서를 {MAX_RUNS_PER_SESSION}번까지 만들 수 있습니다.")
        elif not consultation:
            st.info("상담 내용을 적어 주세요.")
        elif not settings.get_openai_api_key():
            st.error("OpenAI API 키가 없어 보고서를 만들 수 없습니다.")
        elif not (decision := rate_limit.check(ConversationSession(st.session_state).person)).allowed:
            st.warning(rate_limit.message(decision))  # a report counts as one question (src/rate_limit.py)
        else:
            if old := st.session_state.pop(PENDING_STATE_KEY, None):
                forget_paused_run(old["thread_id"])  # a new consultation replaces an unanswered one
            st.session_state.pop(RESULT_STATE_KEY, None)
            st.session_state[RUNS_STATE_KEY] = runs + 1
            start_or_resume(consultation, region.strip(), profile.strip())

    if pending := st.session_state.get(PENDING_STATE_KEY):
        render_questions(pending)
    elif result := st.session_state.get(RESULT_STATE_KEY):
        render_result(result)


# st.Page and AppTest run this file as "__main__"; importing it (tests) renders nothing.
if __name__ == "__main__":
    render_page()
