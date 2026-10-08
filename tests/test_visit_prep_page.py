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
    def __init__(self, passed=True):
        self.passed, self.calls, self.run_dirs = passed, [], []

    def __call__(self, consultation, region, profile, run_dir, on_step):
        self.calls.append((consultation, region, profile))
        self.run_dirs.append(run_dir)
        on_step("planner", {"plan": [{"kind": "health"}, {"kind": "place"}]})
        on_step("reviewer", {"review": {"passed": self.passed, "unsupported": [] if self.passed else ["x"]}})
        (run_dir / config.REPORT_FILE).write_text("# 방문 준비 보고서\n\n설사 정리", encoding="utf-8")
        return {"review": {"passed": self.passed}, "round": 0 if self.passed else 2}


class VisitPrepPageTests(unittest.TestCase):
    def open_page(self, team, api_key="sk-test"):
        patches = [patch.object(visit_prep, "run_team", side_effect=team),
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
