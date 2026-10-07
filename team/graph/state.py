"""Graph layer: shared state, the Send input, run context and the findings reducer."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from typing_extensions import TypedDict


def merge_findings(current: dict, new: dict) -> dict:
    """Reducer for researchers running in parallel: merge {task_id: finding} without losing any.
    task_ids never repeat (the planner numbers new tasks after the existing ones)."""
    merged = dict(current or {})
    merged.update(new or {})
    return merged


class State(TypedDict):
    consultation: str                                    # what the guardian wrote
    region: str                                          # area for the hospital search, "" when not given
    profile: str                                         # pet profile text, "" when not given
    urgent: str                                          # urgent-sign notice from src/health_safety.py, "" when none
    plan: list[dict]                                     # planner: every task so far
    # Parallel researchers write in the same step, so this field needs a reducer
    # (without one LangGraph raises InvalidUpdateError).
    findings: Annotated[dict[str, dict], merge_findings]
    round: int                                           # supervisor: times work was sent back after a rejection
    draft: str                                           # writer: report file name
    review: dict | None                                  # reviewer verdict; set means there is a rejection to handle
    feedback: str                                        # reviewer feedback, or the writer's research request
    instruction: str                                     # supervisor's instruction to the next worker


class ResearchInput(TypedDict):
    """What Send passes to one researcher: the task and the consultation, not the whole state."""
    task: dict
    consultation: str
    urgent: bool


class Context(TypedDict):
    """Run resources that are not state."""
    run_dir: Path
    writer: Any
