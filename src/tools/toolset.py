"""The functions the chat graph calls, resolved from their modules at call time.

Looking names up on each call (not binding them once) keeps
`patch.object(health, "retrieve_health", ...)` effective inside the graph.
"""

from __future__ import annotations

from src.tools import general, health, history, places, report, review, router

TOOL_SOURCES = {
    router: ("is_date_question", "current_date_answer", "classify_question",
             "is_symptom_and_place_request", "symptom_part"),
    history: ("build_rag_search_query",),
    health: ("infer_rag_filters", "retrieve_health", "generate_health_answer", "ask_rag", "detect_urgent_sign"),
    report: ("analyze_report", "search_reports", "generate_report_answer", "report_evidence_from_docs"),
    places: ("run_sql_search",),
    general: ("answer_without_tool",),
    review: ("review_evidence", "rewrite_search_query", "decompose_question"),
}
_MODULE_OF = {name: module for module, names in TOOL_SOURCES.items() for name in names}

_MISSING = [f"{module.__name__}.{name}" for name, module in _MODULE_OF.items() if not hasattr(module, name)]
if _MISSING:  # fail at import, not mid-conversation
    raise ImportError(f"chat graph tools are missing: {', '.join(_MISSING)}")


class Toolset:
    def __getattr__(self, name: str):
        module = _MODULE_OF.get(name)
        if module is None:
            raise AttributeError(name)
        return getattr(module, name)


TOOLS = Toolset()
