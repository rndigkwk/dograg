"""The rails (day64 "rail integration"): every check between the guardian and the model, by stage.

rails/rails.yml is the source: one line per rail with its rule id, what it does and where. A rail
that is not listed is off; a required one cannot be left out (load fails, so the app does not
start). The output rails run in the file's order (src/guardrails.py). The other stages run where
the graph puts them; this module only answers whether each is on.

The rule ids go into the request log and Langfuse next to the guard names ("rules", from
result["guards"]), so a count by rule needs no lookup.
"""

from __future__ import annotations

from functools import lru_cache

import yaml

from src.settings import PROJECT_DIR

RAILS_FILE = PROJECT_DIR / "rails" / "rails.yml"
STAGES = ("input", "retrieval", "answer", "output", "execution")
# The rails the code knows, by stage. A name not here is a typo: load fails rather than ignore it.
KNOWN = {
    "input": {"pii_mask", "urgent_notice", "crisis_rule", "crisis_model"},
    "retrieval": {"document_instructions", "note_instructions"},
    "answer": {"citation_check", "fee_pointer"},
    "output": {"links_removed", "crisis_notice"},
    "execution": {"question_limit", "model_time_limit", "agent_tools"},
}
# Never off, whatever the file says: a missing one is an error, not a quiet change.
REQUIRED = {"pii_mask", "urgent_notice", "crisis_rule", "crisis_notice", "question_limit", "model_time_limit",
            "agent_tools"}


class RailsConfigError(ValueError):
    pass


@lru_cache(maxsize=1)
def load() -> dict[str, list[dict]]:
    """rails.yml by stage, checked: known names, unique ids and names, the required rails present."""
    data = yaml.safe_load(RAILS_FILE.read_text(encoding="utf-8")) or {}
    unknown_stages = set(data) - set(STAGES)
    if unknown_stages:
        raise RailsConfigError(f"unknown stage in {RAILS_FILE.name}: {sorted(unknown_stages)}")
    seen_ids, seen_names = set(), set()
    for stage in STAGES:
        for rail in data.setdefault(stage, []) or []:
            name, rule = rail.get("name"), rail.get("id")
            if name not in KNOWN[stage]:
                raise RailsConfigError(f"{stage} has no rail {name!r} (known: {sorted(KNOWN[stage])})")
            if not rule or rule in seen_ids or name in seen_names:
                raise RailsConfigError(f"rail {name!r}: missing or repeated id or name")
            seen_ids.add(rule)
            seen_names.add(name)
    missing = REQUIRED - seen_names
    if missing:
        raise RailsConfigError(f"required rails left out of {RAILS_FILE.name}: {sorted(missing)}")
    return data


def enabled(name: str) -> bool:
    return any(rail["name"] == name for stage in STAGES for rail in load()[stage])


def output_order() -> list[str]:
    return [rail["name"] for rail in load()["output"]]


def rule_ids(guards: list[str] | None) -> list[str]:
    """The rule ids of the rails that changed an answer, from the guard names in result["guards"]."""
    by_guard = {guard: rail["id"] for stage in STAGES for rail in load()[stage] for guard in rail.get("guards", [])}
    return list(dict.fromkeys(by_guard[guard] for guard in guards or [] if guard in by_guard))
