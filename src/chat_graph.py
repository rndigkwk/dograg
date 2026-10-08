"""LangGraph chatbot: route the question, then run the matching tool path.

With CRAG off every path calls the same functions the app used before, so behavior
is unchanged. With CRAG on (ENABLE_CRAG, and a chat model available), health and
report questions go through retrieve -> grade -> (rewrite ->) generate | abstain,
following the course's CRAG graph (day53) without its web-search step.

`tools` is src.tools.toolset.TOOLS (or a test double). Nodes look functions up on it
at call time, so tests can patch individual functions.
"""

from __future__ import annotations

import time
import warnings
from collections.abc import Callable
from typing import Any, Literal

from langchain_core.callbacks import get_usage_metadata_callback
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from src import tracing
from src.crag import (
    HEALTH_CANDIDATE_K,
    MAX_REWRITES,
    evidence_id,
    grade_documents,
    merge_documents,
    needs_decomposition,
)
from src.run_log import log_chat_run, question_fingerprint, summarize_usage

HEALTH_ABSTAIN = (
    "검색된 상담 자료에서 이 질문에 답할 근거를 찾지 못해 답변을 드리지 않았습니다. "
    "증상이 계속되거나 걱정되면 가까운 동물병원에 문의해 주세요."
)
REPORT_ABSTAIN = "검색된 보고서에서 이 질문에 답할 근거를 찾지 못했습니다. 질문의 대상이나 항목을 바꿔 다시 물어봐 주세요."
# Day53: an abstention says what was searched, what the evidence did not cover (the grader's own
# feedback, no extra model call) and how to ask again, instead of only "not found".
ABSTAIN_SEARCHED = {"rag": "반려견 건강 상담 사례(AI Hub 19,206건)", "report": "반려동물 보고서 5종"}
ABSTAIN_TIPS = {
    "rag": "증상이 언제부터·하루 몇 번인지, 나이·품종, 함께 나타난 증상을 넣어 다시 물어봐 주세요.",
    "report": "보고서 이름이나 연도, 알고 싶은 항목(예: 2025 한국 반려동물 보고서의 월평균 양육비)을 넣어 다시 물어봐 주세요.",
}
# 스트리밍 중 LangGraph가 근거 평가의 구조화 출력(parsed=RetrievalReview)을 직렬화하며 내는 경고입니다.
# 동작에는 영향이 없고 배포 로그만 어지럽히므로 이 경고만 숨깁니다.
warnings.filterwarnings(
    "ignore",
    message=r"Pydantic serializer warnings:[\s\S]*Expected `none`[\s\S]*field_name='parsed'",
    category=UserWarning,
)
# 사용자에게 보일 답변을 만드는 노드. 라우터·근거 평가·재작성의 모델 출력은 스트리밍하지 않습니다.
ANSWER_NODES = frozenset({"health_simple", "report_simple", "health_generate", "report_generate", "general"})


class ChatState(TypedDict, total=False):
    # 입력
    question: str
    top_k: int
    chat_history: list
    location: tuple[float, float] | None
    pet_profile: Any  # src.storage.models.PetProfile or None (design doc phase 4)
    crag: bool  # 건강 상담 CRAG
    crag_reports: bool  # 보고서 CRAG (기본 꺼짐)
    # classify
    route: str
    contextual_question: str
    # retrieve / grade / rewrite (CRAG)
    filters: dict
    search_query: str
    sub_queries: list[str]
    documents: list
    decision: Literal["", "correct", "ambiguous", "incorrect"]
    feedback: str
    rewrite_count: int
    trace: list[dict]
    # 결과
    answer: str
    evidence_rows: list
    safety_notice: str | None
    hospital_rows: list
    abstained: bool


