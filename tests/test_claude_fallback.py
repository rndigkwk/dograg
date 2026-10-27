"""src/resources.py with_claude_fallback: a call OpenAI fails goes once to Claude."""

import unittest
from unittest.mock import patch

import anthropic
import httpx
import openai
from langchain_core.language_models import FakeListChatModel
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel

from src import model_outage, resources
from src.supabase_store import Breaker

KEYS = {"ANTHROPIC_API_KEY": "test-key", "ANTHROPIC_WORKSPACE_ID": "test-workspace"}


def _error(kind, status):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
    return kind("provider said no", response=response, body=None)


def failing(error):
    def call(_):
        raise error
    return RunnableLambda(call)


def setting(name):
    return KEYS.get(name)


class FallbackWiringTests(unittest.TestCase):
    def test_without_an_anthropic_key_the_model_is_unchanged(self):
        model = FakeListChatModel(responses=["openai"])
        with patch.object(resources.settings, "get_setting", return_value=None):
            self.assertIs(resources.with_claude_fallback(model, 20), model)

    def test_claude_haiku_without_thinking_and_with_the_workspace_header(self):
        with patch.object(resources.settings, "get_setting", side_effect=setting):
            wrapped = resources.with_claude_fallback(FakeListChatModel(responses=["openai"]), 20)
        claude = wrapped.fallbacks[0]
        self.assertEqual(claude.model, resources.FALLBACK_MODEL_NAME)
        self.assertEqual(claude.thinking, {"type": "disabled"})
        self.assertEqual(claude.default_headers, {"anthropic-workspace-id": "test-workspace"})
        self.assertEqual(claude.default_request_timeout, 20)

    def test_openai_is_not_retried_when_claude_is_behind_it(self):
        with patch.object(resources.settings, "get_setting", side_effect=setting):
            self.assertEqual(resources.openai_max_retries(), 0)
        with patch.object(resources.settings, "get_setting", return_value=None):
            self.assertEqual(resources.openai_max_retries(), resources.MODEL_MAX_RETRIES)

    def test_the_outage_drill_points_openai_at_nothing(self):
        with patch.object(resources.settings, "get_setting", return_value="openai"):
            self.assertEqual(resources.openai_base_url(), resources.UNREACHABLE_OPENAI_URL)
        for value in (None, "supabase"):
            with patch.object(resources.settings, "get_setting", return_value=value):
                self.assertIsNone(resources.openai_base_url())


class WrappedModelTests(unittest.TestCase):
    """Each test with its own breaker on a clock it moves."""

    def setUp(self):
        self.now = 0.0
        self.breaker = Breaker(cooldown=resources.OPENAI_BREAKER_SECONDS, clock=lambda: self.now, name="OpenAI call",
                               instead="Claude alone")
        patcher = patch.object(resources, "load_openai_breaker", return_value=self.breaker)
        patcher.start()
        self.addCleanup(patcher.stop)

    def wrap(self, primary, claude):
        with patch.object(resources.settings, "get_setting", side_effect=setting), \
                patch("langchain_anthropic.ChatAnthropic", return_value=claude):
            return resources.with_claude_fallback(primary, 20)


class FallbackBehaviourTests(WrappedModelTests):
    def test_rate_limit_timeout_and_server_errors_go_to_claude(self):
        errors = [_error(openai.RateLimitError, 429), _error(openai.InternalServerError, 500),
                  openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com"))]
        for error in errors:
            with self.subTest(type(error).__name__):
                model = self.wrap(failing(error), FakeListChatModel(responses=["claude"]))
                self.assertEqual(model.invoke("질문").content, "claude")

    def test_a_request_openai_rejects_stays_an_error(self):
        model = self.wrap(failing(_error(openai.BadRequestError, 400)), FakeListChatModel(responses=["claude"]))
        with self.assertRaises(openai.BadRequestError):
            model.invoke("질문")

    def test_when_claude_fails_too_the_openai_error_still_shows_the_search(self):
        quota = openai.RateLimitError(
            "Error code: 429 - {'type': 'insufficient_quota'}",
            response=httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com")), body=None)
        bad_key = anthropic.AuthenticationError(
            "invalid x-api-key", response=httpx.Response(401, request=httpx.Request("POST", "https://api.anthropic.com")),
            body=None)
        model = self.wrap(failing(quota), failing(bad_key))
        with self.assertRaises(openai.RateLimitError) as raised:
            model.invoke("질문")
        self.assertEqual(model_outage.outage_kind(raised.exception), "quota")

    def test_structured_output_is_asked_of_claude_as_well(self):
        from langchain_anthropic import ChatAnthropic
        from langchain_core.runnables import RunnableWithFallbacks
        from langchain_openai import ChatOpenAI

        class Verdict(BaseModel):
            ok: bool

        with patch.object(resources.settings, "get_setting", side_effect=setting):
            model = resources.with_claude_fallback(ChatOpenAI(model="gpt-test", api_key="test"), 20)
        structured = model.with_structured_output(Verdict)
        self.assertIsInstance(structured, RunnableWithFallbacks)
        bound = structured.fallbacks[0].first
        self.assertIsInstance(getattr(bound, "bound", bound), ChatAnthropic)
        self.assertIs(structured.breaker, self.breaker)


class OpenAIBreakerTests(WrappedModelTests):
    """After a call fails over to Claude, Claude alone answers for OPENAI_BREAKER_SECONDS."""

    def counting(self, error):
        self.openai_calls = 0

        def call(_):
            self.openai_calls += 1
            raise error
        return RunnableLambda(call)

    def test_after_a_timeout_openai_is_skipped_until_the_cooldown_ends(self):
        timeout = openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com"))
        model = self.wrap(self.counting(timeout), FakeListChatModel(responses=["claude"]))
        with self.assertLogs("src.supabase_store", level="WARNING") as logs:
            self.assertEqual(model.invoke("질문").content, "claude")
        self.assertIn("OpenAI call failed; using Claude alone for 120s", logs.output[0])
        for call in (lambda: model.invoke("질문").content, lambda: "".join(c.content for c in model.stream("질문"))):
            self.assertEqual(call(), "claude")
        self.assertEqual(self.openai_calls, 1)
        self.now = resources.OPENAI_BREAKER_SECONDS + 1
        with self.assertLogs("src.supabase_store", level="WARNING"):
            model.invoke("질문")
        self.assertEqual(self.openai_calls, 2)

    def test_an_answered_call_or_a_rejected_request_leaves_openai_in_use(self):
        self.wrap(FakeListChatModel(responses=["openai"]), FakeListChatModel(responses=["claude"])).invoke("질문")
        with self.assertRaises(openai.BadRequestError):
            self.wrap(failing(_error(openai.BadRequestError, 400)), FakeListChatModel(responses=["claude"])).invoke("질문")
        self.assertFalse(self.breaker.open)

    def test_claude_failing_while_openai_is_skipped_still_shows_the_search(self):
        self.breaker.trip()
        bad_key = anthropic.AuthenticationError(
            "invalid x-api-key", response=httpx.Response(401, request=httpx.Request("POST", "https://api.anthropic.com")),
            body=None)
        model = self.wrap(failing(_error(openai.RateLimitError, 429)), failing(bad_key))
        with self.assertRaises(anthropic.AuthenticationError) as raised:
            model.invoke("질문")
        self.assertEqual(model_outage.outage_kind(raised.exception), "unavailable")


if __name__ == "__main__":
    unittest.main()
