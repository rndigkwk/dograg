"""Router speed and accuracy: our rules + LLM fallback at three reasoning efforts, Jev, OpenAI Decisions.

    uv run python scripts/evaluate_router_speed.py llm                                    # rules + LLM (default/low/none)
    uv run --with typesafe-sdk==0.7.1 python scripts/evaluate_router_speed.py jev       # Jev on every question
    uv run --project ../openai-decisions-examples-main python scripts/evaluate_router_speed.py decisions
    uv run python scripts/evaluate_router_speed.py app        # the app's router as it is (rules + Decisions over HTTP)
    uv run python scripts/evaluate_router_speed.py summary

Questions: every routed evaluation question we have (136): the Jev shadow set (40), the place
routing set (36) and the CRAG set (60; health groups -> rag, report groups -> analysis).
"Rules" questions are the ones the keyword rules decide without a model; the rest reach the
LLM fallback. Jev and Decisions are run on every question, so "rules + Jev" and "rules +
Decisions" (the external model only as the fallback) are computed from the same records.
The Decisions command needs openai>=3.26 (the course example project has it); it imports
nothing from the app. Results: output/experiments/router_<command>.json.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_DIR / "output" / "experiments"
DATA = PROJECT_DIR / "tests" / "data"
ROUTES = ("rag", "sql", "analysis", "none")
EFFORTS = ("default", "low", "none")
# The same four routes the app's ROUTER_PROMPT describes (src/tools/router.py).
ROUTE_INSTRUCTIONS = (
    "반려견 서비스 챗봇에 들어온 질문을 처리할 도구 하나로 분류하세요. "
    "rag: 반려견 증상, 질병, 치료, 건강 정보(몸 상태를 설명하면 병원 언급이 있어도 rag). "
    "sql: 동물병원·동물약국·반려동물 동반 시설·애견미용·위탁·장묘업체를 찾거나 그 목록·주소·위치·개수·이용 조건을 묻는 질문. "
    "analysis: 반려동물 보고서(현황, 복지, 산업, 의료보험, 장묘)의 통계, 추이, 비교, 비중, 분포 (동물병원이 언급돼도 통계면 analysis). "
    "none: 인사, 감사, 기능 문의, 서비스 범위 밖 대화."
)


def questions() -> list[dict]:
    rows = []
    for item in json.loads((DATA / "jev_router_questions.json").read_text(encoding="utf-8")):
        rows.append({"id": f"jev-{item['id']}", "question": item["question"], "expected": item["expected"]})
    places = json.loads((DATA / "place_routing_questions.json").read_text(encoding="utf-8"))
    for item in places if isinstance(places, list) else places["items"]:
        rows.append({"id": f"place-{item['id']}", "question": item["question"], "expected": item["route"]})
    for item in json.loads((DATA / "crag_eval_questions.json").read_text(encoding="utf-8"))["items"]:
        expected = "rag" if item["group"].startswith("health") else "analysis"
        rows.append({"id": f"crag-{item['id']}", "question": item["question"], "expected": expected})
    return rows


def save(name: str, data) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"router_{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# --- our router -----------------------------------------------------------------------
class _NeedsModel(Exception):
    pass


def run_llm(repeats: int) -> None:
    sys.path.insert(0, str(PROJECT_DIR))
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ["ROUTER_FALLBACK"] = "llm"  # the chat-model router alone, without the Decisions call before it
    from langchain_openai import ChatOpenAI

    from src import resources, settings
    from src.tools import router

    class NoModel:
        def with_structured_output(self, *args, **kwargs):
            raise _NeedsModel

    def make(effort):
        kwargs = {} if effort == "default" else {"reasoning_effort": effort}
        return ChatOpenAI(model=resources.CHAT_MODEL_NAME, api_key=settings.get_openai_api_key(), **kwargs)

    original = resources.load_chat_model
    rows = []
    try:
        for item in questions():
            row = dict(item)
            resources.load_chat_model = NoModel
            started = time.perf_counter()
            try:
                row["rules_route"] = router.classify_question(item["question"])
                row["rules_seconds"] = time.perf_counter() - started
            except _NeedsModel:
                row["rules_route"] = None  # the rules could not decide: the LLM fallback runs
            rows.append(row)
        fallback = [row for row in rows if row["rules_route"] is None]
        print(f"rules decide {len(rows) - len(fallback)}/{len(rows)}; LLM fallback for {len(fallback)}", flush=True)
        for effort in EFFORTS:
            model = make(effort)
            resources.load_chat_model = lambda model=model: model
            router.classify_question("워밍업 질문입니다")  # connection setup is not part of a decision
            for repeat in range(repeats):
                for row in fallback:
                    started = time.perf_counter()
                    route = router.classify_question(row["question"])
                    row.setdefault(f"llm_{effort}", []).append(
                        {"route": route, "seconds": round(time.perf_counter() - started, 3)})
                print(effort, "repeat", repeat + 1, "done", flush=True)
    finally:
        resources.load_chat_model = original
    save("llm", rows)


def run_app(repeats: int) -> None:
    """The app's classify_question as configured (ROUTER_FALLBACK), with each fallback's source."""
    sys.path.insert(0, str(PROJECT_DIR))
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from src.tools import router

    sources = []
    original = router.decide_route

    def traced(question, chat_history=None):
        route = original(question, chat_history)
        sources.append("decisions" if route else "llm")
        return route

    router.decide_route = traced
    router.classify_question("워밍업 질문입니다")
    rows = []
    try:
        for item in questions():
            row = {**item, "calls": []}
            for _ in range(repeats):
                sources.clear()
                started = time.perf_counter()
                route = router.classify_question(item["question"])
                row["calls"].append({"route": route, "seconds": round(time.perf_counter() - started, 3),
                                     "source": sources[0] if sources else "rules"})
            rows.append(row)
    finally:
        router.decide_route = original
    save("app", rows)
    print("fallback sources:", {s: sum(c["source"] == s for r in rows for c in r["calls"]) for s in ("rules", "decisions", "llm")})


# --- Jev ------------------------------------------------------------------------------
def run_jev() -> None:
    from dotenv import load_dotenv
    from typesafe_sdk import Choice, TypeSafeClient

    load_dotenv(PROJECT_DIR / ".env")
    client = TypeSafeClient(timeout=30.0)
    question = Choice(instructions=ROUTE_INSTRUCTIONS, criteria={
        "rag": "반려견의 증상, 질병, 치료, 건강 정보",
        "sql": "반려동물 시설(병원·약국·동반 시설·미용·위탁·장묘)을 찾거나 목록·주소·위치·개수·이용 조건을 묻는 요청",
        "analysis": "반려동물 보고서의 통계, 추이, 비교, 비중, 분포",
        "none": "인사·감사·기능 문의·범위 밖 대화",
    })
    model = os.getenv("TYPESAFE_MODEL") or "jev-1.13.0"
    client.system_one(model=model, state="워밍업", questions={"route": question})
    rows = []
    try:
        for item in questions():
            started = time.perf_counter()
            try:
                answer = client.system_one(model=model, state={"user_query": item["question"]},
                                           questions={"route": question}).answers["route"]
                route, error = str(answer.choice), None
            except Exception as exc:  # noqa: BLE001 - keep the timing of a failed call
                route, error = None, type(exc).__name__
            rows.append({**item, "route": route, "error": error, "seconds": round(time.perf_counter() - started, 3)})
    finally:
        client.close()
    save("jev", rows)


# --- OpenAI Decisions -------------------------------------------------------------------
def run_decisions() -> None:
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(PROJECT_DIR / ".env")
    client = OpenAI()
    question = {"type": "choice", "name": "route", "instructions": ROUTE_INSTRUCTIONS,
                "choices": [{"value": route} for route in ROUTES]}
    model = os.getenv("OPENAI_CHAT_MODEL") or "gpt-6-luna"

    def decide(text):
        result = client.decisions.create(
            model=model, input=[{"role": "user", "content": [{"type": "input_text", "text": text}]}],
            questions=[question])
        return result.answers[0].model_dump().get("choice")

    decide("워밍업")
    rows = []
    for item in questions():
        started = time.perf_counter()
        try:
            route, error = decide(item["question"]), None
        except Exception as exc:  # noqa: BLE001 - keep the timing of a failed call
            route, error = None, f"{type(exc).__name__}: {str(exc)[:200]}"
        rows.append({**item, "route": route, "error": error, "seconds": round(time.perf_counter() - started, 3)})
    save("decisions", rows)


# --- summary ----------------------------------------------------------------------------
def describe(routes: list[tuple[str | None, str]], seconds: list[float]) -> dict:
    values = sorted(seconds)
    return {
        "correct": sum(route == expected for route, expected in routes), "of": len(routes),
        "mean_ms": round(statistics.fmean(values) * 1000, 1),
        "p50_ms": round(statistics.median(values) * 1000, 1),
        "p95_ms": round(values[int(0.95 * (len(values) - 1))] * 1000, 1),
    }


def summary() -> None:
    llm = json.loads((OUT_DIR / "router_llm.json").read_text(encoding="utf-8"))
    external = {name: {row["id"]: row for row in json.loads(path.read_text(encoding="utf-8"))}
                for name in ("jev", "decisions") if (path := OUT_DIR / f"router_{name}.json").exists()}
    fallback = [row for row in llm if row["rules_route"] is None]
    table = {}
    for effort in EFFORTS:
        repeats = len(fallback[0][f"llm_{effort}"])
        for repeat in range(repeats):
            routes, seconds = [], []
            for row in llm:
                if row["rules_route"] is None:
                    call = row[f"llm_{effort}"][repeat]
                    routes.append((call["route"], row["expected"]))
                    seconds.append(call["seconds"])
                else:
                    routes.append((row["rules_route"], row["expected"]))
                    seconds.append(row["rules_seconds"])
            table.setdefault(f"rules + LLM ({effort})", []).append(describe(routes, seconds))
            sub = [row[f"llm_{effort}"][repeat] for row in fallback]
            table.setdefault(f"LLM fallback only ({effort})", []).append(
                describe([(call["route"], row["expected"]) for call, row in zip(sub, fallback)],
                         [call["seconds"] for call in sub]))
    for name, rows in external.items():
        table[f"{name} on every question"] = [describe([(rows[r["id"]]["route"], r["expected"]) for r in llm],
                                                       [rows[r["id"]]["seconds"] for r in llm])]
        mixed_routes, mixed_seconds = [], []
        for row in llm:
            if row["rules_route"] is None:
                mixed_routes.append((rows[row["id"]]["route"], row["expected"]))
                mixed_seconds.append(rows[row["id"]]["seconds"])
            else:
                mixed_routes.append((row["rules_route"], row["expected"]))
                mixed_seconds.append(row["rules_seconds"])
        table[f"rules + {name}"] = [describe(mixed_routes, mixed_seconds)]
        table[f"{name} fallback only"] = [describe([(rows[r["id"]]["route"], r["expected"]) for r in fallback],
                                                   [rows[r["id"]]["seconds"] for r in fallback])]
    if (path := OUT_DIR / "router_app.json").exists():
        app = json.loads(path.read_text(encoding="utf-8"))
        fallback_ids = {row["id"] for row in fallback}
        for repeat in range(len(app[0]["calls"])):
            calls = [(row["calls"][repeat], row["expected"], row["id"]) for row in app]
            table.setdefault("app router (rules + Decisions over HTTP)", []).append(
                describe([(c["route"], e) for c, e, _ in calls], [c["seconds"] for c, _, _ in calls]))
            table.setdefault("app router, fallback only", []).append(
                describe([(c["route"], e) for c, e, i in calls if i in fallback_ids],
                         [c["seconds"] for c, _, i in calls if i in fallback_ids]))
    result = {"questions": len(llm), "rules_decided": len(llm) - len(fallback),
              "rules_correct": sum(r["rules_route"] == r["expected"] for r in llm if r["rules_route"]),
              "table": table}
    save("summary", result)
    print(json.dumps(result, ensure_ascii=False, indent=1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("llm", "jev", "decisions", "app", "summary"))
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    {"llm": lambda: run_llm(args.repeats), "jev": run_jev, "decisions": run_decisions,
     "app": lambda: run_app(args.repeats), "summary": summary}[args.command]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
