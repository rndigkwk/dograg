"""src/tools/router.py: the Decisions API as the fallback for questions the keyword rules cannot decide."""

import unittest
from unittest.mock import Mock, patch

import httpx

from src import resources, settings
from src.tools import router

UNDECIDED = "닭 뼈를 삼켰는데 가까운 동물병원에 갈 수 없어요"  # health + hospital lookup: rules defer


def response(answer, status=200):
    return httpx.Response(status, json={"answers": [answer]}, request=httpx.Request("POST", router.DECISIONS_URL))


class ChatRouter:
    """Stands in for the chat model: records whether the structured-output router ran."""

    def __init__(self, route="sql"):
        self.route, self.calls = route, 0

    def with_structured_output(self, schema):
        def invoke(value):
            self.calls += 1
            return router.RouteDecision(route=self.route)

        from langchain_core.runnables import RunnableLambda

        return RunnableLambda(invoke)


class DecisionsRouterTests(unittest.TestCase):
    def classify(self, post, setting=None, question=UNDECIDED):
        chat = ChatRouter()
        values = {"ROUTER_FALLBACK": setting}
        with patch.object(resources, "load_chat_model", return_value=chat), \
                patch.object(settings, "get_setting", side_effect=values.get), \
                patch.object(settings, "get_openai_api_key", return_value="sk-test"), \
                patch.object(router.httpx, "post", post):
            return router.classify_question(question), chat.calls

    def test_the_decisions_choice_is_used_without_the_chat_model(self):
        post = Mock(return_value=response({"type": "choice", "choice": "rag", "confidence": 0.9}))
        self.assertEqual(self.classify(post), ("rag", 0))
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["questions"][0]["type"], "choice")
        self.assertEqual([c["value"] for c in body["questions"][0]["choices"]], list(router.ROUTES))
        self.assertIn(UNDECIDED, body["input"])
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer sk-test"})

    def test_a_refusal_an_error_or_a_timeout_falls_back_to_the_chat_model(self):
        for post in (Mock(return_value=response({"type": "refusal"})),
                     Mock(return_value=response({"type": "choice", "choice": "rag"}, status=500)),
                     Mock(side_effect=httpx.ReadTimeout("slow")),
                     Mock(return_value=response({"type": "choice", "choice": "weather"}))):
            self.assertEqual(self.classify(post), ("sql", 1))

    def test_rules_decide_first_and_the_setting_can_turn_decisions_off(self):
        post = Mock(side_effect=AssertionError("rules decide this one"))
        self.assertEqual(self.classify(post, question="강아지가 이틀째 설사를 해요"), ("rag", 0))
        post = Mock(side_effect=AssertionError("ROUTER_FALLBACK=llm"))
        self.assertEqual(self.classify(post, setting="llm"), ("sql", 1))

    def test_no_api_key_means_no_call(self):
        with patch.object(settings, "get_openai_api_key", return_value=None), \
                patch.object(router.httpx, "post", side_effect=AssertionError("no key")):
            self.assertIsNone(router.decide_route(UNDECIDED))


if __name__ == "__main__":
    unittest.main()
