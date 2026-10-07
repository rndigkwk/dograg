"""Tools layer: the writer's file tool and handoff tools.

The handoff tools return Command(graph=Command.PARENT): control leaves the writer agent
and moves in the outer team graph, to the reviewer or back to the supervisor.
"""

from __future__ import annotations

from pathlib import Path

from langchain.tools import tool
from langgraph.types import Command

from team.core.config import REPORT_FILE


def make_write_report(run_dir: Path):
    """write_report bound to this run's folder; the writer never sees a path."""

    @tool
    def write_report(markdown: str) -> str:
        """방문 준비 보고서 전체(마크다운)를 이번 실행 폴더의 visit_report.md에 저장합니다. 다시 부르면 덮어씁니다."""
        (run_dir / REPORT_FILE).write_text(markdown, encoding="utf-8")
        return f"{REPORT_FILE}에 {len(markdown)}자를 저장했습니다."

    return write_report


@tool
def request_review() -> Command:
    """보고서를 write_report로 저장한 뒤 검수자에게 넘깁니다."""
    return Command(goto="reviewer", graph=Command.PARENT, update={"draft": REPORT_FILE})


@tool
def request_research(missing: str) -> Command:
    """조사 결과만으로 보고서에 꼭 필요한 내용을 쓸 수 없을 때, 무엇이 빠졌는지 적어 슈퍼바이저에게 추가 조사를 요청합니다."""
    # The supervisor handles it like a rejection, so the round limit applies to it as well.
    return Command(goto="supervisor", graph=Command.PARENT,
                   update={"review": {"passed": False, "by": "writer"}, "feedback": missing})
