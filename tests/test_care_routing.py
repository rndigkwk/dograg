"""src/tools/router.py: everyday care questions are health questions, not small talk or report statistics."""

import unittest
from unittest.mock import patch

from src import resources
from src.tools import router


class CareRoutingTests(unittest.TestCase):
    def route(self, question):
        with patch.object(resources, "load_chat_model", return_value=object()), \
                patch.object(router, "decide_route", return_value="model") as decide:
            route = router.classify_question(question)
        return route, decide.called

    def test_care_questions_go_to_the_health_answer_without_the_model(self):
        for question in ("새 간식을 사려는데 어떤 걸 고르면 좋을까요?", "사료를 바꾸려면 어떻게 섞어서 줘야 해요?",
                         "우리 강아지가 밤에 자꾸 짖는데 어떻게 하죠?", "강아지 하네스랑 목줄 중에 뭐가 좋아요?"):
            self.assertEqual(self.route(question), ("rag", False), question)

    def test_care_words_with_a_place_request_still_search_places(self):
        self.assertEqual(self.route("강남구 애견미용 알려줘")[0], "sql")
        self.assertNotEqual(self.route("강아지 산책하기 좋은 공원 어디 있어?")[0], "rag")

    def test_obesity_and_checkups_are_statistics_only_with_a_statistics_word(self):
        self.assertEqual(self.route("강아지 비만인지 어떻게 알 수 있어요?"), ("model", True))
        self.assertEqual(self.route("강아지 건강검진은 몇 살부터 매년 받아야 하나요?"), ("model", True))
        self.assertEqual(self.route("반려견 비만 비율 통계 알려줘"), ("analysis", False))
        self.assertEqual(self.route("건강검진 받는 가구 비중이 어때?"), ("analysis", False))

    def test_not_about_a_dog_stays_with_the_model(self):
        self.assertEqual(self.route("오늘 저녁 메뉴 추천해 줘"), ("model", True))


if __name__ == "__main__":
    unittest.main()
