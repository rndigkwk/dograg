"""api/visit_prep.py: the visit-prep report streamed, with the team replaced by a fake (no model calls)."""

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import main
from api import visit_prep as visit_api
from src import rate_limit, settings, visit_prep_runs, visit_prep_store
from tests.test_visit_prep_page import FakeTeam

ME = "0123456789abcdef0123456789abcdef"
SOMEONE_ELSE = "fedcba9876543210fedcba9876543210"


class FlakyTeam:
    """Fails its first `failures` calls, then runs as the fake team; records the retries."""

    def __init__(self, team, failures):
        self.team, self.failures, self.retries = team, failures, []

    def __call__(self, *args, thread_id, resume=None, retry=False):
        if retry:
            self.retries.append((thread_id, retry))
        if self.failures:
            self.failures -= 1
            raise RuntimeError("model call failed")
        return self.team(*args, thread_id=thread_id, resume=resume)


def events(response) -> list[tuple[str, dict]]:
    out = []
    for block in response.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


class VisitPrepApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.create_app())
        self.team = FakeTeam()
        visit_prep_store._reset_for_tests(visit_prep_store.MemoryStore())
        self.addCleanup(visit_prep_store._reset_for_tests, None)
        visit_prep_runs.paused_runs().clear()
        self.addCleanup(visit_prep_runs.paused_runs().clear)
        self.run_team = patch.object(visit_api, "_run_team", return_value=self.team)
        self.run_team_mock = self.run_team.start()
        self.addCleanup(self.run_team.stop)
        for item in (
                     patch.object(visit_prep_runs, "prepare_search", return_value=None),
                     patch.object(settings, "get_openai_api_key", return_value="sk-test"),
                     patch.object(rate_limit, "check", return_value=rate_limit.Decision(True))):
            item.start()
            self.addCleanup(item.stop)

    def start(self, consultation="말티즈가 설사를 해요", who=ME, **extra):
        return self.client.post("/visit-prep", json={"consultation": consultation, **extra},
                                headers={"X-RagDog-Client": who})

    def answer(self, thread_id, text, who=ME):
        return self.client.post(f"/visit-prep/{thread_id}/answer", json={"answer": text},
                                headers={"X-RagDog-Client": who})

    def test_progress_then_the_report(self):
        got = events(self.start(region="강남구", profile="말티즈, 4살"))
        self.assertEqual([kind for kind, _ in got], ["step", "step", "step", "result"])
        self.assertEqual(got[0][1]["line"], visit_prep_runs.PREPARED)
        result = got[-1][1]
        self.assertTrue(result["passed"])
        self.assertIn("방문 준비 보고서", result["report"])
        self.assertNotIn("[qa-5250]", result["report"])  # evidence ids become readable citations
        self.assertEqual(self.team.calls, [("말티즈가 설사를 해요", "강남구", "말티즈, 4살")])

    def test_chosen_notes_reach_the_team_after_the_consultation(self):
        from datetime import date, timedelta

        week_ago = (date.today() - timedelta(days=7)).isoformat()
        notes = [{"date": week_ago, "text": "설사로 병원에서 정장제를 받음. 연락처 010-1234-5678"},
                 {"date": "2026-08-01", "text": "경련이 한 번 있었음"}]
        got = events(self.start(notes=notes))
        consultation = self.team.calls[0][0]
        self.assertTrue(consultation.startswith("말티즈가 설사를 해요\n\n[보호자가 고른 지난 상담 기록"))
        self.assertIn(f"- {week_ago} (7일 전): 설사로 병원에서 정장제를 받음.", consultation)
        self.assertNotIn("010-1234-5678", consultation)  # masked as in chat
        # An old note's urgent word is not today's emergency.
        self.assertNotIn("urgent", [kind for kind, _ in got])
        self.assertFalse(got[-1][1]["urgent"])

    def test_without_notes_the_consultation_is_as_typed(self):
        events(self.start())
        self.assertEqual(self.team.calls[0][0], "말티즈가 설사를 해요")
        self.assertEqual(self.start(notes=[{"date": "x", "text": "a"}]).status_code, 422)

    def test_urgent_consultations_warn_first(self):
        got = events(self.start("강아지가 경련을 하고 쓰러졌어요"))
        self.assertEqual(got[0], ("urgent", {"notice": visit_api.URGENT}))
        self.assertEqual(got[-1][0], "result")

    def test_a_paused_run_resumes_only_for_its_owner_and_only_once(self):
        self.team.questions = ["언제부터였나요?"]
        got = events(self.start())
        self.assertEqual(got[-1][0], "paused")
        thread_id, questions = got[-1][1]["thread_id"], got[-1][1]["questions"]
        self.assertEqual(questions, ["언제부터였나요?"])
        self.assertIn(thread_id, visit_prep_runs.paused_runs())
        self.assertEqual(self.answer(thread_id, "어제부터", who=SOMEONE_ELSE).status_code, 404)
        resumed = events(self.answer(thread_id, "어제부터요"))
        self.assertEqual(resumed[-1][0], "result")
        self.assertTrue(resumed[-1][1]["answered"])
        self.assertEqual(self.team.resumes, [(thread_id, "어제부터요")])
        self.assertNotIn(thread_id, visit_prep_runs.paused_runs())
        self.assertEqual(self.answer(thread_id, "또").status_code, 404)

    def test_an_expired_pause_cannot_be_answered(self):
        self.team.questions = ["언제부터였나요?"]
        thread_id = events(self.start())[-1][1]["thread_id"]
        paused_at = visit_prep_runs.paused_runs()[thread_id]
        with patch("time.time", return_value=paused_at + visit_prep_runs.PAUSED_RUN_TTL_SECONDS + 1):
            self.assertEqual(self.answer(thread_id, "어제부터").status_code, 404)

    def test_two_reports_a_day_and_the_question_limit(self):
        for _ in range(visit_api.REPORTS_PER_DAY):
            self.assertEqual(events(self.start())[-1][0], "result")
        self.assertEqual(events(self.start()), [("limited", {"message": visit_api.REPORTS_USED, "wait_minutes": None})])
        with patch.object(rate_limit, "check", return_value=rate_limit.Decision(False, 40)):
            got = events(self.start(who=SOMEONE_ELSE))
        self.assertEqual((got[0][0], got[0][1]["wait_minutes"]), ("limited", 40))
        self.assertEqual(len(self.team.calls), visit_api.REPORTS_PER_DAY)

    def test_one_team_at_a_time_and_a_busy_refusal_costs_nothing(self):
        lock = visit_prep_runs.team_lock()
        self.assertTrue(lock.acquire(blocking=False))
        try:
            got = events(self.start())
        finally:
            lock.release()
        self.assertEqual(got, [("busy", {"message": visit_api.BUSY})])
        # Not run, so not used up: both of today's reports are still there.
        self.assertTrue(visit_api._take_report(ME, visit_prep_store.now()))
        self.assertTrue(visit_api._take_report(ME, visit_prep_store.now()))
        self.assertEqual(self.team.calls, [])

    def test_a_failed_run_is_an_error_and_frees_the_team(self):
        with patch.object(visit_api, "_run_team", return_value=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))), \
                self.assertLogs("api.visit_prep", level="ERROR"):
            got = events(self.start())
        kind, data = got[-1]
        self.assertEqual((kind, data["message"]), ("error", visit_api.FAILED_RETRY))
        self.assertRegex(data["thread_id"], r"^[0-9a-f]{32}$")
        self.assertTrue(visit_prep_runs.team_lock().acquire(blocking=False))
        visit_prep_runs.team_lock().release()

    def retry(self, thread_id, who=ME):
        return self.client.post(f"/visit-prep/{thread_id}/retry", headers={"X-RagDog-Client": who})

    def test_a_failed_run_goes_on_from_its_checkpoint_without_a_new_report(self):
        team = FlakyTeam(self.team, failures=1)
        with patch.object(visit_api, "_run_team", return_value=team), self.assertLogs("api.visit_prep", level="ERROR"):
            first = events(self.start())
        thread_id = first[-1][1]["thread_id"]
        self.assertEqual(self.retry(thread_id, who=SOMEONE_ELSE).status_code, 404)  # the owner's only
        self.assertEqual(self.answer(thread_id, "어제부터요").status_code, 409)  # continued, not answered
        with patch.object(visit_api, "_run_team", return_value=team):
            got = events(self.retry(thread_id))
        self.assertEqual(got[-1][0], "result")
        self.assertFalse(got[-1][1]["answered"])
        self.assertEqual(team.retries, [(thread_id, True)])  # the same thread, from its checkpoint
        self.assertEqual(self.retry(thread_id).status_code, 404)  # once it ended there is nothing to go on with
        events(self.start())  # the retry was not a new report: the second of the day is still there
        self.assertEqual(events(self.start())[-1][0], "limited")

    def test_a_paused_run_is_not_retried(self):
        self.team.questions = ["언제부터였나요?"]
        thread_id = events(self.start())[-1][1]["thread_id"]
        self.assertEqual(self.retry(thread_id).status_code, 404)
        self.assertEqual(events(self.answer(thread_id, "어제부터요"))[-1][0], "result")  # the pause still waits

    def test_retries_stop_after_the_last_try(self):
        team = FlakyTeam(self.team, failures=10)
        with patch.object(visit_api, "_run_team", return_value=team), self.assertLogs("api.visit_prep", level="ERROR"):
            thread_id = events(self.start())[-1][1]["thread_id"]
            for _ in range(visit_api.MAX_RETRIES - 1):
                self.assertEqual(events(self.retry(thread_id))[-1][1].get("thread_id"), thread_id)
            self.assertEqual(events(self.retry(thread_id))[-1], ("error", {"message": visit_api.FAILED}))
        self.assertEqual(self.retry(thread_id).status_code, 404)

    def test_the_guardian_location_goes_to_the_team(self):
        events(self.start(location=[37.4939633, 127.0448504]))
        events(self.start(who=SOMEONE_ELSE))
        self.assertEqual([call.args for call in self.run_team_mock.call_args_list],
                         [(ME, (37.4939633, 127.0448504)), (SOMEONE_ELSE, None)])

    def test_bad_requests(self):
        self.assertEqual(self.start("   ").status_code, 422)
        self.assertEqual(self.start("가" * 501).status_code, 422)
        self.assertEqual(self.start(location=[51.5, -0.12]).status_code, 422)  # outside Korea
        self.assertEqual(self.start(location=[37.5]).status_code, 422)
        self.assertEqual(self.client.post("/visit-prep/x/answer", json={"answer": "가" * 301},
                                          headers={"X-RagDog-Client": ME}).status_code, 422)
        with patch.object(settings, "get_openai_api_key", return_value=None):
            self.assertEqual(self.start().status_code, 503)
        self.assertEqual(self.team.calls, [])


if __name__ == "__main__":
    unittest.main()
