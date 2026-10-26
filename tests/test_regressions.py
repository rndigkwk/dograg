import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from langchain_core.runnables import RunnableLambda
from streamlit.testing.v1 import AppTest

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from src import resources, settings
from src.private_data import needs_private_data
from src.tools import health, router

# main.py shows only the "moved" notice unless STREAMLIT_FULL_APP is set (P5, 2026-10-23);
# these tests drive the full Streamlit app.
os.environ.setdefault("STREAMLIT_FULL_APP", "1")

class HomeFallbackTest(unittest.TestCase):
    @needs_private_data
    def test_home_renders_when_remote_images_are_unavailable(self):
        import streamlit as st

        st.cache_data.clear()  # another test may already have cached a downloaded hero image
        with patch.object(requests, "get", side_effect=requests.ConnectionError):
            app = AppTest.from_file(str(PROJECT_DIR / "main.py"), default_timeout=30).run()

        self.assertEqual([error.message for error in app.exception], [])
        self.assertTrue(
            any("data:image/svg+xml;base64" in item.value for item in app.markdown),
            "The home hero image should still render without network access.",
        )


class QuestionRoutingTest(unittest.TestCase):
    def test_symptom_and_care_question_stays_on_health_route(self):
        with patch.object(resources, "load_chat_model", return_value=None):
            self.assertEqual(
                router.classify_question("강아지가 구토하는데 동물병원에 가야 하나요?"),
                "rag",
            )
            self.assertEqual(
                router.classify_question("구토하면 동물병원에 가야 할지 알려줘"),
                "rag",
            )

    def test_symptom_comparison_stays_on_health_route(self):
        with patch.object(resources, "load_chat_model", return_value=None):
            self.assertEqual(
                router.classify_question("강아지 구토와 설사 증상을 비교해줘"),
                "rag",
            )

    def test_hospital_list_and_report_comparison_keep_existing_routes(self):
        with patch.object(resources, "load_chat_model", return_value=None):
            self.assertEqual(router.classify_question("강남구 동물병원 목록 알려줘"), "sql")
            self.assertEqual(
                router.classify_question("2025 반려동물 보고서의 양육비를 비교해줘"),
                "analysis",
            )


class RouterConflictTest(unittest.TestCase):
    """Keyword rules decide only single-signal questions; conflicts go to the LLM router."""

    def setUp(self):
        # These check the rules hand conflicts to the model fallback; the Decisions call before the
        # chat model (tests/test_router_decisions.py) must not reach the network here.
        decisions = patch.object(router, "decide_route", return_value=None)
        decisions.start()
        self.addCleanup(decisions.stop)

    @staticmethod
    def fake_router(route):
        decision = SimpleNamespace(route=route)
        structured = Mock(return_value=decision)
        model = Mock()
        model.with_structured_output.return_value = RunnableLambda(lambda _: structured())
        return model, structured

    def test_health_story_mentioning_nearby_hospital_goes_to_llm(self):
        model, llm_router = self.fake_router("rag")
        with patch.object(resources, "load_chat_model", return_value=model):
            route = router.classify_question("닭 뼈를 삼켰는데 가까운 동물병원에 갈 수 없는 상황이에요")
        self.assertEqual(route, "rag")
        llm_router.assert_called_once()

    def test_report_question_mentioning_hospitals_goes_to_llm(self):
        model, llm_router = self.fake_router("analysis")
        with patch.object(resources, "load_chat_model", return_value=model):
            route = router.classify_question("의료·보험서비스 연구에서 동물병원 소비자가 지불한 평균 가격은?")
        self.assertEqual(route, "analysis")
        llm_router.assert_called_once()

    def test_single_signal_questions_skip_the_llm(self):
        model, llm_router = self.fake_router("none")
        with patch.object(resources, "load_chat_model", return_value=model):
            self.assertEqual(router.classify_question("강남구 동물병원 목록 알려줘"), "sql")
            self.assertEqual(router.classify_question("강아지 배가 부풀고 흉터가 생겼어요"), "rag")
            self.assertEqual(router.classify_question("반려동물 장묘 서비스 이용 실태"), "analysis")
        llm_router.assert_not_called()

    def test_without_model_conflicts_keep_previous_priority(self):
        with patch.object(resources, "load_chat_model", return_value=None):
            self.assertEqual(router.classify_question("닭 뼈를 삼켰는데 가까운 동물병원에 갈 수 없어요"), "sql")


