"""The app with browser-stored conversations (design doc phase 3), via AppTest.

The browser bridge and the chatbot are replaced by fakes: the bridge reports a
stored snapshot and records what the app asks it to write. Home-page tests run
main.py. AppTest.switch_page runs a page file without main.py when the app uses
st.navigation, so chat-page tests run `chat_app`, which follows main.py's order.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

from app_pages import rag as chat_page
from src import conversation_ui
from src.storage.models import PetProfile, Thread, Turn
from src.storage.snapshot import NOTICE_KEY, PROFILE_KEY, THREADS_KEY

MAIN = str(Path(__file__).resolve().parents[1] / "main.py")


def chat_app():
    """main.py's order for the chat page: sync with the browser, sidebar, then the page body."""
    from app_pages import rag
    from src.conversation_ui import (
        render_conversation_sidebar,
        render_profile_sidebar,
        sync_conversations,
    )

    session = sync_conversations()
    render_conversation_sidebar(session)
    render_profile_sidebar(session)
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
            "safety_notice": None, "abstained": False, "trace_id": f"trace-{len(question)}"}


class ConversationPageTests(unittest.TestCase):
    def run_app(self, browser, at=None, *, home=False, detected=None):
        self.detect = Mock(return_value=detected)
        with patch.object(conversation_ui, "sync_local_store", browser), \
                patch.object(chat_page, "chatbot", side_effect=fake_chatbot), \
                patch.object(chat_page, "detect_profile", self.detect):
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

    def test_health_answers_offer_a_visit_report_for_their_own_question(self):
        from app_pages.visit_prep import CONSULTATION_KEY

        browser = FakeBrowser()
        at = self.run_app(browser)
        for question in ("강아지가 구토해요", "강아지가 밤새 기침해요"):  # lengths differ: the fake trace id uses it
            at.chat_input[0].set_value(question)
            at = self.run_app(browser, at)
        buttons = [button for button in at.button if button.label == "이 상담으로 방문 준비 보고서 만들기"]
        self.assertEqual(len(buttons), 2)  # one under each health answer
        buttons[0].click()  # the first answer's button, not the latest question
        at = self.run_app(browser, at)
        self.assertEqual(at.session_state[CONSULTATION_KEY], "강아지가 구토해요")

    def test_first_answer_button_keeps_its_key_after_the_save_rerun(self):
        # Without the save-and-rerun, the run that answers is what the browser shows until the
        # next run. Its button must have the key the next run gives it, or a click is lost.
        from src.conversation_session import ConversationSession

        browser = FakeBrowser()
        at = self.run_app(browser)
        at.chat_input[0].set_value("강아지가 구토해요")
        with patch.object(ConversationSession, "pending_values", return_value=None):
            at = self.run_app(browser, at)
        answering = [b.key for b in at.button if b.label == "이 상담으로 방문 준비 보고서 만들기"]
        at = self.run_app(browser, at)
        later = [b.key for b in at.button if b.label == "이 상담으로 방문 준비 보고서 만들기"]
        self.assertEqual(len(answering), 1)
        self.assertNotIn("None", answering[0])
        self.assertEqual(answering, later)

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

    def test_urgent_question_shows_nearby_hospitals_before_the_answer(self):
        hospital = {"id": "hospital-1", "name": "강남동물병원", "road_address": "서울특별시 강남구 1",
                    "phone": "02-111-1111", "distance_km": 0.4}
        night = {**hospital, "id": "hospital-2", "name": "24시 동물의료센터", "distance_km": 2.1}
        browser = FakeBrowser(notice=True)
        at = self.run_app(browser)
        with patch.object(chat_page, "render_location_control", return_value=((37.5, 127.0), None)), \
                patch.object(chat_page, "emergency_hospitals", return_value={"nearest": [hospital], "night": [night]}) as lookup:
            at.chat_input[0].set_value("강아지가 경련을 해요")
            at = self.run_app(browser, at)
        lookup.assert_called_once_with((37.5, 127.0))
        text = " ".join(m.value for m in at.markdown)
        self.assertIn("강남동물병원", text)
        self.assertIn("tel:021111111", text)
        self.assertIn("24시 동물의료센터", text)
        self.assertEqual([e.message for e in at.exception], [])

    def test_urgent_question_without_location_points_to_the_place_page(self):
        browser = FakeBrowser(notice=True)
        at = self.run_app(browser)
        with patch.object(chat_page, "emergency_hospitals") as lookup:
            at.chat_input[0].set_value("강아지가 경련을 해요")
            at = self.run_app(browser, at)
        lookup.assert_not_called()
        self.assertTrue(any("현재 위치 사용" in c.value for c in at.caption))

    def test_answer_feedback_becomes_a_trace_score(self):
        browser = FakeBrowser(notice=True)
        at = self.run_app(browser)
        at.chat_input[0].set_value("기침해요")
        at = self.run_app(browser, at)
        self.assertEqual(len(at.feedback), 1)
        with patch.object(chat_page, "record_feedback") as record:
            at.feedback[0].set_value(1)
            at = self.run_app(browser, at)
        record.assert_called_once_with("trace-4", helpful=True)
        self.assertEqual([e.message for e in at.exception], [])

    def test_no_feedback_without_a_trace(self):
        browser = FakeBrowser(notice=True)
        at = self.run_app(browser)
        with patch.object(chat_page, "chatbot", side_effect=lambda q, **k: {**fake_chatbot(q), "trace_id": None}):
            at.chat_input[0].set_value("기침해요")
            at = at.run()
        self.assertEqual(len(at.feedback), 0)

    def interrupt(self, at, question, thread=None):
        """State a rerun leaves when it stops the run that was answering `question`."""
        at.session_state[conversation_ui.CHAT_MESSAGES_STATE_KEY] = [{"role": "user", "content": question}]
        at.session_state[chat_page.IN_FLIGHT_STATE_KEY] = {"question": question, "chat_history": [], "thread": thread}

    def test_an_interrupted_answer_is_finished_on_the_next_run(self):
        browser = FakeBrowser(notice=True)
        at = self.run_app(browser)
        self.interrupt(at, "강아지가 이틀째 설사를 해요")
        at = self.run_app(browser, at)  # e.g. the location result arrived mid-answer
        self.assertEqual([m.markdown[0].value for m in at.chat_message],
                         ["강아지가 이틀째 설사를 해요", "답변: 강아지가 이틀째 설사를 해요"])
        self.assertNotIn(chat_page.IN_FLIGHT_STATE_KEY, at.session_state)
        [thread] = browser.stored_threads()
        self.assertEqual(thread["turns"][0]["answer"], "답변: 강아지가 이틀째 설사를 해요")
        at = self.run_app(browser, at)
        self.assertEqual(len(at.chat_message), 2)  # answered once, not again on later runs

    def test_an_interrupted_answer_is_dropped_after_switching_conversations(self):
        stored = Thread(title="다른 대화", turns=[Turn(question="q", answer="a", route="rag")])
        browser = FakeBrowser(threads=[stored], notice=True)
        at = self.run_app(browser)
        self.interrupt(at, "기침해요", thread="some-other-thread")
        with patch.object(chat_page, "chatbot") as chatbot:
            at = self.run_app(browser, at)
        chatbot.assert_not_called()
        self.assertNotIn(chat_page.IN_FLIGHT_STATE_KEY, at.session_state)

    def test_history_shows_on_the_home_page_and_opens_the_chat(self):
        stored = Thread(title="홈에서 연 대화", turns=[Turn(question="기침해요", answer="진료받으세요", route="rag")])
        browser = FakeBrowser(threads=[stored], notice=True)
        at = self.run_app(browser, home=True)
        self.assertEqual([e.message for e in at.exception], [])
        self.assertIn("홈에서 연 대화", self.sidebar_labels(at))
        at.sidebar.button(key=f"thread_{stored.id}").click()
        at = self.run_app(browser, at)  # st.switch_page to the chat page
        self.assertEqual([m.markdown[0].value for m in at.chat_message], ["기침해요", "진료받으세요"])

    def test_notice_is_saved_on_the_home_page_too(self):
        browser = FakeBrowser()
        at = self.run_app(browser, home=True)
        self.assertEqual([e.message for e in at.exception], [])
        self.assertEqual(len(at.sidebar.info), 1)
        self.assertEqual(browser.values[NOTICE_KEY], "1")

    def test_history_comes_before_the_brand_card(self):
        at = self.run_app(FakeBrowser(notice=True), home=True)
        sidebar = [getattr(node, "label", None) or getattr(node, "value", "") for node in at.sidebar]
        first_brand = next(i for i, text in enumerate(sidebar) if "pet-brand" in str(text))
        first_history = next(i for i, text in enumerate(sidebar) if "대화 기록" in str(text))
        self.assertLess(first_history, first_brand)


    # --- pet profile (design doc phase 4) ---------------------------------------
    def stored_profile(self, browser):
        return json.loads(browser.values.get(PROFILE_KEY) or "{}")

    def test_profile_form_saves_to_the_browser(self):
        browser = FakeBrowser(notice=True)
        at = self.run_app(browser)
        [name] = [w for w in at.sidebar.text_input if w.label == "이름"]
        name.input("초코")
        [conditions] = [w for w in at.sidebar.text_input if w.label.startswith("지병")]
        conditions.input("슬개골 탈구, 피부염")
        [save] = [b for b in at.sidebar.button if b.label == "저장"]
        save.click()
        at = self.run_app(browser, at)
        self.assertEqual([e.message for e in at.exception], [])
        self.assertEqual(self.stored_profile(browser), {"name": "초코", "conditions": ["슬개골 탈구", "피부염"]})

    def test_detected_profile_is_saved_only_after_a_click(self):
        browser = FakeBrowser(notice=True)
        at = self.run_app(browser)
        at.chat_input[0].set_value("우리 초코가 5개월인데 설사해요")
        at = self.run_app(browser, at, detected=PetProfile(name="초코"))
        self.assertEqual(self.detect.call_count, 1)
        self.assertEqual(self.stored_profile(browser), {})  # nothing saved yet
        at.button(key="profile_suggest_save").click()
        at = self.run_app(browser, at)
        self.assertEqual(self.stored_profile(browser), {"name": "초코"})

    def test_no_detection_when_a_profile_exists_or_after_declining(self):
        browser = FakeBrowser(notice=True)
        browser.values[PROFILE_KEY] = PetProfile(name="보리").model_dump_json(exclude_defaults=True)
        at = self.run_app(browser)
        at.chat_input[0].set_value("기침해요")
        at = self.run_app(browser, at, detected=PetProfile(name="초코"))
        self.assertEqual(self.detect.call_count, 0)

        browser = FakeBrowser(notice=True)
        at = self.run_app(browser)
        at.chat_input[0].set_value("우리 초코가 기침해요")
        at = self.run_app(browser, at, detected=PetProfile(name="초코"))
        at.button(key="profile_suggest_dismiss").click()
        at = self.run_app(browser, at)
        at.chat_input[0].set_value("또 기침해요")
        at = self.run_app(browser, at, detected=PetProfile(name="초코"))
        self.assertEqual(self.detect.call_count, 0)  # declined once: not asked again this session
        self.assertEqual(self.stored_profile(browser), {})


if __name__ == "__main__":
    unittest.main()
