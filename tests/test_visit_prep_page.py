"""Visit-prep report page (app_pages/visit_prep.py) via AppTest, with the team replaced by a fake."""

import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from app_pages import visit_prep
from src import settings
from team.core import config


def page_app():
    from app_pages import visit_prep

    visit_prep.render_page()


class FakeTeam:
    def __init__(self, passed=True, outcome="complete", questions=()):
        self.passed, self.outcome, self.calls, self.run_dirs = passed, outcome, [], []
        self.questions, self.resumes = list(questions), []

    def __call__(self, consultation, region, profile, run_dir, on_step, *, thread_id, resume=None):
        self.calls.append((consultation, region, profile))
        self.thread_ids = [*getattr(self, "thread_ids", []), thread_id]
        getattr(self, "events", []).append("run_team")
        self.run_dirs.append(run_dir)
        if self.questions and resume is None:  # stops at ask_guardian
            return {"paused": True, "questions": self.questions, "thread_id": thread_id}
        if resume is not None:
            self.resumes.append((thread_id, resume))
        on_step("planner", {"plan": [{"kind": "health"}, {"kind": "place"}]})
        on_step("reviewer", {"review": {"passed": self.passed, "unsupported": [] if self.passed else ["x"]}})
        (run_dir / config.REPORT_FILE).write_text(
            "# 방문 준비 보고서\n\n설사 정리 [상담 내용]\n\n사료를 천천히 바꾼 사례 [qa-5250] [qa-5250]", encoding="utf-8")
        findings = {"t1": {"summary": "설사 사례", "key_points": [{"fact": "사료는 10일에 걸쳐 바꾼다", "evidence_id": "qa-5250"}]}}
        return {"review": {"passed": self.passed}, "round": 0 if self.passed else 2, "findings": findings,
                "outcome": self.outcome, "paused": False}


