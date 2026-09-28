import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from langchain_core.runnables import RunnableLambda
from streamlit.testing.v1 import AppTest


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from pages import rag


class HomeFallbackTest(unittest.TestCase):
    def test_home_renders_when_remote_images_are_unavailable(self):
        with patch.object(requests, "get", side_effect=requests.ConnectionError):
            app = AppTest.from_file(str(PROJECT_DIR / "main.py"), default_timeout=30).run()

        self.assertEqual([error.message for error in app.exception], [])
        self.assertTrue(
            any("data:image/svg+xml;base64" in item.value for item in app.markdown),
            "The home hero image should still render without network access.",
        )


class QuestionRoutingTest(unittest.TestCase):
    def test_symptom_and_care_question_stays_on_health_route(self):
        with patch.object(rag, "load_chat_model", return_value=None):
            self.assertEqual(
                rag.classify_question("강아지가 구토하는데 동물병원에 가야 하나요?"),
                "rag",
            )
            self.assertEqual(
                rag.classify_question("구토하면 동물병원에 가야 할지 알려줘"),
                "rag",
            )

    def test_symptom_comparison_stays_on_health_route(self):
        with patch.object(rag, "load_chat_model", return_value=None):
            self.assertEqual(
                rag.classify_question("강아지 구토와 설사 증상을 비교해줘"),
                "rag",
            )

    def test_hospital_list_and_report_comparison_keep_existing_routes(self):
        with patch.object(rag, "load_chat_model", return_value=None):
            self.assertEqual(rag.classify_question("강남구 동물병원 목록 알려줘"), "sql")
            self.assertEqual(
                rag.classify_question("2025 반려동물 보고서의 양육비를 비교해줘"),
                "analysis",
            )


class Gpt6ModelConfigTest(unittest.TestCase):
    def test_gpt6_chat_models_use_provider_default_temperature(self):
        fake_model = RunnableLambda(lambda value: value)
        with patch.object(rag, "get_openai_api_key", return_value="test-key"), patch.object(
            rag, "ChatOpenAI", return_value=fake_model
        ) as constructor:
            rag.load_rag_chain.clear()
            rag.load_rag_chain()
            self.assertEqual(
                constructor.call_args.kwargs,
                {"model": "gpt-6-luna", "api_key": "test-key"},
            )

            constructor.reset_mock()
            rag.load_chat_model.clear()
            rag.load_chat_model()
            self.assertEqual(
                constructor.call_args.kwargs,
                {"model": "gpt-6-luna", "api_key": "test-key"},
            )

        rag.load_rag_chain.clear()
        rag.load_chat_model.clear()


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


if __name__ == "__main__":
    unittest.main()
