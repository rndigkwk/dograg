"""Check that the deployed app works, not only that it is awake.

    uvx --with playwright python scripts/check_deployed_app.py [URL]   # after `playwright install chromium`

Two deployments are checked (keep-alive.yml): Streamlit Community Cloud (default URL) and
Cloud Run (CLOUD_RUN_URL). Cloud Run scales to zero after idle minutes, so on the scheduled runs
"ready after" is its cold start; each run adds one line per deployment to the job summary.

Wakes the app (scripts/wake_app.py), opens every page and fails when one shows Streamlit's
error box, then asks the chatbot two questions and waits for each answer:
- a date question, answered in code (no search, no model call)
- a health question, answered by the RAG path: search (Supabase on the deployments, docs/adr/0007)
  and the answer model. It passes when the answer shows its evidence section. This also keeps the
  Supabase free project from pausing for inactivity (a few database requests a week are enough);
  the workflow's database job then checks that the search really reached Supabase. Run by .github/workflows/keep-alive.yml every 8 hours and a few
minutes after each push to main.

With --expect-commit (the workflow passes the commit it runs for), the footer's data-commit must be
that commit: Streamlit Cloud twice kept serving the code before a merge until it was rebooted
(2026-10-13), and both questions above still pass on old code. The check reloads for a while first,
because a redeploy can still be on its way.

Why: on 2026-10-09 the app was redeployed without a reboot; the chat page showed an
ImportError (new app_pages/rag.py, old src/chat_graph.py still in memory) and the wake-up
visit, which only waited for the home page, reported success.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

CLOUD_RUN_URL = "https://ragdog-892238791473.asia-northeast3.run.app"
# The frozen Streamlit backup (branch streamlit-backup, since 2026-10-15); checked by hand only.
STREAMLIT_BACKUP_URL = "https://dograg-hsckizrbd7fddwtv8mt7cs.streamlit.app"
CHECK_AGENT = "RagDogCheck"  # added to the browser's user agent; same as src/data_gaps.CHECK_AGENT
CLOUD_RUN_URL = "https://ragdog-892238791473.asia-northeast3.run.app"
PAGES = ("", "data", "rag", "hospital", "visit_prep")
# Streamlit's uncaught-exception box, and the text it shows when the message is redacted.
ERROR_SELECTOR = '[data-testid="stException"]'
ERROR_TEXTS = ("This app has encountered an error", "Traceback:")
CHAT_INPUT = 'textarea[data-testid="stChatInputTextArea"]'
CHAT_MESSAGE = '[data-testid="stChatMessage"]'
FOOTER = ".app-footer"
COMMIT_WAIT_S = 600  # a redeploy can still be running when the check starts
DATE_QUESTION = "오늘 날짜 알려줘"
DATE_ANSWER = "오늘은"  # src/tools/router.py current_date_answer
HEALTH_QUESTION = "강아지가 어제부터 노란 토를 해요"
HEALTH_ANSWER = "검색 근거"  # the evidence section under a health answer (app_pages/rag.py)
PAGE_TIMEOUT_S = 90
SETTLE_S = 20
ANSWER_TIMEOUT_S = 60
HEALTH_ANSWER_TIMEOUT_S = 120


def error_in(texts: list[str], error_boxes: int = 0) -> str | None:
    """The first error shown on a page, from its frames' text and the count of error boxes."""
    if error_boxes:
        return "Streamlit error box"
    for text in texts:
        for marker in ERROR_TEXTS:
            if marker in text:
                start = text.find(marker)
                return " ".join(text[start:start + 300].split())
    return None


def _frames(page):
    return [frame for frame in page.frames if not frame.is_detached()]


def _page_error(page) -> str | None:
    texts, boxes = [], 0
    for frame in _frames(page):
        try:
            boxes += frame.locator(ERROR_SELECTOR).count()
            texts.append(frame.locator("body").inner_text(timeout=2000))
        except Exception:  # noqa: BLE001 - a frame can go away while Streamlit reruns
            continue
    return error_in(texts, boxes)


def _app_frame(page, selector: str, timeout_s: float):
    """The frame that renders the app (an iframe on *.streamlit.app) once `selector` is in it."""
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        for frame in _frames(page):
            try:
                if frame.locator(selector).count():
                    return frame
            except Exception:  # noqa: BLE001
                continue
        if _page_error(page):
            return None
        page.wait_for_timeout(1000)
    return None


def check_pages(page, url: str) -> list[str]:
    problems = []
    for path in PAGES:
        page.goto(f"{url.rstrip('/')}/{path}", wait_until="domcontentloaded")
        # Every page draws the sidebar navigation; wait for it, then for the page body to settle.
        frame = _app_frame(page, '[data-testid="stSidebarNav"]', PAGE_TIMEOUT_S)
        # The navigation comes first; a page that fails while importing shows its error box
        # a few seconds later (10 s for a fresh import of the chat graph, measured locally).
        error = None
        for _ in range(SETTLE_S):
            if error := _page_error(page):
                break
            page.wait_for_timeout(1000)
        if error:
            problems.append(f"/{path}: {error}")
        elif frame is None:
            problems.append(f"/{path}: did not render in {PAGE_TIMEOUT_S}s")
        else:
            print(f"/{path}: ok")
    return problems