class VisitPrepPageTests(unittest.TestCase):
    def open_page(self, team, api_key="sk-test"):
        self.events = []
        team.events = self.events
        prepare = lambda: self.events.append("prepare_search")  # records the call order
        patches = [patch.object(visit_prep, "run_team", side_effect=team),
                   patch.object(visit_prep, "prepare_search", side_effect=prepare),
                   patch.object(settings, "get_openai_api_key", return_value=api_key)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        at = AppTest.from_function(page_app, default_timeout=30)
        at.run()
        return at

    def submit(self, at, consultation, region=""):
        at.text_area[0].set_value(consultation)
        at.text_input[0].set_value(region)
        at.button[0].click().run()

    def test_report_is_shown_with_progress_and_the_temporary_folder_is_removed(self):
        team = FakeTeam()
        at = self.open_page(team)
        self.submit(at, "말티즈가 설사를 해요", "강남구")
        self.assertEqual(team.calls, [("말티즈가 설사를 해요", "강남구", "")])
        markdown = " ".join(item.value for item in at.markdown)
        self.assertIn("설사 정리", markdown)
        self.assertIn("상담을 조사 작업으로 나눴습니다: 증상, 병원", markdown)
        self.assertIn("검수 통과", " ".join(item.value for item in at.success))
        self.assertFalse(Path(team.run_dirs[0]).exists())  # nothing kept on the server
        # Search resources load in the page's thread first, never first inside a worker thread
        self.assertEqual(self.events, ["prepare_search", "run_team"])
        self.assertIn("검색 자료를 준비했습니다", markdown)
        # Evidence ids are shown as short numbers with a source list
        self.assertIn("설사 정리 ①", markdown)
        self.assertIn("바꾼 사례 ②", markdown)
        self.assertNotIn("[qa-5250]", markdown)
        self.assertIn("② 비슷한 건강 상담 사례 (AI Hub qa-5250)", markdown)

    def test_questions_pause_the_run_and_the_answer_resumes_the_same_thread(self):
        team = FakeTeam(questions=["언제부터 설사했나요?", "하루에 몇 번인가요?"])
        at = self.open_page(team)
        self.submit(at, "말티즈가 설사를 해요")
        markdown = " ".join(item.value for item in at.markdown)
        self.assertIn("1. 언제부터 설사했나요?", markdown)
        self.assertNotIn("설사 정리", markdown)  # no report yet
        at.text_area(key=visit_prep.ANSWER_KEY).set_value("어제 저녁부터 세 번이요")
        next(button for button in at.button if button.label == "답하고 보고서 만들기").click().run()
        self.assertEqual(len(team.resumes), 1)
        thread_id, answer = team.resumes[0]
        self.assertEqual(answer, "어제 저녁부터 세 번이요")
        self.assertEqual(thread_id, team.thread_ids[0])  # the paused run, not a new one
        self.assertEqual(len(team.calls), 2)
        self.assertIn("설사 정리", " ".join(item.value for item in at.markdown))
        self.assertIn("보호자 답변 반영", " ".join(item.value for item in at.success))
        self.assertEqual(at.session_state[visit_prep.RUNS_STATE_KEY], 1)  # answering is not a second run
        self.assertNotIn(visit_prep.PENDING_STATE_KEY, at.session_state)

    def test_an_unanswered_pause_expires_and_gives_the_run_back(self):
        team = FakeTeam(questions=["언제부터 설사했나요?"])
        at = self.open_page(team)
        self.submit(at, "말티즈가 설사를 해요")
        thread_id = team.thread_ids[0]
        self.assertIn(thread_id, visit_prep.paused_runs())
        self.assertEqual(at.session_state[visit_prep.RUNS_STATE_KEY], 1)
        # 31 minutes later another page view clears it from the server
        expired = visit_prep.forget_expired_runs(now=visit_prep.paused_runs()[thread_id] + 31 * 60)
        self.assertEqual(expired, [thread_id])
        at.run()
        self.assertIn(visit_prep.EXPIRED_NOTICE, " ".join(item.value for item in at.info))
        self.assertNotIn(visit_prep.PENDING_STATE_KEY, at.session_state)
        self.assertEqual(at.session_state[visit_prep.RUNS_STATE_KEY], 0)
        self.assertNotIn("답하고 보고서 만들기", [button.label for button in at.button])

    def test_skipping_the_questions_resumes_with_an_empty_answer(self):
        team = FakeTeam(questions=["언제부터 설사했나요?"])
        at = self.open_page(team)
        self.submit(at, "말티즈가 설사를 해요")
        next(button for button in at.button if button.label == "건너뛰고 바로 만들기").click().run()
        self.assertEqual([answer for _, answer in team.resumes], [""])
        self.assertNotIn("보호자 답변 반영", " ".join(item.value for item in at.success))

    def test_a_question_carried_from_the_chat_fills_the_box(self):
        from streamlit.testing.v1 import AppTest

        with patch.object(settings, "get_openai_api_key", return_value="sk-test"):
            at = AppTest.from_function(page_app, default_timeout=30)
            at.session_state[visit_prep.CONSULTATION_KEY] = "시츄 눈이 빨개요"
            at.run()
        self.assertEqual(at.text_area[0].value, "시츄 눈이 빨개요")

    def test_unchecked_report_is_marked_for_a_person(self):
        at = self.open_page(FakeTeam(passed=False))
        self.submit(at, "말티즈가 설사를 해요")
        self.assertIn("수의사(사람)의 확인", " ".join(item.value for item in at.warning))

    def test_runs_stop_at_the_session_limit(self):
        team = FakeTeam()
        at = self.open_page(team)
        for _ in range(visit_prep.MAX_RUNS_PER_SESSION):
            self.submit(at, "말티즈가 설사를 해요")
        self.submit(at, "말티즈가 설사를 해요")  # still enabled on screen, but disabled when the click reruns
        self.assertEqual(len(team.calls), visit_prep.MAX_RUNS_PER_SESSION)
        self.assertTrue(at.button[0].disabled)

    def test_a_run_in_progress_elsewhere_blocks_a_second_one(self):
        team = FakeTeam()
        at = self.open_page(team)
        lock = visit_prep.team_lock()
        lock.acquire()
        try:
            self.submit(at, "말티즈가 설사를 해요")
        finally:
            lock.release()
        self.assertEqual(team.calls, [])
        self.assertIn("다른 사용자의 보고서", " ".join(item.value for item in at.info))

    def test_a_failed_research_task_shows_in_the_progress(self):
        self.assertEqual(visit_prep.step_line("researcher", {"failures": {"t3": {"kind": "cost", "error": "x"}}}),
                         "조사 하나가 오류로 실패했습니다: 비용 (나머지 조사로 계속합니다)")

    def test_held_report_explains_that_required_research_failed(self):
        at = self.open_page(FakeTeam(passed=False, outcome="held"))
        self.submit(at, "말티즈가 설사를 해요")
        self.assertIn("비슷한 상담 사례 조사가 오류로 실패", " ".join(item.value for item in at.warning))

    def test_urgent_consultation_points_to_a_hospital_first(self):
        at = self.open_page(FakeTeam())
        self.submit(at, "강아지가 경련을 해요")
        self.assertIn("지금 가까운 동물병원에 연락", " ".join(item.value for item in at.error))

    def test_no_api_key_means_no_run(self):
        team = FakeTeam()
        at = self.open_page(team, api_key=None)
        self.submit(at, "말티즈가 설사를 해요")
        self.assertEqual(team.calls, [])


if __name__ == "__main__":
    unittest.main()
