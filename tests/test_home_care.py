"""src/home_care.py: the fixed home-care line (answer rail ANS-03) on the gaps the answers stated."""

import unittest

from src.home_care import NOTE, home_care_note


class HomeCareNoteTests(unittest.TestCase):
    def test_home_care_gaps_get_the_note(self):
        # Gap sentences the deployed answers wrote (ragdog_data_gaps, 2026-10-15 to 10-24).
        for sentence in ("검색된 자료에는 집에서 할 수 있는 구체적인 관리 방법은 없습니다.",
                         "검색된 자료에는 일시적인 구토의 집 관리법은 없습니다.",
                         "다만 자료는 3개월 강아지 사례라 성견의 지속 설사 대처법은 검색된 자료에 없습니다.",
                         "검색된 자료에는 안전한 섭취량이나 집에서 할 처치 방법은 없습니다."):
            with self.subTest(sentence=sentence):
                self.assertEqual(home_care_note(f"구토가 계속되면 병원에 가세요 [사례 1]. {sentence}"), NOTE)

    def test_other_gaps_and_covered_answers_do_not(self):
        for answer in ("검색된 자료에는 서울 지역의 구체적인 비용이 없습니다.",
                       "미니쉘 4개의 정확한 위험량은 검색된 자료에 없습니다.",
                       "자료에 따르면 집에서 미지근한 물로 닦아 줄 수 있습니다 [사례 1].",
                       "집에서는 물을 조금씩 주세요 [사례 2]."):
            with self.subTest(answer=answer):
                self.assertEqual(home_care_note(answer), "")

    def test_the_note_never_suggests_a_treatment(self):
        self.assertIn("사람 약을 먹이거나 바르지 마세요", NOTE)
        self.assertIn("동물병원", NOTE)


if __name__ == "__main__":
    unittest.main()
