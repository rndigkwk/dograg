"""Short-term conversation history shared by the router and the answer prompts.

The prompts get the last SHORT_TERM_MEMORY_TURNS turns word for word. Older turns used to be
dropped; in a long conversation they are now folded into a running summary (day52 context
engineering: summary of what came before + recent messages). The search query is still built
from the guardian's recent questions only, so the summary never changes what is searched.
"""

from __future__ import annotations

import re
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
    return reply.text.strip()[: SUMMARY_MAX_CHARS * 2]


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


TOPIC_QUERY_PROMPT = """반려견 건강 상담 사례를 검색할 검색어 한 문장을 만듭니다.
[현재 질문]이 [이전 질문]의 이야기를 이어서 묻는 것이면(그 증상·상황에 대한 추가 질문, 생략된 주어나 대상), 이전 질문의 증상·상황을 넣어 혼자 읽어도 뜻이 통하는 질문으로 쓰세요.
[현재 질문]이 새로운 증상이나 주제를 묻는 것이면 [현재 질문]을 그대로 쓰세요. 이전 질문의 내용을 섞지 마세요.
검색어만 쓰고 설명은 쓰지 마세요."""
# Earlier health questions shown to the rewrite (the last few; older ones are in the summary).
TOPIC_QUERY_QUESTIONS = 3


def _health_turn(messages: list, index: int) -> bool:
    """Was the user question at messages[index] a health question?

    The app records the route of each answer; a question answered by another route (facilities,
    fees, reports, date, small talk) is not health context. That catches facility follow-ups with
    no facility word ("24시 하는 곳은?" after "일산 동물병원 알려줘"), which the word check below
    took for health questions (tests/data/place_follow_up_questions.json). A question without a
    recorded route falls back to the word check."""
    answer = messages[index + 1] if index + 1 < len(messages) else {}
    if answer.get("role") == "assistant" and answer.get("route"):
        return answer["route"] == "rag"
    return not _other_topic(messages[index].get("content", ""))


def earlier_health_questions(question, chat_history=None) -> list[str]:
    """The guardian's recent health questions before this one."""
    messages = get_recent_chat_history(chat_history)
    return [message.get("content", "") for index, message in enumerate(messages)
            if message.get("role") == "user" and message.get("content")
            and message.get("content") != question and _health_turn(messages, index)]


def memory_search_query(question, chat_history=None):
    """The health search query, from this question and the conversation so far.

    - No earlier health question: the question itself, no model call.
    - Earlier health questions: one low-effort call writes a standalone query, carrying the earlier
      symptom only when this question continues it (TOPIC_QUERY_PROMPT). Prepending every recent
      question searched new topics with old ones; on questions asked after others (holdout,
      tests/data/topic_switch_holdout.json) a new topic found 0.38 of its own documents, 0.90
      with the rewrite (median 1.8 s, docs/wiki/retrieval-experiments.md).
    - A long conversation with a summary of older turns (day52): the rewrite also carries a
      condition from the summary (MEMORY_QUERY_PROMPT).
    A failed or unavailable model keeps the rule-built query (build_rag_search_query)."""
    query = build_rag_search_query(question, chat_history, health=True)
    summary = next((message.get("content", "") for message in chat_history or []
                    if message.get("role") == SUMMARY_ROLE), "")
    earlier = earlier_health_questions(question, chat_history)
    if not summary and not earlier:
        return query
    # Imported here: the chat model is only needed once there is a conversation.
    from src import resources

    model = resources.load_chat_model()
    if model is None:
        return query
    if summary:
        messages = [("system", MEMORY_QUERY_PROMPT),
                    ("user", f"[이전 대화 요약]\n{summary}\n\n[최근 질문들]\n{query}\n\n[현재 질문]\n{question}")]
    else:
        messages = [("system", TOPIC_QUERY_PROMPT),
                    ("user", "[이전 질문]\n" + "\n".join(earlier[-TOPIC_QUERY_QUESTIONS:]) + f"\n\n[현재 질문]\n{question}")]
    try:
        reply = model.bind(reasoning_effort="low").invoke(messages)
    except Exception:  # noqa: BLE001 - a failed rewrite keeps the rule-built query
        return query
    rewritten = " ".join(reply.text.split())
    return rewritten[:200] or query


# A health question that names the pet or starts from an earlier answer. Without either, a short
# question ("수술해야 하나요?", "그럼 사료는요?") leans on the one before it.
PET_WORDS = re.compile(r"강아지|반려견|노견|노령견|자견|퍼피|개가|개는|개를|말티즈|푸들|포메|비숑|시츄|치와와|닥스|리트리버|진돗개|믹스|고양이|냥")
FOLLOW_UP_WORDS = ("그럼", "그러면", "그거", "그건", "그게", "그렇", "계속", "이거", "이건", "저거", "아까", "그때", "그래도", "그것")


def leans_on_earlier(question: str) -> bool:
    """A health question that needs the one before it to be searched."""
    text = question.strip()
    if any(text.startswith(word) or f" {word}" in text for word in FOLLOW_UP_WORDS):
        return True
    return not PET_WORDS.search(text)


def _other_topic(question: str) -> bool:
    """A fee, facility or date question: never context for a health search."""
    from src.tools import fees, places, router

    return fees.is_fee_question(question) or router.is_date_question(question) or places.is_place_question(question)


def build_rag_search_query(question, chat_history=None, health=False):
    """The search query: this question, plus the one earlier question it leans on.

    All recent questions used to be prepended, so a new topic was searched with the old ones
    ("심장사상충 약 얼마나 자주" after a fee and a place question found nothing; a facility search
    after "강남구 …" searched 강남구 and 마포구 together). Now (tests/data/topic_switch_*.json):
    - health=True (health search): only a question that leans on the earlier one gets the last
      earlier health question; fee, facility and date questions are never carried over.
    - otherwise (facilities, reports): a question that names its own region stands alone; one
      that does not ("그 중에 24시는?") gets the last earlier question that named a region, or
      the last earlier question."""
    previous_questions = [
        message.get("content", "")
        for message in get_recent_chat_history(chat_history)
        if message.get("role") == "user" and message.get("content") and message.get("content") != question
    ]
    if not previous_questions:
        return question
    if health:
        if not leans_on_earlier(question):
            return question
        earlier = next(iter(earlier_health_questions(question, chat_history)[-1:]), None)
    else:
        from src.tools import places

        if places.extract_search_parameters(question):
            return question
        earlier = next((text for text in reversed(previous_questions) if places.extract_search_parameters(text)),
                       previous_questions[-1])
    return f"{earlier}\n{question}" if earlier else question
