"""Service levels of the deployed app over the last days, from its Langfuse traces. Read-only, no
model calls.

    uv run python scripts/slo_report.py                 # API (cloudrun-api), last 7 days
    uv run python scripts/slo_report.py --days 28 --environment cloudrun
    uv run python scripts/slo_report.py --check         # exit 1 when an objective is missed

Each answered question is one `chat` span (src/tracing.py) whose output is the masked run record:
latency_ms, error, route, abstained. Its model calls are GENERATION observations with Langfuse's cost.
Objectives are in docs/slo.md (SLO below); with --check a miss exits 1, which the weekly workflow
turns into a GitHub issue. Fewer than MIN_QUESTIONS questions are reported but never judged.

Langfuse Cloud closed GET /api/public/traces for new organizations (410), so this reads
GET /api/public/v2/observations, page by page.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

# docs/slo.md. Latency in seconds (end to end, server side), rates as fractions, cost in USD.
SLO = {
    "error_rate": 0.02,
    "rag_p95_s": 25.0,
    "report_p95_s": 45.0,
    "rag_abstain_rate": 0.30,
    "cost_per_question_usd": 0.01,
}
MIN_QUESTIONS = 20
REPORT_ROUTES = {"analysis", "report"}


def observations(host: str, auth: str, since: dt.datetime, until: dt.datetime, **params) -> list[dict]:
    rows, cursor = [], None
    while True:
        query = {"fromStartTime": since.isoformat(), "toStartTime": until.isoformat(), "limit": 100, **params}
        if cursor:
            query["cursor"] = cursor
        request = urllib.request.Request(f"{host}/api/public/v2/observations?{urllib.parse.urlencode(query)}",
                                         headers={"Authorization": auth})
        for attempt in range(6):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    body = json.loads(response.read())
                break
            except urllib.error.HTTPError as error:  # Langfuse Cloud limits the requests per minute
                if error.code != 429 or attempt == 5:
                    raise
                time.sleep(float(error.headers.get("Retry-After") or 10 * (attempt + 1)))
        time.sleep(1)
        rows += body["data"]
        cursor = (body.get("meta") or {}).get("cursor")
        if not cursor or not body["data"]:
            return rows


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def summarize(chats: list[dict], generations: list[dict]) -> dict:
    """chats: chat spans (output = run record); generations: model calls with totalCost."""
    cost = defaultdict(float)
    for generation in generations:
        cost[generation.get("traceId")] += generation.get("totalCost") or 0.0
    records = []
    for chat in chats:
        output = chat.get("output")
        record = json.loads(output) if isinstance(output, str) else (output or {})
        records.append({**record, "cost": cost.get(chat.get("traceId"), 0.0)})
    rag = [r for r in records if r.get("route") == "rag"]
    reports = [r for r in records if r.get("route") in REPORT_ROUTES]
    seconds = lambda rows: [r["latency_ms"] / 1000 for r in rows if isinstance(r.get("latency_ms"), (int, float))]
    by_route = defaultdict(int)
    for r in records:
        by_route[r.get("route") or "none"] += 1
    return {
        "questions": len(records),
        "by_route": dict(sorted(by_route.items(), key=lambda kv: -kv[1])),
        "error_rate": sum(bool(r.get("error")) for r in records) / len(records) if records else None,
        "p50_s": percentile(seconds(records), 0.5),
        "rag_p95_s": percentile(seconds(rag), 0.95),
        "report_p95_s": percentile(seconds(reports), 0.95),
        "rag_abstain_rate": sum(bool(r.get("abstained")) for r in rag) / len(rag) if rag else None,
        **guide_use(rag, seconds),
        "cost_per_question_usd": sum(r["cost"] for r in records) / len(records) if records else None,
        "cost_total_usd": sum(r["cost"] for r in records),
    }


def guide_use(rag: list[dict], seconds) -> dict:
    """How many answered health questions used a care guide (run record guide_count, 2026-10-19), and
    their cost and p50 against those without. Older records have no guide_count and are left out."""
    counted = [r for r in rag if "guide_count" in r and not r.get("abstained")]
    used = [r for r in counted if r["guide_count"]]
    unused = [r for r in counted if not r["guide_count"]]
    mean_cost = lambda rows: sum(r["cost"] for r in rows) / len(rows) if rows else None
    return {
        "rag_answered_with_guide_count": len(counted),
        "rag_guide_rate": len(used) / len(counted) if counted else None,
        "rag_cost_with_guide_usd": mean_cost(used),
        "rag_cost_without_guide_usd": mean_cost(unused),
        "rag_p50_with_guide_s": percentile(seconds(used), 0.5),
        "rag_p50_without_guide_s": percentile(seconds(unused), 0.5),
    }


def misses(summary: dict) -> list[str]:
    if summary["questions"] < MIN_QUESTIONS:
        return []
    return [f"{name} {summary[name]:.3g} > {limit}" for name, limit in SLO.items()
            if summary.get(name) is not None and summary[name] > limit]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--environment", default="cloudrun-api")
    parser.add_argument("--check", action="store_true", help="exit 1 when an objective is missed")
    parser.add_argument("--json", type=Path, help="also write the summary here")
    args = parser.parse_args(argv)
    from src import settings

    keys = [settings.get_setting(k) for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")]
    if not all(keys):
        raise SystemExit("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are needed")
    host = (settings.get_setting("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com").rstrip("/")
    auth = "Basic " + base64.b64encode(f"{keys[0]}:{keys[1]}".encode()).decode()
    until = dt.datetime.now(dt.UTC)
    since = until - dt.timedelta(days=args.days)
    scope = {"environment": args.environment}
    chats = [o for o in observations(host, auth, since, until, name="chat", fields="core,basic,io", **scope)
             if o.get("environment") == args.environment]
    traces = {c.get("traceId") for c in chats}
    generations = [o for o in observations(host, auth, since, until, type="GENERATION", fields="core,basic,usage", **scope)
                   if o.get("traceId") in traces]
    summary = {"environment": args.environment, "days": args.days, **summarize(chats, generations)}
    failed = misses(summary)
    summary["missed"] = failed
    if args.json:
        args.json.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    fmt = lambda v, d=1: "-" if v is None else f"{v:.{d}f}"
    print(f"{args.environment}, last {args.days} days: {summary['questions']} questions {summary['by_route']}")
    print(f"  errors {fmt(summary['error_rate'] and summary['error_rate'] * 100)}%  "
          f"p50 {fmt(summary['p50_s'])} s  rag p95 {fmt(summary['rag_p95_s'])} s  report p95 {fmt(summary['report_p95_s'])} s")
    print(f"  rag abstained {fmt(summary['rag_abstain_rate'] and summary['rag_abstain_rate'] * 100)}%  "
          f"cost/question ${fmt(summary['cost_per_question_usd'], 4)}  total ${fmt(summary['cost_total_usd'], 3)}")
    if summary["rag_guide_rate"] is not None:
        print(f"  care guides in {fmt(summary['rag_guide_rate'] * 100)}% of {summary['rag_answered_with_guide_count']} answered "
              f"health questions; cost ${fmt(summary['rag_cost_with_guide_usd'], 4)} with, "
              f"${fmt(summary['rag_cost_without_guide_usd'], 4)} without; "
              f"p50 {fmt(summary['rag_p50_with_guide_s'])} s with, {fmt(summary['rag_p50_without_guide_s'])} s without")
    if summary["questions"] < MIN_QUESTIONS:
        print(f"  fewer than {MIN_QUESTIONS} questions: not judged")
    for line in failed:
        print(f"  MISSED {line}")
    return 1 if args.check and failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
