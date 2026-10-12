import unittest
from unittest.mock import patch

from src import resources
from src.tools import general


class GeneralReplyTests(unittest.TestCase):
    """Small talk gets fixed replies about this service; no model is called (docs/curriculum-fit.md)."""

    def test_fixed_replies_without_a_model(self):
        with patch.object(resources, "load_chat_model", side_effect=AssertionError("no model call")):
            self.assertEqual(general.answer_without_tool("고마워요"), general.THANKS_REPLY)
            self.assertEqual(general.answer_without_tool("너 이름이 뭐야?"), general.SERVICE_GUIDE)
            self.assertEqual(general.answer_without_tool("안녕하세요"), general.GREETING_REPLY)
            self.assertEqual(general.answer_without_tool("파이썬 코드 짜줘"), general.OUT_OF_SCOPE_REPLY)

    def test_no_reply_claims_another_ability(self):
        for reply in (general.SERVICE_GUIDE, general.GREETING_REPLY, general.THANKS_REPLY, general.OUT_OF_SCOPE_REPLY):
            for claim in ("코딩", "번역", "ChatGPT"):
                self.assertNotIn(claim, reply)


if __name__ == "__main__":
    unittest.main()
