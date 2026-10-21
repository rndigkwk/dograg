"""The deployed API's logs as one JSON line per record, and one summary line per answer (2026-10-20).

Cloud Logging reads a JSON line on stdout as a structured entry: "severity" becomes the entry's level
and the other keys are fields to filter and count by (jsonPayload.outcome, jsonPayload.route, ...).
Without it each Python log record was plain text, and a traceback arrived as several entries.

configure() is called by api/main.create_app() on the deployment only (settings.deployed()); local
runs and tests keep the default logging. The root logger stays at WARNING, so the libraries' INFO
lines (every HTTP request of httpx, for one) stay out; this module's logger writes the summaries.

summarized(kind, stream, ...) watches an answer's event stream (api/chat.py, api/visit_prep.py)
and, when it ends, logs one line: how it ended (the last event: result, error, limited, paused, ...),
the route, the time, whether the search was on the local stores or the answer was the quota notice,
the trace id (to open the Langfuse trace) and whether it was the deployment check. No question or
answer text: only those fields are read from the events.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Iterator

from src import data_gaps

logger = logging.getLogger("ragdog.requests")
# The keys a summary may take from the last event's data: decided by the app, never text.
RESULT_KEYS = ("route", "trace_id", "search", "degraded", "abstained", "status", "passed", "round", "guards")
CONFIGURED_MARK = "_ragdog_json"


class JsonFormatter(logging.Formatter):
    """One line per record: severity, message (with the traceback), logger and any `fields`."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        entry = {"severity": record.levelname, "message": message, "logger": record.name}
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            entry.update(fields)
        return json.dumps(entry, ensure_ascii=False, default=str)


def configure() -> None:
    """JSON lines on stdout for the root logger and this module's summaries; safe to call twice."""
    root = logging.getLogger()
    if any(getattr(handler, CONFIGURED_MARK, False) for handler in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    setattr(handler, CONFIGURED_MARK, True)
    root.handlers = [handler]
    root.setLevel(logging.WARNING)
    logger.setLevel(logging.INFO)


def _parse(chunk: str) -> tuple[str, dict] | None:
    """The kind and data of one server-sent event as api/chat.event() writes it."""
    kind = data = None
    for line in chunk.splitlines():
        if line.startswith("event: "):
            kind = line[len("event: "):]
        elif line.startswith("data: "):
            data = line[len("data: "):]
    if kind is None:
        return None
    try:
        parsed = json.loads(data) if data else {}
    except ValueError:
        parsed = {}
    return kind, parsed if isinstance(parsed, dict) else {}


def summarized(kind: str, stream: Iterator[str], agent: str = "") -> Iterator[str]:
    """The stream unchanged, then one summary line for it (see the module docstring)."""
    started = time.perf_counter()
    last_kind, last_data, kinds = None, {}, []
    try:
        for chunk in stream:
            parsed = _parse(chunk)
            if parsed is not None:
                last_kind, last_data = parsed
                kinds.append(last_kind)
            yield chunk
    finally:
        # A closed connection (GeneratorExit) also ends here: the outcome says how far it got.
        fields = {"kind": kind, "outcome": last_kind or "none",
                  "latency_ms": round((time.perf_counter() - started) * 1000),
                  "urgent": "urgent" in kinds, "check": data_gaps.CHECK_AGENT in (agent or ""),
                  **{key: last_data[key] for key in RESULT_KEYS if key in last_data}}
        logger.info("%s %s", kind, fields["outcome"], extra={"fields": fields})
