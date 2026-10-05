"""Judge whether chatbot answers stay within their evidence (real model calls).

    uv run python scripts/evaluate_faithfulness.py --crag on
    uv run python scripts/evaluate_faithfulness.py --crag off
    uv run python scripts/evaluate_faithfulness.py --judge-only output/faithfulness_on.json

Phase 1 asks the app the 60 questions in tests/data/crag_eval_questions.json and records,
for every generated answer, the exact evidence text given to the answer model
(format_rag_context / format_report_context). Phase 2 asks a judge model to split each
answer into claims and label them (src/faithfulness.py). Abstentions are not judged.

The judge is the app's own chat model, so it may be lenient toward its own style;
spot-check the unsupported claims listed in the output. Runs on a disposable Chroma
copy; retrieved evidence and answers are sent to the OpenAI API.
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


def generate(rag, items: list[dict], crag: bool) -> list[dict]:
    captured: list[str] = []
    health_answer, report_answer = rag.generate_health_answer, rag.generate_report_answer

    def record_health(question, docs, *args, **kwargs):
        captured.append(rag.format_rag_context(docs))
        return health_answer(question, docs, *args, **kwargs)

    def record_report(question, docs, *args, **kwargs):
        captured.append(rag.format_report_context(docs))
        return report_answer(question, docs, *args, **kwargs)

    rag.generate_health_answer, rag.generate_report_answer = record_health, record_report
    rows = []
    try:
        for index, item in enumerate(items, start=1):
            captured.clear()
            started = time.perf_counter()
            try:
                result, error = rag.chatbot(item["question"], crag=crag, crag_reports=False), None
            except Exception as exc:  # noqa: BLE001 - one failure should not stop the evaluation
                result, error = {}, type(exc).__name__
            rows.append({
                "id": item["id"], "group": item["group"], "question": item["question"],
                "route": result.get("route", "error"), "abstained": result.get("abstained", False),
                "error": error, "answer": result.get("answer", ""),
                "context": captured[-1] if captured else None,
                "latency_ms": round((time.perf_counter() - started) * 1000),
            })
            print(f"[gen {index}/{len(items)}] {item['id']} {rows[-1]['route']}"
                  f"{' abstain' if rows[-1]['abstained'] else ''}", flush=True)
    finally:
        rag.generate_health_answer, rag.generate_report_answer = health_answer, report_answer
    return rows


def judge(rag, rows: list[dict]) -> None:
    from src.faithfulness import (
        build_judge,
        build_verifier,
        recheck_unsupported,
        score_judgment,
    )

    model = rag.load_chat_model()
    judge_chain, verifier = build_judge(model), build_verifier(model)
    for index, row in enumerate(rows, start=1):
        row.pop("score", None)
        if row["abstained"] or not row.get("context") or not row["answer"]:
            continue
        try:
            judgment = judge_chain.invoke({"question": row["question"], "context": row["context"], "answer": row["answer"]})
            row["first_pass"] = score_judgment(judgment, row["context"])
            row["rechecked_supported"] = recheck_unsupported(
                judgment, row["context"],
                lambda claim, context=row["context"]: verifier.invoke({"context": context, "claim": claim}),
            )
            row["score"] = score_judgment(judgment, row["context"])
            row["claims"] = [claim.model_dump() for claim in judgment.claims]
        except Exception as exc:  # noqa: BLE001
            row["judge_error"] = type(exc).__name__
        print(f"[judge {index}/{len(rows)}] {row['id']} {row.get('score', {}).get('faithfulness')}", flush=True)


def summarize(rows: list[dict]) -> dict:
    from src.faithfulness import summarize_scores

    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["group"]].append(row)
    summary = {}
    for group, items in sorted(groups.items()):
        scored = [r["score"] for r in items if "score" in r]
        first = [r["first_pass"] for r in items if "first_pass" in r]
        summary[group] = {
            "questions": len(items),
            "abstained": sum(r["abstained"] for r in items),
            "not_judged": sum("score" not in r and not r["abstained"] for r in items),
            **summarize_scores(scored),
            "first_pass_faithfulness": summarize_scores(first)["faithfulness"] if first else None,
            "rechecked_supported": sum(r.get("rechecked_supported", 0) for r in items),
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--crag", choices=["on", "off"], default="on")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, help="first N questions only (smoke run)")
    parser.add_argument("--judge-only", type=Path, help="re-judge answers saved by an earlier run")
    args = parser.parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"

    from pages import rag

    if args.judge_only:
        output = args.output or args.judge_only
        report = json.loads(args.judge_only.read_text(encoding="utf-8"))
        rows = report["rows"]
    else:
        output = args.output or PROJECT_DIR / "output" / f"faithfulness_{args.crag}.json"
        os.environ["CHAT_RUN_LOG"] = str(output.with_suffix(".runs.jsonl"))
        items = json.loads(QUESTIONS.read_text(encoding="utf-8"))["items"][: args.limit]
        with tempfile.TemporaryDirectory(prefix="dograg-faith-", ignore_cleanup_errors=True) as directory:
            rag.CHROMA_DIR = Path(directory) / "chroma_db"
            shutil.copytree(PROJECT_DIR / "data" / "chroma_db", rag.CHROMA_DIR)
            rows = generate(rag, items, crag=args.crag == "on")
        report = {"crag": args.crag, "questions": str(QUESTIONS.relative_to(PROJECT_DIR))}
    judge(rag, rows)
    report.update(summary=summarize(rows), rows=rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
