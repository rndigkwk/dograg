"""src/tools/history.py: recent turns word for word, older turns folded into a running summary."""

import unittest

from src.tools import history


def conversation(turns: int) -> list[dict]:
    messages = []
    for number in range(1, turns + 1):
        messages += [{"role": "user", "content": f"질문 {number}"}, {"role": "assistant", "content": f"답변 {number}"}]
    return messages


class FakeSummarizer:
    def __init__(self):
        self.calls = []

    def __call__(self, previous, messages):
        self.calls.append((previous, [message["content"] for message in messages]))
        return f"{previous}+{messages[0]['content']}~{messages[-1]['content']}"


class HistorySummaryTests(unittest.TestCase):
    def test_short_conversations_are_passed_as_they_are(self):
        summarize, memory = FakeSummarizer(), {}
        messages = conversation(9)  # up to window + batch turns: no summary yet
        self.assertEqual(history.history_with_summary(messages, memory, summarize), messages)
        self.assertEqual(summarize.calls, [])
        self.assertFalse(history.summary_due(messages, memory))

    def test_older_turns_are_folded_in_batches_and_nothing_is_dropped(self):
        summarize, memory = FakeSummarizer(), {}
        messages = conversation(10)
        self.assertTrue(history.summary_due(messages, memory))
        shown = history.history_with_summary(messages, memory, summarize)
        # Turns 1-4 go into the summary; the last 6 turns stay word for word
        self.assertEqual(summarize.calls, [("", ["질문 1", "답변 1", "질문 2", "답변 2", "질문 3", "답변 3", "질문 4", "답변 4"])])
        self.assertEqual(shown[0], {"role": history.SUMMARY_ROLE, "content": "+질문 1~답변 4"})
        self.assertEqual(shown[1:], messages[8:])
        # The next two questions reuse the summary without a model call
        for turns in (11, 12, 13):
            history.history_with_summary(conversation(turns), memory, summarize)
        self.assertEqual(len(summarize.calls), 1)
        # Past the batch again: the previous summary is passed on, only new turns are added
        shown = history.history_with_summary(conversation(14), memory, summarize)
        self.assertEqual(summarize.calls[1], ("+질문 1~답변 4", ["질문 5", "답변 5", "질문 6", "답변 6", "질문 7", "답변 7",
                                                               "질문 8", "답변 8"]))
        self.assertEqual(shown[1]["content"], "질문 9")

    def test_a_shorter_conversation_starts_over(self):
        summarize, memory = FakeSummarizer(), {}
        history.history_with_summary(conversation(10), memory, summarize)
        self.assertEqual(history.history_with_summary(conversation(2), memory, summarize), conversation(2))
        self.assertEqual(memory, {})

    def test_the_summary_reaches_the_prompts_but_not_the_search_query(self):
        shown = [{"role": history.SUMMARY_ROLE, "content": "어제 피검사에서 간 수치가 높았다"},
                 {"role": "user", "content": "간식은 뭘 줘도 되나요?"}]
        self.assertIn("이전 대화 요약: 어제 피검사에서 간 수치가 높았다", history.format_chat_history(shown))
        self.assertEqual(history.build_rag_search_query("사료는요?", shown), "간식은 뭘 줘도 되나요?\n사료는요?")


class MemorySearchQueryTests(unittest.TestCase):
    """Day52: in a long conversation the summary's condition reaches the health search query."""

    def test_without_a_summary_the_usual_query_is_kept_and_no_model_is_called(self):
        from unittest.mock import patch

        from src import resources

        recent = [{"role": "user", "content": "간식은 뭘 줘도 되나요?"}]
        with patch.object(resources, "load_chat_model", side_effect=AssertionError("no model call")):
            self.assertEqual(history.memory_search_query("사료는요?", recent), "간식은 뭘 줘도 되나요?\n사료는요?")

    def test_with_a_summary_the_model_rewrites_the_query(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        from src import resources

        model = Mock()
        model.bind.return_value.invoke.return_value = SimpleNamespace(content=" 췌장염 퇴원 후  기름진 음식 급여 시기 ")
        shown = [{"role": history.SUMMARY_ROLE, "content": "슈나우저가 췌장염으로 입원했다가 어제 퇴원했다"},
                 {"role": "user", "content": "목욕은 얼마나 자주?"}]
        with patch.object(resources, "load_chat_model", return_value=model):
            query = history.memory_search_query("기름진 음식은 언제부터 줘도 되나요?", shown)
        self.assertEqual(query, "췌장염 퇴원 후 기름진 음식 급여 시기")
        prompt = model.bind.return_value.invoke.call_args.args[0][1][1]
        self.assertIn("췌장염으로 입원", prompt)  # the summary goes to the rewrite
        model.bind.return_value.invoke.side_effect = RuntimeError("API down")
        with patch.object(resources, "load_chat_model", return_value=model):  # a failed rewrite keeps the usual query
            self.assertEqual(history.memory_search_query("기름진 음식은?", shown), "목욕은 얼마나 자주?\n기름진 음식은?")


if __name__ == "__main__":
    unittest.main()
