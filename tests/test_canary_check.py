"""scripts/canary_check.py: the checks a new API revision passes before it gets traffic."""

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import canary_check

from src import data_gaps

COMMIT = "abc1234def"


def sse(*events):
    return "".join(f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n" for kind, data in events)


class FakeApi(BaseHTTPRequestHandler):
    """A deployed API: `answers` maps a question to its event stream; `commit` and `tables` as served."""

    commit = COMMIT
    tables = 200
    answers: ClassVar[dict] = {}

    def log_message(self, *args):
        pass

    def _send(self, status, body, kind="application/json"):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, json.dumps({"status": "ok", "commit": self.commit}))
        else:
            self._send(self.tables, "[]")

    def do_POST(self):
        question = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["question"]
        self.server.agents.append(self.headers["User-Agent"])
        self._send(200, self.answers.get(question, ""), "text/event-stream")


GOOD = {
    canary_check.DATE_QUESTION: sse(("result", {"route": "none", "answer": "오늘은 10월 20일입니다."})),
    canary_check.HEALTH_QUESTION: sse(("step", {"message": "찾는 중"}), ("result", {"route": "rag", "answer": "설사가…"})),
}


class CanaryCheckTests(unittest.TestCase):
    def serve(self, **overrides):
        handler = type("Api", (FakeApi,), {"answers": GOOD, **overrides})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.agents = []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.server = server
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_a_good_revision_passes_every_check(self):
        lines = canary_check.run(self.serve(), COMMIT, sleep=lambda s: None)
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(data_gaps.CHECK_AGENT in agent for agent in self.server.agents))

    def test_the_old_revision_answering_fails(self):
        with self.assertRaisesRegex(canary_check.CheckFailed, "did not report"):
            canary_check.run(self.serve(commit="old0000"), COMMIT, sleep=lambda s: None)

    def test_a_missing_table_fails(self):
        with self.assertRaisesRegex(canary_check.CheckFailed, "answered 500"):
            canary_check.run(self.serve(tables=500), COMMIT, sleep=lambda s: None)

    def test_a_broken_chat_fails(self):
        broken = {**GOOD, canary_check.HEALTH_QUESTION: sse(("error", {"message": "문제가 생겼습니다"}))}
        with self.assertRaisesRegex(canary_check.CheckFailed, "no answer"):
            canary_check.run(self.serve(answers=broken), COMMIT, sleep=lambda s: None)

    def test_the_quota_notice_is_not_an_answer(self):
        degraded = {**GOOD, canary_check.HEALTH_QUESTION: sse(("result", {"route": "rag", "answer": "한도", "degraded": True}))}
        with self.assertRaisesRegex(canary_check.CheckFailed, "quota notice"):
            canary_check.run(self.serve(answers=degraded), COMMIT, sleep=lambda s: None)

    def test_the_check_agent_is_the_projects(self):
        self.assertEqual(canary_check.CHECK_AGENT, data_gaps.CHECK_AGENT)


class FaultInjectionTests(unittest.TestCase):
    def test_a_revision_with_the_chat_fault_answers_nothing(self):
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from api import main
        from src import settings

        real = settings.get_setting
        with patch.object(settings, "get_setting", side_effect=lambda name: "chat" if name == "RAGDOG_FAULT" else real(name)):
            response = TestClient(main.create_app()).post("/chat", json={"question": "기침해요"},
                                                          headers={"X-RagDog-Client": "0" * 32})
        self.assertIn("event: error", response.text)
        self.assertNotIn("event: result", response.text)


if __name__ == "__main__":
    unittest.main()
