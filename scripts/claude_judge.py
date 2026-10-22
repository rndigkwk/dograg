"""Claude as a second-family judge or writer for the evaluation scripts (not on the app's path).

The app and its judges all run on OpenAI (gpt-6-luna), so a judge may favour its own family's
answers (docs/wiki/judge-validation.md). This gives the evaluation scripts a Claude model behind the
same call they make on a LangChain structured-output model, `model.invoke([("system", ...), ("user",
...)])` returning the schema's instance, so their prompts and scoring stay as they are.

Credentials come from .env: CLAUDE (the API key) and CLAUDE_WORKSPACE_ID (the key is not scoped to
a workspace, so every request names one). Run with the SDK added to the project's environment:

    uv run --with anthropic python scripts/judge_validation.py claude
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "claude-haiku-5-5"  # the user's choice for the first runs (2026-10-22)


class Refused(RuntimeError):
    """Claude declined the request (stop_reason "refusal"); the caller records it, not a verdict."""


def client():
    import anthropic
    from dotenv import load_dotenv

    load_dotenv(PROJECT_DIR / ".env")
    return anthropic.Anthropic(api_key=os.environ["CLAUDE"].strip(),
                               default_headers={"anthropic-workspace-id": os.environ["CLAUDE_WORKSPACE_ID"].strip()})


class StructuredClaude:
    """`invoke(messages)` like a LangChain `with_structured_output(schema)` model."""

    def __init__(self, schema, model: str = DEFAULT_MODEL, max_tokens: int = 8000):
        self.schema, self.model, self.max_tokens = schema, model, max_tokens
        self.client = client()

    def invoke(self, messages):
        system = "\n\n".join(text for role, text in messages if role == "system")
        user = "\n\n".join(text for role, text in messages if role != "system")
        from pydantic import ValidationError

        try:
            response = self.client.messages.parse(
                model=self.model, max_tokens=self.max_tokens, system=system,
                messages=[{"role": "user", "content": user}], output_format=self.schema)
        except ValidationError as exc:  # the output stopped mid-JSON: a mid-stream refusal (or the token limit)
            raise Refused("output cut off") from exc
        if response.stop_reason == "refusal":
            raise Refused(getattr(response.stop_details, "category", None) or "refusal")
        return response.parsed_output
