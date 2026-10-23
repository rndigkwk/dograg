"""The app with browser-stored conversations (design doc phase 3), via AppTest.

The browser bridge and the chatbot are replaced by fakes: the bridge reports a
stored snapshot and records what the app asks it to write. Home-page tests run
main.py. AppTest.switch_page runs a page file without main.py when the app uses
st.navigation, so chat-page tests run `chat_app`, which follows main.py's order.
"""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

from app_pages import rag as chat_page
from src import conversation_ui
from src.private_data import needs_private_data
from src.storage.models import PetProfile, Thread, Turn
from src.storage.snapshot import NOTICE_KEY, PROFILE_KEY, THREADS_KEY
from src.tools import urgency
from src.tools.profile import MemorySuggestion

# main.py shows only the "moved" notice unless STREAMLIT_FULL_APP is set (P5, 2026-10-23);
# these tests drive the full Streamlit app.
os.environ.setdefault("STREAMLIT_FULL_APP", "1")
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
    def __init__(self, threads=(), notice=False, status="ok", loaded=True):
        self.values = {
            THREADS_KEY: json.dumps([t.model_dump(mode="json") for t in threads], ensure_ascii=False),
            NOTICE_KEY: "1" if notice else "",
        }
        self.status = status
        self.loaded = loaded  # False: the browser has not reported its storage yet
        self.writes = []

    def __call__(self, key, *, request, version, values):
        if not self.loaded:
            return None
        if values is not None:
            self.writes.append(values)
            self.values.update(values)
        return {"request": request, "status": self.status, "values": dict(self.values)}

    def stored_threads(self):
        return json.loads(self.values[THREADS_KEY] or "[]")


def fake_chatbot(question, **kwargs):
    if "블랙홀" in question:  # no evidence: the chatbot abstains
        from src.chat_graph import HEALTH_ABSTAIN

        return {"route": "rag", "answer": HEALTH_ABSTAIN + "\n\n- **찾아본 것:** 9건", "evidence_rows": [],
                "hospital_rows": [], "safety_notice": None, "abstained": True, "trace_id": f"trace-{len(question)}"}
    return {"route": "rag", "answer": f"답변: {question}", "evidence_rows": [], "hospital_rows": [],
            "safety_notice": None, "abstained": False, "trace_id": f"trace-{len(question)}"}


