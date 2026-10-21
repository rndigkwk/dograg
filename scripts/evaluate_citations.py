"""Sentence citations and invented numbers in health answers (real model calls, no judge).

    uv run python scripts/evaluate_citations.py --name before
    uv run python scripts/evaluate_citations.py --name after

The 20 answerable health questions of tests/data/crag_eval_questions.json go through the app (CRAG
on). For every answer, the evidence the answer model was given is captured and the answer is
checked with src/citations.py, the same check the app runs:
- cited_rate: sentences carrying a [사례 n] / [지침 n] citation, of all sentences
- invalid: citations to evidence that was not given
- unsupported: sentences with a number found in neither the cited evidence (all of it when the
  sentence cites nothing) nor the question
- guards: what the app's check did (citation_fixed: rewritten once; citation_dropped: sentences cut)
- latency_ms: the whole answer, rewrite included
Model calls: about 5 per question (100 a run), plus the rewrites. Results:
output/experiments/citations_<name>.json.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

QUESTIONS = PROJECT_DIR / "tests" / "data" / "crag_eval_questions.json"


def evidence_lists(docs) -> tuple[list[str], list[str]]:
    """The case and guide texts in format_rag_context order (the [사례 n], [지침 n] numbers)."""
    cases = [f"{doc.page_content}\n{doc.metadata.get('qa.output', '')}" for doc in docs
             if doc.metadata.get("kind") != "care_guide"]
    guides = [doc.page_content for doc in docs if doc.metadata.get("kind") == "care_guide"]
    return cases, guides


def measure(answer: str, docs, question: str) -> dict:
    from src import citations

    cases, guides = evidence_lists(docs)
    problems = citations.check_answer(answer, cases, guides, context=question)
    lines = citations.sentences(answer)
    return {
        "sentences": len(lines),
        "cited": sum(bool(citations.cited(line)) for line in lines),
        "invalid": len(problems.invalid),
        "unsupported": len(problems.unsupported),
        "unsupported_sentences": problems.unsupported,
        "numbers": sum(len(citations.claimed_numbers(line)) for line in lines),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"
    items = [item for item in json.loads(QUESTIONS.read_text(encoding="utf-8"))["items"]
             if item["group"] == "health_answerable"][: args.limit]
    from cost_guard import confirm

    if not confirm("evaluate_citations", len(items) * 5, "about 5 per question (app), no judge", args.yes):
        return 1
    from src import chatbot as app
    from src import resources
    from src.tools import health

    captured: list = []
    original = health.generate_health_answer

    def record(question, docs, *rest, **kwargs):
        captured.append(list(docs))
        return original(question, docs, *rest, **kwargs)

    rows = []
    with tempfile.TemporaryDirectory(prefix="ragdog-cite-", ignore_cleanup_errors=True) as directory:
        resources.CHROMA_DIR = Path(directory) / "chroma_db"
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", resources.CHROMA_DIR)
        health.generate_health_answer = record
        try:
            for item in items:
                captured.clear()
                started = time.perf_counter()
                result = app.chatbot(item["question"], crag=True, crag_reports=False)
                row = {"id": item["id"], "route": result.get("route"), "abstained": result.get("abstained", False),
                       "guards": result.get("guards", []), "latency_ms": round((time.perf_counter() - started) * 1000),
                       "answer": result.get("answer", "")}
                if captured and not row["abstained"]:
                    row.update(measure(row["answer"], captured[-1], item["question"]))
                rows.append(row)
                print(f"{item['id']} {row['route']} cited {row.get('cited')}/{row.get('sentences')} "
                      f"unsupported {row.get('unsupported')} invalid {row.get('invalid')} {row['guards']}", flush=True)
        finally:
            health.generate_health_answer = original
    answered = [row for row in rows if "sentences" in row]
    latencies = sorted(row["latency_ms"] for row in rows)
    summary = {
        "answered": len(answered), "questions": len(rows),
        "cited_rate": round(sum(r["cited"] for r in answered) / max(1, sum(r["sentences"] for r in answered)), 3),
        "answers_with_unsupported_number": sum(r["unsupported"] > 0 for r in answered),
        "unsupported_sentences": sum(r["unsupported"] for r in answered),
        "invalid_citations": sum(r["invalid"] for r in answered),
        "numbers": sum(r["numbers"] for r in answered),
        "rewritten": sum("citation_fixed" in r["guards"] for r in rows),
        "dropped": sum("citation_dropped" in r["guards"] for r in rows),
        "latency_p50_s": round(statistics.median(latencies) / 1000, 1),
        "latency_p90_s": round(latencies[int(0.9 * (len(latencies) - 1))] / 1000, 1),
    }
    print(json.dumps(summary, ensure_ascii=False))
    output = PROJECT_DIR / "output" / "experiments" / f"citations_{args.name}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
