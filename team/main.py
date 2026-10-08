"""Run the visit-prep team on one consultation.

    uv run python -m team.main "4살 말티즈가 이틀째 설사하고 오늘 두 번 토했어요" --region 강남구
    uv run python -m team.main "..." --region 마포구 --profile "말티즈, 4살, 3.2kg, 중성화함"

Writes output/visit_prep/<time>/visit_report.md and result.json (status, review verdict,
rounds, plan, findings with evidence ids). Real model calls (OpenAI); with Langfuse keys
set, the run is traced with the chatbot's masking.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from src import tracing
from src.health_safety import detect_urgent_sign
from team.agents.workers import create_writer
from team.core.config import OUTPUT_DIR
from team.graph.builder import build_graph


def run(consultation: str, region: str = "", profile: str = "", *, run_dir: Path | None = None,
        on_step: Callable[[str, dict], None] | None = None) -> dict:
    """Run the team once. run_dir defaults to a new output/visit_prep/<time>/ folder;
    on_step(node, update) is called as each node finishes (the app shows progress with it)."""
    if run_dir is None:
        run_dir = OUTPUT_DIR / datetime.now(UTC).astimezone().strftime("%Y%m%d_%H%M%S")
        run_dir.mkdir(parents=True)
        print("산출물 폴더:", run_dir)
    callbacks = []
    if tracing.client() is not None:
        from langfuse.langchain import CallbackHandler

        callbacks.append(CallbackHandler())
    state = None
    for mode, chunk in build_graph().stream(
        {
            "consultation": consultation, "region": region, "profile": profile,
            "urgent": detect_urgent_sign(consultation) or "",
            "plan": [], "findings": {}, "round": 0, "draft": "", "review": None, "feedback": "", "instruction": "",
        },
        context={"run_dir": run_dir, "writer": create_writer(run_dir)},
        config={"callbacks": callbacks, "recursion_limit": 40},
        stream_mode=["updates", "values"],
    ):
        if mode == "values":
            state = chunk
        elif on_step is not None:
            for node, update in chunk.items():
                on_step(node, update or {})
    tracing.flush()
    print("저장한 파일:", sorted(path.name for path in run_dir.iterdir()))
    return {"run_dir": run_dir, **state}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("consultation", help="보호자의 상담 내용")
    parser.add_argument("--region", default="", help="근처 동물병원을 찾을 시·군·구 (예: 강남구)")
    parser.add_argument("--profile", default="", help="반려견 정보 (예: 말티즈, 4살, 중성화함)")
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    run(args.consultation, args.region, args.profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
