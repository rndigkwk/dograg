import unittest

from src.faithfulness import (
    Claim,
    ClaimCheck,
    FaithfulnessJudgment,
    quote_found,
    recheck_unsupported,
    score_judgment,
    summarize_scores,
)

CONTEXT = "질문: 설사를 해요\n답변: 수분을 충분히 보충하고 하루 정도 금식시키세요."


def judgment(*claims):
    return FaithfulnessJudgment(claims=[Claim(text=t, verdict=v, quote=q) for t, v, q in claims])


class FaithfulnessScoringTests(unittest.TestCase):
    def test_quote_matches_ignoring_whitespace_and_quotes(self):
        self.assertTrue(quote_found("“수분을 충분히  보충하고”", CONTEXT))
        self.assertFalse(quote_found("항생제를 먹이세요", CONTEXT))
        self.assertFalse(quote_found("", CONTEXT))

    def test_general_advice_is_not_counted_against_faithfulness(self):
        score = score_judgment(judgment(
            ("수분을 보충하세요", "supported", "수분을 충분히 보충"),
            ("항생제를 먹이세요", "unsupported", ""),
            ("동물병원에 가세요", "general", ""),
        ), CONTEXT)
        self.assertEqual(score["faithfulness"], 0.5)
        self.assertEqual(score["general"], 1)
        self.assertEqual(score["quotes_verified"], 1)
        self.assertEqual(score["unsupported_claims"], ["항생제를 먹이세요"])

    def test_answer_with_only_general_claims_has_no_score(self):
        score = score_judgment(judgment(("자료에 없습니다", "general", "")), CONTEXT)
        self.assertIsNone(score["faithfulness"])

    def test_unverified_quote_is_reported(self):
        score = score_judgment(judgment(("금식하세요", "supported", "이틀 금식")), CONTEXT)
        self.assertEqual(score["supported"], 1)
        self.assertEqual(score["quotes_verified"], 0)

    def test_summary_pools_claims_across_answers(self):
        scores = [
            score_judgment(judgment(("a", "supported", "수분"), ("b", "supported", "금식")), CONTEXT),
            score_judgment(judgment(("c", "unsupported", ""), ("d", "supported", "보충")), CONTEXT),
        ]
        summary = summarize_scores(scores)
        self.assertEqual(summary["faithfulness"], 0.75)
        self.assertEqual(summary["answers_without_unsupported"], 1)
        self.assertEqual(summary["quotes_verified"], "3/3")


    def test_recheck_flips_only_claims_with_a_real_quote(self):
        result = judgment(
            ("하루 금식", "unsupported", ""),
            ("항생제 투여", "unsupported", ""),
            ("병원 방문", "general", ""),
        )
        checks = {
            "하루 금식": ClaimCheck(supported=True, quote="하루 정도 금식"),
            "항생제 투여": ClaimCheck(supported=True, quote="항생제를 투여"),  # invented quote
        }
        flipped = recheck_unsupported(result, CONTEXT, checks.__getitem__)
        self.assertEqual(flipped, 1)
        self.assertEqual([c.verdict for c in result.claims], ["supported", "unsupported", "general"])
        self.assertEqual(score_judgment(result, CONTEXT)["quotes_verified"], 1)


if __name__ == "__main__":
    unittest.main()
