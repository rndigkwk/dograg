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

# What to do on the way to the hospital, by kind of sign. The consultation data rarely has these,
# so the answer said only "go to the hospital": against ChatGPT on the same urgent questions it lost
# on safety and usefulness (scripts/compare_chatgpt.py, 2026-10-29). Fixed text, no doses or numbers:
# the standard first steps of veterinary poison-control and emergency guidance.
FIRST_AID = (
    (TOXINS + r".{0,30}" + SWALLOWED, (
        "먹은 것의 포장지나 남은 것을 챙겨 가세요. 성분과 양을 병원에서 확인할 수 있습니다.",
        "언제, 얼마나 먹었는지 적어 두세요.",
        "수의사가 시키기 전에는 억지로 토하게 하지 마세요. 소금물이나 과산화수소를 먹이지 마세요.",
        "병원에 가기 전에 전화로 무엇을 먹었는지 먼저 알리세요.",
    )),
    (r"헛구역질", (
        "물과 음식을 주지 마세요.",
        "배를 누르거나 문지르지 마세요.",
        "시간이 지나면 위험해지는 상황이니, 지켜보지 말고 바로 출발하세요.",
    )),
    (r"(?:소변|오줌)", (
        "물을 억지로 먹이지 마세요.",
        "마지막으로 소변을 본 때와, 피가 섞였는지를 병원에 알리세요.",
        "요도가 막힌 경우 몇 시간 안에 위험해질 수 있으니, 내일까지 기다리지 마세요.",
    )),
    (r"발작|경련|거품", (
        "입에 손이나 물건을 넣지 마세요.",
        "주변의 딱딱한 물건을 치우고, 계단이나 높은 곳에서 떨어지지 않게 하세요.",
        "발작이 시작되고 끝난 시간을 재고, 할 수 있으면 영상으로 남기세요.",
    )),
    (r"숨|호흡|혀|잇몸|목에", (
        "안거나 눕힐 때 목과 가슴을 누르지 마세요. 목줄과 옷을 풀어 주세요.",
        "흥분하지 않게 조용히 옮기세요.",
    )),
    (r"피|혈|상처|물려|치(?:였|여)", (
        "피가 나는 곳을 깨끗한 천으로 꾹 눌러 주세요.",
        "다쳤으면 담요나 판자에 눕혀 몸을 덜 움직이게 옮기세요. 아파서 물 수 있으니 조심하세요.",
    )),
    (r"열사병", (
        "그늘이나 시원한 곳으로 옮기고, 미지근한 물로 몸을 적셔 주세요. 얼음물은 쓰지 마세요.",
        "식히면서 바로 병원으로 가세요.",
    )),
)


TOXIN_ASKED = (
    "이미 먹었다면 증상이 없어도 바로 동물병원에 연락하세요. 중독 증상은 늦게 나타날 수 있습니다.",
    "수의사가 시키기 전에는 억지로 토하게 하지 마세요.",
)


def first_aid_steps(question: str, urgent: bool = False) -> list[str]:
    """The fixed first steps for the urgent sign in the question, empty when there is none.
    urgent: the model's second check (src/tools/urgency.py) found one the rules missed."""
    if not urgent and not detect_urgent_sign(question):
        # "포도를 먹여도 되나요?": not an emergency, but the answer said "watch for vomiting if it
        # ate some", and poisoning shows late (scripts/compare_chatgpt.py q08, 2026-10-29).
        return list(TOXIN_ASKED) if re.search(TOXINS, question) else []
    for pattern, steps in FIRST_AID:
        if re.search(pattern, question):
            return list(steps)
    return []


def _in_past_sentence(question: str, start: int) -> bool:
    sentence_start = max((m.end() for m in SENTENCE_END.finditer(question, 0, start)), default=0)
    return bool(PAST.search(question[sentence_start:start]))


# A visit-prep consultation may carry saved notes the guardian chose after this heading
# (api/visit_prep.py with_notes). An urgent sign in an old note is not today's emergency.
SAVED_NOTES_HEADING = "[보호자가 고른 지난 상담 기록: 같은 증상이 되풀이되는지 참고만 하고, 지금 상태로 단정하지 마세요]"


def todays_text(consultation: str) -> str:
    """The guardian's own text of a consultation, without the saved notes or the care schedule
    appended to it (api/visit_prep.py)."""
    from src.care_schedule import CARE_HEADING

    for heading in (SAVED_NOTES_HEADING, CARE_HEADING):
        consultation = consultation.split(heading, 1)[0]
    return consultation.rstrip()


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
