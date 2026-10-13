"""Mask personal data in what guardians type before it goes to a model API.

The guardrail baseline (docs/wiki/safety-and-evidence.md, scripts/evaluate_guardrails.py) found that
a phone number, address, e-mail, resident registration or card number typed into the chat reached
api.openai.com in every request (16/16). None of it helps answer a dog-health question, so it is
replaced by a label before the graph runs; what the guardian sees in the chat stays as typed.

Masked: mobile and landline numbers (with or without separators), e-mail addresses, resident
registration numbers, card numbers, and the street-and-number part of an address that follows a
district (마포구 월드컵로 123 -> 마포구 [주소]). The district stays: facility search needs it.
Not masked: personal names (no reliable pattern; a dog's name looks the same) and numbers that are
part of a dog question (나이, 체중, 횟수, 날짜, 체온).
"""

from __future__ import annotations

import re

# Order matters: longer number shapes first, so a card number is not read as a phone number.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("이메일", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("카드번호", re.compile(r"(?<!\d)\d{4}[- ]\d{4}[- ]\d{4}[- ]\d{4}(?!\d)|(?<!\d)\d{16}(?!\d)")),
    ("주민등록번호", re.compile(r"(?<!\d)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[- ]?[1-8]\d{6}(?!\d)")),
    ("전화번호", re.compile(r"(?<!\d)01[016789][- .]?\d{3,4}[- .]?\d{4}(?!\d)")),
    ("전화번호", re.compile(r"(?<!\d)0(?:2|[3-6][1-5])[- .]\d{3,4}[- .]\d{4}(?!\d)")),
)
# A road or neighbourhood name with its number, after a district: 월드컵로 123, 우동 1234-5,
# 테헤란로 12길 34, 신사동 123번지. Only after 구/군 so "운동 30분" or "도로 2개" stay.
_ADDRESS = re.compile(
    r"(?P<district>[가-힣]+[구군])\s+"
    r"(?P<street>[가-힣0-9]+(?:로|길|동|리|가)(?:\s*\d+(?:번?길))?\s*\d+(?:-\d+)?(?:번지)?)"
)


def mask_pii(text: str) -> str:
    """The text with personal data replaced by [전화번호], [주소] and the like."""
    if not text:
        return text
    for label, pattern in _PATTERNS:
        text = pattern.sub(f"[{label}]", text)
    return _ADDRESS.sub(lambda m: f"{m.group('district')} [주소]", text)


def mask_history(messages: list | None) -> list | None:
    """The guardian's earlier messages masked the same way (assistant messages are left as they are)."""
    if not messages:
        return messages
    return [{**message, "content": mask_pii(message.get("content", ""))} if message.get("role") == "user" else message
            for message in messages]
