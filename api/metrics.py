"""Prometheus metrics for the API, only when RAGDOG_METRICS=1 (the kind cluster, deploy/k8s/).

Cloud Run does not turn this on. Its instances scale to zero and run side by side, so counters kept
in a process restart at 0 and split across instances, and there is no Prometheus server to scrape
them; Cloud Run already records requests, latency and response codes in Cloud Monitoring, which
the weekly SLO report reads (scripts/slo_report.py --cloud-run). In a cluster the pods stay up and
Prometheus scrapes each one, so the same counters mean something there (Day 79).

Labels use the route template (/places/{kind}), not the raw path, so a scanner's random paths
cannot grow the series without bound; requests that match no route share one label.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

# Seconds. Most routes answer within 0.5 s; a health answer takes 5 to 20 s (docs/slo.md).
BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 25, 45, 90)


def install(app: FastAPI, registry: CollectorRegistry | None = None) -> CollectorRegistry:
    registry = registry or CollectorRegistry()
    requests = Counter("ragdog_requests_total", "Requests by route, method and status.",
                       ["route", "method", "status"], registry=registry)
    latency = Histogram("ragdog_request_seconds", "Time to the response's first byte, by route.",
                        ["route"], buckets=BUCKETS, registry=registry)

    @app.middleware("http")
    async def record(request: Request, call_next):
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            label = getattr(route, "path", None) or "unmatched"
            if label != "/metrics":
                requests.labels(label, request.method, str(status)).inc()
                latency.labels(label).observe(time.perf_counter() - started)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    return registry
