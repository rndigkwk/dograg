"""Run the visit-prep team on one consultation.

    uv run python -m team.main "4살 말티즈가 이틀째 설사하고 오늘 두 번 토했어요" --region 강남구
    uv run python -m team.main "..." --region 마포구 --profile "말티즈, 4살, 3.2kg, 중성화함"

Writes output/visit_prep/<time>/visit_report.md and result.json (status, review verdict,
rounds, plan, findings with evidence ids). Real model calls (OpenAI); with Langfuse keys
set, the run is traced with the chatbot's masking.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from langgraph.types import Command

from src import tracing
from src.health_safety import detect_urgent_sign
from src.run_log import question_fingerprint
from team.agents.workers import create_writer
from team.core import config
from team.core.config import OUTPUT_DIR
from team.graph.builder import build_graph
from team.graph.nodes import failed_kinds, fallback_kinds, run_status


def run(consultation: str, region: str = "", profile: str = "", *, run_dir: Path | None = None,
        on_step: Callable[[str, dict], None] | None = None, session: str | None = None,
        ask: bool = False, checkpointer=None, thread_id: str | None = None, resume: str | None = None) -> dict:
    """Run the team once. run_dir defaults to a new output/visit_prep/<time>/ folder;
    on_step(node, update) is called as each node finishes (the app shows progress with it).
    With Langfuse on, the run is one `visit-prep` trace (tag `visit-prep`, the app's hashed
    browser session as its session) whose output is the run record below; text stays masked.

    ask=True lets the team stop before planning to ask the guardian (needs a checkpointer and
    a thread_id). The run then returns with "questions" and "paused": True; call run again with
    the same checkpointer and thread_id and resume=<the answer> ("" to skip) to finish it."""
    if run_dir is None:
        run_dir = OUTPUT_DIR / datetime.now(UTC).astimezone().strftime("%Y%m%d_%H%M%S")
        run_dir.mkdir(parents=True)
        print("산출물 폴더:", run_dir)
    if resume is not None:
        inputs = Command(resume=resume)
    else:
        inputs = {
            "consultation": consultation, "region": region, "profile": profile,
            "urgent": detect_urgent_sign(consultation) or "", "ask": ask, "questions": [],
            "plan": [], "findings": {}, "failures": {}, "outcome": "", "round": 0, "draft": "",
            "review": None, "feedback": "", "instruction": "",
        }
    run_config = {"recursion_limit": 40}
    if thread_id is not None:
        run_config["configurable"] = {"thread_id": thread_id}
    state, paused = None, False
    visits: dict[str, int] = {}
    started = time.perf_counter()
    with tracing.run_trace("visit-prep", question_fingerprint(consultation), session=session, tags=["visit-prep"],
                           metadata={"region_given": bool(region), "profile_given": bool(profile),
                                     "resumed": resume is not None}) as trace:
        try:
            for mode, chunk in build_graph(checkpointer).stream(
                inputs,
                context={"run_dir": run_dir, "writer": create_writer(run_dir)},
                config={**run_config, "callbacks": trace.callbacks},
                stream_mode=["updates", "values"],
            ):
                if mode == "values":
                    state = chunk
                    continue
                for node, update in chunk.items():
                    if node == "__interrupt__":  # stopped in ask_guardian, waiting for the answer
                        paused = True
                        continue
                    # One "updates" event per finished top-level node (each parallel researcher
                    # counts once), so these are the node visits of the run.
                    visits[node] = visits.get(node, 0) + 1
                    if on_step is not None:
                        on_step(node, update or {})
        finally:
            trace.finish({"status": "waiting_for_guardian", "questions": len(state.get("questions", []))} if paused
                         else run_record(state, time.perf_counter() - started, visits))
    tracing.flush()
    if paused:
        return {"run_dir": run_dir, **state, "paused": True, "visits": visits}
    save_visits(run_dir, visits)
    print("저장한 파일:", sorted(path.name for path in run_dir.iterdir()))
    return {"run_dir": run_dir, **state, "paused": False, "visits": visits}


def repeated_nodes(visits: dict[str, int]) -> list[str]:
    """Workers that ran more often than a normal run needs (config.VISIT_LIMITS). The supervisor
    is left out: it runs after every worker, so its count only follows theirs."""
    return sorted(node for node, limit in config.VISIT_LIMITS.items() if visits.get(node, 0) > limit)


def save_visits(run_dir: Path, visits: dict[str, int]) -> None:
    """Add the visit counts to result.json: the publisher writes it before the run ends."""
    path = run_dir / config.RESULT_FILE
    if not path.exists():
        return
    record = json.loads(path.read_text(encoding="utf-8"))
    record.update(visits=visits, repeated_nodes=repeated_nodes(visits))
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def run_record(state: dict | None, seconds: float, visits: dict[str, int] | None = None) -> dict:
    """What the trace keeps of a run: status, rounds, task kinds and node visits, no text."""
    visits = visits or {}
    if state is None:
        return {"error": "team run did not finish", "seconds": round(seconds, 1), "visits": visits}
    review = state.get("review") or {}
    return {
        "visits": visits,
        "repeated_nodes": repeated_nodes(visits),
        "status": run_status(state),
        "outcome": state.get("outcome") or "complete",
        "round": state.get("round", 0),
        "kind": [task["kind"] for task in state.get("plan", [])],
        "failed_kinds": failed_kinds(state),
        "fallback_kinds": fallback_kinds(state),
        # Exception class names only (the messages can quote the request): enough to tell an
        # API outage from a code error when a production run is held.
        "failed_errors": sorted({failure["error"].split(":", 1)[0] for failure in (state.get("failures") or {}).values()}),
        "supported_claims": review.get("supported", 0),
        "unsupported_claims": len(review.get("unsupported", [])),
        "seconds": round(seconds, 1),
    }


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
