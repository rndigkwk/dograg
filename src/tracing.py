"""Langfuse tracing for chat runs, with every piece of user and document text masked.

On when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set (environment or
.streamlit/secrets.toml) and LANGFUSE_TRACING_ENABLED is not "false". Each chat run
is one trace:

- root span `chat`: input is the question's hash and length (src/run_log.py), output is
  the run record (route, CRAG decision, candidate/kept evidence ids, token counts)
- child spans from the LangChain callback handler: one per graph node and model call,
  with timings, model names and token usage

`mask_text` runs on every input, output and metadata value the SDK sends. It keeps
numbers, booleans and the values of SAFE_KEYS, and replaces every other string with
its length, so questions, answers, profiles and retrieved documents never leave the
server. Tracing never breaks an answer: setup or export failures only disable it.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from src import settings

logger = logging.getLogger(__name__)

# Keys whose string values are app vocabulary or public dataset ids, never user text.
SAFE_KEYS = frozenset({
    "route", "decision", "step", "error", "kind", "question_sha256",
    "candidate_ids", "kept_ids", "evidence_ids", "useful_ids", "role", "type",
    "langgraph_node", "langgraph_step", "langgraph_triggers", "langgraph_path", "checkpoint_ns",
    "ls_provider", "ls_model_name", "ls_model_type", "model", "model_name", "finish_reason",
    # experiment outputs (scripts/langfuse_experiments.py): evaluation labels, not user text
    "outcome", "behavior", "group", "evidence_pages",
    # visit-prep team run records: the status word and the kinds of research that failed
    # (error messages stay masked: they can quote the request)
    "status", "failed_kinds", "failed_errors",
})


def _masked(text: str) -> str:
    return f"[masked {len(text)} chars]"


def mask_text(*, data: Any, **_: Any) -> Any:
    """Langfuse `mask` hook: user and document text out, structure and numbers kept."""
    return _mask(data, safe=False)


def _mask(data: Any, *, safe: bool) -> Any:
    if isinstance(data, str):
        return data if safe else _masked(data)
    if isinstance(data, dict):
        return {key: _mask(value, safe=safe or key in SAFE_KEYS) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [_mask(item, safe=safe) for item in data]
    if data is None or isinstance(data, (bool, int, float)):
        return data
    return _masked(str(data))  # documents, messages and other objects: as text, masked


def release() -> str | None:
    """The deployed version on every trace, so runs before and after a merge can be compared:
    LANGFUSE_RELEASE when set, else the checked-out commit (read from .git, no subprocess)."""
    configured = settings.get_setting("LANGFUSE_RELEASE")
    if configured:
        return configured
    git = settings.PROJECT_DIR / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head[:7]  # detached HEAD: the commit itself
        ref = head[5:]
        ref_file = git / ref
        if ref_file.exists():
            return ref_file.read_text(encoding="utf-8").strip()[:7]
        for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0][:7]
    except OSError:
        pass
    return None


def sample_rate() -> float:
    """Share of runs to keep (LANGFUSE_SAMPLE_RATE, default 1.0 = all). A dropped run sends
    nothing, so keep 1.0 until traffic makes the volume a problem."""
    try:
        return min(max(float(settings.get_setting("LANGFUSE_SAMPLE_RATE") or 1.0), 0.0), 1.0)
    except ValueError:
        return 1.0


def environment() -> str:
    configured = settings.get_setting("LANGFUSE_TRACING_ENVIRONMENT")
    if configured:
        return configured
    return "production" if settings.deployed() else "development"


def _running_tests() -> bool:
    """unittest/pytest runs: .env may hold real keys, and test runs must not reach Langfuse."""
    program = sys.argv[0] if sys.argv else ""
    return "unittest" in program or "pytest" in program or Path(program).parent.name == "tests"


def enabled() -> bool:
    return bool(
        not _running_tests()
        and settings.get_setting("LANGFUSE_PUBLIC_KEY")
        and settings.get_setting("LANGFUSE_SECRET_KEY")
        and str(settings.get_setting("LANGFUSE_TRACING_ENABLED") or "true").lower() != "false"
    )


@lru_cache(maxsize=1)
def client():
    """The Langfuse client, or None when tracing is off or cannot start."""
    if not enabled():
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(
            public_key=settings.get_setting("LANGFUSE_PUBLIC_KEY"),
            secret_key=settings.get_setting("LANGFUSE_SECRET_KEY"),
            base_url=settings.get_setting("LANGFUSE_BASE_URL") or settings.get_setting("LANGFUSE_HOST"),
            environment=environment(),
            release=release(),
            sample_rate=sample_rate(),
            mask=mask_text,
        )
    except Exception:
        logger.warning("Langfuse tracing is off: client setup failed", exc_info=True)
        return None


def session_id(raw: str | None) -> str | None:
    """A browser session's random id, hashed again so the trace cannot be joined to anything else."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16] if raw else None


class ChatTrace:
    """What run_chat needs from a trace: LangChain callbacks and a place for the run record."""

    def __init__(self, span=None, handler=None):
        self._span = span
        self.callbacks = [handler] if handler is not None else []
        # Random id of this run's trace; the page attaches answer feedback to it.
        self.trace_id = getattr(span, "trace_id", None)

    def finish(self, record: dict) -> None:
        if self._span is None:
            return
        try:
            self._span.update(output=record, level="ERROR" if record.get("error") else None)
        except Exception:
            logger.warning("Langfuse trace update failed", exc_info=True)


@contextmanager
def run_trace(name: str, fingerprint: dict, *, metadata: dict, session: str | None = None,
              tags: list[str] | None = None) -> Iterator[ChatTrace]:
    """One Langfuse trace around a run (chat answer, visit-prep team); a no-op when tracing is off.
    Tags separate the kinds of run in the trace list (search `traceTags:visit-prep`)."""
    langfuse = client()
    if langfuse is None:
        yield ChatTrace()
        return
    with ExitStack() as stack:
        try:
            from langfuse import propagate_attributes
            from langfuse.langchain import CallbackHandler

            span = stack.enter_context(langfuse.start_as_current_observation(
                as_type="span", name=name, input=fingerprint, metadata=metadata,
            ))
            stack.enter_context(propagate_attributes(
                session_id=session, trace_name=name, tags=tags or [name],
                metadata={key: str(value) for key, value in metadata.items()},
            ))
            trace = ChatTrace(span, CallbackHandler())
        except Exception:
            logger.warning("Langfuse trace start failed", exc_info=True)
            trace = ChatTrace()
        yield trace


def chat_trace(fingerprint: dict, *, metadata: dict, session: str | None = None) -> AbstractContextManager[ChatTrace]:
    return run_trace("chat", fingerprint, metadata=metadata, session=session, tags=["chat"])


FEEDBACK_SCORE = "user_feedback"


def record_feedback(trace_id: str | None, helpful: bool) -> bool:
    """Store a 👍/👎 as a BOOLEAN score on the run's trace. The score id is derived from the
    trace id, so changing the vote overwrites the earlier score instead of adding one."""
    langfuse = client()
    if langfuse is None or not trace_id:
        return False
    try:
        langfuse.create_score(
            name=FEEDBACK_SCORE, value=1 if helpful else 0, data_type="BOOLEAN",
            trace_id=trace_id, score_id=f"{trace_id}-{FEEDBACK_SCORE}",
        )
        return True
    except Exception:
        logger.warning("Langfuse feedback score failed", exc_info=True)
        return False


def flush() -> None:
    """Send queued traces now (scripts call this before exiting; the app exports in the background)."""
    langfuse = client()
    if langfuse is not None:
        langfuse.flush()
