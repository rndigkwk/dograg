"""Short-term conversation history shared by the router and the answer prompts.

The prompts get the last SHORT_TERM_MEMORY_TURNS turns word for word. Older turns used to be
dropped; in a long conversation they are now folded into a running summary (day52 context
engineering: summary of what came before + recent messages). The search query is still built
from the guardian's recent questions only, so the summary never changes what is searched.
"""

from __future__ import annotations

from collections.abc import Callable

SHORT_TERM_MEMORY_TURNS = 6
# Unsummarized turns may grow to SHORT_TERM_MEMORY_TURNS + SUMMARY_BATCH_TURNS before the oldest
# SUMMARY_BATCH_TURNS are folded into the summary: one summary call every 3 questions, not every one.
SUMMARY_BATCH_TURNS = 3
SUMMARY_ROLE = "summary"
SUMMARY_MAX_CHARS = 600
SUMMARY_PROMPT = """반려견 건강 상담 챗봇의 이전 대화를 요약합니다. [기존 요약]에 [새 대화]의 내용을 더해 하나의 요약으로 다시 쓰세요.
- 남길 것: 반려견에 대해 보호자가 말한 사실(증상과 시작 시점·횟수, 먹은 약이나 음식, 병원 진료·검사 결과, 지병, 사는 지역), 보호자가 정한 것이나 바꾼 것.
- 숫자·약 이름·검사 수치는 대화에 나온 그대로 옮기고, 바뀐 내용은 최신 값으로 쓰되 바뀌었다는 것을 남기세요.
- 챗봇이 안내한 일반 정보는 한 줄로만 남기고, 대화에 없는 내용은 쓰지 마세요.
- {max_chars}자 이내, 문장형으로 씁니다."""


def get_recent_chat_history(messages, max_turns=SHORT_TERM_MEMORY_TURNS):
    """세션에 저장된 대화에서 최근 사용자-AI 대화만 반환합니다."""
    if not messages:
        return []
    return list(messages[-max_turns * 2:])


def _plain(messages) -> list[dict]:
    return [{"role": message.get("role"), "content": message.get("content", "")} for message in messages]


def summarize_turns(previous_summary: str, messages: list[dict]) -> str:
    """One model call: the previous summary plus these turns, rewritten as one summary."""
    # Imported here: the chat model is only needed once a conversation gets long.
    from src import resources

    model = resources.load_chat_model()
    if model is None:
        return previous_summary
    reply = model.bind(reasoning_effort="low").invoke([
        ("system", SUMMARY_PROMPT.format(max_chars=SUMMARY_MAX_CHARS)),
        ("user", f"[기존 요약]\n{previous_summary or '없음'}\n\n[새 대화]\n{format_chat_history(_plain(messages))}"),
    ])
    return str(reply.content).strip()[: SUMMARY_MAX_CHARS * 2]


def summary_due(messages, memory: dict, max_turns: int = SHORT_TERM_MEMORY_TURNS,
                batch_turns: int = SUMMARY_BATCH_TURNS) -> bool:
    """Will history_with_summary call the model this time? (the app shows a spinner then)"""
    upto = memory.get("upto", 0)
    if upto > len(messages or []):
        upto = 0
    return len(messages or []) - upto > (max_turns + batch_turns) * 2


def history_with_summary(messages, memory: dict, summarize: Callable[[str, list[dict]], str] = summarize_turns,
                         max_turns: int = SHORT_TERM_MEMORY_TURNS, batch_turns: int = SUMMARY_BATCH_TURNS) -> list:
    """Recent turns word for word, led by a summary of everything older.

    memory ({"upto": messages already summarized, "summary": text}) belongs to one conversation
    and is updated in place. Turns past the window are folded in batches of batch_turns, so the
    word-for-word part holds max_turns to max_turns + batch_turns turns and nothing is dropped."""
    messages = list(messages or [])
    if memory.get("upto", 0) > len(messages):  # the conversation was cut or replaced: start over
        memory.clear()
    upto = memory.get("upto", 0)
    if summary_due(messages, memory, max_turns, batch_turns):
        fold = len(messages) - upto - max_turns * 2
        memory["summary"] = summarize(memory.get("summary", ""), messages[upto: upto + fold])
        memory["upto"] = upto = upto + fold
    recent = messages[upto:]
    if not memory.get("summary"):
        return recent
    return [{"role": SUMMARY_ROLE, "content": memory["summary"]}, *recent]


def format_chat_history(messages):
    """대화 이력을 RAG 프롬프트에 넣을 문자열로 변환합니다."""
    role_labels = {"user": "사용자", "assistant": "AI", SUMMARY_ROLE: "이전 대화 요약"}
    return "\n".join(
        f"{role_labels.get(message.get('role'), message.get('role', '대화'))}: "
        f"{message.get('content', '')}"
        for message in messages or []
    ) or "이전 대화 없음"


MEMORY_QUERY_PROMPT = """반려견 건강 상담 사례를 검색할 검색어 한 문장을 만듭니다.
[이전 대화 요약]에 보호자가 말한 지병·검사 결과·먹는 약·알레르기·수술이나 입원 중 [현재 질문]의 답에 영향을 주는 것이 있으면, 그 상태를 검색어에 넣으세요(예: "췌장염 퇴원 후 기름진 음식 급여 시기").
관련 없는 지난 이야기는 넣지 마세요. 검색어만 쓰고 설명은 쓰지 마세요."""


def memory_search_query(question, chat_history=None):
    """The health search query. Without a summary of older turns it is the usual query (recent
    questions + this one). With one (a long conversation, day52), one low-effort model call
    rewrites it as a standalone query that carries a condition from the summary, so the search
    finds cases about that condition, not only the generic question."""
    query = build_rag_search_query(question, chat_history)
    summary = next((message.get("content", "") for message in chat_history or []
                    if message.get("role") == SUMMARY_ROLE), "")
    if not summary:
        return query
    # Imported here: the chat model is only needed once a conversation gets long.
    from src import resources

    model = resources.load_chat_model()
    if model is None:
        return query
    try:
        reply = model.bind(reasoning_effort="low").invoke([
            ("system", MEMORY_QUERY_PROMPT),
            ("user", f"[이전 대화 요약]\n{summary}\n\n[최근 질문들]\n{query}\n\n[현재 질문]\n{question}"),
        ])
    except Exception:  # noqa: BLE001 - a failed rewrite keeps the usual query
        return query
    rewritten = " ".join(str(reply.content).split())
    return rewritten[:200] or query


def build_rag_search_query(question, chat_history=None):
    """현재 질문과 이전 사용자 질문을 합쳐 후속 질문 검색을 보강합니다."""
    previous_questions = [
        message.get("content", "")
        for message in get_recent_chat_history(chat_history)
        if message.get("role") == "user" and message.get("content")
    ]
    return "\n".join(dict.fromkeys(previous_questions + [question]))
