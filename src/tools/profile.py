"""The pet profile in answers (design doc phase 4): life stage, prompt context, detection, and the
automatic memory that offers new facts from health questions once a profile exists (2026-10-15)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, ValidationError

from src import resources
from src.pii import mask_pii
from src.storage.models import MAX_PROFILE_ITEMS, PetProfile

PUPPY_MAX_MONTHS = 12  # same boundaries as health.infer_life_cycle_filter
ADULT_MAX_MONTHS = 6 * 12 + 11


def today() -> date:
    return datetime.now(UTC).date()


def age_in_months(birth_month: date, on: date | None = None) -> int:
    on = on or today()
    return max(0, (on.year - birth_month.year) * 12 + on.month - birth_month.month)


def life_stage(profile: PetProfile | None, on: date | None = None) -> str | None:
    """자견 (≤12 months), 성견 (to 6 years 11 months) or 노령견, from the birth month."""
    if profile is None or profile.birth_month is None:
        return None
    months = age_in_months(profile.birth_month, on)
    if months <= PUPPY_MAX_MONTHS:
        return "자견"
    return "성견" if months <= ADULT_MAX_MONTHS else "노령견"


def describe_age(profile: PetProfile, on: date | None = None) -> str | None:
    if profile.birth_month is None:
        return None
    months = age_in_months(profile.birth_month, on)
    age = f"{months}개월" if months < 24 else f"약 {months // 12}살"
    return f"{age} ({life_stage(profile, on)})"


def profile_context(profile: PetProfile | None) -> str:
    """The profile as prompt text. Values were length-limited when stored (src/storage/models.py)."""
    if profile is None or profile.is_empty():
        return "등록된 정보 없음"
    lines = []
    if profile.name:
        lines.append(f"이름: {profile.name}")
    if profile.breed:
        lines.append(f"견종: {profile.breed}")
    if age := describe_age(profile):
        lines.append(f"나이: {age}")
    if profile.weight_kg:
        lines.append(f"체중: {profile.weight_kg:g}kg")
    if profile.neutered is not None:
        lines.append(f"중성화: {'함' if profile.neutered else '안 함'}")
    for label, items in (("지병", profile.conditions), ("복용약", profile.medications), ("알레르기", profile.allergies),
                         ("수술·시술", profile.procedures)):
        if items:
            lines.append(f"{label}: {', '.join(items)}")
    return "\n".join(lines)


def profile_summary(profile: PetProfile) -> str:
    """One line for the sidebar and the save suggestion."""
    return profile_context(profile).replace("\n", " · ")


DETECT_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        (
        "사용자 질문에서 사용자 본인이 키우는 반려견의 정보만 뽑으세요.\n"
        "- 질문에 직접 적힌 내용만 씁니다. 추측하지 마세요. 없으면 비워 둡니다.\n"
        "- 다른 사람이나 다른 개(친구네 개, 예전에 키우던 개 등)의 정보면 about_own_dog=false로 하세요.\n"
        "- 나이는 개월 수로 바꿉니다(3살 → 36, 5개월 → 5).\n"
        "- conditions는 이미 진단받은 지병만 넣습니다. 지금 나타난 증상(구토, 설사 등)은 넣지 않습니다.\n"
        "- medications는 지금 먹고 있거나 맞고·넣고 있는 약, allergies는 알려진 알레르기만 넣습니다.\n"
        "- procedures는 이미 받은 수술·시술입니다(예: 슬개골 수술, 결석 제거 수술). 중성화는 neutered=true로만 씁니다.\n"
        "- 계획이나 가정(나중에 수술하면, 먹여도 되나요)과 약·병에 대한 일반 질문은 넣지 않습니다. 실제로 겪은 일만 넣습니다."
        ),
    ),
    ("human", "{question}"),
])


class DetectedProfile(BaseModel):
    about_own_dog: bool = True
    name: str | None = None
    breed: str | None = None
    age_months: int | None = Field(default=None, ge=0, le=360)
    weight_kg: float | None = None
    neutered: bool | None = None
    conditions: list[str] = Field(default_factory=list)
    medications: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    procedures: list[str] = Field(default_factory=list)


def to_profile(detected: DetectedProfile, on: date | None = None) -> PetProfile | None:
    """A validated PetProfile from the detector's output, or None when it has nothing usable."""
    if not detected.about_own_dog:
        return None
    birth_month = None
    if detected.age_months is not None:
        on = on or today()
        total = on.year * 12 + (on.month - 1) - detected.age_months
        birth_month = date(total // 12, total % 12 + 1, 1)
    try:
        profile = PetProfile(
            name=detected.name, breed=detected.breed, birth_month=birth_month,
            weight_kg=detected.weight_kg if detected.weight_kg and 0 < detected.weight_kg < 150 else None,
            neutered=detected.neutered, conditions=detected.conditions,
            medications=detected.medications, allergies=detected.allergies, procedures=detected.procedures,
        )
    except ValidationError:
        return None
    return None if profile.is_empty() else profile


def detect(question: str) -> DetectedProfile | None:
    """The chat model's reading of the question; personal data masked first, as for the answer (src/pii.py)."""
    model = resources.load_chat_model()
    if model is None:
        return None
    return (DETECT_PROMPT | model.with_structured_output(DetectedProfile)).invoke({"question": mask_pii(question)})


def detect_profile(question: str) -> PetProfile | None:
    """Profile facts in the question, for an empty profile; the page asks before saving anything."""
    detected = detect(question)
    return None if detected is None else to_profile(detected)


# Automatic memory: once a profile is stored, a health question can still bring a new diagnosis, a new
# medicine, a surgery or a new weight. Detection used to be skipped for a stored profile because of its
# cost (design doc decision 8.2); these cues keep the call to questions that can carry such a fact
# (tests/data/profile_memory_questions.json).
MEMORY_CUES = re.compile(
    r"진단|수술|시술|처방|복용|먹고 ?있|먹이고 ?있|먹기 시작|맞고 ?있|넣고 ?있|바르고 ?있|투약|알레르기|앓고|지병|"
    r"\d+(?:\.\d+)? ?(?:kg|킬로)|체중|몸무게|중성화|제거"
)
LIST_LABELS = {"conditions": "지병", "medications": "복용약", "allergies": "알레르기", "procedures": "수술·시술"}


def may_have_memory(question: str) -> bool:
    return bool(MEMORY_CUES.search(question or ""))


def _known(value: str, items: list[str]) -> bool:
    """Already stored, ignoring spaces, or one contains the other (심장병 / 심장병 3기)."""
    key = re.sub(r"\s+", "", value).casefold()
    for item in items:
        other = re.sub(r"\s+", "", item).casefold()
        if key in other or other in key:
            return True
    return False


@dataclass
class MemorySuggestion:
    profile: PetProfile  # the stored profile with the new facts added
    new_facts: dict  # only what is new, by PetProfile field
    summary: str  # for the page: "지병 + 슬개골 탈구 · 체중 5kg → 7kg"


def new_facts(current: PetProfile, found: PetProfile) -> tuple[dict, list[str]]:
    """What `found` adds to `current`. Lists gain unknown items; weight and neutering follow the newer
    statement; name, breed and age only fill a gap (a different one is more likely another dog)."""
    facts, parts = {}, []
    for field, label in LIST_LABELS.items():
        added = [item for item in getattr(found, field) if not _known(item, getattr(current, field))]
        if added:
            facts[field] = added
            parts.append(f"{label} + {', '.join(added)}")
    if found.weight_kg and found.weight_kg != current.weight_kg:
        facts["weight_kg"] = found.weight_kg
        parts.append(f"체중 {current.weight_kg:g}kg → {found.weight_kg:g}kg" if current.weight_kg
                     else f"체중 {found.weight_kg:g}kg")
    if found.neutered and not current.neutered:
        facts["neutered"] = True
        parts.append("중성화 함")
    for field, label in (("name", "이름"), ("breed", "견종")):
        if getattr(found, field) and not getattr(current, field):
            facts[field] = getattr(found, field)
            parts.append(f"{label} {facts[field]}")
    if found.birth_month and not current.birth_month:
        facts["birth_month"] = found.birth_month
        parts.append(f"나이 {describe_age(found)}")
    return facts, parts


def suggest_memory(current: PetProfile | None, question: str) -> MemorySuggestion | None:
    """New facts about the user's own dog in a health question, offered for saving (nothing is saved
    without a click). An empty profile is read on every health question; a stored one only when the
    question has a memory cue."""
    if current is not None and not current.is_empty() and not may_have_memory(question):
        return None
    detected = detect(question)
    found = None if detected is None else to_profile(detected)
    if found is None:
        return None
    base = current or PetProfile()
    facts, parts = new_facts(base, found)
    if not facts:
        return None
    merged = base.model_dump()
    for field, value in facts.items():
        merged[field] = (merged[field] + value)[:MAX_PROFILE_ITEMS] if field in LIST_LABELS else value
    return MemorySuggestion(PetProfile.model_validate(merged), facts, " · ".join(parts))
