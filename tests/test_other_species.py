"""src/tools/health.py other_species: a health question about another animal, not food or a dog's (2026-10-20)."""

import unittest

from src.tools.health import other_species


class OtherSpeciesTests(unittest.TestCase):
    def test_another_animal_as_the_patient(self):
        self.assertEqual(other_species("페럿이 계속 설사를 해요"), "페럿")
        self.assertEqual(other_species("닭이 기침을 해요. 조류독감인가요?"), "닭")
        self.assertEqual(other_species("토끼 이빨이 너무 길어져서 식욕이 없어요"), "토끼")
        self.assertEqual(other_species("우리 집 고양이가 토해요"), "고양이")

    def test_food_and_dog_questions_stay(self):
        self.assertIsNone(other_species("콩이는 닭고기 알레르기가 있어서 연어 사료를 먹이는데 요즘 귀를 자꾸 긁어요."))
        self.assertIsNone(other_species("루이는 소고기 알레르기가 있어요. 오리 간식은 괜찮을까요?"))
        self.assertIsNone(other_species("저희 강아지가 고양이 사료를 먹었어요"))
        self.assertIsNone(other_species("개가 닭 뼈를 먹었어요"))
        self.assertIsNone(other_species("3개월 된 아이가 설사를 해요"))


if __name__ == "__main__":
    unittest.main()
