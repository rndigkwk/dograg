"""Service levels of the deployed app over the last days, from its Langfuse traces. Read-only, no
model calls.

    uv run python scripts/slo_report.py                 # API (cloudrun-api), last 7 days
    uv run python scripts/slo_report.py --days 28 --environment cloudrun
    uv run python scripts/slo_report.py --check         # exit 1 when an objective is missed
    uv run python scripts/slo_report.py --cloud-run     # also Cloud Run's requests by response code

Each answered question is one `chat` span (src/tracing.py) whose output is the masked run record:
latency_ms, error, route, abstained. Its model calls are GENERATION observations with Langfuse's cost.
Objectives are in docs/slo.md (SLO below); with --check a miss exits 1, which the weekly workflow
turns into a GitHub issue. Fewer than MIN_QUESTIONS questions are reported but never judged.

Also shown, never judged (Day 79, 2026-11-11): the error budget of each objective that counts bad
answers (errors, answers slower than the p95 target) with its burn rate, and the same numbers per
deployed release (the commit in each span's resource attributes), so a slowdown after a deploy points
to its commit.

Langfuse Cloud closed GET /api/public/traces for new organizations (410), so this reads
GET /api/public/v2/observations, page by page.

--cloud-run adds availability from Cloud Monitoring: the share of all requests to the service (chat,
places, fees, health) that did not end in 5xx. It counts what the run records miss, requests that
failed before a trace was written (503, out-of-memory restarts, timeouts). Watched, not judged. The
token is `gcloud auth print-access-token` (the weekly workflow logs in with Workload Identity and
needs roles/monitoring.viewer).
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import math
import subprocess
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
# Error budgets: the share of bad answers each objective allows. A p95 target lets 5% be slower.
BUDGET_SHARE = {"errors": SLO["error_rate"], "rag_latency": 0.05, "report_latency": 0.05}
RELEASE_KEY = "resourceAttributes.langfuse.release"  # set from LANGFUSE_RELEASE (src/tracing.py)


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


def cloud_run_requests(project: str, service: str, since: dt.datetime, until: dt.datetime) -> dict:
    """Request counts by response code class (2xx, 4xx, 5xx) from Cloud Monitoring, one-day deltas."""
    token = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True,
                           check=True, shell=sys.platform == "win32").stdout.strip()
    query = {
        "filter": f'metric.type="run.googleapis.com/request_count" AND resource.labels.service_name="{service}"',
        "interval.startTime": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "interval.endTime": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "aggregation.alignmentPeriod": "86400s",
        "aggregation.perSeriesAligner": "ALIGN_DELTA",
        "aggregation.crossSeriesReducer": "REDUCE_SUM",
        "aggregation.groupByFields": "metric.labels.response_code_class",
    }
    request = urllib.request.Request(
        f"https://monitoring.googleapis.com/v3/projects/{project}/timeSeries?{urllib.parse.urlencode(query)}",
        headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.loads(response.read())
    return availability({
        series["metric"]["labels"].get("response_code_class", "unknown"):
            sum(int(point["value"].get("int64Value", 0)) for point in series.get("points", []))
        for series in body.get("timeSeries", [])
    })


def availability(counts: dict) -> dict:
    total = sum(counts.values())
    return {"requests": total, "by_class": dict(sorted(counts.items())),
            "availability": 1 - counts.get("5xx", 0) / total if total else None}


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
        release = str((chat.get("metadata") or {}).get(RELEASE_KEY) or "unknown")[:7]
        records.append({**record, "cost": cost.get(chat.get("traceId"), 0.0), "release": release,
                        "start": chat.get("startTime") or ""})
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
        "rag_within_target_rate": within(seconds(rag), SLO["rag_p95_s"]),
        "report_within_target_rate": within(seconds(reports), SLO["report_p95_s"]),
        **guide_use(rag, seconds),
        "cost_per_question_usd": sum(r["cost"] for r in records) / len(records) if records else None,
        "cost_total_usd": sum(r["cost"] for r in records),
        "budgets": budgets(records, rag, reports, seconds),
        "by_release": by_release(records),
    }


def budget(bad: int, total: int, share: float) -> dict | None:
    """Day 79's error budget over the window: `share` of the answers may be bad. burn_rate = bad share /
    allowed share: 1 uses the budget up exactly, 2 twice as fast. For errors, burn_rate > 1 is the same
    as missing the error rate objective, so this is watched, not judged."""
    if not total:
        return None
    allowed = share * total
    return {"bad": bad, "total": total, "allowed": round(allowed, 2), "left": round(allowed - bad, 2),
            "burn_rate": bad / total / share}


def budgets(records: list[dict], rag: list[dict], reports: list[dict], seconds) -> dict:
    return {
        "errors": budget(sum(bool(r.get("error")) for r in records), len(records), BUDGET_SHARE["errors"]),
        "rag_latency": budget(sum(v > SLO["rag_p95_s"] for v in seconds(rag)), len(seconds(rag)),
                              BUDGET_SHARE["rag_latency"]),
        "report_latency": budget(sum(v > SLO["report_p95_s"] for v in seconds(reports)), len(seconds(reports)),
                                 BUDGET_SHARE["report_latency"]),
    }


def by_release(records: list[dict]) -> list[dict]:
    """Questions, errors, health p95 and abstain rate per deployed commit, oldest deploy first (Day 79:
    compare traces by version to find the deploy that changed them)."""
    groups = defaultdict(list)
    for r in records:
        groups[r["release"]].append(r)
    rows = []
    for release, rows_of in groups.items():
        rag = [r for r in rows_of if r.get("route") == "rag"]
        latency = [r["latency_ms"] / 1000 for r in rag if isinstance(r.get("latency_ms"), (int, float))]
        reports = [r["latency_ms"] / 1000 for r in rows_of
                   if r.get("route") in REPORT_ROUTES and isinstance(r.get("latency_ms"), (int, float))]
        rows.append({
            "release": release,
            "first": min(r["start"] for r in rows_of)[:10],
            "questions": len(rows_of),
            "errors": sum(bool(r.get("error")) for r in rows_of),
            "slow": sum(v > SLO["rag_p95_s"] for v in latency) + sum(v > SLO["report_p95_s"] for v in reports),
            "rag": len(rag),
            "rag_p95_s": percentile(latency, 0.95),
            "rag_abstain_rate": sum(bool(r.get("abstained")) for r in rag) / len(rag) if rag else None,
        })
    return sorted(rows, key=lambda row: row["first"])


def within(values: list[float], limit: float) -> float | None:
    """The share of answers that finished within the latency target (Day 76's attainment: goodput over
    throughput). Watched, not judged: with one target, a share of 0.95 or more says what p95 <= target
    says, but this shows how many guardians waited longer, which p95 hides (2026-11-06)."""
    return sum(v <= limit for v in values) / len(values) if values else None


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
    parser.add_argument("--cloud-run", action="store_true", help="also read Cloud Run's requests by response code")
    parser.add_argument("--gcp-project", default="ragdog-511311")
    parser.add_argument("--service", default="ragdog-api")
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
    chats = [o for o in observations(host, auth, since, until, name="chat", fields="core,basic,io,metadata", **scope)
             if o.get("environment") == args.environment]
    traces = {c.get("traceId") for c in chats}
    generations = [o for o in observations(host, auth, since, until, type="GENERATION", fields="core,basic,usage", **scope)
                   if o.get("traceId") in traces]
    summary = {"environment": args.environment, "days": args.days, **summarize(chats, generations)}
    if args.cloud_run:
        try:
            summary["cloud_run"] = cloud_run_requests(args.gcp_project, args.service, since, until)
        except (OSError, subprocess.CalledProcessError, urllib.error.URLError) as error:
            summary["cloud_run"] = {"error": str(error)[:200]}  # watched, so a failed read is not a miss
    failed = misses(summary)
    summary["missed"] = failed
    if args.json:
        args.json.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    fmt = lambda v, d=1: "-" if v is None else f"{v:.{d}f}"
    print(f"{args.environment}, last {args.days} days: {summary['questions']} questions {summary['by_route']}")
    print(f"  errors {fmt(summary['error_rate'] and summary['error_rate'] * 100)}%  "
          f"p50 {fmt(summary['p50_s'])} s  rag p95 {fmt(summary['rag_p95_s'])} s  report p95 {fmt(summary['report_p95_s'])} s")
    print(f"  within target: rag {fmt(summary['rag_within_target_rate'] and summary['rag_within_target_rate'] * 100)}% "
          f"(<= {SLO['rag_p95_s']:g} s)  report {fmt(summary['report_within_target_rate'] and summary['report_within_target_rate'] * 100)}% "
          f"(<= {SLO['report_p95_s']:g} s)")
    print(f"  rag abstained {fmt(summary['rag_abstain_rate'] and summary['rag_abstain_rate'] * 100)}%  "
          f"cost/question ${fmt(summary['cost_per_question_usd'], 4)}  total ${fmt(summary['cost_total_usd'], 3)}")
    if summary["rag_guide_rate"] is not None:
        print(f"  care guides in {fmt(summary['rag_guide_rate'] * 100)}% of {summary['rag_answered_with_guide_count']} answered "
              f"health questions; cost ${fmt(summary['rag_cost_with_guide_usd'], 4)} with, "
              f"${fmt(summary['rag_cost_without_guide_usd'], 4)} without; "
              f"p50 {fmt(summary['rag_p50_with_guide_s'])} s with, {fmt(summary['rag_p50_without_guide_s'])} s without")
    for name, b in summary["budgets"].items():
        if b:
            print(f"  budget {name}: {b['bad']} bad of {b['total']}, {b['allowed']:g} allowed, "
                  f"{b['left']:g} left, burn rate {b['burn_rate']:.2f}")
    if "cloud_run" in summary:
        run = summary["cloud_run"]
        if "error" in run:
            print(f"  cloud run requests: not read ({run['error']})")
        else:
            print(f"  cloud run requests {run['requests']} {run['by_class']}: "
                  f"availability {fmt(run['availability'] and run['availability'] * 100, 2)}% (not 5xx)")
    releases = summary["by_release"]
    # Every merge deploys, so a week has many releases: show those with a bad answer and the last three
    # (all of them are in --json).
    shown = [row for i, row in enumerate(releases) if row["errors"] or row["slow"] or i >= len(releases) - 3]
    if shown:
        print(f"  {len(releases)} releases; with errors or slow answers, and the last 3:")
        print("  release  first       questions errors slow  rag  rag p95  abstained")
        for row in shown:
            abstained = "-" if row["rag_abstain_rate"] is None else f"{row['rag_abstain_rate'] * 100:.0f}%"
            print(f"  {row['release']:<8} {row['first']:<11} {row['questions']:>9} {row['errors']:>6} {row['slow']:>4} "
                  f"{row['rag']:>4} {fmt(row['rag_p95_s']):>8} {abstained:>10}")
    if summary["questions"] < MIN_QUESTIONS:
        print(f"  fewer than {MIN_QUESTIONS} questions: not judged")
    for line in failed:
        print(f"  MISSED {line}")
    return 1 if args.check and failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
