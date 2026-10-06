"""What the browser keeps in localStorage, and how it is read back safely.

The page holds one LocalSnapshot per session as the working copy. Each change
bumps `version`; the browser component (phase 3) writes `to_storage()` to
localStorage whenever the version changes, and passes the stored strings to
`from_storage()` when the page opens.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from pydantic import ValidationError

from src.storage.models import MAX_THREADS, PetProfile, Thread

STORAGE_PREFIX = "ragdog:v1:"
THREADS_KEY = STORAGE_PREFIX + "threads"
PROFILE_KEY = STORAGE_PREFIX + "profile"
NOTICE_KEY = STORAGE_PREFIX + "notice_seen"
STORAGE_KEYS = (THREADS_KEY, PROFILE_KEY, NOTICE_KEY)
# localStorage allows about 5MB per site; stay well below it.
MAX_THREADS_JSON_CHARS = 1_000_000

logger = logging.getLogger(__name__)


@dataclass
class LocalSnapshot:
    threads: list[Thread] = field(default_factory=list)
    profile: PetProfile = field(default_factory=PetProfile)
    notice_seen: bool = False
    version: int = 0
    dropped: int = 0  # invalid or oversized records ignored on the last load

    def touch(self) -> None:
        self.version += 1

    def to_storage(self) -> dict[str, str]:
        threads = [thread.model_dump(mode="json") for thread in self.threads]
        return {
            THREADS_KEY: json.dumps(threads, ensure_ascii=False),
            PROFILE_KEY: self.profile.model_dump_json(exclude_defaults=True),
            NOTICE_KEY: "1" if self.notice_seen else "",
        }

    @classmethod
    def from_storage(cls, raw: dict | None) -> LocalSnapshot:
        """Build a snapshot from untrusted localStorage strings; bad parts are dropped, never raised."""
        snapshot = cls()
        if not isinstance(raw, dict):
            return snapshot
        snapshot.notice_seen = raw.get(NOTICE_KEY) == "1"
        snapshot.threads, dropped_threads = _load_threads(raw.get(THREADS_KEY))
        snapshot.profile, dropped_profile = _load_profile(raw.get(PROFILE_KEY))
        snapshot.dropped = dropped_threads + dropped_profile
        if snapshot.dropped:
            logger.info("Ignored %d invalid stored records", snapshot.dropped)
        return snapshot


def _parse(text) -> object | None:
    if not isinstance(text, str) or not text or len(text) > MAX_THREADS_JSON_CHARS:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _load_threads(text) -> tuple[list[Thread], int]:
    data = _parse(text)
    if not isinstance(data, list):
        return [], int(bool(text))
    threads, dropped, seen = [], 0, set()
    for item in data:
        try:
            thread = Thread.model_validate(item)
        except ValidationError:
            dropped += 1
            continue
        if thread.id in seen:
            dropped += 1
            continue
        seen.add(thread.id)
        threads.append(thread)
    threads.sort(key=lambda thread: thread.updated_at, reverse=True)
    dropped += max(0, len(threads) - MAX_THREADS)
    return threads[:MAX_THREADS], dropped


def _load_profile(text) -> tuple[PetProfile, int]:
    data = _parse(text)
    if data is None:
        return PetProfile(), int(bool(text))
    try:
        return PetProfile.model_validate(data), 0
    except ValidationError:
        return PetProfile(), 1


def threads_json_size(threads: list[Thread]) -> int:
    return len(json.dumps([thread.model_dump(mode="json") for thread in threads], ensure_ascii=False))
