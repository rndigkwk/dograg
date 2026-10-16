"""Check the Postgres visit-prep store (src/visit_prep_store.py) against Supabase, in a throwaway schema.

    uv run python scripts/check_visit_prep_store.py

Makes a schema visit_prep_check_<random> with scripts/setup_visit_prep_store.py, exercises every
store function there, and drops the schema at the end (also on failure): the real `visit_prep`
schema is not touched. Uses the admin SUPABASE_DB_URL from .env. No model calls: the graph that
pauses and resumes is a two-node LangGraph with an interrupt. Prints each check; exit 1 on failure.
"""

from __future__ import annotations

import secrets
import sys
import time
from pathlib import Path
from typing import TypedDict

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from setup_visit_prep_store import setup  # noqa: E402

from src import settings  # noqa: E402
from src.visit_prep_store import PAUSED_RUN_TTL_SECONDS, PostgresStore  # noqa: E402


class State(TypedDict):
    question: str
    answer: str


def graph(checkpointer):
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    def ask(state: State) -> dict:
        return {"answer": interrupt({"questions": [state["question"]]})}

    builder = StateGraph(State)
    builder.add_node("ask", ask)
    builder.add_edge(START, "ask")
    builder.add_edge("ask", END)
    return builder.compile(checkpointer=checkpointer)


def main() -> int:
    from langgraph.types import Command

    url = settings.get_setting("SUPABASE_DB_URL")
    schema = f"visit_prep_check_{secrets.token_hex(4)}"
    results: list[tuple[str, bool]] = []
    check = lambda name, ok: results.append((name, bool(ok)))  # noqa: E731
    try:
        setup(url, schema)
        store, now = PostgresStore(url, schema), time.time()

        check("first report of the day", store.take_report("browser-a", 2, now))
        check("second report", store.take_report("browser-a", 2, now))
        check("third refused", not store.take_report("browser-a", 2, now))
        store.refund_report("browser-a")
        check("a refund frees one", store.take_report("browser-a", 2, now))
        check("another person counts apart", store.take_report("browser-b", 2, now))

        thread = secrets.token_hex(16)
        pending = {"thread_id": thread, "consultation": "말티즈가 설사를 해요", "region": "", "profile": "", "steps": ["a"], "seconds": 3}
        store.save_paused(thread, "browser-a", pending, now)
        check("someone else cannot take it", store.take_paused(thread, "browser-b", now) is None)
        taken = store.take_paused(thread, "browser-a", now)
        check("the owner takes it", taken and taken["consultation"] == "말티즈가 설사를 해요")
        check("only once", store.take_paused(thread, "browser-a", now) is None)
        store.put_back(thread, "browser-a", taken, taken["paused_at"])
        check("put back after a busy refusal", store.take_paused(thread, "browser-a", now) is not None)

        old = secrets.token_hex(16)
        store.save_paused(old, "browser-a", {**pending, "thread_id": old}, now - PAUSED_RUN_TTL_SECONDS - 5)
        check("an expired pause cannot be taken", store.take_paused(old, "browser-a", now) is None)
        check("expire removes it", old in store.expire(now))

        # A run paused on one server resumes on another (two stores, two connection pools).
        run = secrets.token_hex(16)
        config = {"configurable": {"thread_id": run}}
        first = graph(store.checkpointer()).invoke({"question": "언제부터였나요?", "answer": ""}, config)
        check("the graph paused", "__interrupt__" in first)
        other = PostgresStore(url, schema)
        resumed = graph(other.checkpointer()).invoke(Command(resume="어제부터요"), config)
        check("another server resumes it", resumed["answer"] == "어제부터요")
        other.checkpointer().delete_thread(run)
        with psycopg.connect(url, autocommit=True) as conn:
            left = conn.execute(f"select count(*) from {schema}.checkpoints where thread_id = %s", [run]).fetchone()[0]
            check("finished run deleted", left == 0)
            row = conn.execute(f"select owner from {schema}.report_starts limit 1").fetchone()[0]
            check("people stored as hashes", row != "browser-a" and len(row) == 32)
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(f"drop schema if exists {schema} cascade")
    for name, ok in results:
        print(("ok  " if ok else "FAIL"), name)
    print(f"schema {schema} dropped; {sum(ok for _, ok in results)}/{len(results)} passed")
    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
