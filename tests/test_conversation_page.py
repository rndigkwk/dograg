"""The app with browser-stored conversations (design doc phase 3), via AppTest.

The browser bridge and the chatbot are replaced by fakes: the bridge reports a
stored snapshot and records what the app asks it to write. Home-page tests run
main.py. AppTest.switch_page runs a page file without main.py when the app uses
st.navigation, so chat-page tests run `chat_app`, which follows main.py's order.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from pages import rag as chat_page
from src import conversation_ui
from src.storage.models import Thread, Turn
from src.storage.snapshot import NOTICE_KEY, THREADS_KEY

MAIN = str(Path(__file__).resolve().parents[1] / "main.py")


def chat_app():
    """main.py's order for the chat page: sync with the browser, sidebar, then the page body."""
    from pages import rag
    from src.conversation_ui import render_conversation_sidebar, sync_conversations

    session = sync_conversations()
    render_conversation_sidebar(session)
    rag.render_page()


class FakeBrowser:
    def __init__(self, threads=(), notice=False, status="ok"):
        self.values = {
            THREADS_KEY: json.dumps([t.model_dump(mode="json") for t in threads], ensure_ascii=False),
            NOTICE_KEY: "1" if notice else "",
        }
        self.status = status
        self.writes = []

    def __call__(self, key, *, request, version, values):
        if values is not None:
            self.writes.append(values)
            self.values.update(values)
        return {"request": request, "status": self.status, "values": dict(self.values)}

    def stored_threads(self):
        return json.loads(self.values[THREADS_KEY] or "[]")


def fake_chatbot(question, **kwargs):
    return {"route": "rag", "answer": f"답변: {question}", "evidence_rows": [], "hospital_rows": [],
            "safety_notice": None, "abstained": False}


class ConversationPageTests(unittest.TestCase):
    def run_app(self, browser, at=None, *, home=False):
        with patch.object(conversation_ui, "sync_local_store", browser), \
                patch.object(chat_page, "chatbot", side_effect=fake_chatbot):
            if at is None:
                at = AppTest.from_file(MAIN, default_timeout=30) if home else AppTest.from_function(chat_app, default_timeout=30)
            return at.run()

    def sidebar_labels(self, at):
        return [button.label for button in at.sidebar.button]

    def test_stored_threads_are_listed_and_open(self):
        stored = Thread(title="예전 설사 상담", turns=[Turn(question="설사해요", answer="수분 보충", route="rag")])
        browser = FakeBrowser(threads=[stored], notice=True)
        at = self.run_app(browser)
        self.assertEqual([e.message for e in at.exception], [])
        self.assertIn("예전 설사 상담", self.sidebar_labels(at))
        self.assertEqual(len(at.sidebar.info), 0)  # notice already seen on this browser
        at.sidebar.button(key=f"thread_{stored.id}").click()
        at = self.run_app(browser, at)
        self.assertEqual([m.markdown[0].value for m in at.chat_message], ["설사해요", "수분 보충"])

    def test_question_is_saved_to_the_browser(self):
        browser = FakeBrowser()
        at = self.run_app(browser)
        self.assertEqual(len(at.sidebar.info), 1)  # first visit: storage notice
        self.assertEqual(browser.values[NOTICE_KEY], "1")  # saved right away, not on the next click
        at.chat_input[0].set_value("강아지가 구토해요")
        at = self.run_app(browser, at)
        self.assertEqual([e.message for e in at.exception], [])
        [thread] = browser.stored_threads()
        self.assertEqual(thread["title"], "강아지가 구토해요")
        self.assertEqual(thread["turns"][0]["answer"], "답변: 강아지가 구토해요")
        self.assertIn("강아지가 구토해요", self.sidebar_labels(at))

    def test_clear_device_removes_everything(self):
        stored = Thread(title="지울 대화", turns=[Turn(question="q", answer="a", route="rag")])
        browser = FakeBrowser(threads=[stored], notice=True)
        at = self.run_app(browser)
        at.sidebar.button(key="clear_device").click()
        at = self.run_app(browser, at)
        self.assertEqual(browser.stored_threads(), [])
        self.assertNotIn("지울 대화", self.sidebar_labels(at))
        self.assertEqual(len(at.sidebar.info), 1)  # cleared device: the storage notice shows again

    def test_blocked_storage_still_answers(self):
        browser = FakeBrowser(status="unavailable")
        at = self.run_app(browser)
        self.assertTrue(any("저장되지 않습니다" in c.value for c in at.sidebar.caption))
        at.chat_input[0].set_value("강아지가 기침해요")
        at = self.run_app(browser, at)
        self.assertEqual([e.message for e in at.exception], [])
        self.assertEqual(browser.writes, [])
        self.assertIn("답변: 강아지가 기침해요", [m.markdown[0].value for m in at.chat_message])

    def test_history_shows_on_the_home_page_and_opens_the_chat(self):
        stored = Thread(title="홈에서 연 대화", turns=[Turn(question="기침해요", answer="진료받으세요", route="rag")])
        browser = FakeBrowser(threads=[stored], notice=True)
        at = self.run_app(browser, home=True)
        self.assertEqual([e.message for e in at.exception], [])
        self.assertIn("홈에서 연 대화", self.sidebar_labels(at))
        at.sidebar.button(key=f"thread_{stored.id}").click()
        at = self.run_app(browser, at)  # st.switch_page to the chat page
        self.assertEqual([m.markdown[0].value for m in at.chat_message], ["기침해요", "진료받으세요"])

    def test_history_comes_before_the_brand_card(self):
        at = self.run_app(FakeBrowser(notice=True), home=True)
        sidebar = [getattr(node, "label", None) or getattr(node, "value", "") for node in at.sidebar]
        first_brand = next(i for i, text in enumerate(sidebar) if "pet-brand" in str(text))
        first_history = next(i for i, text in enumerate(sidebar) if "대화 기록" in str(text))
        self.assertLess(first_history, first_brand)


if __name__ == "__main__":
    unittest.main()
