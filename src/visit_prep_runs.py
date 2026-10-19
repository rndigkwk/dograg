"""Visit-prep report runs, shared by the page (app_pages/visit_prep.py) and the API (api/visit_prep.py).

A run makes 10-20 model calls and takes one to two minutes, so the server runs one team at a
time (team_lock). A run may stop before planning to ask the guardian (day51 interrupt); it then
waits (team_checkpointer, keyed by thread id) until answered, and is deleted when it finishes, is
replaced, or nobody answers within PAUSED_RUN_TTL_SECONDS. Since 2026-10-16 the wait is in Supabase
when the database is configured (src/visit_prep_store.py, deleted after 30 minutes), else in memory.
Moved from the page unchanged (2026-10-15, ADR-0008).
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

from src import resources
from src.health_safety import detect_urgent_sign, todays_text

MAX_CONSULTATION_CHARS = 500
PAUSED_RUN_TTL_SECONDS = 30 * 60
PREPARED = "검색 자료를 준비했습니다"
STEP_LABELS = {
    "clarify": None,  # shown as the questions themselves
    "ask_guardian": "보호자 답변을 상담 내용에 더했습니다",
    "planner": "상담을 조사 작업으로 나눴습니다",
    "researcher": "조사 하나를 마쳤습니다",
    "supervisor": "다음 담당을 정했습니다",
    "writer": "보고서를 썼습니다",
    "reviewer": "문장마다 근거를 대조했습니다",
    "publisher": "결과를 정리했습니다",
}
_lock = threading.Lock()
_paused: dict[str, float] = {}


def team_lock() -> threading.Lock:
    """One team run at a time on the server: each run holds several model calls in flight."""
    return _lock


def team_checkpointer():
    """Where a run paused for the guardian's answer waits, keyed by thread_id: Supabase when the
    database is configured (src/visit_prep_store.py), else this server's memory."""
    from src import visit_prep_store

    return visit_prep_store.store().checkpointer()


def paused_runs() -> dict[str, float]:
    """{thread_id: time it paused} for every run waiting on a guardian's answer, server-wide."""
    return _paused


def remember_paused_run(thread_id: str) -> None:
    paused_runs()[thread_id] = time.time()


def forget_paused_run(thread_id: str) -> None:
    team_checkpointer().delete_thread(thread_id)
    paused_runs().pop(thread_id, None)


def forget_expired_runs(now: float | None = None, *, delete: bool = True) -> list[str]:
    """Delete paused runs nobody answered within PAUSED_RUN_TTL_SECONDS; returns their ids.

    delete=False only drops them from this server's list: the API leaves the checkpoints to
    src/visit_prep_store.py, because another instance may be resuming a run paused here."""
    now = time.time() if now is None else now
    expired = [thread_id for thread_id, paused_at in list(paused_runs().items())
               if now - paused_at > PAUSED_RUN_TTL_SECONDS]
    for thread_id in expired:
        if delete:
            forget_paused_run(thread_id)
        else:
            paused_runs().pop(thread_id, None)
    return expired


def step_line(node: str, update: dict) -> str | None:
    label = STEP_LABELS.get(node)
    if node == "planner" and update.get("plan"):
        kinds = {"health": "증상", "place": "병원", "cost": "비용"}
        tasks = ", ".join(kinds.get(task["kind"], task["kind"]) for task in update["plan"])
        return f"{label}: {tasks}"
    if node == "researcher" and update.get("failures"):
        kinds = {"health": "증상", "place": "병원", "cost": "비용"}
        failed = ", ".join(kinds.get(item["kind"], item["kind"]) for item in update["failures"].values())
        return f"조사 하나가 오류로 실패했습니다: {failed} (나머지 조사로 계속합니다)"
    if node == "reviewer" and update.get("review"):
        review = update["review"]
        verdict = "통과" if review.get("passed") else f"반려(근거 없는 문장 {len(review.get('unsupported', []))}개)"
        return f"{label}: {verdict}"
    return label


