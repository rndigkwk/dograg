"""A second question typed while the first is being answered: is the first still answered?

    uvx --with playwright python scripts/evaluate_chat_input_lock.py [URL] [--trials 3]

Seen on the deployed app (2026-10-12): during a slow first answer (cold start) a second question
was sent 8 s later. Streamlit stopped the running answer for the new input, and the first question
stayed on screen without an answer. Each trial opens a fresh browser session, asks QUESTIONS[0],
tries to send QUESTIONS[1] after WAIT_S, waits until the page is idle (input enabled, both
questions answered or ANSWER_TIMEOUT_S), sends QUESTIONS[1] then if it could not be sent before,
and records:
- input_disabled: the chat input was disabled while the first answer was running
- sent_during: the second question went in while the first was running
- first_answered / second_answered: each question has an assistant message right after it
- first_answer_s: seconds from sending the first question to its finished answer
--single asks only the first question (its answer time, to compare before and after a change).
Real model calls on the app under test.
"""

from __future__ import annotations

import argparse
import json
import time

CHAT_INPUT = 'textarea[data-testid="stChatInputTextArea"]'
CHAT_MESSAGE = '[data-testid="stChatMessage"]'
QUESTIONS = ("강아지가 기침을 계속해요", "강아지가 설사를 해요")
DONE_MARK = "thumb_up"  # feedback buttons appear once an answer is finished
WAIT_S = 3
ANSWER_TIMEOUT_S = 120


def messages(frame) -> list[str]:
    return [text for text in frame.locator(CHAT_MESSAGE).all_inner_texts()]


def answered(texts: list[str], question: str) -> bool:
    """The user message with this question is followed by a finished assistant message."""
    for index, text in enumerate(texts):
        if text.startswith("face") and question in text:
            following = texts[index + 1] if index + 1 < len(texts) else ""
            return following.startswith("smart_toy") and DONE_MARK in following
    return False


def send(box, question: str) -> bool:
    try:
        box.fill(question, timeout=2000)
        box.press("Enter", timeout=2000)
        return True
    except Exception:  # noqa: BLE001 - a disabled input refuses the text
        return False


def trial(browser, url: str, single: bool = False) -> dict:
    page = browser.new_context().new_page()
    page.goto(f"{url.rstrip('/')}/rag", wait_until="domcontentloaded")
    page.wait_for_selector(CHAT_INPUT, timeout=90_000)
    frame = page.main_frame
    box = frame.locator(CHAT_INPUT)
    send(box, QUESTIONS[0])
    started = time.perf_counter()
    page.wait_for_timeout(WAIT_S * 1000)
    input_disabled = box.is_disabled()
    sent_during = not single and not answered(messages(frame), QUESTIONS[0]) and send(box, QUESTIONS[1])
    first_answer_s = None
    second_sent = sent_during or single
    while time.perf_counter() - started < ANSWER_TIMEOUT_S:
        page.wait_for_timeout(1000)
        texts = messages(frame)
        if first_answer_s is None and answered(texts, QUESTIONS[0]):
            first_answer_s = round(time.perf_counter() - started, 1)
        if not second_sent and first_answer_s is not None and box.is_enabled():
            second_sent = send(box, QUESTIONS[1])
        if single and first_answer_s is not None:
            break
        if second_sent and answered(texts, QUESTIONS[1]) and box.is_enabled():
            break
    texts = messages(frame)
    page.context.close()
    return {"input_disabled": input_disabled, "sent_during": sent_during,
            "first_answered": answered(texts, QUESTIONS[0]), "second_answered": answered(texts, QUESTIONS[1]),
            "first_answer_s": first_answer_s, "messages": len(texts)}


def main() -> int:
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default="http://localhost:8501")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--single", action="store_true", help="only the first question: its answer time")
    args = parser.parse_args()
    rows = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for number in range(args.trials):
            rows.append(trial(browser, args.url, single=args.single))
            print(number + 1, json.dumps(rows[-1], ensure_ascii=False), flush=True)
        browser.close()
    keys = ("input_disabled", "sent_during", "first_answered", "second_answered")
    print(json.dumps({key: f"{sum(row[key] for row in rows)}/{len(rows)}" for key in keys}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
