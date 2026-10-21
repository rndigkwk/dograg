"""Checks on the way out, without a model (day64 response filtering, 2026-10-21).

run_chat (src/chat_graph.py) applies them to every answer, whatever route made it:
- crisis_notice: a guardian who says they want to die or hurt themselves (often after losing their
  dog) gets the crisis lines first, before anything else the answer says. A rule, not the model: the
  model added them only sometimes. It runs on blocked, abstained and off-scope answers too.
- strip_foreign_links: a link reaches the guardian only when it comes from the app's own material
  (a place's homepage, a care guide's source). A link the model wrote itself, or one an injected
  record asked for, is removed.
Each check that fired is named in the result's "guards" (counted in the request log and Langfuse).
"""

from __future__ import annotations

import re

CRISIS_PATTERNS = (
    re.compile(r"(?:죽고|사라지고|따라\s*가고|끝내고)\s*싶"),
    re.compile(r"자살"),
    re.compile(r"자해\s*(?:하고\s*싶|충동|생각|를?\s*했|하고\s*있)"),
    re.compile(r"살\s*(?:이유|의미)가\s*없"),
    re.compile(r"(?:삶|인생)을?\s*(?:끝내|포기)"),
    re.compile(r"목숨을?\s*끊"),
)
# 자살예방상담전화 109 (24시간), 정신건강위기상담전화 1577-0199
CRISIS_NOTICE = ("많이 힘드시죠. 혼자 견디지 않으셔도 괜찮아요. 마음이 많이 힘들다면 지금 자살예방상담전화 **109**(24시간)나 "
                 "정신건강위기상담전화 **1577-0199**에 전화해 이야기해 주세요. 당장 위험한 상황이면 112나 119에 바로 연락해 주세요.")
CRISIS = "crisis_notice"
LINKS_REMOVED = "links_removed"

LINK = re.compile(r"https?://([A-Za-z0-9.-]+)[^\s)\]>\"']*")
REMOVED_LINK = "(링크 생략)"


def is_crisis(question: str) -> bool:
    return any(pattern.search(question or "") for pattern in CRISIS_PATTERNS)


def with_crisis_notice(answer: str) -> str:
    return f"{CRISIS_NOTICE}\n\n{answer}" if answer else CRISIS_NOTICE


def material_hosts(*row_lists) -> set[str]:
    """The link hosts that appear in the app's own rows (places, evidence): the links it may pass on."""
    hosts = set()
    for rows in row_lists:
        for row in rows or []:
            values = row.values() if isinstance(row, dict) else [row]
            for value in values:
                if isinstance(value, str):
                    hosts.update(match.group(1).lower() for match in LINK.finditer(value))
    return hosts


def strip_foreign_links(answer: str, allowed_hosts: set[str]) -> tuple[str, bool]:
    """The answer with every link whose host is not allowed replaced by REMOVED_LINK, and whether any was."""
    removed = False

    def replace(match: re.Match) -> str:
        nonlocal removed
        if match.group(1).lower() in allowed_hosts:
            return match.group(0)
        removed = True
        return REMOVED_LINK

    return LINK.sub(replace, answer or ""), removed


def apply_output_guards(question: str, result: dict) -> dict:
    """The result with the crisis lines in front when the question needs them and foreign links
    removed; result["guards"] names what fired, after what earlier checks named (citations)."""
    guards = list(result.get("guards") or [])
    answer, removed = strip_foreign_links(result.get("answer", ""),
                                          material_hosts(result.get("hospital_rows"), result.get("evidence_rows")))
    if removed:
        guards.append(LINKS_REMOVED)
    if is_crisis(question):
        answer = with_crisis_notice(answer)
        guards.append(CRISIS)
    return {**result, "answer": answer, "guards": guards}