class Gpt6ModelConfigTest(unittest.TestCase):
    def test_gpt6_chat_models_use_provider_default_temperature(self):
        fake_model = RunnableLambda(lambda value: value)
        # The RAG chain (health) and the shared chat model (resources) each build ChatOpenAI.
        with patch.object(settings, "get_openai_api_key", return_value="test-key"), patch.object(
            health, "ChatOpenAI", return_value=fake_model
        ) as constructor, patch.object(resources, "ChatOpenAI", new=constructor):
            health.load_rag_chain.clear()
            with patch.object(settings, "get_setting", return_value=None):
                health.load_rag_chain()
            # No temperature; the answer model reasons at "low" (2026-10-22) unless configured, with a time
            # limit and one retry (2026-10-23); base_url is None outside the OpenAI outage drill.
            self.assertEqual(
                constructor.call_args.kwargs,
                {"model": "gpt-6-luna", "api_key": "test-key", "reasoning_effort": "low", "timeout": 45, "max_retries": 1,
                 "base_url": None},
            )
            health.load_rag_chain.clear()
            with patch.object(settings, "get_setting", return_value="medium"):
                health.load_rag_chain()
            self.assertEqual(constructor.call_args.kwargs["reasoning_effort"], "medium")

            constructor.reset_mock()
            resources.load_chat_model.clear()
            resources.load_chat_model()
            self.assertEqual(
                constructor.call_args.kwargs,
                {"model": "gpt-6-luna", "api_key": "test-key", "timeout": 30, "max_retries": 1, "base_url": None},
            )

        health.load_rag_chain.clear()
        resources.load_chat_model.clear()

    def test_evidence_review_skips_reasoning_unless_configured(self):
        values = {"CRAG_REVIEW_REASONING_EFFORT": None}
        with patch.object(settings, "get_openai_api_key", return_value="test-key"), \
                patch.object(settings, "get_setting", side_effect=values.get), \
                patch.object(resources, "ChatOpenAI") as constructor:
            resources.load_review_model.clear()
            resources.load_review_model()
            self.assertEqual(constructor.call_args.kwargs["reasoning_effort"], "none")
            values["CRAG_REVIEW_REASONING_EFFORT"] = "low"
            resources.load_review_model.clear()
            resources.load_review_model()
            self.assertEqual(constructor.call_args.kwargs["reasoning_effort"], "low")
        resources.load_review_model.clear()


class ChromaIsolationTest(unittest.TestCase):
    def test_smoke_test_uses_disposable_copy_of_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "chroma"
            source.mkdir()
            (source / "chroma.sqlite3").write_bytes(b"original")
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_DIR / "tests" / "chroma_smoke.py"),
                    "--source",
                    str(source),
                    "--check-copy-only",
                ],
                cwd=PROJECT_DIR,
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("isolated copy verified", result.stdout)
            self.assertEqual((source / "chroma.sqlite3").read_bytes(), b"original")
            self.assertEqual(sorted(path.name for path in source.iterdir()), ["chroma.sqlite3"])

    def local_copy(self, temp_dir):
        source = Path(temp_dir) / "chroma_db"
        source.mkdir()
        (source / "chroma.sqlite3").write_bytes(b"v1")
        copy = Path(temp_dir) / "runtime"
        patches = [patch.object(resources, name, value) for name, value in
                   (("CHROMA_DIR", source), ("SOURCE_CHROMA_DIR", source), ("LOCAL_CHROMA_COPY", copy))]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return source, copy

    def test_local_runs_open_a_copy_refreshed_when_the_source_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source, copy = self.local_copy(temp_dir)
            with patch.object(settings, "deployed", return_value=False):
                opened = resources.chroma_dir()
                self.assertEqual(opened, copy / "chroma_db")
                (opened / "chroma.sqlite3").write_bytes(b"written by chroma")
                self.assertEqual(resources.chroma_dir(), opened)  # unchanged source: no new copy
                self.assertEqual((opened / "chroma.sqlite3").read_bytes(), b"written by chroma")
                (source / "chroma.sqlite3").write_bytes(b"v2 rebuilt")
                self.assertEqual((resources.chroma_dir() / "chroma.sqlite3").read_bytes(), b"v2 rebuilt")
            self.assertEqual((source / "chroma.sqlite3").read_bytes(), b"v2 rebuilt")

    def test_deployed_app_and_redirected_dirs_open_the_folder_itself(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source, copy = self.local_copy(temp_dir)
            with patch.object(settings, "deployed", return_value=True):
                self.assertEqual(resources.chroma_dir(), source)
            with patch.object(settings, "deployed", return_value=False), \
                    patch.object(resources, "CHROMA_DIR", Path(temp_dir) / "script_copy"):
                self.assertEqual(resources.chroma_dir(), Path(temp_dir) / "script_copy")
            self.assertFalse(copy.exists())


if __name__ == "__main__":
    unittest.main()
