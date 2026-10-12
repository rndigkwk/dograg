import unittest

from scripts.evaluate_crag import leads_with_missing


class LeadsWithMissingTests(unittest.TestCase):
    """The first sentence opens with what the material lacks (docs/wiki/safety-and-evidence.md)."""

    def test_a_gap_first_counts(self):
        self.assertTrue(leads_with_missing("검색된 자료에는 구체적인 주기가 없습니다. 다만 정기적으로 다듬으세요."))
        self.assertTrue(leads_with_missing("부드럽게 닦는 방법은 **검색된 자료에는 안내되어 있지 않습니다**."))

    def test_an_answer_first_does_not_count(self):
        self.assertFalse(leads_with_missing("정기적으로 다듬어 주세요. 검색된 자료에는 구체적인 주기가 없습니다."))
        # The part before "…지만" answers; the gap comes after it.
        self.assertFalse(leads_with_missing("검색된 자료에서는 2~4주마다 짜라고 안내하지만, 모든 강아지에게 필요하지는 않습니다."))
        # Advice with a negative is not a gap.
        self.assertFalse(leads_with_missing("검색된 자료에서는 아프지 않게 천천히 닦도록 안내합니다."))
        self.assertFalse(leads_with_missing("검색 자료에서는 고정이 적절하지 않은 부목은 유합이 잘 안 된다고 합니다."))


if __name__ == "__main__":
    unittest.main()
