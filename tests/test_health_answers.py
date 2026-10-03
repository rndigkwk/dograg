import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.documents import Document

from pages import rag
from src.health_answers import attach_health_answers, load_health_answers


def write_csv(directory: str) -> Path:
    path = Path(directory) / "df.csv"
    path.write_text(
        ',meta.lifeCycle,qa.input,qa.output\n'
        '0,성견,구토해요,"반복 구토는\r\n진료가 필요합니다."\n'
        '1,자견,설사해요,수분을 보충해 주세요.\n',
        encoding="utf-8",
        newline="",
    )
    return path


class HealthAnswerLookupTests(unittest.TestCase):
    def test_answers_are_keyed_by_row_id_without_carriage_returns(self):
        with tempfile.TemporaryDirectory() as directory:
            answers = load_health_answers(write_csv(directory))
        self.assertEqual(answers["0"], "반복 구토는\n진료가 필요합니다.")
        self.assertEqual(answers["1"], "수분을 보충해 주세요.")

    def test_attach_fills_missing_answer_and_keeps_existing(self):
        docs = [
            Document(id="1", page_content="설사해요", metadata={"meta.lifeCycle": "자견"}),
            Document(id="9", page_content="x", metadata={"qa.output": "기존 답변"}),
            Document(id="404", page_content="y", metadata={}),
        ]
        attach_health_answers(docs, {"1": "수분을 보충해 주세요."})
        self.assertEqual(docs[0].metadata["qa.output"], "수분을 보충해 주세요.")
        self.assertEqual(docs[1].metadata["qa.output"], "기존 답변")
        self.assertNotIn("qa.output", docs[2].metadata)

    def test_ask_rag_reads_answers_from_csv(self):
        doc = Document(id="1", page_content="설사해요", metadata={"meta.department": "내과"})
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(rag, "HEALTH_CSV_PATH", write_csv(directory)), \
                patch.object(rag, "initialize_rag", return_value=(object(), None)), \
                patch.object(rag, "load_health_bm25_index", return_value=object()), \
                patch("src.hybrid_retrieval.retrieve_hybrid", return_value=[doc]):
            rag.load_health_answer_table.clear()
            result = rag.ask_rag("강아지가 설사해요")
            rag.load_health_answer_table.clear()
        self.assertEqual(result["evidence_rows"][0]["qa.output"], "수분을 보충해 주세요.")

    def test_project_csv_covers_every_indexed_row(self):
        answers = load_health_answers(rag.HEALTH_CSV_PATH)
        self.assertEqual(len(answers), 19206)
        self.assertTrue(all(str(index) in answers for index in range(19206)))


if __name__ == "__main__":
    unittest.main()
