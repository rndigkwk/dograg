import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from langchain_core.documents import Document

from scripts import build_care_guides as build
from src.tools import care_guides
from src.tools.health import format_rag_context


class FakeEmbeddings:
    def __init__(self, vector):
        self.vector = vector

    def embed_query(self, text):
        return self.vector


def piece(chunk_id, title, page):
    return {"id": chunk_id, "title": title, "page": page, "organization": "동물사랑배움터",
            "url": "https://apms.epis.or.kr/x", "text": f"조각 {chunk_id}", "context": f"문맥 {chunk_id}"}


class CareGuideSearchTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        folder = Path(self.folder.name)
        chunks = [piece("a0", "재난", 2), piece("a1", "재난", 2), piece("b0", "재난", 3), piece("c0", "윤리", 39)]
        (folder / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
        # similarity to the query (1, 0): 0.9, 0.8 (same page as a0), 0.6, 0.3 (below the floor)
        vectors = np.array([[0.9, 0.436], [0.8, 0.6], [0.6, 0.8], [0.3, 0.954]], dtype=np.float32)
        np.save(folder / "vectors.npy", vectors)
        patcher = patch.object(care_guides, "GUIDE_DIR", folder)
        patcher.start()
        self.addCleanup(patcher.stop)
        embeddings = patch.object(care_guides.resources, "load_health_embeddings", return_value=FakeEmbeddings([1.0, 0.0]))
        embeddings.start()
        self.addCleanup(embeddings.stop)
        care_guides.load_guides.cache_clear()
        self.addCleanup(care_guides.load_guides.cache_clear)

    def test_the_closest_pieces_above_the_floor_one_per_page(self):
        docs = care_guides.retrieve_care_guides("재난 대비")
        self.assertEqual([doc.id for doc in docs], ["a0", "b0"])
        self.assertEqual(docs[0].page_content, "문맥 a0")
        self.assertEqual(docs[0].metadata["piece"], "조각 a0")
        self.assertTrue(all(care_guides.is_guide(doc) for doc in docs))

    def test_nothing_above_the_floor_gives_nothing(self):
        with patch.object(care_guides, "GUIDE_FLOOR", 0.95):
            self.assertEqual(care_guides.retrieve_care_guides("설사"), [])

    def test_without_the_guide_files_the_search_gives_nothing(self):
        with patch.object(care_guides, "GUIDE_DIR", Path(self.folder.name) / "missing"):
            care_guides.load_guides.cache_clear()
            self.assertEqual(care_guides.retrieve_care_guides("재난 대비"), [])

    def test_a_failing_model_gives_nothing_and_the_answer_goes_on(self):
        with patch.object(care_guides.resources, "load_health_embeddings", side_effect=RuntimeError("model")), \
                self.assertLogs("src.tools.care_guides", level="WARNING"):
            self.assertEqual(care_guides.retrieve_care_guides("재난 대비"), [])


class GuideContextTests(unittest.TestCase):
    def test_the_answer_model_sees_guides_apart_from_the_cases(self):
        case = Document(id="1", page_content="토해요", metadata={"qa.output": "금식하세요"})
        guide = Document(id="g", page_content="2~3주 주기로 손질", metadata={
            "kind": "care_guide", "organization": "동물사랑배움터", "title": "윤리 가이드라인", "page": 39})
        context = format_rag_context([guide, case])
        self.assertTrue(context.startswith("[사례 1] 다른 보호자의 질문: 토해요"))
        self.assertIn("[지침 1] 동물사랑배움터 「윤리 가이드라인」 39쪽: 2~3주 주기로 손질", context)


class BuildTests(unittest.TestCase):
    def test_pieces_overlap_and_each_has_a_wider_context(self):
        text = "가" * 600
        pairs = build.chunks_of(text)
        self.assertEqual([len(p) for p, _ in pairs], [240, 240, 240])  # starts 0, 180, 360
        self.assertTrue(all(len(c) == min(build.CONTEXT_CHARS, len(text)) for _, c in pairs))

    def test_a_short_page_is_one_piece(self):
        self.assertEqual(build.chunks_of("짧은 쪽"), [("짧은 쪽", "짧은 쪽")])

    def test_every_public_guide_is_in_the_repository_with_its_licence_and_source(self):
        for name, (title, organization, url) in build.PUBLIC_GUIDES.items():
            text = (build.PUBLIC_DIR / name).read_text(encoding="utf-8")
            self.assertIn("공공누리 제1유형", text, name)
            self.assertIn(url, text, name)
            self.assertTrue(url.startswith("https://"), name)

    def test_contents_pages_are_found(self):
        self.assertTrue(build.is_contents_page("가. 필요성····· 2\n1. 기본자세····· 2\n2. 환경····· 4"))
        self.assertFalse(build.is_contents_page("반려견의 발톱은 2~3주 주기로 손질합니다."))


if __name__ == "__main__":
    unittest.main()
