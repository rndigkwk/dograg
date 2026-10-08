"""Conservative, non-diagnostic health warnings."""

import re


URGENT_PATTERNS = (
    r"숨을\s*못\s*쉬", r"호흡\s*곤란", r"의식(?:이)?\s*없", r"쓰러졌",
    r"발작", r"경련", r"독성.*(?:먹|삼켰)", r"(?:초콜릿|자일리톨|포도|약물).*(?:먹|삼켰)",
    r"(?:계속|반복).{0,8}헛구역질",
    # Bluish tongue or gums (lack of oxygen), and a swollen belly with unproductive retching
    # (gastric dilatation-volvulus): both missed before, found by the visit-prep consultation set.
    r"(?:혀|잇몸).{0,8}(?:보라|파랗|파래|청색)",
    r"배가.{0,12}(?:부풀|빵빵|불러).{0,40}(?:헛구역질|토하려.{0,12}(?:안\s*나|아무것도))",
)
NEGATION = re.compile(r"^(?:은|는|이|가)?\s*(?:없어요|없습니다|아니에요|아닙니다|안\s*해요|하지\s*않)")


def detect_urgent_sign(question: str) -> str | None:
    for pattern in URGENT_PATTERNS:
        for match in re.finditer(pattern, question):
            if re.search(r"안\s*(?:먹|삼키)|먹지\s*않|삼키지\s*않", match.group()):
                continue
            if not NEGATION.match(question[match.end():]):
                return "응급 징후가 의심됩니다. 지체하지 말고 가까운 동물병원에 연락하거나 진료를 받으세요. 온라인 답변은 진단이 아닙니다."
    return None


def has_usable_evidence(scored_docs: list[tuple], threshold: float | None = None) -> bool:
    if not scored_docs:
        return False
    if threshold is None:
        return True
    return any(score <= threshold for _, score in scored_docs)
