"""Compare DogRAG's existing router with Jev in non-invasive shadow mode.

Run with a Jev SDK available and API keys loaded from the project environment:
    uv run --with typesafe-sdk==0.7.1 python scripts/jev_router_shadow.py

Only synthetic evaluation questions are sent to external model APIs. The Jev
prediction is recorded for comparison and never controls the app's route.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.runnables import RunnableLambda

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

ROUTES = ("rag", "sql", "analysis", "none")
MODEL_NAME = os.getenv("TYPESAFE_MODEL", "jev-1.13.0")


def summarize_latencies(seconds: list[float]) -> dict[str, float | int | None]:
    """Summarize wall-clock durations in milliseconds."""
    if not seconds:
        return {"count": 0, "mean_ms": None, "median_ms": None, "p50_ms": None, "p95_ms": None}

    values = sorted(value * 1000 for value in seconds)

    def percentile(fraction: float) -> float:
        position = (len(values) - 1) * fraction
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return values[lower]
        return values[lower] + (values[upper] - values[lower]) * (position - lower)

    return {
        "count": len(values),
        "mean_ms": statistics.fmean(values),
        "median_ms": statistics.median(values),
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
    }


def extract_jev_route(response: Any) -> tuple[str, float | None]:
    answer = response.answers["route"]
    route = str(answer.choice)
    if route not in ROUTES:
        raise ValueError(f"Jev returned unsupported route: {route}")
    confidence = getattr(answer, "confidence", None)
    return route, float(confidence) if confidence is not None else None


def summarize_predictions(
    records: list[dict[str, Any]], prediction_key: str, error_key: str | None = None
) -> dict[str, Any]:
    total = len(records)
    correct = sum(record.get(prediction_key) == record["expected"] for record in records)
    wrong_routes = sum(
        record.get(prediction_key) is not None
        and record.get(prediction_key) != record["expected"]
        for record in records
    )
    unclassified = sum(record.get(prediction_key) is None for record in records)
    confusion = {expected: {predicted: 0 for predicted in (*ROUTES, "unclassified")} for expected in ROUTES}
    for record in records:
        predicted = record.get(prediction_key) or "unclassified"
        confusion[record["expected"]][predicted] += 1
    failures = (
        sum(record.get(error_key) is not None for record in records)
        if error_key
        else 0
    )
    return {
        "correct": correct,
        "total": total,
        "accuracy": correct / total if total else None,
        "wrong_route_count": wrong_routes,
        "wrong_route_rate": wrong_routes / total if total else None,
        "unclassified_count": unclassified,
        "api_or_runtime_failures": failures,
        "confusion_matrix": confusion,
    }


def build_route_question(Choice: Any) -> Any:
    return Choice(
        instructions=(
            "사용자의 현재 요청을 DogRAG가 처리할 도구 경로 하나로 분류하세요. "
            "건강 상담과 병원 검색이 함께 있으면 질문의 핵심 요청을 선택하고, "
            "단순 대화나 서비스 범위 밖 주제는 none으로 분류하세요."
        ),
        criteria={
            "rag": "반려견의 증상, 질병, 치료, 건강 정보, 건강 Q&A 근거를 묻는 요청",
            "sql": "동물병원의 목록, 병원명, 주소, 지역, 위치, 가까운 병원 검색 요청",
            "analysis": "2025 한국 반려동물 보고서의 통계, 현황, 추이, 비교, 비중, 분포 분석 요청",
            "none": "인사·감사·앱 사용 문의·일반 대화 또는 반려견 건강/병원/보고서 범위 밖 요청",
        },
    )


class _CountingChatModel:
    def __init__(self, model: Any, counter: dict[str, int]):
        self._model = model
        self._counter = counter

    def with_structured_output(self, *args: Any, **kwargs: Any) -> RunnableLambda:
        runnable = self._model.with_structured_output(*args, **kwargs)

        def count_and_invoke(value: Any) -> Any:
            self._counter["count"] += 1
            return runnable.invoke(value)

        return RunnableLambda(count_and_invoke)


def load_questions(path: Path) -> list[dict[str, str]]:
    questions = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(questions, list) or not 30 <= len(questions) <= 50:
        raise ValueError("Evaluation file must contain 30 to 50 labeled questions")
    for index, row in enumerate(questions):
        if row.get("expected") not in ROUTES or not row.get("question", "").strip():
            raise ValueError(f"Question row {index} has a missing question or invalid route")
    return questions


def run_evaluation(question_path: Path) -> dict[str, Any]:
    load_dotenv(PROJECT_DIR / ".env")
    if not os.getenv("TYPESAFE_API_KEY"):
        raise RuntimeError("TYPESAFE_API_KEY is not configured")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not configured for existing-router fallbacks")

    try:
        from typesafe_sdk import Choice, TypeSafeClient
    except ImportError as exc:
        raise RuntimeError(
            "typesafe-sdk is required; run with --with typesafe-sdk==0.7.1"
        ) from exc

    from pages import rag

    questions = load_questions(question_path)
    jev_client = TypeSafeClient(timeout=30.0)
    route_question = build_route_question(Choice)
    model_counter = {"count": 0}
    original_load_chat_model = rag.load_chat_model

    def counted_load_chat_model() -> Any:
        model = original_load_chat_model()
        if model is None:
            return None
        return _CountingChatModel(model, model_counter)

    rag.load_chat_model = counted_load_chat_model
    records: list[dict[str, Any]] = []
    old_total = 0.0
    jev_total = 0.0
    old_calls_before = model_counter["count"]
    jev_calls = 0
    try:
        for index, sample in enumerate(questions, start=1):
            question = sample["question"]
            record: dict[str, Any] = {
                "id": sample.get("id", str(index)),
                "expected": sample["expected"],
            }

            started = time.perf_counter()
            try:
                record["existing_route"] = rag.classify_question(question)
                record["existing_error"] = None
            except Exception as exc:  # preserve timing and keep the evaluation moving
                record["existing_route"] = None
                record["existing_error"] = type(exc).__name__
            record["existing_latency_ms"] = (time.perf_counter() - started) * 1000
            old_total += record["existing_latency_ms"] / 1000
            record["existing_model_calls_total"] = model_counter["count"]

            started = time.perf_counter()
            try:
                response = jev_client.system_one(
                    model=MODEL_NAME,
                    state={
                        "user_query": question,
                        "service_scope": (
                            "DogRAG 반려견 건강 Q&A, 동물병원 검색, "
                            "2025 반려동물 보고서 분석 Streamlit 서비스의 질문 라우팅"
                        ),
                    },
                    questions={"route": route_question},
                )
                record["jev_route"], record["jev_confidence"] = extract_jev_route(response)
                record["jev_error"] = None
                record["jev_model"] = getattr(response, "model", MODEL_NAME)
                jev_calls += 1
            except Exception as exc:  # keep per-question failure and elapsed time
                record["jev_route"] = None
                record["jev_confidence"] = None
                record["jev_error"] = type(exc).__name__
            record["jev_latency_ms"] = (time.perf_counter() - started) * 1000
            jev_total += record["jev_latency_ms"] / 1000
            records.append(record)
            print(
                f"[{index:02d}/{len(questions)}] {record['id']} "
                f"existing={record['existing_route']} ({record['existing_latency_ms']:.0f} ms) "
                f"Jev={record['jev_route']} ({record['jev_latency_ms']:.0f} ms)"
            )
    finally:
        rag.load_chat_model = original_load_chat_model
        jev_client.close()

    existing_latencies = [record["existing_latency_ms"] / 1000 for record in records]
    existing_classified_latencies = [
        record["existing_latency_ms"] / 1000
        for record in records
        if record["existing_route"] is not None and record["existing_error"] is None
    ]
    jev_latencies = [record["jev_latency_ms"] / 1000 for record in records]

    result = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "shadow; Jev result never changes application behavior",
        "jev_model": MODEL_NAME,
        "question_count": len(records),
        "routing_accuracy": {
            "existing": summarize_predictions(records, "existing_route", "existing_error"),
            "jev": summarize_predictions(records, "jev_route", "jev_error"),
        },
        "latency": {
            "existing_router_all_attempts": summarize_latencies(existing_latencies),
            "existing_router_successful_predictions": summarize_latencies(
                existing_classified_latencies
            ),
            "jev_router": summarize_latencies(jev_latencies),
        },
        "model_calls": {
            "existing_router_structured_llm_calls": model_counter["count"] - old_calls_before,
            "jev_system_one_calls": jev_calls,
        },
        "records": records,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--questions",
        type=Path,
        default=PROJECT_DIR / "tests" / "data" / "jev_router_questions.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_DIR / "output" / "jev_router_shadow_results.json",
    )
    args = parser.parse_args()
    result = run_evaluation(args.questions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nAccuracy:", json.dumps(result["routing_accuracy"], ensure_ascii=False))
    print("Latency:", json.dumps(result["latency"], ensure_ascii=False))
    print("Model calls:", json.dumps(result["model_calls"], ensure_ascii=False))
    print("Results saved to:", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
