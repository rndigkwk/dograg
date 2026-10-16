"""api/feedback.py: votes, reasons and consented reviews (no model calls)."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import feedback as feedback_api
from api import main
from src import feedback_store, tracing

TRACE = "0123456789abcdef0123456789abcdef"
ME = {"X-RagDog-Client": "a" * 32}


class FeedbackApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.create_app())
        feedback_api._sent.clear()

    def test_votes_and_reasons_become_langfuse_scores(self):
        with patch.object(tracing, "record_feedback", return_value=True) as vote, \
                patch.object(tracing, "record_feedback_reason", return_value=True) as why:
            self.assertEqual(self.client.post("/feedback", json={"trace_id": TRACE, "helpful": False}, headers=ME).json(),
                             {"recorded": True})
            self.client.post("/feedback/reason", json={"trace_id": TRACE, "reason": "틀린 정보"}, headers=ME)
        vote.assert_called_once_with(TRACE, helpful=False)
        why.assert_called_once_with(TRACE, "틀린 정보")

    def test_a_review_is_stored_with_evidence_labels_only(self):
        rows = [{"meta.department": "내과", "qa.output": "아주 긴 수의사 답변 " * 20, "page": 3}]
        with patch.object(feedback_store, "enabled", return_value=True), \
                patch.object(feedback_store, "save_review", return_value=True) as save:
            response = self.client.post("/feedback/review", headers=ME, json={
                "trace_id": TRACE, "question": "기침해요 010-1234-5678", "answer": "병원에 가세요",
                "route": "rag", "reason": "근거가 부족해요", "evidence_rows": rows})
        self.assertEqual(response.json(), {"saved": True})
        stored = save.call_args.kwargs
        self.assertEqual(stored["evidence"], [{"meta.department": "내과", "page": 3}])
        self.assertEqual(stored["question"], "기침해요 010-1234-5678")  # save_review masks it (tests/test_feedback_store.py)

    def test_refusals(self):
        bad = (("/feedback", {"trace_id": "x", "helpful": True}),
               ("/feedback/reason", {"trace_id": TRACE, "reason": "그냥"}),
               ("/feedback/review", {"trace_id": TRACE, "question": "", "answer": "a"}),
               ("/feedback/review", {"trace_id": TRACE, "question": "q", "answer": "a", "reason": "그냥"}))
        for path, body in bad:
            self.assertEqual(self.client.post(path, json=body, headers=ME).status_code, 422, (path, body))
        with patch.object(feedback_store, "enabled", return_value=False):
            self.assertEqual(self.client.post("/feedback/review", headers=ME,
                                              json={"trace_id": TRACE, "question": "q", "answer": "a"}).status_code, 503)

    def test_a_browser_sends_a_limited_number(self):
        with patch.object(tracing, "record_feedback", return_value=True), \
                patch.object(feedback_api, "FEEDBACK_PER_HOUR", 3):
            codes = [self.client.post("/feedback", json={"trace_id": TRACE, "helpful": True}, headers=ME).status_code
                     for _ in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])

    def test_new_browser_ids_do_not_escape_the_network_cap(self):
        # The browser id is the caller's to choose; one network still gets FEEDBACK_PER_HOUR_NETWORK.
        with patch.object(tracing, "record_feedback", return_value=True),                 patch.object(feedback_api, "FEEDBACK_PER_HOUR_NETWORK", 3):
            codes = [self.client.post("/feedback", json={"trace_id": TRACE, "helpful": True},
                                      headers={"X-RagDog-Client": f"{n:032x}"}).status_code for n in range(4)]
        self.assertEqual(codes, [200, 200, 200, 429])

    def test_the_reasons_are_the_pages(self):
        self.assertEqual(self.client.get("/feedback/reasons").json(), list(feedback_store.REASONS))


if __name__ == "__main__":
    unittest.main()
