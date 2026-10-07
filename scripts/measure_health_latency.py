"""Per-node latency of health answers (real model calls), for paired comparisons.

    uv run python scripts/measure_health_latency.py --output output/latency/nodes_default.json
    CRAG_REVIEW_REASONING_EFFORT=medium uv run python scripts/measure_health_latency.py --output ...

Runs the 40 health questions of tests/data/crag_eval_questions.json with CRAG on and
records, per question, the time each graph node took (from the on_step callback),
the time to the first answer token, the total, and the outcome. Comparing two runs
question by question separates a node's change from the run-to-run spread of the
answer model, which dominates end-to-end numbers. Runs on a disposable Chroma copy.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

QUESTIONS = PROJECT_DIR / "tests" / "data" / "crag_eval_questions.json"


def measure(question: str) -> dict:
    from src.chatbot import chatbot

    started = time.perf_counter()
    nodes: dict[str, float] = {}
    previous = started
    first_token: list[float] = []

    def on_step(node: str, update: dict) -> None:
        nonlocal previous
        now = time.perf_counter()
        nodes[node] = round(nodes.get(node, 0.0) + now - previous, 2)
        previous = now

    def on_token(text: str) -> None:
        if not first_token:
            first_token.append(time.perf_counter())

    result = chatbot(question, crag=True, on_step=on_step, on_token=on_token)
    total = time.perf_counter() - started
    return {
        "nodes": nodes,
        "first_token_s": round((first_token[0] if first_token else time.perf_counter()) - started, 2),
        "total_s": round(total, 2),
        "result": result,
    }


def main() -> int:
    from evaluate_crag import outcome

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")

    from src import resources, settings

    items = [item for item in json.loads(QUESTIONS.read_text(encoding="utf-8"))["items"] if item["group"].startswith("health")]
    rows = []
    with tempfile.TemporaryDirectory(prefix="ragdog-latency-", ignore_cleanup_errors=True) as directory:
        resources.CHROMA_DIR = Path(directory) / "chroma_db"
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", resources.CHROMA_DIR)
        measure("워밍업: 강아지가 설사를 해요")  # models, indexes and caches load outside the measurement
        for index, item in enumerate(items[: args.limit], start=1):
            measured = measure(item["question"])
            result = measured.pop("result")
            rows.append({"id": item["id"], "expected": item["expected"],
                         "outcome": outcome(result, result.get("decision")), **measured})
            print(f"[{index}/{len(items)}] {item['id']} {rows[-1]['outcome']} {rows[-1]['total_s']}s", flush=True)
    report = {"review_effort": settings.get_setting("CRAG_REVIEW_REASONING_EFFORT") or resources.REVIEW_REASONING_EFFORT,
              "rows": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