def prepare_search() -> None:
    """Load the search resources in this page's own script thread before the team starts.

    Researchers run in worker threads with no Streamlit session. A cached loader with a
    spinner (the BM25 index) loading there for the first time raises NoSessionContext, and
    right after a reboot that failed every health researcher on the deployed app (run held)."""
    resources.load_vector_db()
    resources.load_health_bm25_index()
    resources.load_health_answer_table()
    resources.load_report_vector_db()
    resources.load_report_bm25_index()


RUN_DIR_PREFIX = "ragdog-visit-"
STALE_RUN_DIR_SECONDS = 60 * 60  # src/visit_prep_store.py drops a crashed run's checkpoints after an hour


def run_folder(thread_id: str) -> Path:
    """A run's working folder (the draft report the reviewer reads), kept until the run ends, so a
    failed run continued on this server finds its draft. On another instance it is missing and the
    writer drafts again (the reviewer sends a missing report back to it)."""
    folder = Path(tempfile.gettempdir()) / f"{RUN_DIR_PREFIX}{thread_id}"
    folder.mkdir(exist_ok=True)
    return folder


def sweep_run_folders(now: float | None = None) -> None:
    """Remove the folders of runs that failed and were never continued."""
    now = time.time() if now is None else now
    for folder in Path(tempfile.gettempdir()).glob(f"{RUN_DIR_PREFIX}*"):
        try:
            if now - folder.stat().st_mtime > STALE_RUN_DIR_SECONDS:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            continue


def generate(consultation: str, region: str, profile: str, *, run_team, prepare=prepare_search, on_line=None,
             pending: dict | None = None, answer: str | None = None, retry: bool = False,
             thread_id: str | None = None) -> dict:
    """Run the team in a temporary folder and keep only the report text and its status.

    run_team(consultation, region, profile, run_dir, on_step, thread_id=, resume=) runs the graph
    (the page and the API pass their own, with their session). The first call may return
    {"paused": True, ...} with the questions; the second passes that pending run and the answer
    ("" to skip), and the same thread resumes from the question. on_line gets each progress line.
    retry=True with a failed run's record (pending) goes on from its last checkpoint. thread_id names
    a new run (the API keeps it to offer the retry); one is made when not given."""
    from team.core import config
    from team.core.citations import readable_report
    from team.graph.nodes import run_status as status_of

    started = time.perf_counter()
    thread_id = pending["thread_id"] if pending else (thread_id or uuid.uuid4().hex)
    sweep_run_folders()
    prepare()
    steps = list(pending["steps"]) if pending else [PREPARED]
    if not pending and on_line:
        on_line(PREPARED)
    run_dir = run_folder(thread_id)  # kept if the run fails (run_folder), removed when it ends

    def show(node: str, update: dict) -> None:
        line = step_line(node, update)
        if line:
            steps.append(line)
            if on_line:
                on_line(line)

    if retry:
        state = run_team(consultation, region, profile, run_dir, show, thread_id=thread_id, resume=None, retry=True)
    else:
        state = run_team(consultation, region, profile, run_dir, show, thread_id=thread_id,
                         resume=answer if pending else None)
    if state["paused"]:
        remember_paused_run(thread_id)
        return {"paused": True, "thread_id": thread_id, "questions": state["questions"],
                "consultation": consultation, "region": region, "profile": profile, "steps": steps,
                "seconds": round(time.perf_counter() - started)}
    # The saved report cites evidence ids for the reviewer; people get ①② and a source list.
    report = readable_report((run_dir / config.REPORT_FILE).read_text(encoding="utf-8"),
                             state.get("findings") or {})
    shutil.rmtree(run_dir, ignore_errors=True)
    forget_paused_run(thread_id)
    run_status = status_of(state)
    seconds = round(time.perf_counter() - started) + (pending["seconds"] if pending else 0)
    return {"paused": False, "report": report, "passed": run_status == config.PASSED, "status": run_status,
            "round": state["round"], "steps": steps, "urgent": bool(detect_urgent_sign(todays_text(consultation))),
            "seconds": seconds, "answered": bool(pending and answer and not retry)}