class ConversationPageTests(unittest.TestCase):
    def run_app(self, browser, at=None, *, home=False, detected=None):
        self.detect = Mock(return_value=detected)
        with patch.object(conversation_ui, "sync_local_store", browser), \
                patch.object(chat_page, "chatbot", side_effect=fake_chatbot), \
                patch.object(chat_page, "suggest_memory", self.detect),                 patch.object(urgency, "decide_urgent", return_value=None):  # no Decisions call in tests
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

    def test_an_abstained_answer_offers_no_visit_report(self):
        browser = FakeBrowser()
        at = self.run_app(browser)
        for question in ("강아지가 블랙홀 근처에 가면?", "강아지가 구토해요"):
            at.chat_input[0].set_value(question)
            at = self.run_app(browser, at)
        buttons = [button for button in at.button if button.label == "이 상담으로 방문 준비 보고서 만들기"]
        self.assertEqual(len(buttons), 1)  # only under the answered question
        # A reopened conversation keeps no "abstained" flag; the abstention text still hides it
        at = self.run_app(browser)
        next(button for button in at.sidebar.button if button.label == "강아지가 블랙홀 근처에 가면?").click()
        at = self.run_app(browser, at)
        self.assertEqual(len(at.chat_message), 4)
        buttons = [button for button in at.button if button.label == "이 상담으로 방문 준비 보고서 만들기"]
        self.assertEqual(len(buttons), 1)

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

    def test_a_thumbs_down_asks_why_and_sends_only_with_consent(self):
        browser = FakeBrowser(notice=True)
        at = self.run_app(browser)
        at.chat_input[0].set_value("기침해요 제 번호 010-1234-5678")
        at = self.run_app(browser, at)
        reasons = lambda at: [r for r in at.radio if r.label == "어떤 점이 아쉬웠나요?"]  # noqa: E731
        self.assertEqual(reasons(at), [])  # nothing before a vote
        with patch.object(chat_page, "record_feedback"),                 patch.object(chat_page.feedback_store, "enabled", return_value=True),                 patch.object(chat_page.feedback_store, "save_review", return_value=True) as save,                 patch.object(chat_page, "record_feedback_reason") as reason:
            at.feedback[0].set_value(0)
            at = self.run_app(browser, at)
            self.assertEqual(reasons(at)[0].options, list(chat_page.feedback_store.REASONS))
            reasons(at)[0].set_value("틀린 정보")
            at = self.run_app(browser, at)
            reason.assert_called_once()
            trace_id, chosen = reason.call_args.args
            self.assertEqual(chosen, "틀린 정보")
            save.assert_not_called()  # no consent yet
            [consent] = [c for c in at.checkbox if c.label.startswith("이 질문과 답변을 개선에")]
            consent.check()
            at = self.run_app(browser, at)
            [send] = [b for b in at.button if b.label == "보내기"]
            send.click()
            at = self.run_app(browser, at)
        save.assert_called_once()
        kwargs = save.call_args.kwargs
        self.assertEqual((kwargs["reason"], kwargs["trace_id"]), ("틀린 정보", trace_id))
        self.assertIn("010-1234-5678", kwargs["question"])  # masked inside save_review, as stored
        self.assertTrue(any("고맙습니다" in c.value for c in at.caption))
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

    def test_the_input_is_closed_while_a_question_is_answered(self):
        # A question sent mid-answer stopped the running answer and left the first one unanswered
        # (deployed app, 2026-10-12; scripts/evaluate_chat_input_lock.py).
        import streamlit

        browser = FakeBrowser(notice=True)
        at = self.run_app(browser)
        disabled: list[bool] = []
        while_answering: list[bool] = []
        real_input = streamlit.chat_input

        def chat_input(*args, **kwargs):
            disabled.append(bool(kwargs.get("disabled")))
            return real_input(*args, **kwargs)

        def chatbot(question, **kwargs):
            while_answering.append(disabled[-1])
            return fake_chatbot(question)

        at.chat_input[0].set_value("강아지가 구토해요")
        with patch.object(chat_page.st, "chat_input", side_effect=chat_input):
            with patch.object(conversation_ui, "sync_local_store", browser), \
                    patch.object(chat_page, "chatbot", side_effect=chatbot), \
                    patch.object(chat_page, "suggest_memory", Mock(return_value=None)), \
                    patch.object(urgency, "decide_urgent", return_value=None):
                at.run()
        self.assertEqual(while_answering, [True])  # answered once, with the input closed
        self.assertFalse(disabled[-1])  # open again afterwards
        self.assertEqual([m.markdown[0].value for m in at.chat_message], ["강아지가 구토해요", "답변: 강아지가 구토해요"])
        self.assertNotIn(chat_page.IN_FLIGHT_STATE_KEY, at.session_state)

    def test_an_interrupted_answer_is_dropped_after_switching_conversations(self):
        stored = Thread(title="다른 대화", turns=[Turn(question="q", answer="a", route="rag")])
        browser = FakeBrowser(threads=[stored], notice=True)
        at = self.run_app(browser)
        self.interrupt(at, "기침해요", thread="some-other-thread")
        with patch.object(chat_page, "chatbot") as chatbot:
            at = self.run_app(browser, at)
        chatbot.assert_not_called()
        self.assertNotIn(chat_page.IN_FLIGHT_STATE_KEY, at.session_state)

    @needs_private_data
    def test_history_shows_on_the_home_page_and_opens_the_chat(self):
        stored = Thread(title="홈에서 연 대화", turns=[Turn(question="기침해요", answer="진료받으세요", route="rag")])
        browser = FakeBrowser(threads=[stored], notice=True)
        at = self.run_app(browser, home=True)
        self.assertEqual([e.message for e in at.exception], [])
        self.assertIn("홈에서 연 대화", self.sidebar_labels(at))
        at.sidebar.button(key=f"thread_{stored.id}").click()
        at = self.run_app(browser, at)  # st.switch_page to the chat page
        self.assertEqual([m.markdown[0].value for m in at.chat_message], ["기침해요", "진료받으세요"])

    @needs_private_data
    def test_notice_is_saved_on_the_home_page_too(self):
        browser = FakeBrowser()
        at = self.run_app(browser, home=True)
        self.assertEqual([e.message for e in at.exception], [])
        self.assertEqual(len(at.sidebar.info), 1)
        self.assertEqual(browser.values[NOTICE_KEY], "1")

    @needs_private_data
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
        found = MemorySuggestion(PetProfile(name="초코"), {"name": "초코"}, "이름 초코")
        at = self.run_app(browser, at, detected=found)
        self.assertEqual(self.detect.call_count, 1)
        self.assertEqual(self.stored_profile(browser), {})  # nothing saved yet
        at.button(key="profile_suggest_save").click()
        at = self.run_app(browser, at)
        self.assertEqual(self.stored_profile(browser), {"name": "초코"})

    def test_new_facts_are_offered_for_a_stored_profile(self):
        browser = FakeBrowser(notice=True)
        browser.values[PROFILE_KEY] = PetProfile(name="보리").model_dump_json(exclude_defaults=True)
        at = self.run_app(browser)
        at.chat_input[0].set_value("보리가 베트메딘을 먹고 있는데 기침해요")
        found = MemorySuggestion(PetProfile(name="보리", medications=["베트메딘"]), {"medications": ["베트메딘"]},
                                 "복용약 + 베트메딘")
        at = self.run_app(browser, at, detected=found)
        self.assertEqual(self.detect.call_args.args[0], PetProfile(name="보리"))  # the stored profile goes in
        self.assertTrue(any("복용약 + 베트메딘" in m.value for m in at.markdown))
        at.button(key="profile_suggest_save").click()
        at = self.run_app(browser, at)
        self.assertEqual(self.stored_profile(browser), {"name": "보리", "medications": ["베트메딘"]})

    def test_declined_facts_are_not_offered_again(self):
        browser = FakeBrowser(notice=True)
        browser.values[PROFILE_KEY] = PetProfile(name="보리").model_dump_json(exclude_defaults=True)
        found = MemorySuggestion(PetProfile(name="보리", medications=["베트메딘"]), {"medications": ["베트메딘"]},
                                 "복용약 + 베트메딘")
        at = self.run_app(browser)
        at.chat_input[0].set_value("보리가 베트메딘을 먹고 있는데 기침해요")
        at = self.run_app(browser, at, detected=found)
        at.button(key="profile_suggest_dismiss").click()
        at = self.run_app(browser, at)
        at.chat_input[0].set_value("베트메딘 먹는데 또 기침해요")
        at = self.run_app(browser, at, detected=found)
        self.assertFalse(any("복용약 + 베트메딘" in m.value for m in at.markdown))
        self.assertEqual(self.stored_profile(browser), {"name": "보리"})

        browser = FakeBrowser(notice=True)  # an empty profile, declined once: not read again this session
        at = self.run_app(browser)
        at.chat_input[0].set_value("우리 초코가 기침해요")
        at = self.run_app(browser, at, detected=MemorySuggestion(PetProfile(name="초코"), {"name": "초코"}, "이름 초코"))
        at.button(key="profile_suggest_dismiss").click()
        at = self.run_app(browser, at)
        at.chat_input[0].set_value("또 기침해요")
        at = self.run_app(browser, at, detected=None)
        self.assertEqual(self.detect.call_count, 0)
        self.assertEqual(self.stored_profile(browser), {})

    def test_no_suggestion_before_the_stored_profile_is_known(self):
        # Asked before the browser reported: the session's profile is still empty, and saving a
        # suggestion then would replace the stored profile.
        browser = FakeBrowser(notice=True, loaded=False)
        browser.values[PROFILE_KEY] = PetProfile(name="두부", medications=["관절 영양제"]).model_dump_json(exclude_defaults=True)
        at = self.run_app(browser)
        at.chat_input[0].set_value("두부가 슬개골 수술을 했어요")
        found = MemorySuggestion(PetProfile(name="두부", procedures=["슬개골 수술"]), {"name": "두부"}, "이름 두부")
        at = self.run_app(browser, at, detected=found)
        self.assertEqual(self.detect.call_count, 0)
        self.assertNotIn("profile_suggest_save", [b.key for b in at.button])

    def test_over_the_question_limit_no_answer_but_emergencies_still_warned(self):
        from src import rate_limit

        refused = rate_limit.Decision(False, 25)
        browser = FakeBrowser(notice=True)
        with patch.object(chat_page.rate_limit, "check", return_value=refused):
            at = self.run_app(browser)
            at.chat_input[0].set_value("강아지 귀 청소는 어떻게 해요?")
            at = self.run_app(browser, at)
            self.assertTrue(any("약 25분 뒤" in w.value for w in at.warning))
            at.chat_input[0].set_value("강아지가 경련을 하고 쓰러졌어요")
            at = self.run_app(browser, at)
        self.assertEqual([e.message for e in at.exception], [])
        self.assertTrue(any("동물병원" in w.value and "약 25분" not in w.value for w in at.warning))
        self.assertEqual(browser.stored_threads(), [])  # nothing was answered, so nothing was recorded
        self.assertEqual(len(at.chat_message), 0)

if __name__ == "__main__":
    unittest.main()
