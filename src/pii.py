"""Mask personal data in what guardians type before it goes to a model API.

The guardrail baseline (docs/wiki/safety-and-evidence.md, scripts/evaluate_guardrails.py) found that
a phone number, address, e-mail, resident registration or card number typed into the chat reached
api.openai.com in every request (16/16). None of it helps answer a dog-health question, so it is
replaced by a label before the graph runs; what the guardian sees in the chat stays as typed.

Masked: mobile and landline numbers (with or without separators), e-mail addresses, resident
registration numbers, card numbers, and the street-and-number part of an address that follows a
district (마포구 월드컵로 123 -> 마포구 [주소]). The district stays: facility search needs it.
Since 2026-10-15 (tests/data/pii_cases.json) also: a person's name where the guardian introduces
themselves (저는 김민수이고, 제 이름은 ..., 보호자 ..., ... 드림), the number of a road or
neighbourhood without a district (역삼동 123-4, 테헤란로 12길 34) and an apartment's 동/호.
Not masked: a name without such a cue (a dog's name looks the same) and numbers that are part of a
dog question (운동 30분, 이동 3번, 3.5kg, 나이, 날짜, 체온).
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


# Korean surnames (two-syllable ones first); a name is the surname and one or two syllables.
_SURNAME = (r"(?:황보|남궁|제갈|선우|독고|사공|[김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주"
            r"우구민진나지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예경봉])")
_NAME = _SURNAME + r"[가-힣]{1,2}"
# Only where the guardians introduce themselves, and only with an ending that closes the name:
# "저는 한번 더" or "제 이름은 몰라도" stay. Not a bare "이름은": "반려견의 이름은 양감자입니다" is the dog.
_INTRODUCED_NAME = re.compile(
    r"(?P<cue>(?:저는|(?:제|내)\s*(?:이름은|성함은)|성함은|보호자|견주)\s*)(?P<name>" + _NAME + r")"
    r"(?=이고|입니다|이에요|예요|이라고|라고|이며|이야|입니다만)"
)
_SIGNED_NAME = re.compile(r"(?P<name>" + _NAME + r")(?=\s*(?:드림|올림))")
# A road or neighbourhood with its number but no district before it: the number must end the phrase
# (space, punctuation, 에, 근처 ...). Most "~로 + number" in consultations are a particle and a
# quantity ("것으로 11세", "수술비로 165만 원", "정도로 5~10알", "간격으로 20~30분"): no unit, no range,
# no decimal may follow.
_UNITS = (r"분|시간|번|회|개|가지|살|세|kg|킬로|일|주|개월|달|월|년|마리|층|시|초|cm|센티|도|%|곳|명|알|봉|g|ml|미리|"
          r"만|천|백|원")
_STREET_NUMBER = re.compile(
    r"(?P<street>[가-힣]+(?:로|길|동))\s+(?P<number>(?:\d+번?길\s*)?\d+(?:-\d+)?(?:번지)?)"
    r"(?![\d.~∼]|\s*(?:" + _UNITS + r"))"
    r"(?=$|[\s,.?!)]|에|근처|쪽|부근|이에요|예요|입니다|인데)"
)
_APARTMENT_UNIT = re.compile(r"\d+\s*동\s*\d+\s*호")


def mask_pii(text: str) -> str:
    """The text with personal data replaced by [전화번호], [주소] and the like."""
    if not text:
        return text
    for label, pattern in _PATTERNS:
        text = pattern.sub(f"[{label}]", text)
    text = _ADDRESS.sub(lambda m: f"{m.group('district')} [주소]", text)
    text = _APARTMENT_UNIT.sub("[주소]", text)
    text = _STREET_NUMBER.sub(lambda m: f"{m.group('street')} [주소]", text)
    text = _INTRODUCED_NAME.sub(lambda m: f"{m.group('cue')}[이름]", text)
    return _SIGNED_NAME.sub("[이름]", text)


def mask_history(messages: list | None) -> list | None:
    """The guardian's earlier messages masked the same way (assistant messages are left as they are)."""
    if not messages:
        return messages
    return [{**message, "content": mask_pii(message.get("content", ""))} if message.get("role") == "user" else message
            for message in messages]
