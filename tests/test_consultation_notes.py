"""Consultation notes (ADR-0009): made on click for signed-in guardians, read as their records."""

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from api import main
from src import rate_limit
from src.tools import health

CLIENT = "0123456789abcdef0123456789abcdef"


def note(day, text):
    return SimpleNamespace(date=day, text=text)


class NotesContextTests(unittest.TestCase):
    def test_none_is_said_plainly(self):
        self.assertEqual(health.notes_context([]), "없음")
        self.assertEqual(health.notes_context(None), "없음")

    def test_dated_lines_and_old_ones_marked(self):
        text = health.notes_context([note("2026-10-10", " 설사 이틀째, 이틀 넘으면 병원 "), note("2026-08-01", "귀 긁음")],
                                    today=date(2026, 10, 17))
        self.assertEqual(text, "- 2026-10-10: 설사 이틀째, 이틀 넘으면 병원\n- 2026-08-01 (오래된 기록): 귀 긁음")

    def test_kept_within_the_budget(self):
        notes = [note("2026-10-10", "가" * 300) for _ in range(6)]
        self.assertLessEqual(len(health.notes_context(notes, today=date(2026, 10, 17))), health.NOTES_MAX_CHARS + 5)

    def test_the_prompt_has_the_notes_and_the_rule(self):
        system = health.RAG_PROMPT.messages[0].prompt.template
        self.assertIn("[지난 상담 기록]\n{notes}", system)
        self.assertIn("12. [지난 상담 기록]은 보호자가 직접 저장한", system)


class GraphTests(unittest.TestCase):
    def test_notes_reach_the_health_answer(self):
        from src.chat_graph import run_chat
        from tests.test_chat_graph import make_tools

        for crag in (False, True):
            with self.subTest(crag=crag):
                tools = make_tools()
                tools.ask_rag = Mock(return_value={"answer": "답", "evidence_rows": [], "safety_notice": None})
                tools.generate_health_answer = Mock(return_value="답")
                saved = [note("2026-10-10", "설사")]
                run_chat(tools, "또 설사해요", top_k=2, crag=crag, notes=saved)
                called = tools.generate_health_answer if crag else tools.ask_rag
                self.assertEqual(called.call_args.kwargs["notes"], saved)


class NoteRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.create_app())
        patcher = patch.object(rate_limit, "check", return_value=rate_limit.Decision(True))
        self.check = patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, **headers):
        return self.client.post("/memory/note", json={"question": "보리가 설사해요", "answer": "이틀 넘으면 병원에 가세요."},
                                headers=headers)

    def test_signed_out_is_refused_before_any_model_call(self):
        with patch("src.tools.notes.make_note", side_effect=AssertionError("no model call")):
            self.assertEqual(self.post().status_code, 401)

    def test_a_signed_in_guardian_gets_a_dated_note(self):
        with patch("src.auth.user_id", return_value="u-1"), \
                patch("src.tools.notes.make_note", return_value="설사 이틀째. 이틀 넘으면 병원.") as make, \
                patch("src.tools.notes.today", return_value=date(2026, 10, 17)):
            body = self.post(Authorization="Bearer x").json()
        self.assertEqual(body, {"note": "설사 이틀째. 이틀 넘으면 병원.", "date": "2026-10-17"})
        make.assert_called_once_with("보리가 설사해요", "이틀 넘으면 병원에 가세요.")
        self.assertEqual(self.check.call_args.args[0], "user:u-1")  # counted like a question, by account

    def test_over_the_limit_no_model(self):
        self.check.return_value = rate_limit.Decision(False, 30)
        with patch("src.auth.user_id", return_value="u-1"), \
                patch("src.tools.notes.make_note", side_effect=AssertionError("no model call")):
            self.assertEqual(self.post(Authorization="Bearer x").status_code, 429)


class ChatNotesTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.create_app())
        for item in (patch("src.tools.urgency.urgent_notice", return_value=None),
                     patch.object(rate_limit, "check", return_value=rate_limit.Decision(True))):
            item.start()
            self.addCleanup(item.stop)

    def post(self, notes):
        return self.client.post("/chat", json={"question": "또 설사해요", "notes": notes}, headers={"X-RagDog-Client": CLIENT})

    def test_notes_are_masked_and_passed_on(self):
        seen = {}

        def fake(question, **kwargs):
            seen.update(kwargs)
            return {"answer": "답", "route": "rag"}

        with patch("src.chatbot.chatbot", side_effect=fake):
            self.post([{"date": "2026-10-10", "text": "설사, 병원 010-1234-5678"}]).read()
        self.assertEqual(seen["notes"][0].date, "2026-10-10")
        self.assertNotIn("010-1234-5678", seen["notes"][0].text)

    def test_bad_notes_are_refused(self):
        self.assertEqual(self.post([{"date": "2026-13-45", "text": "x"}]).status_code, 422)
        self.assertEqual(self.post([{"date": "2026-10-10", "text": "가" * 301}]).status_code, 422)
        self.assertEqual(self.post([{"date": "2026-10-10", "text": "x"}] * 6).status_code, 422)


if __name__ == "__main__":
    unittest.main()
