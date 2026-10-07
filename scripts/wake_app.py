"""Open the deployed app in a headless browser so Streamlit Community Cloud does not put it to
sleep, and wake it if it already sleeps. Run by .github/workflows/keep-alive.yml.

A plain HTTP request is not enough: the platform counts browser sessions, and a sleeping app
only starts after its "Yes, get this app back up!" button is clicked.

    uvx --with playwright python scripts/wake_app.py [URL]   # after `playwright install chromium`
"""

from __future__ import annotations

import argparse
import sys
import time

from playwright.sync_api import sync_playwright

APP_URL = "https://dograg-n4gxibufynkgiuixfrkx2v.streamlit.app"
WAKE_BUTTON = "Yes, get this app back up!"
READY_TEXT = "주요 서비스"  # home page section title, rendered once the app script has run
TIMEOUT_S = 300


def app_ready(page) -> bool:
    """The app renders inside an iframe on *.streamlit.app; check every frame."""
    return any(frame.get_by_text(READY_TEXT).count() for frame in page.frames)


def wake(url: str) -> int:
    started = time.perf_counter()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded")
        state = "awake"
        while time.perf_counter() - started < TIMEOUT_S:
            button = page.get_by_role("button", name=WAKE_BUTTON)
            if button.count():
                state = "woken from sleep"
                button.click()
            if app_ready(page):
                print(f"{state}: app ready after {time.perf_counter() - started:.0f}s")
                browser.close()
                return 0
            page.wait_for_timeout(3000)
        page.screenshot(path="wake_app_failure.png", full_page=True)
        browser.close()
    print(f"app not ready after {TIMEOUT_S}s (screenshot: wake_app_failure.png)")
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default=APP_URL)
    sys.exit(wake(parser.parse_args().url))
