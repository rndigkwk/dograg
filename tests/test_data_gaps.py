import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src import data_gaps

ANSWER = ("검색된 사례에서는 초콜릿 섭취 후 구토가 나타났습니다. **검색된 자료에는 먹은 양에 따른 위험도 기준은 없습니다.**\n"
          "증상이 계속되면 동물병원에 가세요. 제 번호 010-1234-5678 같은 정보는 없습니다.")


class GapSentenceTests(unittest.TestCase):
    def test_the_sentence_that_names_the_gap(self):
        self.assertEqual(data_gaps.gap_sentences(ANSWER), ["검색된 자료에는 먹은 양에 따른 위험도 기준은 없습니다."])

    def test_material_that_does_cover_it_is_not_a_gap(self):
        for sentence in ("자료에서는 2~3일이 지나도 호전되지 않거나 악화되면 다시 상담하라고 안내합니다.",
                         "검색된 자료에 따르면 구토가 없어도 안심할 수 없습니다."):
            self.assertEqual(data_gaps.gap_sentences(sentence), [], sentence)

    def test_other_ways_of_saying_it(self):
        for sentence in ("슬개골 탈구가 이런 증상을 일으키는지는 자료에 나와 있지 않습니다.",
                         "13세에서 수술이 가능한지는 검색된 자료에서는 다루지 않습니다.",
                         "12세 말티즈에게 맞는 식사량은 자료에 없어 수의사와 확인하세요."):
            self.assertEqual(len(data_gaps.gap_sentences(sentence)), 1, sentence)

    def test_personal_data_is_masked(self):
        self.assertEqual(data_gaps.gap_sentences("010-1234-5678로 연락하는 방법은 검색된 자료에는 없습니다."),
                         ["[전화번호]로 연락하는 방법은 검색된 자료에는 없습니다."])

    def test_rows_per_answer(self):
        self.assertEqual(data_gaps.rows_for({"route": "rag", "abstained": True, "answer": "..."}), [("rag", "abstained", None)])
        self.assertEqual(data_gaps.rows_for({"route": "sql", "answer": ANSWER}), [])
        self.assertEqual(len(data_gaps.rows_for({"route": "rag", "answer": ANSWER})), 1)


class RecordTests(unittest.TestCase):
    def test_only_deployments_record(self):
        with patch.object(data_gaps.settings, "deployed", return_value=False), \
                patch.object(data_gaps.settings, "get_setting", return_value="postgresql://x"):
            self.assertIsNone(data_gaps.record({"route": "rag", "answer": ANSWER}))

    def test_the_deployment_check_is_left_out(self):
        check = SimpleNamespace(headers={"User-Agent": f"Mozilla/5.0 HeadlessChrome/140 {data_gaps.CHECK_AGENT}"})
        guardian = SimpleNamespace(headers={"User-Agent": "Mozilla/5.0 Chrome/140 Mobile Safari"})
        with patch.object(data_gaps.settings, "deployed", return_value=True), \
                patch.object(data_gaps.settings, "get_setting", return_value="postgresql://x"):
            with patch("streamlit.context", check):
                self.assertTrue(data_gaps.from_check())
                self.assertIsNone(data_gaps.record({"route": "rag", "answer": ANSWER}))
            with patch("streamlit.context", guardian):
                self.assertFalse(data_gaps.from_check())
        self.assertFalse(data_gaps.from_check())  # outside a Streamlit session

    def test_a_deployment_inserts_in_the_background_into_a_locked_table(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        data_gaps._ready.clear()
        with patch.object(data_gaps.settings, "deployed", return_value=True), \
                patch.object(data_gaps.settings, "get_setting", return_value="postgresql://x"), \
                patch("src.supabase_store.connector", return_value=lambda: conn):
            thread = data_gaps.record({"route": "rag", "answer": ANSWER})
            thread.join(5)
        statements = [call.args[0] for call in conn.execute.call_args_list]
        self.assertTrue(any("enable row level security" in sql for sql in statements))
        rows = conn.cursor.return_value.__enter__.return_value.executemany.call_args.args[1]
        self.assertEqual(rows, [("rag", "missing", "검색된 자료에는 먹은 양에 따른 위험도 기준은 없습니다.")])


if __name__ == "__main__":
    unittest.main()
