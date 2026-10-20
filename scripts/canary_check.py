"""Check a new API revision before it gets any traffic (deploy-cloud-run.yml, docs/wiki/cloud-run.md).

    python3 scripts/canary_check.py https://candidate---ragdog-api-....run.app --expect-commit <sha>

The deploy puts the new revision behind the tag URL with 0% traffic. This script asks it what a
guardian's first minute asks, and the deploy moves the traffic only when every check passes:

1. /health reports the commit being deployed (the right revision answers)
2. /places/kinds and /fees/items answer 200 (no model: the database and tables are there)
3. /chat with a date question, decided by rule (no model): the graph runs end to end (route "none")
4. /chat with a health question: the search, the grader and the answer model run (about 4 model calls)

A result that is the quota notice (src/model_outage.py, "degraded") counts as a failure: a revision
that cannot answer should not take the traffic. Each check prints as it passes; exit 1 on the first
failed one, with the reason. The requests carry the deployment check's user agent
(src/data_gaps.CHECK_AGENT), so their answers stay out of the data-gap table.

The questions count against the question limit (src/rate_limit.py) like a guardian's. Each run asks
as a new browser (a random id): with one fixed id, a few deploys within an hour reached the limit of
10 and the check would have failed on it (the canary drill, 2026-10-20).

--expect-search local: the Supabase outage drill (RAGDOG_FAULT=supabase). The health answer must come
from the local stores, its result carrying "search": "local" (api/chat.py).
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator

# Standard library only: the deploy job runs it with the runner's python3, without the project's
# environment. CHECK_AGENT is src/data_gaps.CHECK_AGENT (tests/test_canary_check.py keeps them equal).
CHECK_AGENT = "RagDogCheck"
CLIENT = secrets.token_hex(16)  # a new browser id (32 hex) for each run, see the docstring
DATE_QUESTION = "오늘 날짜 알려줘"
HEALTH_QUESTION = "강아지가 어제부터 설사를 해요"
HEALTH_ATTEMPTS, HEALTH_WAIT_S = 30, 5


class CheckFailed(Exception):
    pass


def _agent() -> str:
    return f"ragdog-canary {CHECK_AGENT}"


def get(url: str, timeout: float = 30) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": _agent()})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def chat_events(base: str, question: str, timeout: float = 180) -> list[tuple[str, dict]]:
    body = json.dumps({"question": question, "history": []}).encode("utf-8")
    request = urllib.request.Request(f"{base}/chat", data=body, headers={
        "Content-Type": "application/json", "X-RagDog-Client": CLIENT, "User-Agent": _agent()})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("utf-8")
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines.get("data", "{}"))))
    return events


def check_health(base: str, commit: str, sleep=time.sleep) -> str:
    last = ""
    for _ in range(HEALTH_ATTEMPTS):
        status, last = get(f"{base}/health")
        if status == 200 and json.loads(last).get("commit") == commit:
            return f"health: commit {commit[:7]}"
        sleep(HEALTH_WAIT_S)
    raise CheckFailed(f"/health did not report {commit[:7]} (last: {last[:200]})")


def check_tables(base: str) -> str:
    for path in ("/places/kinds", "/fees/items"):
        status, body = get(f"{base}{path}")
        if status != 200:
            raise CheckFailed(f"{path} answered {status}: {body[:200]}")
    return "places and fees: 200"


def check_answer(base: str, question: str, route: str, search: str | None = None) -> str:
    events = chat_events(base, question)
    results = [data for kind, data in events if kind == "result"]
    if not results:
        errors = [data.get("message") for kind, data in events if kind in ("error", "limited")]
        raise CheckFailed(f"no answer to {question!r}: {errors or [kind for kind, _ in events]}")
    result = results[-1]
    if result.get("degraded"):
        raise CheckFailed(f"{question!r} got the quota notice, not an answer")
    if result.get("route") != route:
        raise CheckFailed(f"{question!r} went to {result.get('route')}, not {route}")
    if search and result.get("search") != search:
        raise CheckFailed(f"{question!r} was answered from search {result.get('search', 'supabase')!r}, not {search!r}")
    where = f", search {search}" if search else ""
    return f"chat {route}: answered ({len(result.get('answer', ''))} chars{where})"


def run(base: str, commit: str, sleep=time.sleep, search: str | None = None) -> Iterator[str]:
    """The checks in order, each line as it passes (a failure raises CheckFailed)."""
    base = base.rstrip("/")
    yield check_health(base, commit, sleep)
    yield check_tables(base)
    yield check_answer(base, DATE_QUESTION, "none")
    yield check_answer(base, HEALTH_QUESTION, "rag", search)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="the candidate's tag URL")
    parser.add_argument("--expect-commit", required=True)
    parser.add_argument("--expect-search", choices=["local"], help="the outage drill: answers from the local stores")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # not a redirected stream (tests)
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        for line in run(args.url, args.expect_commit, search=args.expect_search):
            print(f"ok   {line}", flush=True)
    except (CheckFailed, OSError, ValueError) as error:
        print(f"FAIL {error}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
