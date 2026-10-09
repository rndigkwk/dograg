"""Conservative, non-diagnostic health warnings.

Measured with tests/data/emergency_signs.json (scripts/evaluate_emergency.py). The rules were
changed only from the `dev` half; the `holdout` half shows how they do on unseen wording.
"""

import re

# Swallowed, not "may eat" or "should avoid": the question is about something that happened.
SWALLOWED = r"(?:먹었|먹은|먹어\s*버|먹어버|먹고\s*말|삼켰|삼킨|핥아\s*먹|주워\s*먹|뜯어\s*먹|섭취(?:한|했|하였|하게)|주었|줬)"
# Common dog poisons (chocolate, xylitol, grapes, onions, rodenticide, insecticide, antifreeze,
# human pain and blood-pressure medicine): standard veterinary poison lists.
TOXINS = (
    r"(?:초콜릿|초콜렛|자일리톨|포도|건포도|양파|마늘|쥐약|살충제|농약|제초제|부동액|"
    r"타이레놀|아세트아미노펜|이부프로펜|진통제|해열제|혈압약|수면제|사람\s*약|독성)"
)
URGENT_PATTERNS = (
    # breathing
    r"숨을\s*(?:잘\s*)?못\s*쉬", r"호흡\s*곤란", r"숨(?:을|이)?\s*(?:너무\s*|매우\s*|심하게\s*)?(?:가쁘|가빠)",
    r"(?:혀|잇몸).{0,8}(?:보라|파랗|파래|청색)", r"잇몸.{0,8}(?:하얘|하얗|창백)",
    r"목에\s*(?:걸려|걸린|걸렸).{0,20}(?:캑캑|숨)",
    # collapse
    r"의식(?:이)?\s*없", r"쓰러(?:졌|져|지)", r"일어나지\s*못|못\s*일어나",
    # seizures
    r"발작", r"경련", r"거품을?\s*물",
    # poisons
    TOXINS + r".{0,30}" + SWALLOWED,
    # bloat (gastric dilatation-volvulus) and unproductive retching
    r"(?:계속|반복).{0,8}헛구역질",
    r"배가.{0,12}(?:부풀|빵빵|불러).{0,40}(?:헛구역질|토하려.{0,12}(?:안\s*나|아무것도))",
    # bleeding
    r"피(?:가|는)?\s*(?:멈추지\s*않|그치지\s*않|안\s*멈)", r"(?:피|혈).{0,8}(?:설사|토).{0,10}(?:계속|쏟|많이)",
    # injuries
    r"(?:차|오토바이|자전거)에\s*치(?:였|여)", r"물려.{0,10}(?:상처|피).{0,6}(?:깊|많이)", r"상처가\s*깊",
    r"눈알이\s*튀어나|안구가?\s*(?:돌출|튀어나|빠져)",
    # heat and urine
    r"열사병",
    r"(?:소변|오줌)(?:을|를|이)?\s*(?:전혀\s*|하나도\s*|계속\s*)?(?:못\s*(?:봤|봐|누|쌌|싸)|안\s*나와)",
)
# Right after the sign: "발작은 없었고", "경련 같은 건 없고", "숨을 못 쉬는 건 아니고".
NEGATION = re.compile(
    r"^\s*(?:은|는|이|가|을|를)?\s*(?:같은\s*(?:건|것은?)\s*|(?:하)?거나\s*(?:하지는\s*)?|는\s*건\s*|건\s*)?"
    r"(?:없|아니|않|안\s*했)"
)
# "발작이 오면 어떻게…", "열사병을 예방하려면": a question about what to do if it happens.
HYPOTHETICAL = re.compile(r"^\s*(?:이|가|을|를)?\s*\S{0,6}?(?:으)?면(?!서)")
# "작년에 경련을 한 번 했었는데 그 뒤로는 괜찮아요": the same sentence places it in the past.
PAST = re.compile(r"작년|재작년|예전|어릴\s*때|과거에|몇\s*(?:달|년)\s*전|지난\s*(?:해|달)")
SENTENCE_END = re.compile(r"[.?!\n]")

URGENT_NOTICE = "응급 징후가 의심됩니다. 지체하지 말고 가까운 동물병원에 연락하거나 진료를 받으세요. 온라인 답변은 진단이 아닙니다."


def _in_past_sentence(question: str, start: int) -> bool:
    sentence_start = max((m.end() for m in SENTENCE_END.finditer(question, 0, start)), default=0)
    return bool(PAST.search(question[sentence_start:start]))


def detect_urgent_sign(question: str) -> str | None:
    for pattern in URGENT_PATTERNS:
        for match in re.finditer(pattern, question):
            if re.search(r"안\s*(?:먹|삼키)|먹지\s*않|삼키지\s*않", match.group()):
                continue
            rest = question[match.end():]
            if NEGATION.match(rest) or HYPOTHETICAL.match(rest) or _in_past_sentence(question, match.start()):
                continue
            return URGENT_NOTICE
    return None


def has_usable_evidence(scored_docs: list[tuple], threshold: float | None = None) -> bool:
    if not scored_docs:
        return False
    if threshold is None:
        return True
    return any(score <= threshold for _, score in scored_docs)
