"""Storage interfaces and the snapshot-backed implementation used by the chat page.

The same classes serve both cases in the design doc: a snapshot that is never
written out (in-memory, e.g. tests or a browser that blocks storage) and one the
browser component persists to localStorage. Limits are enforced on every write.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.storage.models import (
    MAX_THREADS,
    MAX_TURNS_PER_THREAD,
    PetProfile,
    Thread,
    Turn,
    make_title,
    now_iso,
)
from src.storage.snapshot import (
    MAX_THREADS_JSON_CHARS,
    LocalSnapshot,
    threads_json_size,
)


@dataclass(frozen=True)
class ThreadSummary:
    id: str
    title: str
    updated_at: str
    turn_count: int


class ConversationStore(Protocol):
    def list_threads(self, *, limit: int = MAX_THREADS) -> list[ThreadSummary]: ...
    def create_thread(self, title: str) -> str: ...
    def recent_turns(self, thread_id: str, *, turns: int = 6) -> list[Turn]: ...
    def append_turn(
        self, thread_id: str, question: str, answer: str, *, route: str, evidence_ids: list[str]
    ) -> None: ...
    def delete_thread(self, thread_id: str) -> None: ...
    def clear(self) -> None: ...


class ProfileStore(Protocol):
    def get(self) -> PetProfile | None: ...
    def save(self, profile: PetProfile) -> None: ...
    def clear(self) -> None: ...


class LocalConversationStore:
    def __init__(self, snapshot: LocalSnapshot):
        self.snapshot = snapshot

    def _find(self, thread_id: str) -> Thread:
        for thread in self.snapshot.threads:
            if thread.id == thread_id:
                return thread
        raise KeyError(thread_id)

    def list_threads(self, *, limit: int = MAX_THREADS) -> list[ThreadSummary]:
        ordered = sorted(self.snapshot.threads, key=lambda thread: thread.updated_at, reverse=True)
        return [
            ThreadSummary(thread.id, thread.title, thread.updated_at, len(thread.turns))
            for thread in ordered[:limit]
        ]

    def create_thread(self, title: str) -> str:
        thread = Thread(title=make_title(title))
        self.snapshot.threads.insert(0, thread)
        self._enforce_limits(keep=thread.id)
        self.snapshot.touch()
        return thread.id

    def recent_turns(self, thread_id: str, *, turns: int = 6) -> list[Turn]:
        return list(self._find(thread_id).turns[-turns:]) if turns > 0 else []

    def append_turn(
        self, thread_id: str, question: str, answer: str, *, route: str, evidence_ids: list[str]
    ) -> None:
        thread = self._find(thread_id)
        thread.turns.append(Turn(question=question, answer=answer, route=route, evidence_ids=evidence_ids))
        del thread.turns[:-MAX_TURNS_PER_THREAD]
        thread.updated_at = now_iso()
        self._enforce_limits(keep=thread.id)
        self.snapshot.touch()

    def delete_thread(self, thread_id: str) -> None:
        before = len(self.snapshot.threads)
        self.snapshot.threads = [thread for thread in self.snapshot.threads if thread.id != thread_id]
        if len(self.snapshot.threads) != before:
            self.snapshot.touch()

    def clear(self) -> None:
        self.snapshot.threads = []
        self.snapshot.touch()

    def _enforce_limits(self, *, keep: str) -> None:
        """Keep the newest MAX_THREADS threads and the stored JSON under its size budget.

        The thread being written is never dropped; if it alone is too big, its oldest turns go.
        """
        threads = sorted(self.snapshot.threads, key=lambda thread: (thread.id == keep, thread.updated_at), reverse=True)
        threads = threads[:MAX_THREADS]
        if _text_chars(threads) < MAX_THREADS_JSON_CHARS * 0.8:  # far from the budget: skip the exact JSON size
            self.snapshot.threads = threads
            return
        while len(threads) > 1 and threads_json_size(threads) > MAX_THREADS_JSON_CHARS:
            threads.pop()  # least recently updated, never `keep` (sorted first)
        current = threads[0] if threads else None
        while current is not None and len(current.turns) > 1 and threads_json_size(threads) > MAX_THREADS_JSON_CHARS:
            del current.turns[0]
        self.snapshot.threads = threads


def _text_chars(threads: list[Thread]) -> int:
    """A lower bound of the stored JSON size: the question and answer text alone."""
    return sum(len(turn.question) + len(turn.answer) for thread in threads for turn in thread.turns)


class LocalProfileStore:
    def __init__(self, snapshot: LocalSnapshot):
        self.snapshot = snapshot

    def get(self) -> PetProfile | None:
        return None if self.snapshot.profile.is_empty() else self.snapshot.profile

    def save(self, profile: PetProfile) -> None:
        self.snapshot.profile = PetProfile.model_validate(profile.model_dump())
        self.snapshot.touch()

    def clear(self) -> None:
        self.snapshot.profile = PetProfile()
        self.snapshot.touch()


def clear_device(snapshot: LocalSnapshot) -> None:
    """The sidebar's "clear everything on this device": threads, profile and the seen-notice flag."""
    snapshot.threads = []
    snapshot.profile = PetProfile()
    snapshot.notice_seen = False
    snapshot.touch()


def as_chat_history(turns: list[Turn]) -> list[dict]:
    """Turns in the role/content shape the chat graph's `chat_history` expects."""
    messages = []
    for turn in turns:
        messages.append({"role": "user", "content": turn.question})
        messages.append({"role": "assistant", "content": turn.answer, "route": turn.route})
    return messages
