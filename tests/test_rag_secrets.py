import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from app_pages import rag
from src import settings
from src.tools import health, history


class RagSecretsTest(unittest.TestCase):
    def test_reads_openai_key_from_streamlit_secrets_when_env_is_missing(self):
        # Use a temporary secrets file: the real one is not in git, so CI has none.
        with tempfile.TemporaryDirectory() as directory:
            secrets = Path(directory) / ".streamlit" / "secrets.toml"
            secrets.parent.mkdir()
            secrets.write_text('OPENAI_API_KEY = "sk-test-from-secrets"\n', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=False), patch.object(settings, "PROJECT_DIR", Path(directory)):
                os.environ.pop("OPENAI_API_KEY", None)
                self.assertEqual(settings.get_openai_api_key(), "sk-test-from-secrets")

    def test_environment_key_takes_precedence_and_missing_file_returns_none(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(settings, "PROJECT_DIR", Path(directory)):
            with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-from-env"}):
                self.assertEqual(settings.get_openai_api_key(), "sk-test-from-env")
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("OPENAI_API_KEY", None)
                self.assertIsNone(settings.get_openai_api_key())

    def test_formats_evidence_row_for_streamlit_display(self):
        row = {
            "meta.lifeCycle": "adult",
            "meta.department": "internal",
            "meta.disease": "vomiting",
            "qa.input": "My dog keeps vomiting.",
            "qa.output": "Repeated vomiting should be checked by a vet.",
        }

        item = rag.format_evidence_row(row, 0)

        self.assertEqual(item["title"], "1. adult / internal / vomiting")
        self.assertNotIn("My dog keeps vomiting.", item["body"])
        self.assertIn("Repeated vomiting should be checked by a vet.", item["body"])

    def test_builds_filter_context_for_prompt(self):
        filters = {
            "life_cycle": "adult",
            "department": "internal",
            "disease": "vomiting",
        }

        context = health.build_filter_context(filters)

        self.assertIn("adult", context)
        self.assertIn("internal", context)
        self.assertIn("vomiting", context)

    def test_omits_all_filters_from_prompt_context(self):
        filters = {
            "life_cycle": health.ALL_FILTER,
            "department": health.ALL_FILTER,
            "disease": health.ALL_FILTER,
        }

        context = health.build_filter_context(filters)

        self.assertIn("없음", context)

    def test_builds_rag_search_query_from_question(self):
        query = history.build_rag_search_query("eye discharge")

        self.assertEqual(query, "eye discharge")

    def test_builds_metadata_filter_for_vector_search(self):
        filters = {
            "life_cycle": "senior",
            "department": "orthopedics",
            "disease": "fracture",
        }

        metadata_filter = health.build_metadata_filter(filters)

        self.assertEqual(
            metadata_filter,
            {
                "$and": [
                    {"meta.lifeCycle": "senior"},
                    {"meta.department": "orthopedics"},
                    {"meta.disease": "fracture"},
                ]
            },
        )

    def test_etc_disease_filter_searches_etc_and_none_metadata(self):
        filters = {
            "life_cycle": health.ALL_FILTER,
            "department": health.ALL_FILTER,
            "disease": health.ETC_DISEASE,
        }

        metadata_filter = health.build_metadata_filter(filters)

        self.assertEqual(
            metadata_filter,
            {
                "$or": [
                    {"meta.disease": health.ETC_DISEASE},
                    {"meta.disease": health.NONE_DISEASE},
                ]
            },
        )


if __name__ == "__main__":
    unittest.main()
