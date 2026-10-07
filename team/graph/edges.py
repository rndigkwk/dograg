"""Graph layer: fan the plan out to researchers with Send."""

from __future__ import annotations

from langgraph.types import Send

from team.graph.state import State


def dispatch(state: State) -> list[Send] | str:
    """One researcher per task that has no finding yet, all running at once; when every task
    is done, go straight to the supervisor (an empty Send list would end the graph)."""
    todo = [task for task in state["plan"] if task["task_id"] not in state["findings"]]
    if not todo:
        return "supervisor"
    payload = {"consultation": state["consultation"], "urgent": bool(state["urgent"])}
    return [Send("researcher", {"task": task, **payload}) for task in todo]
