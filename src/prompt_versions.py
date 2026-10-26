"""A short fingerprint of every model prompt, so a score change can be traced to a prompt change.

The prompts are constants in the code (ChatPromptTemplate or a string) and git is their history.
A commit alone does not say which prompt changed, so each prompt gets an 8-character hash of its
text (`versions()`) and the whole set one more (`digest()`):

- every chat trace carries the digest (metadata `prompts`, src/chat_graph.py)
- the experiment results (scripts/langfuse_experiments.py, scripts/evaluate_guardrails.py) carry
  the per-prompt hashes, and the weekly regression copies them to eval_history and MLflow

A hash changes only when a prompt's text changes, never with the commit. PROMPTS lists them by
hand; tests/test_prompt_versions.py fails when a prompt constant in src/ is not listed.

    uv run python -m src.prompt_versions
"""

from __future__ import annotations

import hashlib
import importlib
import json
from functools import lru_cache
from typing import Any

# name -> (module, attribute)
PROMPTS = {
    "crag.grade": ("src.crag", "GRADE_PROMPT"),
    "crag.rewrite": ("src.crag", "REWRITE_PROMPT"),
    "crag.decompose": ("src.crag", "DECOMPOSE_PROMPT"),
    "crisis": ("src.crisis", "PROMPT"),
    "faithfulness.judge": ("src.faithfulness", "JUDGE_PROMPT"),
    "faithfulness.verify": ("src.faithfulness", "VERIFY_PROMPT"),
    "health.rag": ("src.tools.health", "RAG_PROMPT"),
    "health.revise": ("src.tools.health", "REVISE_PROMPT"),
    "history.summary": ("src.tools.history", "SUMMARY_PROMPT"),
    "history.memory_query": ("src.tools.history", "MEMORY_QUERY_PROMPT"),
    "history.topic_query": ("src.tools.history", "TOPIC_QUERY_PROMPT"),
    "notes": ("src.tools.notes", "NOTE_PROMPT"),
    "places.sql": ("src.tools.places", "SQL_GENERATION_PROMPT"),
    "places.answer": ("src.tools.places", "SQL_ANSWER_PROMPT"),
    "profile.detect": ("src.tools.profile", "DETECT_PROMPT"),
    "report.analysis": ("src.tools.report", "REPORT_ANALYSIS_PROMPT"),
    "router": ("src.tools.router", "ROUTER_PROMPT"),
    "router.decisions": ("src.tools.router", "ROUTE_INSTRUCTIONS"),
    "urgency": ("src.tools.urgency", "URGENT_INSTRUCTIONS"),
}


def prompt_text(prompt: Any) -> str:
    """The text that defines a prompt: a string as is; a ChatPromptTemplate as its messages'
    kinds and templates (placeholders by their variable name)."""
    if isinstance(prompt, str):
        return prompt
    parts = []
    for message in prompt.messages:
        inner = getattr(message, "prompt", None)
        if isinstance(inner, list):
            template = [getattr(p, "template", repr(p)) for p in inner]
        elif inner is not None:
            template = getattr(inner, "template", repr(inner))
        else:
            template = getattr(message, "variable_name", None) or repr(message)
        parts.append([type(message).__name__, template])
    return json.dumps(parts, ensure_ascii=False)


def short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


@lru_cache(maxsize=1)
def versions() -> dict[str, str]:
    """{prompt name: 8-character hash of its text}."""
    found = {}
    for name, (module, attribute) in PROMPTS.items():
        found[name] = short_hash(prompt_text(getattr(importlib.import_module(module), attribute)))
    return found


def digest(found: dict[str, str] | None = None) -> str:
    """One hash for the whole set: changes when any prompt does."""
    found = versions() if found is None else found
    return short_hash(json.dumps(sorted(found.items())))


def record() -> dict:
    """What a result file keeps: {"digest": ..., "versions": {name: hash}}."""
    return {"digest": digest(), "versions": versions()}


if __name__ == "__main__":
    print(json.dumps(record(), indent=1))
