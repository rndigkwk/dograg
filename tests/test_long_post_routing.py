"""src/tools/router.py: one keyword in a long consultation post does not decide its route."""

import unittest
from unittest.mock import patch

from src import resources
from src.tools import router

# The shapes of the misrouted validation consultations (scripts/evaluate_long_post_routing.py).
HOSPITAL_STORY = ("제 반려견은 현재 2세이며, 얼마 전 예방접종을 위해 동물병원을 방문하였습니다. 그 과정에서 수의사께서 "
                  "슬개골탈구가 의심된다고 말씀하시며 엑스레이 촬영을 권하셨는데, 수술이 꼭 필요한지 알려주세요.")
WEATHER_STORY = ("현재 5살 된 닥스훈트를 보호하고 있는 견주입니다. 날씨가 더워지면서 최근 일주일 간 제 강아지가 귀를 "
                 "긁는 횟수가 눈에 띄게 증가하였습니다. 귀 안쪽이 빨갛고 냄새도 납니다.")
RAISING_STORY = ("현재 2개월 된 푸들을 양육하고 있습니다. 분양 받은 곳에서는 예방접종이 1차까지 완료되었다고 "
                 "알려주었으나, 원충 구충을 언제 실시했는지 알 수 없어서 다시 해야 하는지 궁금합니다.")


class LongPostRoutingTests(unittest.TestCase):
    def route(self, question):
        with patch.object(resources, "load_chat_model", return_value=object()), \
                patch.object(router, "decide_route", return_value="model") as decide:
            route = router.classify_question(question)
        return route, decide.called

    def test_long_health_stories_go_to_the_model_router_not_a_keyword_shortcut(self):
        for story in (HOSPITAL_STORY, RAISING_STORY):
            self.assertGreater(len(story), router.LONG_POST_CHARS)
            self.assertEqual(self.route(story), ("model", True))

    def test_weather_in_a_health_story_is_not_out_of_scope(self):
        self.assertFalse(router.is_out_of_scope_question(WEATHER_STORY))
        self.assertNotEqual(self.route(WEATHER_STORY)[0], "none")
        self.assertFalse(router.is_out_of_scope_question("날씨 때문인지 강아지가 기침해요"))  # a symptom

    def test_short_requests_keep_their_shortcuts(self):
        self.assertTrue(router.is_out_of_scope_question("오늘 서울 날씨 어때?"))
        self.assertEqual(self.route("오늘 서울 날씨 어때?"), ("none", False))
        self.assertEqual(self.route("강남구 동물병원 알려줘"), ("sql", False))
        self.assertEqual(self.route("반려동물 양육 만족도 현황이 어떻게 돼?"), ("analysis", False))


if __name__ == "__main__":
    unittest.main()
