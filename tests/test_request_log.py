"""src/request_log.py: JSON log lines for Cloud Logging and one summary line per answer."""

import json
import logging
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import main
from src import rate_limit, request_log
from tests.test_api_chat import CLIENT, fake_chatbot


def sse(kind, data):
    return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class FormatTests(unittest.TestCase):
    def line(self, record):
        return json.loads(request_log.JsonFormatter().format(record))

    def test_one_line_with_severity_and_the_traceback(self):
        try:
            raise RuntimeError("insufficient_quota")
        except RuntimeError:
            import sys

            record = logging.LogRecord("api.chat", logging.ERROR, __file__, 1, "chat failed", None, sys.exc_info())
        text = request_log.JsonFormatter().format(record)
        self.assertNotIn("\n", text)  # one Cloud Logging entry, not one per traceback line
        entry = json.loads(text)
        self.assertEqual((entry["severity"], entry["logger"]), ("ERROR", "api.chat"))
        # The alert phrases (scripts/gcp/alert_policies.json) are still in the entry.
        self.assertIn("chat failed", entry["message"])
        self.assertIn("insufficient_quota", entry["message"])

    def test_configure_twice_keeps_one_handler(self):
        root = logging.getLogger()
        saved = (list(root.handlers), root.level)
        self.addCleanup(lambda: (setattr(root, "handlers", saved[0]), root.setLevel(saved[1])))
        request_log.configure()
        request_log.configure()
        self.assertEqual(len(root.handlers), 1)
        self.assertEqual(root.level, logging.WARNING)
        self.assertEqual(request_log.logger.level, logging.INFO)


class SummaryTests(unittest.TestCase):
    def summary(self, chunks, agent=""):
        with self.assertLogs("ragdog.requests", "INFO") as logs:
            passed = list(request_log.summarized("chat", iter(chunks), agent))
        self.assertEqual(passed, chunks)  # the stream is unchanged
        [record] = logs.records
        return record.fields

    def test_the_last_event_and_its_safe_fields_no_text(self):
        fields = self.summary([sse("step", {"message": "찾는 중"}), sse("token", {"text": "설사가"}),
                               sse("result", {"answer": "설사가 계속되면…", "route": "rag", "trace_id": "t1",
                                              "search": "local", "evidence_rows": [{"id": "7"}]})])
        self.assertEqual((fields["outcome"], fields["route"], fields["trace_id"], fields["search"]),
                         ("result", "rag", "t1", "local"))
        self.assertNotIn("설사", json.dumps(fields, ensure_ascii=False))
        self.assertFalse(fields["check"])
        self.assertGreaterEqual(fields["latency_ms"], 0)

    def test_limits_errors_and_the_deployment_check(self):
        self.assertEqual(self.summary([sse("limited", {"message": "…", "wait_minutes": 12})])["outcome"], "limited")
        fields = self.summary([sse("urgent", {"notice": "…"}), sse("error", {"message": "…"})], agent="x RagDogCheck")
        self.assertEqual((fields["outcome"], fields["urgent"], fields["check"]), ("error", True, True))

    def test_a_closed_connection_is_still_summarized(self):
        with self.assertLogs("ragdog.requests", "INFO") as logs:
            stream = request_log.summarized("chat", iter([sse("step", {}), sse("result", {"route": "rag"})]))
            next(stream)
            stream.close()
        self.assertEqual(logs.records[0].fields["outcome"], "step")


class ApiTests(unittest.TestCase):
    def test_a_chat_answer_logs_one_summary(self):
        client = TestClient(main.create_app())
        with patch("src.chatbot.chatbot", side_effect=fake_chatbot), \
                patch("src.tools.urgency.urgent_notice", return_value=None), \
                patch.object(rate_limit, "check", return_value=rate_limit.Decision(True)), \
                self.assertLogs("ragdog.requests", "INFO") as logs:
            client.post("/chat", json={"question": "강아지가 구토해요"}, headers={"X-RagDog-Client": CLIENT})
        [record] = logs.records
        self.assertEqual((record.fields["kind"], record.fields["outcome"], record.fields["route"]), ("chat", "result", "rag"))


if __name__ == "__main__":
    unittest.main()
