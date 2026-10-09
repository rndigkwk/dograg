"""src/tools/urgency.py: the rules first, then one Decisions call for what they miss."""

import unittest
from unittest.mock import Mock, patch

import httpx

from src.health_safety import URGENT_NOTICE
from src.tools import urgency


def decisions_reply(choice):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"answers": [{"type": "choice", "choice": choice}]}
    return response


class UrgentNoticeTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(urgency.settings, "get_openai_api_key", return_value="test-key")
        patcher.start()
        self.addCleanup(patcher.stop)

    def notice(self, question, reply=None, side_effect=None):
        with patch.object(urgency.httpx, "post", return_value=reply, side_effect=side_effect) as post:
            return urgency.urgent_notice(question), post

    def test_a_rule_match_needs_no_call(self):
        notice, post = self.notice("강아지가 경련을 해요")
        self.assertEqual(notice, URGENT_NOTICE)
        post.assert_not_called()

    def test_only_emergency_now_warns(self):
        question = "중성화 수술한 자리에서 피가 계속 배어 나와요"
        self.assertEqual(self.notice(question, decisions_reply("emergency_now"))[0], URGENT_NOTICE)
        self.assertIsNone(self.notice(question, decisions_reply("see_vet_soon"))[0])
        self.assertIsNone(self.notice(question, decisions_reply("not_urgent"))[0])
        _, post = self.notice(question, decisions_reply("not_urgent"))
        body = post.call_args.kwargs["json"]
        self.assertEqual([c["value"] for c in body["questions"][0]["choices"]], list(urgency.CHOICES))
        self.assertEqual(body["input"], question)

    def test_failure_refusal_or_setting_off_keeps_the_rules_answer(self):
        question = "입술 색이 거무스름하게 변했어요"
        self.assertIsNone(self.notice(question, side_effect=httpx.ConnectTimeout("slow"))[0])
        refusal = Mock(raise_for_status=Mock(), json=Mock(return_value={"answers": [{"type": "refusal"}]}))
        self.assertIsNone(self.notice(question, refusal)[0])
        with patch.dict("os.environ", {"URGENT_SECOND_CHECK": "off"}):
            notice, post = self.notice(question, decisions_reply("emergency_now"))
        self.assertIsNone(notice)
        post.assert_not_called()

    def test_place_and_date_questions_make_no_call(self):
        for question in ("강남구 동물병원 알려줘", "오늘 날짜 알려줘"):
            with self.subTest(question):
                notice, post = self.notice(question, decisions_reply("emergency_now"))
                self.assertIsNone(notice)
                post.assert_not_called()
        # A symptom with a place request is still checked.
        notice, post = self.notice("입술이 거무스름한데 강남구 동물병원 알려줘", decisions_reply("emergency_now"))
        self.assertEqual(notice, URGENT_NOTICE)
        post.assert_called_once()


if __name__ == "__main__":
    unittest.main()