def abstain_message(state: dict) -> str:
    """The abstention text: the fixed notice, then what was searched, what the evidence did not
    cover and how to ask again. Built in code from the graph's own record."""
    kind = "rag" if state.get("route") == "rag" else "report"
    grades = [entry for entry in state.get("trace", []) if entry.get("step", "").endswith("_grade")]
    reviewed = len({doc_id for entry in grades for doc_id in entry.get("candidate_ids", [])})
    rewrites = state.get("rewrite_count", 0)
    searched = f"{ABSTAIN_SEARCHED[kind]}에서 질문과 가까운 {reviewed}건을 근거로 쓸 수 있는지 하나씩 확인했습니다"
    if rewrites:
        searched += f"(검색어를 바꿔 {rewrites}번 더 찾음)"
    lines = [HEALTH_ABSTAIN if kind == "rag" else REPORT_ABSTAIN, "", f"- **찾아본 것:** {searched}."]
    feedback = " ".join(str(state.get("feedback") or "").split())
    if feedback:
        lines.append(f"- **확인하지 못한 것:** {feedback}")
    lines.append(f"- **다시 물어볼 때:** {ABSTAIN_TIPS[kind]}")
    return "\n".join(lines)


def _health_text(doc) -> str:
    return f"질문: {doc.page_content}\n답변: {doc.metadata.get('qa.output', '')}"


def _report_text(doc) -> str:
    return f"{doc.metadata.get('title', '보고서')} {doc.metadata.get('page', '?')}쪽: {doc.page_content}"


