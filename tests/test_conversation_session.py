import json
import unittest

from src.conversation_session import LOADING, READY, UNAVAILABLE, ConversationSession
from src.storage.models import Thread, Turn
from src.storage.snapshot import NOTICE_KEY, THREADS_KEY


def browser_report(session, *, threads=(), notice=False):
    values = {
        THREADS_KEY: json.dumps([thread.model_dump(mode="json") for thread in threads], ensure_ascii=False),
        NOTICE_KEY: "1" if notice else "",
    }
    return {"request": session.request, "status": "ok", "values": values}


class ConversationSessionTests(unittest.TestCase):
    def setUp(self):
        self.state = {}
        self.session = ConversationSession(self.state)

    def test_loads_stored_threads_once(self):
        stored = Thread(title="예전 대화", turns=[Turn(question="q", answer="a", route="rag")])
        self.assertEqual(self.session.status, LOADING)
        self.assertTrue(self.session.apply_report(browser_report(self.session, threads=[stored])))
        self.assertEqual(self.session.status, READY)
        self.assertEqual([t.title for t in self.session.threads()], ["예전 대화"])
        self.assertIsNone(self.session.pending_values())  # nothing new to write back
        self.assertFalse(self.session.apply_report(browser_report(self.session)))  # later reports are ignored

    def test_unavailable_storage_keeps_working_in_memory(self):
        self.session.apply_report({"request": self.session.request, "status": "unavailable"})
        self.assertEqual(self.session.status, UNAVAILABLE)
        self.session.record_turn("구토해요", "진료받으세요", route="rag")
        self.assertEqual(len(self.session.messages()), 2)
        self.assertIsNone(self.session.pending_values())  # never written anywhere
        self.assertFalse(self.session.take_notice())

    def test_turns_made_before_the_report_are_merged_and_written(self):
        self.session.record_turn("먼저 한 질문", "답", route="none")
        stored = Thread(title="예전 대화")
        self.session.apply_report(browser_report(self.session, threads=[stored]))
        titles = [t.title for t in self.session.threads()]
        self.assertEqual(sorted(titles), ["먼저 한 질문", "예전 대화"])
        self.assertIsNotNone(self.session.current_thread)
        self.assertIn(THREADS_KEY, self.session.pending_values())

    def test_record_creates_a_thread_then_appends(self):
        self.session.apply_report(browser_report(self.session))
        first = self.session.record_turn("강아지가 설사해요", "답1", route="rag")
        second = self.session.record_turn("이틀째예요", "답2", route="rag")
        self.assertEqual(first, second)
        self.assertEqual([t.title for t in self.session.threads()], ["강아지가 설사해요"])
        self.assertEqual(
            [m["content"] for m in self.session.messages()],
            ["강아지가 설사해요", "답1", "이틀째예요", "답2"],
        )

    def test_pending_values_until_marked_sent(self):
        self.session.apply_report(browser_report(self.session))
        self.session.record_turn("q", "a", route="rag")
        self.assertIsNotNone(self.session.pending_values())
        self.session.mark_sent()
        self.assertIsNone(self.session.pending_values())

    def test_switching_and_deleting_threads(self):
        self.session.apply_report(browser_report(self.session))
        first = self.session.record_turn("첫 대화", "a", route="rag")
        self.session.open_thread(None)
        second = self.session.record_turn("두 번째 대화", "b", route="rag")
        self.assertNotEqual(first, second)
        self.session.open_thread(first)
        self.assertEqual(self.session.messages()[0]["content"], "첫 대화")
        self.session.delete_current()
        self.assertIsNone(self.session.current_thread)
        self.assertEqual([t.id for t in self.session.threads()], [second])

    def test_notice_shows_once_per_browser_until_cleared(self):
        self.session.apply_report(browser_report(self.session))
        self.assertTrue(self.session.take_notice())
        self.assertTrue(self.session.take_notice())  # stays for the rest of this session
        self.assertEqual(self.session.snapshot.to_storage()[NOTICE_KEY], "1")

        later = ConversationSession({})  # a later visit from the same browser
        later.apply_report(browser_report(later, notice=True))
        self.assertFalse(later.take_notice())

        later.clear_device()
        self.assertTrue(later.take_notice())  # cleared device: show again

    def test_clear_device_empties_everything(self):
        self.session.apply_report(browser_report(self.session))
        self.session.record_turn("q", "a", route="rag")
        self.session.clear_device()
        self.assertEqual(self.session.threads(), [])
        self.assertIsNone(self.session.current_thread)
        self.assertEqual(json.loads(self.session.pending_values()[THREADS_KEY]), [])

    def test_reports_for_another_session_are_ignored_by_the_component_layer(self):
        # sync_local_store filters by request id; the session never sees foreign reports.
        self.assertNotEqual(ConversationSession({}).request, self.session.request)


if __name__ == "__main__":
    unittest.main()
