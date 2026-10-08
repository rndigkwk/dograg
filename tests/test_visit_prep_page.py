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
    def __init__(self, passed=True, outcome="complete"):
        self.passed, self.outcome, self.calls, self.run_dirs = passed, outcome, [], []

    def __call__(self, consultation, region, profile, run_dir, on_step):
        self.calls.append((consultation, region, profile))
        getattr(self, "events", []).append("run_team")
        self.run_dirs.append(run_dir)
        on_step("planner", {"plan": [{"kind": "health"}, {"kind": "place"}]})
        on_step("reviewer", {"review": {"passed": self.passed, "unsupported": [] if self.passed else ["x"]}})
        (run_dir / config.REPORT_FILE).write_text(
            "# 방문 준비 보고서\n\n설사 정리 [상담 내용]\n\n사료를 천천히 바꾼 사례 [qa-5250] [qa-5250]", encoding="utf-8")
        findings = {"t1": {"summary": "설사 사례", "key_points": [{"fact": "사료는 10일에 걸쳐 바꾼다", "evidence_id": "qa-5250"}]}}
        return {"review": {"passed": self.passed}, "round": 0 if self.passed else 2, "findings": findings,
                "outcome": self.outcome}


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