def build_chat_graph(tools):
    def classify(state: ChatState):
        question, history = state["question"], state.get("chat_history")
        if tools.is_date_question(question):
            return {"route": "date"}
        route = tools.classify_question(question, chat_history=history)
        # Health questions in a long conversation carry a condition from the summary (day52);
        # other routes and short conversations keep the plain query (no extra call).
        build_query = tools.memory_search_query if route == "rag" else tools.build_rag_search_query
        return {"route": route, "contextual_question": build_query(question, history)}

    def route_after_classify(state: ChatState) -> str:
        route, crag = state["route"], state.get("crag", False)
        if route == "date":
            return "date_answer"
        if route == "rag":
            return "health_retrieve" if crag else "health_simple"
        if route == "analysis":
            # 보고서는 판정이 정답 근거를 걸러 내서(정답 페이지 12/18 -> 10/18) 따로 켭니다.
            return "report_retrieve" if state.get("crag_reports", False) else "report_simple"
        if route == "sql":
            return "hospital"
        return "general"

    # --- 기존 경로 (CRAG 꺼짐) ---
    def date_answer(state: ChatState):
        return {"route": "none", "answer": tools.current_date_answer()}

    def health_simple(state: ChatState):
        result = tools.ask_rag(
            state["question"],
            k=state["top_k"],
            filters=tools.infer_rag_filters(state["contextual_question"], profile=state.get("pet_profile")),
            chat_history=state.get("chat_history"),
            profile=state.get("pet_profile"),
        )
        return {
            "answer": result["answer"],
            "evidence_rows": result["evidence_rows"],
            "safety_notice": result.get("safety_notice"),
        }

    def report_simple(state: ChatState):
        result = tools.analyze_report(state["question"])
        return {"answer": result["answer"], "evidence_rows": result["evidence_rows"]}

    def hospital(state: ChatState):
        answer, rows = tools.run_sql_search(state["contextual_question"], location=state.get("location"))
        return {"answer": answer, "hospital_rows": rows}

    def general(state: ChatState):
        return {
            "answer": tools.answer_without_tool(state["question"], chat_history=state.get("chat_history")),
            "hospital_rows": [],
        }

    # --- CRAG: 공통 평가 ---
    def _grade(state: ChatState, kind: str, text_of) -> dict:
        candidates = state.get("documents", [])
        try:
            kept, decision, feedback = grade_documents(
                lambda question, context: tools.review_evidence(kind, question, context),
                state["question"], candidates, text_of,
            )
            error = None
        except Exception as exc:  # noqa: BLE001 - 평가 실패는 기존 동작(상위 문서로 답변)으로 낮춥니다.
            kept, decision, feedback = candidates[: state["top_k"]], "ambiguous", ""
            error = type(exc).__name__
        entry = {
            "step": f"{kind}_grade",
            "search_query_chars": len(state.get("search_query", "")),
            "sub_queries": len(state.get("sub_queries", [])),
            "candidate_ids": [evidence_id(doc) for doc in candidates],
            "kept_ids": [evidence_id(doc) for doc in kept],
            "decision": decision,
            "error": error,
        }
        return {
            "documents": kept,
            "decision": decision,
            "feedback": feedback,
            "trace": [*state.get("trace", []), entry],
        }

    def abstain(state: ChatState):
        health = state["route"] == "rag"
        return {
            "answer": abstain_message(state),
            "evidence_rows": [],
            "abstained": True,
            "safety_notice": tools.detect_urgent_sign(state["question"]) if health else None,
        }

    # --- CRAG: 건강 상담 ---
    def health_retrieve(state: ChatState):
        filters = state.get("filters")
        if filters is None:
            filters = tools.infer_rag_filters(state["contextual_question"], profile=state.get("pet_profile"))
        query = state.get("search_query") or state["contextual_question"]
        found = tools.retrieve_health(query, k=max(HEALTH_CANDIDATE_K, state["top_k"]), filters=filters)
        return {
            "filters": filters,
            "search_query": query,
            "documents": merge_documents(state.get("documents", []), found),
        }

    def health_grade(state: ChatState):
        return _grade(state, "health", _health_text)

    def route_after_health_grade(state: ChatState) -> str:
        # v2: 근거가 일부라도 있으면 바로 답합니다(없는 내용은 생성 프롬프트가 없다고 밝힘).
        # 근거가 전혀 없을 때만 검색어를 다시 써서 한 번 더 찾고, 그래도 없으면 보류합니다.
        if state.get("documents"):
            return "health_generate"
        if state.get("rewrite_count", 0) < MAX_REWRITES:
            return "health_rewrite"
        return "abstain"

    def health_rewrite(state: ChatState):
        try:
            query = tools.rewrite_search_query(state["question"], state["search_query"], state.get("feedback", ""))
        except Exception:  # noqa: BLE001 - 재작성 실패 시 같은 검색어로 한 번 더 검색합니다.
            query = state["search_query"]
        # The department filter comes from keywords anywhere in the question, so one stray word
        # can lock the search into the wrong department (h06: a urinary question ending in a
        # "가려움" sentence searched only dermatology). Nothing usable was found, so search
        # again without it; the life stage is stated by the user and stays.
        filters = {key: value for key, value in (state.get("filters") or {}).items() if key != "department"}
        return {
            "search_query": query or state["search_query"],
            "rewrite_count": state.get("rewrite_count", 0) + 1,
            "filters": filters,
        }

    def health_generate(state: ChatState):
        docs = state["documents"][: state["top_k"]]
        answer = tools.generate_health_answer(
            state["question"], docs, filters=state.get("filters"), chat_history=state.get("chat_history"),
            profile=state.get("pet_profile"),
        )
        return {
            "answer": answer,
            "evidence_rows": [doc.metadata for doc in docs],
            "safety_notice": tools.detect_urgent_sign(state["question"]),
        }

    # --- CRAG: 보고서 분석 (질문 분해 + 평가, 재작성 없음) ---
    def report_retrieve(state: ChatState):
        question = state["question"]
        queries = [question]
        if needs_decomposition(question):
            try:
                queries = tools.decompose_question(question)
            except Exception:  # noqa: BLE001 - 분해 실패 시 원질문 하나로 검색합니다.
                queries = [question]
        return {"sub_queries": queries, "documents": tools.search_reports(question, queries)}

    def report_grade(state: ChatState):
        return _grade(state, "report", _report_text)

    def route_after_report_grade(state: ChatState) -> str:
        return "report_generate" if state.get("documents") else "abstain"

    def report_generate(state: ChatState):
        docs = state["documents"]
        answer = tools.generate_report_answer(state["question"], docs)
        return {"answer": answer, "evidence_rows": tools.report_evidence_from_docs(docs)}

    builder = StateGraph(ChatState)
    for name, node in {
        "classify": classify, "date_answer": date_answer, "general": general, "hospital": hospital,
        "health_simple": health_simple, "report_simple": report_simple,
        "health_retrieve": health_retrieve, "health_grade": health_grade,
        "health_rewrite": health_rewrite, "health_generate": health_generate,
        "report_retrieve": report_retrieve, "report_grade": report_grade,
        "report_generate": report_generate, "abstain": abstain,
    }.items():
        builder.add_node(name, node)
    builder.add_edge(START, "classify")
    builder.add_conditional_edges("classify", route_after_classify, [
        "date_answer", "health_simple", "health_retrieve", "report_simple",
        "report_retrieve", "hospital", "general",
    ])
    builder.add_edge("health_retrieve", "health_grade")
    builder.add_conditional_edges("health_grade", route_after_health_grade, [
        "health_generate", "health_rewrite", "abstain",
    ])
    builder.add_edge("health_rewrite", "health_retrieve")  # 검색어를 바꾼 뒤 실제 재검색
    builder.add_edge("report_retrieve", "report_grade")
    builder.add_conditional_edges("report_grade", route_after_report_grade, ["report_generate", "abstain"])
    for name in ("date_answer", "general", "hospital", "health_simple", "report_simple",
                 "health_generate", "report_generate", "abstain"):
        builder.add_edge(name, END)
    return builder.compile()


