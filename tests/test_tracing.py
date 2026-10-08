"""Langfuse tracing (src/tracing.py): what leaves the server for one chat run."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from langchain_core.documents import Document
from langchain_core.language_models import FakeListChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src import tracing
from src.chat_graph import run_chat

QUESTION = "우리 초코가 어제부터 설사를 해요 010-1234-5678"
ANSWER = "수분을 충분히 주고 하루 이상 계속되면 병원에 가 보세요"
DOCUMENT = "설사가 지속되면 탈수 위험이 있습니다"


class MaskTests(unittest.TestCase):
    def test_text_is_masked_and_structure_kept(self):
        data = {
            "question": QUESTION, "top_k": 3, "crag": True,
            "messages": [{"role": "user", "content": QUESTION}],
            "trace": [{"step": "health_grade", "kept_ids": ["12", "40"], "decision": "correct"}],
            "documents": [Document(page_content=DOCUMENT, metadata={"id": "12"})],
        }
        masked = tracing.mask_text(data=data)
        self.assertNotIn("설사", json.dumps(masked, ensure_ascii=False))
        self.assertEqual(masked["question"], f"[masked {len(QUESTION)} chars]")
        self.assertEqual((masked["top_k"], masked["crag"]), (3, True))
        self.assertEqual(masked["messages"][0]["role"], "user")
        self.assertEqual(masked["trace"][0], {"step": "health_grade", "kept_ids": ["12", "40"], "decision": "correct"})
        self.assertEqual(tracing.mask_text(data=QUESTION), f"[masked {len(QUESTION)} chars]")

    def test_off_in_tests_without_keys_or_when_disabled(self):
        values = {"LANGFUSE_PUBLIC_KEY": "pk", "LANGFUSE_SECRET_KEY": "sk", "LANGFUSE_TRACING_ENABLED": None}
        with patch.object(tracing.settings, "get_setting", side_effect=values.get):
            self.assertFalse(tracing.enabled())  # this test run itself
            with patch.object(tracing, "_running_tests", return_value=False):
                self.assertTrue(tracing.enabled())
        values["LANGFUSE_TRACING_ENABLED"] = "false"
        with patch.object(tracing.settings, "get_setting", side_effect=values.get),                 patch.object(tracing, "_running_tests", return_value=False):
            self.assertFalse(tracing.enabled())
        with patch.object(tracing.settings, "get_setting", return_value=None):
            self.assertFalse(tracing.enabled())

    def test_feedback_score_overwrites_by_trace(self):
        langfuse = Mock()
        with patch.object(tracing, "client", return_value=langfuse):
            self.assertTrue(tracing.record_feedback("abc", helpful=False))
            self.assertFalse(tracing.record_feedback(None, helpful=True))
        langfuse.create_score.assert_called_once_with(
            name="user_feedback", value=0, data_type="BOOLEAN", trace_id="abc", score_id="abc-user_feedback",
        )
        with patch.object(tracing, "client", return_value=None):
            self.assertFalse(tracing.record_feedback("abc", helpful=True))

    def test_session_id_is_hashed(self):
        self.assertEqual(len(tracing.session_id("abc")), 16)
        self.assertNotEqual(tracing.session_id("abc"), "abc")
        self.assertIsNone(tracing.session_id(None))


def health_tools():
    """A health route whose answer comes from a real LangChain chain, so the callback sees a model call."""
    model = FakeListChatModel(responses=[ANSWER])
    chain = ChatPromptTemplate.from_messages([("human", "{question}\n{context}")]) | model | StrOutputParser()

    def answer(question, docs, **kwargs):
        return chain.invoke({"question": question, "context": DOCUMENT})

    return SimpleNamespace(
        is_date_question=lambda q: False, classify_question=lambda q, chat_history=None: "rag",
        build_rag_search_query=lambda q, h=None: q, is_symptom_and_place_request=lambda q: False,
        infer_rag_filters=Mock(return_value={}),
        retrieve_health=Mock(return_value=[Document(id="12", page_content=DOCUMENT, metadata={})]),
        review_evidence=Mock(return_value=SimpleNamespace(feedback="", useful_ids=["12"], sufficient=True)),
        generate_health_answer=answer, detect_urgent_sign=lambda q: None,
    )


class TraceExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from langfuse import Langfuse

        # One client per public key: Langfuse reuses the first client's exporter for the same key.
        cls.exporter = InMemorySpanExporter()
        cls.client = Langfuse(
            public_key="pk-lf-test", secret_key="sk-lf-test", base_url="http://localhost:9",
            mask=tracing.mask_text, span_exporter=cls.exporter, flush_at=1,
        )

    @classmethod
    def tearDownClass(cls):
        cls.client.shutdown()

    def setUp(self):
        self.exporter.clear()
        patcher = patch.object(tracing, "client", return_value=self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def exported(self):
        self.client.flush()
        return self.exporter.get_finished_spans()

    def test_one_run_sends_structure_and_no_text(self):
        result = run_chat(health_tools(), QUESTION, top_k=1, crag=True, session_id="browser-session")
        self.assertEqual(result["answer"], ANSWER)
        spans = self.exported()
        names = {span.name for span in spans}
        self.assertIn("chat", names)
        self.assertTrue(any("health" in name for name in names), names)  # graph nodes from the callback

        sent = json.dumps([dict(span.attributes) for span in spans], ensure_ascii=False)
        for secret in ("초코", "설사", "010-1234-5678", "수분을", "탈수"):
            self.assertNotIn(secret, sent)

        [root] = [span for span in spans if span.name == "chat"]
        self.assertEqual(result["trace_id"], format(root.context.trace_id, "032x"))  # for the feedback score
        output = json.loads(root.attributes["langfuse.observation.output"])
        self.assertEqual(output["route"], "rag")
        self.assertEqual(output["trace"][0]["kept_ids"], ["12"])
        self.assertEqual(output["question_chars"], len(QUESTION))
        self.assertEqual(root.attributes["session.id"], tracing.session_id("browser-session"))
        self.assertEqual(root.attributes["langfuse.trace.tags"], ("chat",))

    def test_a_visit_prep_team_run_is_its_own_tagged_trace_without_text(self):
        import tempfile
        from pathlib import Path

        from team import main as team_main
        from team.core import config
        from team.core.schemas import VisitTask
        from team.graph import nodes
        from tests.test_visit_team import (
            FakeLLM,
            FakeResearcher,
            FakeWriter,
            judge_with,
        )

        consultation = "우리 초코가 어제부터 설사를 해요 010-1234-5678"
        tasks = [VisitTask(kind="health", query="설사", angle="a")]
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(config, "llm", return_value=FakeLLM(tasks)), patch.object(config, "review_llm"), \
                patch.object(nodes, "create_researcher", side_effect=FakeResearcher), \
                patch.object(nodes, "build_judge", side_effect=judge_with([])), \
                patch.object(nodes, "build_verifier"), patch.object(nodes, "recheck_unsupported", return_value=0), \
                patch.object(team_main, "create_writer", side_effect=FakeWriter):
            team_main.run(consultation, run_dir=Path(directory), session=tracing.session_id("browser-session"))
        spans = self.exported()
        [root] = [span for span in spans if span.name == "visit-prep"]
        self.assertEqual(root.attributes["langfuse.trace.tags"], ("visit-prep",))
        self.assertEqual(root.attributes["session.id"], tracing.session_id("browser-session"))
        record = json.loads(root.attributes["langfuse.observation.output"])
        self.assertEqual((record["status"], record["outcome"], record["kind"]), (config.PASSED, "complete", ["health"]))
        sent = json.dumps([dict(span.attributes) for span in spans], ensure_ascii=False)
        for secret in ("초코", "설사를", "010-1234-5678"):
            self.assertNotIn(secret, sent)


    def test_a_failing_run_is_still_recorded(self):
        tools = health_tools()
        tools.retrieve_health = Mock(side_effect=RuntimeError("down"))
        with self.assertRaises(RuntimeError):
            run_chat(tools, QUESTION, top_k=1, crag=True)
        [root] = [span for span in self.exported() if span.name == "chat"]
        self.assertEqual(json.loads(root.attributes["langfuse.observation.output"])["error"], "RuntimeError")


class ReleaseTests(unittest.TestCase):
    def git_dir(self, head: str, refs: dict[str, str] | None = None, packed: str | None = None):
        import tempfile
        from pathlib import Path

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        git = Path(directory.name) / ".git"
        git.mkdir()
        (git / "HEAD").write_text(head, encoding="utf-8")
        for ref, sha in (refs or {}).items():
            (git / ref).parent.mkdir(parents=True, exist_ok=True)
            (git / ref).write_text(sha + "\n", encoding="utf-8")
        if packed:
            (git / "packed-refs").write_text(packed, encoding="utf-8")
        patcher = patch.object(tracing.settings, "PROJECT_DIR", Path(directory.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def release(self, configured=None):
        with patch.object(tracing.settings, "get_setting",
                          side_effect=lambda name: configured if name == "LANGFUSE_RELEASE" else None):
            return tracing.release()

    def test_release_is_the_checked_out_commit(self):
        self.git_dir("ref: refs/heads/main\n", {"refs/heads/main": "2d7c606b1234"})
        self.assertEqual(self.release(), "2d7c606")
        self.assertEqual(self.release("2026-10-08"), "2026-10-08")  # LANGFUSE_RELEASE wins

    def test_release_from_packed_refs_or_a_detached_head(self):
        self.git_dir("ref: refs/heads/main\n", packed="# pack-refs\nabcdef1234 refs/heads/main\n")
        self.assertEqual(self.release(), "abcdef1")
        self.git_dir("0123456789abcdef\n")
        self.assertEqual(self.release(), "0123456")

    def test_no_git_folder_means_no_release(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory, patch.object(tracing.settings, "PROJECT_DIR", Path(directory)):
            self.assertIsNone(self.release())

    def test_sample_rate_defaults_to_all_and_is_clamped(self):
        for configured, expected in ((None, 1.0), ("0.2", 0.2), ("5", 1.0), ("-1", 0.0), ("many", 1.0)):
            with patch.object(tracing.settings, "get_setting", return_value=configured):
                self.assertEqual(tracing.sample_rate(), expected)


if __name__ == "__main__":
    unittest.main()
