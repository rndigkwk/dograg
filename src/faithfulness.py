"""Answer faithfulness: is every claim in an answer backed by the evidence the model saw?

An LLM judge splits the answer into claims and labels each one:
- supported: the evidence states it or directly implies it (with a quote from the evidence)
- unsupported: not in the evidence, even if it is true in general
- general: generic safety advice ("see a vet") or statements about missing information

faithfulness = supported / (supported + unsupported). General claims are left out so
that recommending a vet visit is not counted as a hallucination.
The judge's quotes are checked against the evidence text, so a "supported" label
whose quote cannot be found is visible in the results.

Labeling every claim in one call misses evidence in long contexts (it marked
"IDEXX 4Dx" and "생후 5~7개월" unsupported although both were in the evidence), so each
unsupported claim is re-checked on its own. A re-check counts only when its quote
is found in the evidence, so the judge cannot invent support.
"""

from __future__ import annotations

import re
from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

JUDGE_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        (
        "당신은 RAG 답변이 근거에 충실한지 검사하는 평가자입니다.\n"
        "답변을 사실 주장 단위로 나누고, 각 주장을 [근거]와만 비교해 판정하세요. 일반 상식이나 실제 사실 여부는 보지 않습니다.\n"
        "- supported: 근거에 그 내용이 있거나 근거에서 바로 따라 나옵니다. quote에 근거 원문을 그대로 30자 이내로 옮기세요.\n"
        "- unsupported: 근거에 없는 내용입니다. 사실이더라도 근거에 없으면 unsupported입니다. 수치·기간·약물·용량·원인이 근거와 다르면 unsupported입니다.\n"
        "- general: '동물병원에 문의하세요' 같은 일반적인 진료·안전 권고, '자료에서 확인되지 않습니다' 같은 정보 부족 안내, 질문을 되풀이한 문장입니다.\n"
        "인사말과 문장 연결 표현은 주장으로 세지 마세요. quote는 supported일 때만 채우고 나머지는 빈 문자열로 두세요."
        ),
    ),
    ("human", "[질문]\n{question}\n\n[근거]\n{context}\n\n[답변]\n{answer}"),
])


VERIFY_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        (
        "주장 하나가 [근거]에 있는지 확인합니다. 근거 전체를 끝까지 읽으세요.\n"
        "근거에 그 내용이 있거나 근거에서 바로 따라 나오면 supported=true로 하고, quote에 근거 원문을 그대로 30자 이내로 옮기세요.\n"
        "근거에 없으면 supported=false, quote는 빈 문자열입니다. 일반 상식으로 판단하지 마세요."
        ),
    ),
    ("human", "[근거]\n{context}\n\n[주장]\n{claim}"),
])


class ClaimCheck(BaseModel):
    supported: bool
    quote: str = ""


class Claim(BaseModel):
    text: str = Field(description="답변에서 뽑은 주장 하나")
    verdict: Literal["supported", "unsupported", "general"]
    quote: str = Field(default="", description="supported일 때 근거 원문 인용 (30자 이내)")


class FaithfulnessJudgment(BaseModel):
    claims: list[Claim]


def build_judge(model):
    return JUDGE_PROMPT | model.with_structured_output(FaithfulnessJudgment)


def build_verifier(model):
    return VERIFY_PROMPT | model.with_structured_output(ClaimCheck)


def recheck_unsupported(judgment: FaithfulnessJudgment, context: str, verify) -> int:
    """Re-check each unsupported claim alone; flip it only when the quote is in the evidence.

    verify(claim_text) -> ClaimCheck. Returns how many claims were flipped to supported.
    """
    flipped = 0
    for claim in judgment.claims:
        if claim.verdict != "unsupported":
            continue
        check = verify(claim.text)
        if check.supported and quote_found(check.quote, context):
            claim.verdict, claim.quote = "supported", check.quote
            flipped += 1
    return flipped


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "").strip("\"'“”‘’.…")


def quote_found(quote: str, context: str) -> bool:
    """True when the judge's quote appears in the evidence, ignoring whitespace."""
    needle = _normalize(quote)
    return bool(needle) and needle in _normalize(context)


def score_judgment(judgment: FaithfulnessJudgment, context: str) -> dict:
    counts = {"supported": 0, "unsupported": 0, "general": 0}
    verified = 0
    for claim in judgment.claims:
        counts[claim.verdict] += 1
        if claim.verdict == "supported" and quote_found(claim.quote, context):
            verified += 1
    checked = counts["supported"] + counts["unsupported"]
    return {
        **counts,
        "claims": len(judgment.claims),
        "faithfulness": round(counts["supported"] / checked, 4) if checked else None,
        "quotes_verified": verified,
        "unsupported_claims": [c.text for c in judgment.claims if c.verdict == "unsupported"],
    }


def summarize_scores(scores: list[dict]) -> dict:
    """Pool claims across answers (micro average) and count fully faithful answers."""
    supported = sum(s["supported"] for s in scores)
    unsupported = sum(s["unsupported"] for s in scores)
    checked = supported + unsupported
    return {
        "answers": len(scores),
        "claims": sum(s["claims"] for s in scores),
        "supported": supported,
        "unsupported": unsupported,
        "general": sum(s["general"] for s in scores),
        "faithfulness": round(supported / checked, 4) if checked else None,
        "answers_without_unsupported": sum(s["unsupported"] == 0 for s in scores),
        "quotes_verified": f"{sum(s['quotes_verified'] for s in scores)}/{supported}",
    }
