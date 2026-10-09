"""Check that the deployed app works, not only that it is awake.

    uvx --with playwright python scripts/check_deployed_app.py [URL]   # after `playwright install chromium`

Wakes the app (scripts/wake_app.py), opens every page and fails when one shows Streamlit's
error box, then asks the chatbot a date question (answered in code: no model call, no cost)
and waits for the answer. Run by .github/workflows/keep-alive.yml every 8 hours and a few
minutes after each push to main.

Why: on 2026-10-09 the app was redeployed without a reboot; the chat page showed an
ImportError (new app_pages/rag.py, old src/chat_graph.py still in memory) and the wake-up
visit, which only waited for the home page, reported success.
"""

from __future__ import annotations

import argparse
import sys
import time

PAGES = ("", "data", "rag", "hospital", "visit_prep")
# Streamlit's uncaught-exception box, and the text it shows when the message is redacted.
ERROR_SELECTOR = '[data-testid="stException"]'
ERROR_TEXTS = ("This app has encountered an error", "Traceback:")
CHAT_INPUT = 'textarea[data-testid="stChatInputTextArea"]'
CHAT_MESSAGE = '[data-testid="stChatMessage"]'
DATE_QUESTION = "오늘 날짜 알려줘"
DATE_ANSWER = "오늘은"  # src/tools/router.py current_date_answer
PAGE_TIMEOUT_S = 90
SETTLE_S = 20
ANSWER_TIMEOUT_S = 60


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


def check_chat(page, url: str) -> str | None:
    page.goto(f"{url.rstrip('/')}/rag", wait_until="domcontentloaded")
    frame = _app_frame(page, CHAT_INPUT, PAGE_TIMEOUT_S)
    if frame is None:
        return _page_error(page) or f"chat input missing after {PAGE_TIMEOUT_S}s"
    before = frame.locator(CHAT_MESSAGE).count()
    box = frame.locator(CHAT_INPUT)
    box.fill(DATE_QUESTION)
    box.press("Enter")
    started = time.perf_counter()
    while time.perf_counter() - started < ANSWER_TIMEOUT_S:
        page.wait_for_timeout(1000)
        messages = frame.locator(CHAT_MESSAGE)
        if messages.count() >= before + 2 and DATE_ANSWER in messages.nth(messages.count() - 1).inner_text():
            print(f"chat: answered in {time.perf_counter() - started:.1f}s")
            return None
        if error := _page_error(page):
            return error
    return f"no chat answer in {ANSWER_TIMEOUT_S}s"


def check(url: str) -> int:
    # Imported here so tests can load error_in() without Playwright installed.
    from playwright.sync_api import sync_playwright

    from wake_app import wake

    if wake(url):
        return 1
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        problems = check_pages(page, url)
        if chat_problem := check_chat(page, url):
            problems.append(f"chat: {chat_problem}")
        if problems:
            page.screenshot(path="check_app_failure.png", full_page=True)
        browser.close()
    for problem in problems:
        print(f"PROBLEM {problem}")
    if problems:
        print("If the code on main is fine, the app may need a reboot (Manage app -> Reboot app).")
    return 1 if problems else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default="https://dograg-n4gxibufynkgiuixfrkx2v.streamlit.app")
    sys.exit(check(parser.parse_args().url))