def ask(page, frame, question: str, expected: str, timeout_s: float) -> tuple[str | None, float | None]:
    """Send one question; (problem or None, seconds until an answer containing `expected`)."""
    before = frame.locator(CHAT_MESSAGE).count()
    box = frame.locator(CHAT_INPUT)
    box.fill(question)
    box.press("Enter")
    started = time.perf_counter()
    while time.perf_counter() - started < timeout_s:
        page.wait_for_timeout(1000)
        messages = frame.locator(CHAT_MESSAGE)
        if messages.count() >= before + 2 and expected in messages.nth(messages.count() - 1).inner_text():
            seconds = time.perf_counter() - started
            print(f"chat ({question}): answered in {seconds:.1f}s")
            return None, seconds
        if error := _page_error(page):
            return error, None
    return f"no answer to {question!r} in {timeout_s:.0f}s", None


def check_chat(page, url: str) -> tuple[list[str], float | None, float | None]:
    """(problems, seconds to the date answer, seconds to the health answer)."""
    page.goto(f"{url.rstrip('/')}/rag", wait_until="domcontentloaded")
    frame = _app_frame(page, CHAT_INPUT, PAGE_TIMEOUT_S)
    if frame is None:
        return [_page_error(page) or f"chat input missing after {PAGE_TIMEOUT_S}s"], None, None
    problems = []
    date_problem, date_s = ask(page, frame, DATE_QUESTION, DATE_ANSWER, ANSWER_TIMEOUT_S)
    if date_problem:
        problems.append(date_problem)
    # The input is locked while an answer is written (app_pages/rag.py); wait until it opens again.
    frame.locator(f"{CHAT_INPUT}:not([disabled])").wait_for(timeout=ANSWER_TIMEOUT_S * 1000)
    health_problem, health_s = ask(page, frame, HEALTH_QUESTION, HEALTH_ANSWER, HEALTH_ANSWER_TIMEOUT_S)
    if health_problem:
        problems.append(health_problem)
    return problems, date_s, health_s


def same_commit(deployed: str | None, expected: str) -> bool:
    """Short and full hashes of one commit match (Streamlit Cloud reports 7 characters)."""
    if not deployed or not expected:
        return False
    length = min(len(deployed), len(expected))
    return length >= 7 and deployed[:length] == expected[:length]


def deployed_commit(page) -> str | None:
    frame = _app_frame(page, FOOTER, PAGE_TIMEOUT_S)
    return None if frame is None else frame.locator(FOOTER).first.get_attribute("data-commit")


def check_commit(page, url: str, expected: str) -> tuple[str | None, str | None]:
    """(problem or None, the deployed commit). Reloads until the commit matches or COMMIT_WAIT_S."""
    started = time.perf_counter()
    while True:
        page.goto(url, wait_until="domcontentloaded")
        commit = deployed_commit(page)
        if same_commit(commit, expected):
            print(f"commit: {commit}")
            return None, commit
        if time.perf_counter() - started > COMMIT_WAIT_S:
            hint = " (Streamlit Cloud: reboot the app)" if "streamlit.app" in url else ""
            return f"running {commit or 'unknown'}, not {expected[:7]}{hint}", commit
        print(f"commit: {commit}, waiting for {expected[:7]}", flush=True)
        page.wait_for_timeout(60_000)


def summary_line(url: str, ready_s: float | None, chat_s: float | None, problems: list[str],
                 health_s: float | None = None) -> str:
    """One Markdown table row per deployment for the job summary."""
    shown = (lambda value: "-" if value is None else f"{value:.0f}s")
    return (f"| {url} | {shown(ready_s)} | {shown(chat_s)} | {shown(health_s)} | "
            f"{'ok' if not problems else '; '.join(problems)[:200]} |")


def write_summary(line: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as file:
        file.write("| 배포 | 첫 화면까지 | 날짜 답변 | 건강 답변 | 결과 |\n| --- | ---: | ---: | ---: | --- |\n" + line + "\n")


def check(url: str, expected_commit: str | None = None) -> int:
    # Imported here so tests can load error_in() without Playwright installed.
    from playwright.sync_api import sync_playwright

    import eval_history
    from wake_app import wake

    started = time.perf_counter()
    if wake(url):
        write_summary(summary_line(url, None, None, ["did not become ready"]))
        return 1
    ready_s = time.perf_counter() - started  # Cloud Run at zero instances: its cold start
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        agent = browser.new_page().evaluate("navigator.userAgent")
        # the app leaves the answers to this check out of its data-gap table (src/data_gaps.py)
        page = browser.new_page(user_agent=f"{agent} {CHECK_AGENT}")
        problems, commit = [], None
        if expected_commit:
            commit_problem, commit = check_commit(page, url, expected_commit)
            if commit_problem:
                problems.append(f"commit: {commit_problem}")
        problems += check_pages(page, url)
        chat_problems, chat_s, health_s = check_chat(page, url)
        problems += [f"chat: {problem}" for problem in chat_problems]
        if problems:
            page.screenshot(path="check_app_failure.png", full_page=True)
        elif commit is None:
            commit = deployed_commit(page)  # the chat page has the footer
        browser.close()
    for problem in problems:
        print(f"PROBLEM {problem}")
    write_summary(summary_line(url, ready_s, chat_s, problems, health_s))
    eval_history.record("deploy", "streamlit-backup" if "streamlit.app" in url else "cloud-run", not problems,
                        {"ready_s": ready_s, "date_answer_s": chat_s, "health_answer_s": health_s, "problems": problems},
                        commit=commit)
    if problems and "streamlit.app" in url:
        print("If the code on main is fine, the app may need a reboot (Manage app -> Reboot app).")
    return 1 if problems else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default=CLOUD_RUN_URL)
    parser.add_argument("--expect-commit", help="the commit the deployment should run (the workflow's GITHUB_SHA)")
    args = parser.parse_args()
    sys.exit(check(args.url, args.expect_commit))
