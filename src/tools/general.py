"""Small talk and feature questions that need no retrieval."""

from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src import resources
from src.tools import history

GENERAL_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "도구가 필요하지 않은 일반 대화에 짧고 자연스럽게 답하세요. 의료 정보를 추측해서 답하지 마세요.",
    ),
    ("human", "[대화 이력]\n{chat_history}\n\n[현재 질문]\n{question}"),
])


def answer_without_tool(question: str, chat_history=None) -> str:
    model = resources.load_chat_model()
    if model is None:
        return "안녕하세요. 반려견 건강이나 동물병원에 관해 질문해 주세요."
    return (GENERAL_PROMPT | model | StrOutputParser()).invoke({
        "chat_history": history.format_chat_history(chat_history),
        "question": question,
    })