def _execute(graph, inputs: dict, on_token, on_step, config: dict | None = None) -> dict:
    if on_token is None and on_step is None:
        return graph.invoke(inputs, config=config)
    state: dict = {}
    for mode, payload in graph.stream(inputs, config=config, stream_mode=["messages", "updates", "values"]):
        if mode == "messages":
            chunk, metadata = payload
            text = getattr(chunk, "content", "")
            if on_token and isinstance(text, str) and text and metadata.get("langgraph_node") in ANSWER_NODES:
                on_token(text)
        elif mode == "updates":
            for node, update in payload.items():
                if on_step:
                    on_step(node, update or {})
        else:
            state = payload
    return state


def _run_record(fingerprint, crag, crag_reports, started, error, state, usage) -> dict:
    """The run log line and the trace output: ids, counts and decisions, no text."""
    record = {
        **fingerprint,
        "crag": crag,
        "crag_reports": crag_reports,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "error": error,
    }
    if state is not None:
        record.update(
            route=state.get("route"),
            decision=state.get("decision") or None,
            rewrite_count=state.get("rewrite_count", 0),
            abstained=state.get("abstained", False),
            evidence_count=len(state.get("evidence_rows") or []),
            trace=state.get("trace", []),
            token_usage=summarize_usage(usage.usage_metadata),
        )
    return record


def run_chat(
    tools,
    question: str,
    *,
    top_k: int,
    chat_history=None,
    location: tuple[float, float] | None = None,
    crag: bool = False,
    crag_reports: bool = False,
    graph=None,
    pet_profile=None,
    on_token: Callable[[str], None] | None = None,
    on_step: Callable[[str, dict], None] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Run the graph once. on_token receives answer text as the model writes it;
    on_step receives (node name, state update) after each node finishes.
    session_id groups a browser session's runs in Langfuse (src/tracing.py)."""
    if not question or not question.strip():
        raise ValueError("질문을 입력해 주세요.")
    graph = graph or build_chat_graph(tools)
    started = time.perf_counter()
    error = None
    fingerprint = question_fingerprint(question)
    with tracing.chat_trace(
        fingerprint, session=tracing.session_id(session_id),
        metadata={"crag": crag, "crag_reports": crag_reports, "top_k": top_k},
    ) as chat_trace:
        try:
            with get_usage_metadata_callback() as usage:
                state = _execute(graph, {
                    "question": question, "top_k": top_k, "chat_history": chat_history or [],
                    "location": location, "crag": crag, "crag_reports": crag_reports, "pet_profile": pet_profile,
                    "trace": [], "rewrite_count": 0,
                }, on_token, on_step, config={"callbacks": chat_trace.callbacks} if chat_trace.callbacks else None)
        except Exception as exc:
            error = type(exc).__name__
            raise
        finally:
            record = _run_record(fingerprint, crag, crag_reports, started, error, state if error is None else None, usage)
            log_chat_run(record)
            chat_trace.finish(record)
    return {
        "route": state["route"],
        "answer": state["answer"],
        "evidence_rows": state.get("evidence_rows", []),
        "hospital_rows": state.get("hospital_rows", []),
        "safety_notice": state.get("safety_notice"),
        "abstained": state.get("abstained", False),
        "trace_id": chat_trace.trace_id,
        "decision": state.get("decision") or None,  # CRAG grade: correct, ambiguous or incorrect
    }
