"""Graph layer: wire the team graph."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from team.graph.edges import dispatch
from team.graph.nodes import (
    ask_guardian,
    clarify,
    planner,
    publisher,
    researcher,
    reviewer,
    supervisor,
    writer,
)
from team.graph.state import Context, State


def build_graph(checkpointer=None):
    """clarify -> ask_guardian -> planner -> Send to researchers -> supervisor -> writer ->
    reviewer -> publisher, with rejections going back through the supervisor. ask_guardian
    pauses with interrupt, which needs a checkpointer (the app passes one)."""
    builder = StateGraph(State, context_schema=Context)
    builder.add_node("clarify", clarify)
    builder.add_node("ask_guardian", ask_guardian)
    builder.add_node("planner", planner)
    builder.add_node("researcher", researcher)
    builder.add_node("supervisor", supervisor)
    # The writer moves on through its handoff tools, so tell the graph where it may go.
    builder.add_node("writer", writer, destinations=("reviewer", "supervisor"))
    builder.add_node("reviewer", reviewer)
    builder.add_node("publisher", publisher)
    builder.add_edge(START, "clarify")
    builder.add_edge("clarify", "ask_guardian")
    builder.add_edge("ask_guardian", "planner")
    builder.add_conditional_edges("planner", dispatch, ["researcher", "supervisor"])
    builder.add_edge("researcher", "supervisor")  # waits for every parallel researcher
    builder.add_edge("publisher", END)
    return builder.compile(checkpointer=checkpointer)
