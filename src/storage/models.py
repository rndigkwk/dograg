"""Validated records for stored conversations and the pet profile.

Everything here can come back from localStorage, which the user can edit, so
fields are length-limited and whitespace-normalized before they reach prompts.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_THREADS = 20
MAX_TURNS_PER_THREAD = 20
MAX_QUESTION_CHARS = 1_000
MAX_ANSWER_CHARS = 4_000
MAX_TITLE_CHARS = 30
MAX_EVIDENCE_IDS = 12
MAX_PROFILE_TEXT = 30
MAX_PROFILE_ITEMS = 10
DEFAULT_TITLE = "새 대화"
# Every route the chat graph can return (src/chat_graph.py); a missing one fails when the turn is saved.
Route = Literal["rag", "sql", "analysis", "none", "date", "fee"]

_WHITESPACE = re.compile(r"\s+")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def clean_text(value: str, limit: int, *, single_line: bool = False) -> str:
    """Drop control characters, optionally fold newlines, and cut to `limit` characters."""
    text = _CONTROL.sub("", value or "")
    if single_line:
        text = _WHITESPACE.sub(" ", text)
    return text.strip()[:limit]


def make_title(question: str) -> str:
    return clean_text(question, MAX_TITLE_CHARS, single_line=True) or DEFAULT_TITLE


class Turn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str
    answer: str
    route: Route = "none"
    evidence_ids: list[str] = Field(default_factory=list)
    at: str = Field(default_factory=now_iso)

    @field_validator("question")
    @classmethod
    def _question(cls, value: str) -> str:
        return clean_text(value, MAX_QUESTION_CHARS)

    @field_validator("answer")
    @classmethod
    def _answer(cls, value: str) -> str:
        return clean_text(value, MAX_ANSWER_CHARS)

    @field_validator("evidence_ids")
    @classmethod
    def _evidence(cls, value: list[str]) -> list[str]:
        return [clean_text(str(item), 64, single_line=True) for item in value[:MAX_EVIDENCE_IDS] if str(item).strip()]


class Thread(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    title: str = DEFAULT_TITLE
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    turns: list[Turn] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{32}", value or ""):
            raise ValueError("thread id must be 32 hex characters")
        return value

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return make_title(value)

    @field_validator("turns")
    @classmethod
    def _turns(cls, value: list[Turn]) -> list[Turn]:
        return value[-MAX_TURNS_PER_THREAD:]


def _clean_items(values: list[str]) -> list[str]:
    cleaned = [clean_text(str(item), MAX_PROFILE_TEXT, single_line=True) for item in values]
    return list(dict.fromkeys(item for item in cleaned if item))[:MAX_PROFILE_ITEMS]


class PetProfile(BaseModel):
    """Long-term memory about the user's dog (design doc phase 4)."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    breed: str | None = None
    birth_month: date | None = None
    weight_kg: float | None = Field(default=None, gt=0, lt=150)
    neutered: bool | None = None
    conditions: list[str] = Field(default_factory=list)
    medications: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)

    @field_validator("name", "breed")
    @classmethod
    def _short_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return clean_text(value, MAX_PROFILE_TEXT, single_line=True) or None

    @field_validator("conditions", "medications", "allergies")
    @classmethod
    def _items(cls, value: list[str]) -> list[str]:
        return _clean_items(value)

    @field_validator("birth_month")
    @classmethod
    def _birth_month(cls, value: date | None) -> date | None:
        if value is None:
            return None
        value = value.replace(day=1)
        if value < date(1990, 1, 1) or value > datetime.now(UTC).date():
            raise ValueError("birth month is out of range")
        return value

    def is_empty(self) -> bool:
        """True when nothing is known yet; profile detection runs only then (design doc 8.2)."""
        return not self.model_dump(exclude_defaults=True)
