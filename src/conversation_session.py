"""Per-session conversation state for the chat page (design doc phase 3).

Kept free of Streamlit calls so it can be tested with a plain dict as `state`.
The page passes `st.session_state`. Until the browser reports its stored
snapshot, the session works on an in-memory one; when the report arrives, the
stored threads are merged in and anything made meanwhile is kept.
"""

from __future__ import annotations

import uuid
from collections.abc import MutableMapping

from src.storage.snapshot import LocalSnapshot
from src.storage.stores import (
    LocalConversationStore,
    LocalProfileStore,
    ThreadSummary,
    as_chat_history,
    clear_device,
)

LOADING, READY, UNAVAILABLE = "loading", "ready", "unavailable"
HISTORY_TURNS = 6  # turns sent to the graph as chat_history (same as before)
_PREFIX = "conversation_session."


class ConversationSession:
    def __init__(self, state: MutableMapping):
        self.state = state
        state.setdefault(_PREFIX + "request", uuid.uuid4().hex)
        state.setdefault(_PREFIX + "snapshot", LocalSnapshot())
        state.setdefault(_PREFIX + "status", LOADING)
        state.setdefault(_PREFIX + "sent_version", 0)
        state.setdefault(_PREFIX + "current", None)
        state.setdefault(_PREFIX + "notice_this_session", False)

    def _get(self, name):
        return self.state[_PREFIX + name]

    def _set(self, name, value) -> None:
        self.state[_PREFIX + name] = value

    # --- browser sync ---------------------------------------------------
    @property
    def request(self) -> str:
        return self._get("request")

    @property
    def status(self) -> str:
        return self._get("status")

    @property
    def snapshot(self) -> LocalSnapshot:
        return self._get("snapshot")

    def apply_report(self, report: dict | None) -> bool:
        """Take the browser's stored snapshot once. Returns True when the state changed."""
        if self.status != LOADING or not report:
            return False
        if report.get("status") != "ok":
            self._set("status", UNAVAILABLE)
            return True
        stored = LocalSnapshot.from_storage(report.get("values"))
        current = self.snapshot
        known = {thread.id for thread in stored.threads}
        stored.threads = [thread for thread in current.threads if thread.id not in known] + stored.threads
        if current.profile.model_dump(exclude_defaults=True):
            stored.profile = current.profile
        stored.notice_seen = stored.notice_seen or current.notice_seen
        stored.version = current.version
        if current.threads or current.notice_seen:
            stored.touch()  # write the merged result back
        self._set("snapshot", stored)
        self._set("status", READY)
        return True

    def pending_values(self) -> dict[str, str] | None:
        """What the browser still has to write, or None when it is up to date (or storage is off)."""
        if self.status != READY or self.snapshot.version <= self._get("sent_version"):
            return None
        return self.snapshot.to_storage()

    def mark_sent(self) -> None:
        self._set("sent_version", self.snapshot.version)

    # --- conversations ------------------------------------------------------
    @property
    def conversations(self) -> LocalConversationStore:
        return LocalConversationStore(self.snapshot)

    @property
    def profiles(self) -> LocalProfileStore:
        return LocalProfileStore(self.snapshot)

    @property
    def current_thread(self) -> str | None:
        current = self._get("current")
        if current and any(thread.id == current for thread in self.snapshot.threads):
            return current
        return None

    def threads(self) -> list[ThreadSummary]:
        return self.conversations.list_threads()

    def open_thread(self, thread_id: str | None) -> None:
        self._set("current", thread_id)

    def messages(self) -> list[dict]:
        """Stored turns of the open thread, oldest first, as chat messages."""
        current = self.current_thread
        if current is None:
            return []
        return as_chat_history(self.conversations.recent_turns(current, turns=10_000))

    def record_turn(self, question: str, answer: str, *, route: str, evidence_ids: list[str] | None = None) -> str:
        current = self.current_thread
        if current is None:
            current = self.conversations.create_thread(question)
            self.open_thread(current)
        self.conversations.append_turn(current, question, answer, route=route, evidence_ids=evidence_ids or [])
        return current

    def delete_current(self) -> None:
        current = self.current_thread
        if current is not None:
            self.conversations.delete_thread(current)
        self.open_thread(None)

    def clear_device(self) -> None:
        clear_device(self.snapshot)
        self.open_thread(None)
        self._set("notice_this_session", False)

    # --- one-time storage notice --------------------------------------------
    def take_notice(self) -> bool:
        """True while the storage notice should show: from the first time this browser saw it until reload."""
        if self._get("notice_this_session"):
            return True
        if self.status != READY or self.snapshot.notice_seen:
            return False
        self.snapshot.notice_seen = True
        self.snapshot.touch()
        self._set("notice_this_session", True)
        return True
