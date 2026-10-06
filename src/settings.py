"""App settings: environment variables first, then .streamlit/secrets.toml."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parents[1]

load_dotenv(PROJECT_DIR / ".env")


def _secrets() -> dict:
    secrets_path = PROJECT_DIR / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        return {}
    with secrets_path.open("rb") as file:
        return tomllib.load(file)


def get_openai_api_key():
    return os.getenv("OPENAI_API_KEY") or _secrets().get("OPENAI_API_KEY")


def get_setting(name: str):
    """Read a setting from the environment, then .streamlit/secrets.toml."""
    value = os.getenv(name)
    if value is not None:
        return value
    return _secrets().get(name)


def setting_enabled(name: str) -> bool:
    return str(get_setting(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def crag_enabled() -> bool:
    """Health-answer CRAG is off unless ENABLE_CRAG is set."""
    return setting_enabled("ENABLE_CRAG")
