"""CRAG model calls: grade evidence, rewrite the search query, split comparison questions."""

from __future__ import annotations

from src import resources
from src.crag import build_decomposer, build_reviewer, build_rewriter

CRAG_CORPUS_NAMES = {"health": "반려견 건강 상담 Q&A", "report": "반려동물 관련 보고서"}


def review_evidence(kind: str, question: str, context: str):
    return build_reviewer(resources.load_review_model(), CRAG_CORPUS_NAMES[kind])(question, context)


def rewrite_search_query(question: str, search_query: str, feedback: str) -> str:
    return build_rewriter(resources.load_chat_model())(question, search_query, feedback)


def decompose_question(question: str) -> list[str]:
    return build_decomposer(resources.load_chat_model())(question)
