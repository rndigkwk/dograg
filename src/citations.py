"""Sentence citations in a health answer, checked without a model (2026-10-21, day61/day64).

The answer cites its evidence per sentence: [사례 2], [지침 1] (the numbers of format_rag_context,
the same as the evidence cards on the page). The riskiest thing an answer can make up is a quantity
(a dose, an interval, an age), so each sentence's numbers are looked up in what it may draw from:
the evidence it cites, else all the evidence, plus the question, the dog's profile, the notes and
the conversation (a guardian's "5kg" is not invented).

check_answer() returns the problems:
- invalid: a citation to evidence that was not given ([사례 7] with five cases); the marker is removed
- unsupported: a sentence with a number found in none of those texts; the answer is rewritten once
  with those sentences named (src/tools/health.fix_citations), and a sentence still unsupported
  after that is dropped.
Self-RAG (a model judging every claim) was measured and left off: no gain beyond the judge's own
wobble at twice the answer time (docs/wiki/safety-and-evidence.md). This checks only numbers, with
no model, and calls the writer only when a number has no source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CITATION = re.compile(r"\[(사례|지침)\s*(\d+(?:\s*[,，]\s*\d+)*)\]")
# A quantity: a number, a range ("2~3"), with an optional unit. Years and dates are left out below.
QUANTITY = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)(?:\s*[~∼\-]\s*(\d+(?:\.\d+)?))?\s*"
                      r"(mg|㎎|ml|mL|㎖|kg|㎏|g|cc|%|도|℃|회|번|일|주|개월|달|년|세|살|시간|분|초|정|알|방울|cm|mm|kcal|배|개|마리|가지)?")
NUMBER = re.compile(r"(?<![\d.])\d+(?:\.\d+)?(?![\d])")
SENTENCE_END = re.compile(r"(?<=[.!?。])\s+|\n+")
# The model often puts the citation after the full stop ("…권했습니다. [사례 1] 다만 …"); it belongs to
# the sentence before, so it is moved in front of the stop before the answer is split or shown.
CITATION_AFTER_STOP = re.compile(r"([.!?。])[ \t]*((?:\[(?:사례|지침)\s*\d+(?:\s*[,，]\s*\d+)*\][ \t]*)+)")
# Numbers that are not claims: list markers ("1."), citations themselves.
LIST_MARKER = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s*")


@dataclass
class Problems:
    invalid: list[str] = field(default_factory=list)  # "[사례 7]" markers to remove
    unsupported: list[str] = field(default_factory=list)  # sentences with a number from nowhere
    numbers: dict[str, list[str]] = field(default_factory=dict)  # sentence -> the numbers not found

    def __bool__(self) -> bool:
        return bool(self.invalid or self.unsupported)


def attach_citations(answer: str) -> str:
    """'…했습니다. [사례 1] 다음 문장' -> '…했습니다 [사례 1]. 다음 문장'."""
    moved = CITATION_AFTER_STOP.sub(lambda match: f" {match.group(2).strip()}{match.group(1)} ", answer or "")
    return re.sub(r"[ \t]+\n", "\n", moved).strip()


def sentences(answer: str) -> list[str]:
    return [part.strip() for part in SENTENCE_END.split(attach_citations(answer)) if part.strip()]


def cited(sentence: str) -> list[tuple[str, int]]:
    """The (kind, number) pairs a sentence cites: [사례 1, 3] -> [("사례", 1), ("사례", 3)]."""
    found = []
    for kind, numbers in CITATION.findall(sentence):
        found += [(kind, int(number)) for number in re.split(r"\s*[,，]\s*", numbers)]
    return found


def numbers_in(text: str) -> set[str]:
    return {_normal(number) for number in NUMBER.findall(text or "")}


def claimed_numbers(sentence: str) -> list[str]:
    """The numbers a sentence states as facts: not its citations or a list marker."""
    text = LIST_MARKER.sub("", CITATION.sub("", sentence))
    found = []
    for match in QUANTITY.finditer(text):
        for number in match.group(1, 2):
            if number:
                found.append(_normal(number))
    return found


def _normal(number: str) -> str:
    return number.rstrip("0").rstrip(".") if "." in number else number.lstrip("0") or "0"


def evidence_texts(cases: list[str], guides: list[str]) -> dict[tuple[str, int], str]:
    texts = {("사례", number): text for number, text in enumerate(cases, start=1)}
    texts.update({("지침", number): text for number, text in enumerate(guides, start=1)})
    return texts


def check_answer(answer: str, cases: list[str], guides: list[str], context: str = "") -> Problems:
    """The citation and number problems of an answer (see the module docstring).
    cases and guides are the evidence texts in format_rag_context order; context is the question,
    profile, notes and conversation, whose numbers the answer may repeat."""
    texts = evidence_texts(cases, guides)
    everything = numbers_in("\n".join(texts.values()))
    allowed_anywhere = numbers_in(context)
    problems = Problems()
    for sentence in sentences(answer):
        refs = cited(sentence)
        for kind, number in refs:
            marker = f"[{kind} {number}]"
            if (kind, number) not in texts and marker not in problems.invalid:
                problems.invalid.append(marker)
        valid = [ref for ref in refs if ref in texts]
        source = numbers_in("\n".join(texts[ref] for ref in valid)) if valid else everything
        missing = [number for number in claimed_numbers(sentence)
                   if number not in source and number not in allowed_anywhere]
        if missing:
            problems.unsupported.append(sentence)
            problems.numbers[sentence] = missing
    return problems


def remove_invalid(answer: str, invalid: list[str]) -> str:
    for marker in invalid:
        answer = answer.replace(marker, "")
    return re.sub(r"[ \t]+([.,!?])", r"\1", answer)


def drop_sentences(answer: str, unsupported: list[str]) -> str:
    """The answer without the given sentences (each removed once, where it stands)."""
    for sentence in unsupported:
        answer = answer.replace(sentence, "", 1)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]{2,}", " ", answer)).strip()
