"""Evaluate CRAG answer/abstain behavior on a fixed 60-question set (real model calls).

    uv run python scripts/evaluate_crag.py              # CRAG on
    uv run python scripts/evaluate_crag.py --crag off   # same questions, CRAG off

Groups (tests/data/crag_eval_questions.json):
- health_answerable: validation questions; abstaining here is over-abstention.
- health_unanswerable: other species, humans, fictional/impossible; answering here is a miss.
- report_answerable / report_unanswerable: fixed gold pages from the report embedding study.

Runs on a disposable Chroma copy and writes per-run logs to a separate JSONL.
Retrieved Q&A and report excerpts are sent to the OpenAI API.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

QUESTIONS = PROJECT_DIR / "tests" / "data" / "crag_eval_questions.json"


def outcome(result: dict, decision: str | None) -> str:
    """abstain / partial (answered on evidence graded ambiguous) / answer."""
    if result.get("abstained"):
        return "abstain"
    return "partial" if decision == "ambiguous" else "answer"


def gold_page_hit(item: dict, result: dict) -> bool | None:
    gold = {(name, page) for name, page in item.get("gold_pages", [])}
    if not gold:
        return None
    found = {(Path(row.get("source", "")).name, row.get("page")) for row in result.get("evidence_rows", [])}
    return bool(gold & found)


def summarize(rows: list[dict]) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["group"]].append(row)
    summary = {}
    for group, items in sorted(groups.items()):
        count = len(items)
        by_outcome = {key: sum(r["outcome"] == key for r in items) for key in ("answer", "partial", "abstain", "error")}
        entry = {"count": count, **by_outcome,
                 "routes": dict(sorted({r["route"]: sum(x["route"] == r["route"] for x in items) for r in items}.items()))}
        hits = [r["gold_page_hit"] for r in items if r["gold_page_hit"] is not None]
        if hits:
            entry["gold_page_hit"] = f"{sum(hits)}/{len(hits)}"
        tokens = [r["total_tokens"] for r in items if r["total_tokens"]]
        latency = [r["latency_ms"] for r in items if r["latency_ms"]]
        entry["mean_total_tokens"] = round(sum(tokens) / len(tokens)) if tokens else None
        entry["mean_latency_ms"] = round(sum(latency) / len(latency)) if latency else None
        summary[group] = entry
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--crag", choices=["on", "off"], default="on")
    parser.add_argument("--crag-reports", choices=["on", "off"], default="off",
                        help="also run report questions through CRAG (off in the app)")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, help="first N questions only (smoke run)")
    args = parser.parse_args()
    output = args.output or PROJECT_DIR / "output" / f"crag_eval_{args.crag}.json"
    run_log = output.with_suffix(".runs.jsonl")
    run_log.unlink(missing_ok=True)
    os.environ["CHAT_RUN_LOG"] = str(run_log)
    os.environ["HF_HUB_OFFLINE"] = "1"

    from pages import rag

    items = json.loads(QUESTIONS.read_text(encoding="utf-8"))["items"][: args.limit]
    rows = []
    with tempfile.TemporaryDirectory(prefix="dograg-crag-eval-", ignore_cleanup_errors=True) as directory:
        rag.CHROMA_DIR = Path(directory) / "chroma_db"
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", rag.CHROMA_DIR)
        for index, item in enumerate(items, start=1):
            started = time.perf_counter()
            try:
                result = rag.chatbot(item["question"], crag=args.crag == "on", crag_reports=args.crag_reports == "on")
                error = None
            except Exception as exc:  # noqa: BLE001 - one failure should not stop the evaluation
                result, error = {}, type(exc).__name__
            logged = {}
            if run_log.exists():
                lines = run_log.read_text(encoding="utf-8").splitlines()
                logged = json.loads(lines[-1]) if lines else {}
            row_outcome = "error" if error else outcome(result, logged.get("decision"))
            usage = logged.get("token_usage") or {}
            rows.append({
                "id": item["id"], "group": item["group"], "kind": item.get("kind"),
                "expected": item["expected"], "question": item["question"],
                "route": result.get("route", "error"), "outcome": row_outcome, "error": error,
                "decision": logged.get("decision"), "rewrite_count": logged.get("rewrite_count"),
                "evidence_count": len(result.get("evidence_rows", [])),
                "gold_page_hit": gold_page_hit(item, result),
                "total_tokens": sum(v.get("total_tokens", 0) for v in usage.values()),
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "answer_head": result.get("answer", "")[:300],
            })
            print(f"[{index}/{len(items)}] {item['id']} {rows[-1]['route']} {row_outcome}", flush=True)
    report = {"crag": args.crag, "questions": str(QUESTIONS.relative_to(PROJECT_DIR)),
              "summary": summarize(rows), "rows": rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
