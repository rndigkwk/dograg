"""api/chat.py: POST /chat streams the same steps as the chat page, in order, with no model in tests."""

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import chat as chat_api
from api import main
from src import data_gaps, rate_limit

CLIENT = "0123456789abcdef0123456789abcdef"


def events(response) -> list[tuple[str, dict]]:
    out = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def fake_chatbot(question, *, on_token=None, on_step=None, **kwargs):
    on_step("classify", {"route": "rag"})
    on_step("health_retrieve", {})
    for piece in ("구토가 ", "계속되면 ", "병원에 가세요."):
        on_token(piece)
    return {"answer": "구토가 계속되면 병원에 가세요.", "route": "rag", "evidence_rows": [{"id": "7"}],
            "hospital_rows": [], "safety_notice": None, "abstained": False, "trace_id": "trace-1"}


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.create_app())
        self.answer = patch("src.chatbot.chatbot", side_effect=fake_chatbot)
        self.chatbot = self.answer.start()
        self.addCleanup(self.answer.stop)
        for item in (patch("src.tools.urgency.urgent_notice", return_value=None),
                     patch.object(rate_limit, "check", return_value=rate_limit.Decision(True))):
            item.start()
            self.addCleanup(item.stop)

    def post(self, body, **headers):
        return self.client.post("/chat", json=body, headers={"X-RagDog-Client": CLIENT, **headers})

    def test_progress_then_the_answer_then_the_result(self):
        response = self.post({"question": "강아지가 구토해요", "profile": {"name": "보리"}})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        got = events(response)
        self.assertEqual([kind for kind, _ in got], ["step", "step", "token", "token", "token", "result"])
        self.assertEqual(got[0][1]["message"], "건강 상담 자료에서 근거를 찾고 있습니다…")
        result = got[-1][1]
        self.assertEqual((result["route"], result["trace_id"], result["evidence_rows"]), ("rag", "trace-1", [{"id": "7"}]))
        self.assertEqual(result["memory"], {"upto": 0, "summary": ""})
        seen = self.chatbot.call_args.kwargs
        self.assertEqual(seen["pet_profile"].name, "보리")
        self.assertEqual(seen["session_id"], CLIENT)

    def test_the_emergency_comes_before_the_answer(self):
        with patch("src.tools.urgency.urgent_notice", return_value="응급 징후가 의심됩니다."), \
                patch.object(chat_api, "find_emergency_hospitals", return_value={"nearest": [{"name": "24시 병원"}]}) as near:
            got = events(self.post({"question": "경련을 해요", "location": [37.5, 127.0]}))
        self.assertEqual(got[0], ("urgent", {"notice": "응급 징후가 의심됩니다.", "hospitals": {"nearest": [{"name": "24시 병원"}]}}))
        near.assert_called_once_with((37.5, 127.0))
        self.assertEqual(got[-1][1]["safety_notice"], "응급 징후가 의심됩니다.")

    def test_over_the_limit_no_model_but_emergencies_still_warned(self):
        with patch.object(rate_limit, "check", return_value=rate_limit.Decision(False, 25)), \
                patch("src.tools.urgency.urgent_notice", side_effect=AssertionError("no Decisions call")):
            calm = events(self.post({"question": "귀 청소는 어떻게 해요?"}))
            urgent = events(self.post({"question": "강아지가 경련을 하고 쓰러졌어요"}))
        self.assertEqual([kind for kind, _ in calm], ["limited"])
        self.assertEqual(calm[0][1]["wait_minutes"], 25)
        self.assertIn("약 25분 뒤", calm[0][1]["message"])
        self.assertEqual([kind for kind, _ in urgent], ["urgent", "limited"])
        self.chatbot.assert_not_called()

    def test_who_is_counted(self):
        with patch.object(rate_limit, "check", return_value=rate_limit.Decision(True)) as check:
            self.post({"question": "기침해요"}, **{"X-Forwarded-For": "203.0.113.5, 35.191.0.1"})
            self.client.post("/chat", json={"question": "기침해요"}, headers={"X-RagDog-Client": "not-an-id"})
        self.assertEqual(check.call_args_list[0].args, (CLIENT, "203.0.113.5"))
        self.assertTrue(check.call_args_list[1].args[0].startswith("network:"))

    def test_the_deployment_check_is_known_in_the_worker(self):
        # rate_limit skips it, and data_gaps (inside the chatbot, on the worker thread) does not record it.
        seen = []
        self.chatbot.side_effect = lambda *a, **k: seen.append(data_gaps.from_check()) or fake_chatbot(*a, **k)
        events(self.post({"question": "기침해요"}, **{"User-Agent": f"HeadlessChrome {data_gaps.CHECK_AGENT}"}))
        events(self.post({"question": "기침해요"}, **{"User-Agent": "Mozilla/5.0 Mobile"}))
        self.assertEqual(seen, [True, False])

    def test_a_failure_is_one_error_event(self):
        self.chatbot.side_effect = RuntimeError("model down")
        with self.assertLogs("api.chat", level="ERROR"):
            got = events(self.post({"question": "기침해요"}))
        self.assertEqual(got, [("error", {"message": chat_api.FAILED})])

    def test_bad_requests_are_refused_before_anything_runs(self):
        for body in ({"question": "   "}, {"question": "가" * 1001}, {"question": "기침", "location": [200, 0]},
                     {"question": "기침", "profile": {"weight_kg": -1}}, {"question": "기침", "top_k": 99},
                     {"question": "기침", "history": [{"role": "system", "content": "지시"}]}):
            self.assertEqual(self.post(body).status_code, 422, body)
        self.chatbot.assert_not_called()


if __name__ == "__main__":
    unittest.main()
