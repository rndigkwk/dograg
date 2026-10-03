"""Dense + BM25 retrieval helpers for the health-Q&A Chroma collection."""

from __future__ import annotations

import heapq
import json
from typing import Any, Callable, Iterable

from langchain_core.documents import Document


DEFAULT_CANDIDATE_K = 12
DEFAULT_RRF_C = 60


def _document_key(document: Document) -> str:
    stable_id = getattr(document, "id", None) or document.metadata.get("source_id")
    if stable_id:
        return str(stable_id)
    return json.dumps(
        [document.page_content, document.metadata],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def reciprocal_rank_fusion(
    result_lists: Iterable[list[Document]],
    top_k: int,
    c: int = DEFAULT_RRF_C,
    weights: Iterable[float] | None = None,
) -> list[Document]:
    """Combine ranked result lists with weighted reciprocal-rank fusion (equal by default)."""
    result_lists = list(result_lists)
    weights = [0.5] * len(result_lists) if weights is None else list(weights)
    if len(weights) != len(result_lists):
        raise ValueError("RRF weights must match the number of result lists")
    scores: dict[str, float] = {}
    documents_by_key: dict[str, Document] = {}
    for weight, result_list in zip(weights, result_lists):
        for rank, document in enumerate(result_list, start=1):
            key = _document_key(document)
            documents_by_key.setdefault(key, document)
            scores[key] = scores.get(key, 0.0) + weight / (c + rank)
    ordered = sorted(scores, key=lambda key: (-scores[key], key))
    return [documents_by_key[key] for key in ordered[:max(0, top_k)]]


def matches_metadata_filter(metadata: dict[str, Any], where: dict | None) -> bool:
    """Evaluate the equality/AND/OR filter subset emitted by pages.rag."""
    if not where:
        return True
    for key, expected in where.items():
        if key == "$and":
            if not all(matches_metadata_filter(metadata, clause) for clause in expected):
                return False
        elif key == "$or":
            if not any(matches_metadata_filter(metadata, clause) for clause in expected):
                return False
        elif metadata.get(key) != expected:
            return False
    return True


def select_bm25_candidates(
    documents: list[Document],
    scores: Iterable[float],
    where: dict | None,
    top_k: int,
) -> list[Document]:
    """Select the best lexical candidates while honoring Chroma metadata filters."""
    score_values = list(scores)
    if len(score_values) != len(documents):
        raise ValueError("BM25 score count must match the document count")
    eligible = [
        index for index, document in enumerate(documents)
        if matches_metadata_filter(document.metadata, where)
    ]
    indices = heapq.nlargest(
        max(0, top_k), eligible, key=lambda index: (score_values[index], -index)
    )
    return [documents[index] for index in indices]


class HealthBM25Index:
    """An in-memory BM25 index built once from the persisted Chroma corpus."""

    def __init__(self, documents: list[Document], bm25: Any, tokenize: Callable[[str], list[str]]):
        self.documents = documents
        self.bm25 = bm25
        self.tokenize = tokenize

    @classmethod
    def from_chroma(cls, db: Any, tokenize: Callable[[str], list[str]]) -> "HealthBM25Index":
        try:
            from rank_bm25 import BM25Okapi
        except ImportError as exc:
            raise RuntimeError("BM25 검색을 위해 rank-bm25 패키지를 설치해 주세요.") from exc

        stored = db.get(include=["documents", "metadatas"])
        ids = stored.get("ids") or []
        texts = stored.get("documents") or []
        metadatas = stored.get("metadatas") or []
        if not ids or len(ids) != len(texts) or len(ids) != len(metadatas):
            raise ValueError("Chroma 건강 Q&A 컬렉션에 문서 ID/본문/메타데이터가 없습니다.")
        documents = [
            Document(id=source_id, page_content=text, metadata=metadata or {})
            for source_id, text, metadata in zip(ids, texts, metadatas)
            if text
        ]
        if not documents:
            raise ValueError("BM25 색인을 만들 건강 Q&A 문서가 없습니다.")
        tokenized = [tokenize(document.page_content) for document in documents]
        return cls(documents, BM25Okapi(tokenized), tokenize)

    def search(self, query: str, top_k: int, where: dict | None = None) -> list[Document]:
        scores = self.bm25.get_scores(self.tokenize(query))
        return select_bm25_candidates(self.documents, scores, where, top_k)


def retrieve_hybrid(
    db: Any,
    index: HealthBM25Index,
    query: str,
    *,
    top_k: int,
    where: dict | None = None,
    candidate_k: int = DEFAULT_CANDIDATE_K,
) -> list[Document]:
    """Run filtered Dense and BM25 searches, then return their RRF ranking.

    Without an embedding model (no API key), only the BM25 ranking is used.
    """
    if getattr(db, "embeddings", True) is None:
        dense_documents = []
    else:
        dense_documents = db.similarity_search(query, k=candidate_k, filter=where)
    lexical_documents = index.search(query, candidate_k, where=where)
    return reciprocal_rank_fusion(
        [dense_documents, lexical_documents], top_k=top_k
    )
