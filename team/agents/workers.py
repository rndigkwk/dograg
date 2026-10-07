"""Agents layer: researchers and the writer, each built with only the tools its role needs."""

from __future__ import annotations

from pathlib import Path

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
)

from team.core import config
from team.core.prompts import RESEARCHER_PROMPT, RESEARCHER_ROLES, WRITER_PROMPT
from team.core.schemas import Finding, TaskKind
from team.tools.handoff import make_write_report, request_research, request_review
from team.tools.research import RESEARCH_TOOLS


def researcher_tools(kind: TaskKind) -> list:
    return list(RESEARCH_TOOLS[kind])


def writer_tools(run_dir: Path) -> list:
    return [make_write_report(run_dir), request_review, request_research]


def create_researcher(kind: TaskKind):
    """A subagent for one research task: its own tool only, a Finding as output, call limits."""
    tools = researcher_tools(kind)
    return create_agent(
        config.llm(),
        tools=tools,
        system_prompt=RESEARCHER_PROMPT.format(role=RESEARCHER_ROLES[kind], limit=config.TOOL_CALL_LIMIT),
        response_format=Finding,
        middleware=[
            # Limit the research tool only: the structured answer (Finding) is also a tool call
            # and must stay possible after the last search.
            *(ToolCallLimitMiddleware(tool_name=tool.name, run_limit=config.TOOL_CALL_LIMIT) for tool in tools),
            ModelCallLimitMiddleware(run_limit=config.AGENT_CALL_LIMIT, exit_behavior="end"),
        ],
        name=f"{kind}_researcher",
    )


def create_writer(run_dir: Path):
    """The writer: saves the report and hands off; it has no search tool."""
    return create_agent(
        config.writer_llm(),
        tools=writer_tools(run_dir),
        system_prompt=WRITER_PROMPT,
        middleware=[ModelCallLimitMiddleware(run_limit=config.AGENT_CALL_LIMIT, exit_behavior="end")],
        name="writer",
    )
