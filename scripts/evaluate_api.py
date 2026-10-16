"""The CRAG and place-routing sets asked through the deployed API (POST /chat), not in-process.

    uv run python scripts/evaluate_api.py --name api-2026-10-15 --yes
    uv run python scripts/check_regression.py crag api-2026-10-15 routing api-2026-10-15

scripts/langfuse_experiments.py runs the same sets by calling the chatbot in this process; this
asks the Cloud Run API the Next.js frontend will call (ADR-0008), so the server's settings,
secrets, search backend and streaming are measured too. Results go to output/experiments in the
same format, so check_regression.py compares them with the weekly limits.

Differences from the in-process run:
- outcome is answer or abstain: the API does not return the CRAG decision, so "partial" counts
  as answer (the metrics treat them alike).
- kind (routing) is read from the place rows the answer listed; a count answer ("몇 곳") lists
  none, so its kind is not scored (kind_unscored in the result).
- latency is the whole request seen from here (network and streaming included), one question at
  a time: the API runs as one instance.

The user agent carries RagDogCheck (src/data_gaps.CHECK_AGENT), so these answers are not recorded as
data gaps. The question limit is skipped only with the check token: RAGDOG_CHECK_TOKEN in the
environment, sent as X-RagDog-Check and equal to the API's secret of that name. Without it the run
counts as one browser and one network (src/rate_limit.py: 60 questions an hour per network), so 96
questions stop at the limit (the user agent alone skipped it until 2026-10-16; anyone can set one).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_guard  # noqa: E402
from langfuse_experiments import DATASETS  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parents[1]
API_URL = "https://ragdog-api-892238791473.asia-northeast3.run.app"
AGENT = "RagDogCheck/1.0 (scripts/evaluate_api.py)"
CALLS_PER_QUESTION = {"crag": 4, "routing": 2}  # route + grade + answer (+ rewrite); route + SQL or answer


def ask(client: httpx.Client, url: str, question: str) -> tuple[dict | None, float]:
    """The result event of one /chat request, and the seconds it took."""
    started = time.perf_counter()
    result, kind = None, None
    with client.stream("POST", f"{url}/chat", json={"question": question}) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith("event: "):
                kind = line[len("event: "):]
            elif line.startswith("data: ") and kind in ("result", "error", "limited"):
                data = json.loads(line[len("data: "):])
                if kind != "result":
                    raise RuntimeError(f"{kind}: {data}")
                result = data
    return result, round(time.perf_counter() - started, 2)


def crag_scores(items: list[dict]) -> dict:
    def rate(expected, bad):
        chosen = [i for i in items if i["expected"] == expected]
        return sum(i["output"]["outcome"] in bad for i in chosen) / len(chosen) if chosen else 0.0

    latencies = sorted(i["output"]["latency_s"] for i in items)
    return {
        "accuracy": sum(i["scores"]["correct_behavior"] for i in items) / len(items),
        "over_abstain": rate("answer", {"abstain"}),
        "missed_abstain": rate("abstain", {"answer", "partial"}),
        "latency_p50_s": statistics.median(latencies),
        "latency_p90_s": latencies[int(0.9 * (len(latencies) - 1))],
    }


def routing_scores(items: list[dict]) -> dict:
    kinds = [i["scores"]["kind_correct"] for i in items if "kind_correct" in i["scores"]]
    return {
        "route_accuracy": sum(i["scores"]["route_correct"] for i in items) / len(items),
        "kind_accuracy": sum(kinds) / len(kinds) if kinds else 0.0,
        "kind_unscored": sum(1 for i in items if i["kind_unscored"]),
    }


def run_set(client: httpx.Client, url: str, set_name: str) -> list[dict]:
    raw = json.loads(DATASETS[set_name][1].read_text(encoding="utf-8"))["items"]
    items = []
    for number, item in enumerate(raw, 1):
        result, seconds = ask(client, url, item["question"])
        if set_name == "crag":
            outcome = "abstain" if result["abstained"] else "answer"
            ok = outcome == "abstain" if item["expected"] == "abstain" else outcome != "abstain"
            items.append({"id": item["id"], "expected": item["expected"],
                          "output": {"route": result["route"], "outcome": outcome, "latency_s": seconds},
                          "scores": {"correct_behavior": float(ok)}})
        else:
            row_kinds = [row["kind"] for row in result["hospital_rows"] if row.get("kind")]
            kind = row_kinds[0] if row_kinds else None
            scores = {"route_correct": float(result["route"] == item["route"])}
            unscored = item["route"] == "sql" and kind is None
            if item["route"] == "sql" and not unscored:
                scores["kind_correct"] = float(kind == item["kind"])
            items.append({"id": item["id"], "output": {"route": result["route"], "kind": kind, "latency_s": seconds},
                          "scores": scores, "kind_unscored": unscored})
        mark = "ok" if all(items[-1]["scores"].values()) else "MISS"
        print(f"[{set_name} {number}/{len(raw)}] {mark} {item['id']} {result['route']} {seconds}s", flush=True)
    return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", required=True, help="run name: output/experiments/<set>_<name>.json")
    parser.add_argument("--url", default=API_URL)
    parser.add_argument("--sets", nargs="+", default=["crag", "routing"], choices=["crag", "routing"])
    parser.add_argument("--yes", action="store_true", help="go on above the cost guard's threshold")
    args = parser.parse_args(argv)

    counts = {name: len(json.loads(DATASETS[name][1].read_text(encoding="utf-8"))["items"]) for name in args.sets}
    calls = sum(counts[name] * CALLS_PER_QUESTION[name] for name in args.sets)
    detail = ", ".join(f"{name} {count}문항" for name, count in counts.items())
    if not cost_guard.confirm("evaluate_api", calls, detail, yes=args.yes):
        return 1

    headers = {"User-Agent": AGENT}
    if token := os.environ.get("RAGDOG_CHECK_TOKEN"):
        headers["X-RagDog-Check"] = token
    else:
        print("RAGDOG_CHECK_TOKEN이 없어 질문 한도가 적용됩니다(네트워크당 시간 60번).", flush=True)
    with httpx.Client(timeout=180, headers=headers) as client:
        print(client.get(f"{args.url}/health").json(), flush=True)  # also wakes the instance
        for set_name in args.sets:
            items = run_set(client, args.url, set_name)
            scores = crag_scores(items) if set_name == "crag" else routing_scores(items)
            print(json.dumps({set_name: scores}, ensure_ascii=False), flush=True)
            saved = PROJECT_DIR / "output" / "experiments" / f"{set_name}_{args.name}.json"
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_text(json.dumps({"run": args.name, "url": args.url, "run_scores": scores, "items": items},
                                        ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
