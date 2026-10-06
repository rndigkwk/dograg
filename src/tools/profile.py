"""The pet profile in answers (design doc phase 4): life stage, prompt context, detection."""

from __future__ import annotations

from datetime import UTC, date, datetime

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, ValidationError

from src import resources
from src.storage.models import PetProfile

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
    for label, items in (("지병", profile.conditions), ("복용약", profile.medications), ("알레르기", profile.allergies)):
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
        "- medications는 지금 먹고 있는 약, allergies는 알려진 알레르기만 넣습니다."
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
            medications=detected.medications, allergies=detected.allergies,
        )
    except ValidationError:
        return None
    return None if profile.is_empty() else profile


def detect_profile(question: str) -> PetProfile | None:
    """Ask the chat model for profile facts in the question. Runs only while the profile is empty
    (design doc decision 8.2); the page asks the user before saving anything."""
    model = resources.load_chat_model()
    if model is None:
        return None
    detected = (DETECT_PROMPT | model.with_structured_output(DetectedProfile)).invoke({"question": question})
    return to_profile(detected)
