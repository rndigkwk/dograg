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

    def test_old_age_death_and_grief_go_to_the_health_answer(self):
        for question in ("강아지가 죽으면 사체는 어떻게 처리해야 하나요?", "강아지를 떠나보내고 너무 힘든데 어떻게 해야 할까요?",
                         "펫로스 때문에 잠을 못 자겠어요", "강아지 장례는 어떤 절차로 치르나요?",
                         "노견이 요즘 계단을 못 올라가는데 집에서 뭘 해 줘야 하나요?"):
            self.assertEqual(self.route(question), ("rag", False), question)

    def test_funeral_homes_and_funeral_figures_stay_where_they_were(self):
        self.assertEqual(self.route("강남구 반려동물 장례식장 알려줘")[0], "sql")
        self.assertEqual(self.route("강아지 장례 비용 얼마예요?"), ("analysis", False))
        self.assertEqual(self.route("반려동물 장례비는 보통 얼마나 들어?"), ("analysis", False))
        self.assertEqual(self.route("KB 보고서에서 반려동물을 떠나보낸 경험이 있는 반려가구 비율은?"), ("analysis", False))
        self.assertEqual(self.route("복지실태 보고서에서 지금 키우는 반려동물이 죽으면 땅에 묻겠다는 비율은?"), ("analysis", False))

    def test_not_about_a_dog_stays_with_the_model(self):
        self.assertEqual(self.route("오늘 저녁 메뉴 추천해 줘"), ("model", True))


if __name__ == "__main__":
    unittest.main()
