"""Append one JSON line per chatbot run: route, CRAG decisions and token usage.

The question text is never written; only a short hash and its length, so the
log can be reviewed later without storing what users typed.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_LOG_PATH = Path(__file__).resolve().parents[1] / "output" / "chat_runs.jsonl"


def question_fingerprint(question: str) -> dict:
    return {
        "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest()[:16],
        "question_chars": len(question),
    }


def summarize_usage(usage_metadata: dict | None) -> dict:
    """Collapse LangChain usage metadata ({model: {...}}) into per-model token counts."""
    summary = {}
    for model, usage in (usage_metadata or {}).items():
        summary[model] = {
            key: int(usage.get(key, 0) or 0)
            for key in ("input_tokens", "output_tokens", "total_tokens")
        }
    return summary


def log_chat_run(record: dict, path: Path | None = None) -> bool:
    """Best effort: logging must never break a chat answer."""
    target = Path(path or os.getenv("CHAT_RUN_LOG") or DEFAULT_LOG_PATH)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), **record}
        with target.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except (OSError, TypeError, ValueError):
        return False
