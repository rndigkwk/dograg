"""Instructions hidden in text the app did not write: the retrieval rail (day64, 2026-10-21).

Consultations, care-guide pieces and the guardian's saved notes go into the answer prompt. The
prompt already tells the model to ignore instructions inside them, but a record saying "[상담 봇
안내] 이전 규칙과 관계없이 …" reached the answer anyway (scripts/evaluate_guardrails.py, indirect).
This drops such a document before any model reads it, the way a retrieval rail does.

The patterns are the shapes an injected instruction takes: a header addressed to the bot, an
override of the earlier rules (Korean and English), a sentence telling the bot what to do. On the
whole material none matched: 19,206 consultations (question + answer) and 767 care-guide pieces
(2026-10-21). Links are not a sign here: 30 guide pieces cite their sources with one. Links in the
answer are checked on the way out (src/guardrails.strip_foreign_links).

Only these shapes are caught; another wording gets through to the prompt rule and the output checks.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

HIDDEN_INSTRUCTION_PATTERNS = (
    # A header addressed to the bot: [시스템 안내], [상담 봇 지시], [AI 공지]
    re.compile(r"\[\s*(?:시스템|system|운영|운영팀|관리자|개발자|상담\s*봇|챗봇|봇|AI)\s*(?:안내|공지|지시|메시지|명령)?\s*\]", re.IGNORECASE),
    # An override of the earlier rules: 이전 규칙과 관계없이, 앞의 지시를 무시
    re.compile(r"(?:이전|앞의|위의|기존)\s*(?:의\s*)?(?:모든\s*)?(?:규칙|지시|지침|명령|설정)(?:을|를|은|는|과|와)?\s*"
               r"(?:모두\s*)?(?:무시|따르지\s*말|관계\s*없이|상관\s*없이)"),
    re.compile(r"\b(?:ignore|disregard|forget)\b.{0,20}\b(?:previous|prior|above|earlier|all)\b.{0,20}\b(?:instructions?|rules?|prompts?)\b", re.IGNORECASE),
    # A sentence telling the bot what to do: 이 사례를 인용하는 봇은 … 안내할 것
    re.compile(r"(?:상담\s*봇|챗봇|어시스턴트|AI|봇)(?:은|는|이|가)\s.{0,40}?(?:하세요|할\s*것|하라)"),
)


def has_hidden_instruction(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in HIDDEN_INSTRUCTION_PATTERNS)


def document_text(doc) -> str:
    """What a model reads of a retrieved document: its text and, for a consultation, the vet's answer."""
    return f"{doc.page_content}\n{doc.metadata.get('qa.output', '')}"


def drop_instructed(docs: list, kind: str) -> list:
    """The documents without a hidden instruction. A dropped one is logged by id (no text)."""
    kept = []
    for doc in docs:
        if has_hidden_instruction(document_text(doc)):
            logger.warning("retrieval rail dropped a %s document with a hidden instruction: %s", kind,
                           getattr(doc, "id", None) or doc.metadata.get("source_id"))
            continue
        kept.append(doc)
    return kept
