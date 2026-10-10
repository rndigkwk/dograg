"""Evaluation sets as Langfuse datasets, and runs of the app over them as Langfuse experiments.

    uv run python scripts/langfuse_experiments.py upload                     # create/refresh datasets
    uv run python scripts/langfuse_experiments.py run crag --name effort-low  # 60 questions, real model
    uv run python scripts/langfuse_experiments.py run routing --name rules    # 36 questions
    uv run python scripts/langfuse_experiments.py run visit --name baseline   # 12 consultations, visit-prep team

Datasets (item ids are fixed, so uploading again updates items instead of adding):
- ragdog-crag-60: tests/data/crag_eval_questions.json. Expected: answer or abstain.
- ragdog-place-routing-36: tests/data/place_routing_questions.json. Expected: route and kind.
- ragdog-visit-prep-12: tests/data/visit_prep_consultations.json. Expected: urgent flag, and
  whether the consultation is about a dog (review should pass) or another species.

Each run becomes an experiment run in Langfuse with item scores (correct_behavior,
route_correct, kind_correct, gold_page_hit, latency_s) and run scores (accuracy,
over_abstain, missed_abstain, latency p50/p90). Run metadata records the model and its
reasoning effort, so runs can be compared side by side in the Langfuse UI.

These questions are our own evaluation data (AI Hub validation Q&A and hand-written
questions), not user conversations. Traces still go through the app's masking
(src/tracing.py), so answers appear as lengths; the scores carry the results.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

DATASETS = {
    "crag": ("ragdog-crag-60", PROJECT_DIR / "tests" / "data" / "crag_eval_questions.json"),
    "routing": ("ragdog-place-routing-36", PROJECT_DIR / "tests" / "data" / "place_routing_questions.json"),
    "visit": ("ragdog-visit-prep-12", PROJECT_DIR / "tests" / "data" / "visit_prep_consultations.json"),
}


def dataset_items(kind: str) -> list[dict]:
    """Dataset items as Langfuse stores them: input, expected_output, metadata, fixed id."""
    name, path = DATASETS[kind]
    items = json.loads(path.read_text(encoding="utf-8"))["items"]
    if kind == "crag":
        return [{
            "id": f"{name}-{item['id']}", "input": {"question": item["question"]},
            "expected_output": {"behavior": item["expected"], "gold_pages": item.get("gold_pages", [])},
            "metadata": {"id": item["id"], "group": item["group"]},
        } for item in items]
    if kind == "visit":
        return [{
            "id": f"{name}-{item['id']}",
            "input": {key: item[key] for key in ("consultation", "region", "profile")},
            "expected_output": {"scope": item["scope"], "urgent": item["urgent"]},
            "metadata": {"id": item["id"]},
        } for item in items]
    return [{
        "id": f"{name}-{item['id']}", "input": {"question": item["question"]},
        "expected_output": {"route": item["route"], "kind": item["kind"]},
        "metadata": {"id": item["id"]},
    } for item in items]


def upload(langfuse) -> None:
    for kind, (name, path) in DATASETS.items():
        langfuse.create_dataset(name=name, description=f"RagDog evaluation set from {path.relative_to(PROJECT_DIR).as_posix()}")
        items = dataset_items(kind)
        for item in items:
            langfuse.create_dataset_item(dataset_name=name, **item)
        print(f"{name}: {len(items)} items")


# --- CRAG answer/abstain set ----------------------------------------------------
def crag_task(*, item, **kwargs):
    from evaluate_crag import outcome

    from src.chatbot import chatbot

    started = time.perf_counter()
    result = chatbot(item.input["question"], crag=True, crag_reports=False)
    return {
        "route": result["route"],
        "decision": result.get("decision"),
        "outcome": outcome(result, result.get("decision")),
        "latency_s": round(time.perf_counter() - started, 2),
        "evidence_pages": [[Path(row.get("source", "")).name, row.get("page")] for row in result.get("evidence_rows", [])],
    }


def crag_evaluators():
    from langfuse import Evaluation

    def correct_behavior(*, output, expected_output, **kwargs):
        expected = expected_output["behavior"]
        ok = output["outcome"] == "abstain" if expected == "abstain" else output["outcome"] in ("answer", "partial")
        return Evaluation(name="correct_behavior", value=1.0 if ok else 0.0, comment=f"expected {expected}, got {output['outcome']}")

    def gold_page_hit(*, output, expected_output, **kwargs):
        gold = {tuple(page) for page in expected_output.get("gold_pages") or []}
        if not gold:
            return []
        hit = bool(gold & {tuple(page) for page in output["evidence_pages"]})
        return Evaluation(name="gold_page_hit", value=1.0 if hit else 0.0)

    def latency(*, output, **kwargs):
        return Evaluation(name="latency_s", value=output["latency_s"])

    return [correct_behavior, gold_page_hit, latency]


def crag_run_evaluators():
    from langfuse import Evaluation

    def summary(*, item_results, **kwargs):
        def rate(results, expected, bad):
            chosen = [r for r in results if r.item.expected_output["behavior"] == expected]
            return sum(r.output["outcome"] in bad for r in chosen) / len(chosen) if chosen else 0.0

        correct = [e.value for r in item_results for e in r.evaluations if e.name == "correct_behavior"]
        latencies = sorted(r.output["latency_s"] for r in item_results)
        return [
            Evaluation(name="accuracy", value=sum(correct) / len(correct)),
            Evaluation(name="over_abstain", value=rate(item_results, "answer", {"abstain"})),
            Evaluation(name="missed_abstain", value=rate(item_results, "abstain", {"answer", "partial"})),
            Evaluation(name="latency_p50_s", value=statistics.median(latencies)),
            Evaluation(name="latency_p90_s", value=latencies[int(0.9 * (len(latencies) - 1))]),
        ]

    return [summary]


# --- place routing set ----------------------------------------------------------
def routing_task(*, item, **kwargs):
    from unittest.mock import patch

    from src import resources
    from src.tools import places, router

    question = item.input["question"]
    rules_only = patch.object(resources, "load_chat_model", return_value=None)
    with rules_only if ROUTING_RULES_ONLY else nullcontext():
        route = router.classify_question(question)
    return {"route": route, "kind": places.place_kind(question)}


ROUTING_RULES_ONLY = False  # set from --rules-only


def routing_evaluators():
    from langfuse import Evaluation

    def route_correct(*, output, expected_output, **kwargs):
        return Evaluation(name="route_correct", value=1.0 if output["route"] == expected_output["route"] else 0.0)

    def kind_correct(*, output, expected_output, **kwargs):
        if expected_output["route"] != "sql":
            return []  # only place searches have a kind to get right
        return Evaluation(name="kind_correct", value=1.0 if output["kind"] == expected_output["kind"] else 0.0)

    return [route_correct, kind_correct]


def routing_run_evaluators():
    from langfuse import Evaluation

    def summary(*, item_results, **kwargs):
        def mean(name):
            values = [e.value for r in item_results for e in r.evaluations if e.name == name]
            return sum(values) / len(values) if values else 0.0
        return [Evaluation(name="route_accuracy", value=mean("route_correct")),
                Evaluation(name="kind_accuracy", value=mean("kind_correct"))]

    return [summary]


# --- visit-prep team set ---------------------------------------------------------
def visit_task(*, item, **kwargs):
    from team.core import config
    from team.main import run as run_team

    started = time.perf_counter()
    state = run_team(**item.input)
    seconds = round(time.perf_counter() - started, 1)
    result = json.loads((state["run_dir"] / config.RESULT_FILE).read_text(encoding="utf-8"))
    report = (state["run_dir"] / config.REPORT_FILE).read_text(encoding="utf-8")
    review = result["review"] or {}
    return {
        "status": "passed" if result["status"] == config.PASSED else "human_check",
        "round": result["round"],
        "latency_s": seconds,
        "urgent": bool(result["urgent"]),
        "tasks": [task["kind"] for task in result["plan"]],
        "hospitals": sum(len(f["key_points"]) for f in result["findings"].values() if f["kind"] == "place"),
        "supported": review.get("supported", 0),
        "unsupported": len(review.get("unsupported", [])),
        "says_no_evidence": any(phrase in report for phrase in NO_EVIDENCE_PHRASES),
        "visits": state["visits"],
        "repeated_nodes": result.get("repeated_nodes", []),
        "reasks": len(result.get("reasks") or {}),
        "no_answer": sum(failure["error"].startswith("NoAnswer") for failure in result["failures"].values()),
        "run_dir": state["run_dir"].relative_to(PROJECT_DIR).as_posix(),
        **fee_citations(report),
    }


FEE_CSV = PROJECT_DIR / "data" / "vet_fees" / "vet_fees.csv"
NUMBER = r"\d{1,3}(?:,\d{3})+|\d+"
WON = re.compile(rf"({NUMBER})(?:\s*~\s*({NUMBER}))?\s*원")  # "50,000원", and both ends of "15,000~110,000원"


def _fee_rows() -> list[dict]:
    if not FEE_CSV.exists():
        return []
    with FEE_CSV.open(encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def _rows_for(evidence_id: str, rows: list[dict]) -> list[dict]:
    """Survey rows an evidence id (team/tools/research.py regional_fee_stats) can stand for."""
    text = evidence_id.removeprefix("fee-")
    found = []
    for row in rows:
        if "-".join(row["item"].split()) not in text:
            continue
        if row["level"] == "national":
            if text.startswith("전국"):
                found.append(row)
        elif row["sido"] in text and (row["level"] == "sido" or row["sigungu"] in text):
            found.append(row)
    return found


def fee_citations(report: str) -> dict:
    """Regional fee statistics in a report: how many distinct fee- ids it cites, and whether every
    amount on a line citing one is a value of a cited row (median, mean, min or max), i.e. copied
    from the survey rather than made up or mixed up."""
    rows = _fee_rows()
    cited, amounts, wrong = set(), 0, []
    for line in report.splitlines():
        ids = re.findall(r"\[(fee-[^\]]+)\]", line)
        if not ids:
            continue
        cited.update(ids)
        values = {int(row[key]) for evidence_id in ids for row in _rows_for(evidence_id, rows)
                  for key in ("median", "mean", "min", "max")}
        for amount in (number for match in WON.findall(line) for number in match if number):
            amounts += 1
            if int(amount.replace(",", "")) not in values:
                wrong.append(amount)
    return {"fee_ids": sorted(cited), "fee_amounts": amounts, "fee_amounts_wrong": wrong}


NO_EVIDENCE_PHRASES = ("찾지 못", "근거가 없", "근거를 찾", "자료가 없", "확인되지 않", "확인할 수 없")


def visit_evaluators():
    from langfuse import Evaluation

    def passed(*, output, **kwargs):
        return Evaluation(name="passed", value=1.0 if output["status"] == "passed" else 0.0)

    def urgent_correct(*, output, expected_output, **kwargs):
        ok = output["urgent"] == expected_output["urgent"]
        return Evaluation(name="urgent_correct", value=1.0 if ok else 0.0,
                          comment=f"expected {expected_output['urgent']}, got {output['urgent']}")

    def scope_handled(*, output, expected_output, **kwargs):
        """Dog cases: a checked report. Other species: stopped for a person, or the report
        says the evidence was not found (never a confident answer from dog material)."""
        if expected_output["scope"] == "dog":
            ok = output["status"] == "passed"
        else:
            ok = output["status"] == "human_check" or output["says_no_evidence"]
        return Evaluation(name="scope_handled", value=1.0 if ok else 0.0)

    def hospitals_listed(*, input, output, **kwargs):
        if not input["region"]:
            return []
        return Evaluation(name="hospitals_listed", value=1.0 if output["hospitals"] else 0.0)

    def numbers(*, output, **kwargs):
        return [Evaluation(name="rounds", value=output["round"]), Evaluation(name="latency_s", value=output["latency_s"]),
                Evaluation(name="node_visits", value=sum(output["visits"].values()),
                           comment=", ".join(f"{node} {count}" for node, count in output["visits"].items()))]

    def repeat_suspect(*, output, **kwargs):
        """A worker ran more often than a normal run needs (team/core/config.py VISIT_LIMITS)."""
        return Evaluation(name="repeat_suspect", value=1.0 if output["repeated_nodes"] else 0.0,
                          comment=", ".join(output["repeated_nodes"]) or None)

    def regional_fees(*, input, output, **kwargs):
        """Consultations that ask about cost and give a region: the report quotes that region's survey
        row (a fee- citation) and every quoted amount matches the survey."""
        if not input["region"] or not any(word in input["consultation"] for word in COST_WORDS):
            return []
        cited = any(fee_id_in_region(i, input["region"]) and not i.startswith("fee-전국-") for i in output.get("fee_ids", []))
        exact = cited and output["fee_amounts"] > 0 and not output["fee_amounts_wrong"]
        return [Evaluation(name="regional_fee_cited", value=1.0 if cited else 0.0, comment=", ".join(output.get("fee_ids", [])) or None),
                Evaluation(name="fee_amounts_exact", value=1.0 if exact else 0.0,
                           comment=f"{output.get('fee_amounts', 0)} amounts, wrong: {output.get('fee_amounts_wrong') or 'none'}")]

    def fee_region(*, input, output, **kwargs):
        """Every fee statistic a report cites is the guardian's region or the nation (a 해운대구
        consultation once cited 대구광역시 rows)."""
        if not input["region"] or not output.get("fee_ids"):
            return []
        wrong = [i for i in output["fee_ids"] if not fee_id_in_region(i, input["region"])]
        return Evaluation(name="fee_region_ok", value=0.0 if wrong else 1.0, comment=", ".join(wrong) or None)

    def no_answer(*, output, **kwargs):
        """Researchers that stopped without an answer: asked again (reasks), still nothing (no_answer)."""
        return [Evaluation(name="reasked", value=1.0 if output.get("reasks") else 0.0),
                Evaluation(name="no_answer", value=1.0 if output.get("no_answer") else 0.0)]

    return [passed, urgent_correct, scope_handled, hospitals_listed, numbers, repeat_suspect, regional_fees, fee_region,
            no_answer]


def fee_id_in_region(evidence_id: str, region: str) -> bool:
    return evidence_id.startswith("fee-전국-") or f"-{region}-" in evidence_id


COST_WORDS = ("병원비", "진료비", "검사비", "비용", "얼마")


def visit_run_evaluators():
    from langfuse import Evaluation

    def summary(*, item_results, **kwargs):
        def mean(name, results=item_results):
            values = [e.value for r in results for e in r.evaluations if e.name == name]
            return sum(values) / len(values) if values else 0.0

        dogs = [r for r in item_results if r.item.expected_output["scope"] == "dog"]
        latencies = sorted(r.output["latency_s"] for r in item_results)
        return [
            Evaluation(name="dog_pass_rate", value=mean("passed", dogs)),
            Evaluation(name="human_check_rate", value=sum(r.output["status"] == "human_check" for r in item_results) / len(item_results)),
            Evaluation(name="scope_handled_rate", value=mean("scope_handled")),
            Evaluation(name="urgent_accuracy", value=mean("urgent_correct")),
            Evaluation(name="hospitals_listed_rate", value=mean("hospitals_listed")),
            Evaluation(name="mean_rounds", value=mean("rounds")),
            Evaluation(name="repeat_suspect_rate", value=mean("repeat_suspect")),
            Evaluation(name="mean_node_visits", value=mean("node_visits")),
            Evaluation(name="regional_fee_cited_rate", value=mean("regional_fee_cited")),
            Evaluation(name="fee_amounts_exact_rate", value=mean("fee_amounts_exact")),
            Evaluation(name="fee_region_ok_rate", value=mean("fee_region_ok")),
            Evaluation(name="reask_rate", value=mean("reasked")),
            Evaluation(name="no_answer_rate", value=mean("no_answer")),
            Evaluation(name="mean_unsupported", value=statistics.mean(r.output.get("unsupported", 0) for r in item_results)),
            Evaluation(name="latency_p50_s", value=statistics.median(latencies)),
            Evaluation(name="latency_p90_s", value=latencies[int(0.9 * (len(latencies) - 1))]),
        ]

    return [summary]


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_DIR, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run(langfuse, kind: str, run_name: str, description: str | None, concurrency: int):
    from src import resources, settings

    name, _ = DATASETS[kind]
    dataset = langfuse.get_dataset(name)
    metadata = {
        "model": resources.CHAT_MODEL_NAME,
        "reasoning_effort": settings.get_setting("CHAT_REASONING_EFFORT") or "default",
        "commit": git_commit(),
    }
    if kind == "crag":
        task, evaluators, run_evaluators = crag_task, crag_evaluators(), crag_run_evaluators()
    elif kind == "visit":
        task, evaluators, run_evaluators = visit_task, visit_evaluators(), visit_run_evaluators()
    else:
        metadata["router"] = "rules only" if ROUTING_RULES_ONLY else "rules + LLM"
        task, evaluators, run_evaluators = routing_task, routing_evaluators(), routing_run_evaluators()
    return dataset.run_experiment(
        name=name, run_name=run_name, description=description, task=task,
        evaluators=evaluators, run_evaluators=run_evaluators, max_concurrency=concurrency, metadata=metadata,
    )


def main() -> int:
    global ROUTING_RULES_ONLY
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("upload")
    run_parser = commands.add_parser("run")
    run_parser.add_argument("set", choices=sorted(DATASETS))
    run_parser.add_argument("--name", required=True, help="run name shown in Langfuse, e.g. effort-low")
    run_parser.add_argument("--description")
    run_parser.add_argument("--rules-only", action="store_true", help="routing set: keyword rules without the LLM router")
    run_parser.add_argument("--concurrency", type=int, default=1,
                            help="parallel items (default 1: the app's search caches were not built for threads)")
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")

    from src import resources, tracing

    langfuse = tracing.client()
    if langfuse is None:
        print("Langfuse is not configured (LANGFUSE_PUBLIC_KEY/SECRET_KEY).", file=sys.stderr)
        return 1
    try:
        if args.command == "upload":
            upload(langfuse)
            return 0
        ROUTING_RULES_ONLY = args.rules_only
        with tempfile.TemporaryDirectory(prefix="ragdog-experiment-", ignore_cleanup_errors=True) as directory:
            resources.CHROMA_DIR = Path(directory) / "chroma_db"  # Chroma writes to its folder even when reading
            shutil.copytree(PROJECT_DIR / "data" / "chroma_db", resources.CHROMA_DIR)
            result = run(langfuse, args.set, args.name, args.description, args.concurrency)
        print(result.format())
        print(json.dumps({e.name: e.value for e in result.run_evaluations}, ensure_ascii=False))
        saved = PROJECT_DIR / "output" / "experiments" / f"{args.set}_{args.name}.json"
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps({
            "run": args.name, "url": result.dataset_run_url,
            "run_scores": {e.name: e.value for e in result.run_evaluations},
            "items": [{"id": r.item.metadata["id"], "output": r.output,
                       "scores": {e.name: e.value for e in r.evaluations}} for r in result.item_results],
        }, ensure_ascii=False, indent=2), encoding="utf-8")  # local copy for item-by-item comparisons
        if result.dataset_run_url:
            print(result.dataset_run_url)
        return 0
    finally:
        langfuse.flush()


if __name__ == "__main__":
    raise SystemExit(main())
