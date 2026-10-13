"""What happens to search when Supabase fails (SEARCH_BACKEND=supabase, docs/adr/0007)?

    uv run --group tools --with psutil --with "psycopg[binary]" python scripts/evaluate_search_fallback.py

Each scenario runs in a fresh process, as the app would after a restart, and asks the same eight
questions (six health, two report) through the app's search functions (retrieve_health,
search_reports_hybrid):
- local:       SEARCH_BACKEND=local, today's app (Chroma + Kiwi BM25)
- supabase:    the Supabase tables, healthy
- unreachable: SUPABASE_DB_URL points at a host that never answers (connect timeout)
- refused:     the right host with a wrong password (the database answers with an error at once)
Per scenario: seconds for the first and later questions, peak memory (RSS), whether the local stores
were loaded, how many times the breaker tripped, and the share of top-3 documents equal to the
local run (the fallback should give exactly the local results). Results:
output/experiments/search_fallback.json.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

PROJECT_DIR = Path(__file__).resolve().parents[1]
OUT = PROJECT_DIR / "output" / "experiments" / "search_fallback.json"
HEALTH_QUESTIONS = ["강아지가 어제부터 노란 토를 해요", "산책 후에 다리를 절어요", "귀를 자꾸 긁고 냄새가 나요",
                    "노령견이 물을 너무 많이 마셔요", "설사에 피가 섞여 나와요", "예방접종 후에 얼굴이 부었어요"]
REPORT_QUESTIONS = ["반려동물 양육 가구 비율은 어떻게 변했나요?", "반려견 양육비는 한 달에 얼마나 드나요?"]


def child(scenario: str, chroma_copy: str) -> None:
    import psutil

    sys.path.insert(0, str(PROJECT_DIR))
    from src import resources
    from src.tools import health, report

    resources.CHROMA_DIR = Path(chroma_copy)
    process = psutil.Process()
    peak = process.memory_info().rss
    timings, tops = [], []
    for question in HEALTH_QUESTIONS + REPORT_QUESTIONS:
        started = time.perf_counter()
        if question in HEALTH_QUESTIONS:
            docs = health.retrieve_health(question, k=3)
        else:
            docs = report.search_reports_hybrid(question, k=3)
        timings.append(round(time.perf_counter() - started, 2))
        tops.append([d.id for d in docs])
        peak = max(peak, process.memory_info().rss)
    breaker = resources.load_search_breaker() if resources.search_backend() == "supabase" else None
    print(json.dumps({
        "backend": resources.search_backend(),
        "first_question_s": timings[0], "later_questions_s_max": max(timings[1:]), "seconds": timings,
        "peak_rss_mb": round(peak / 2**20),
        "local_stores_loaded": "chromadb" in sys.modules or "kiwipiepy" in sys.modules,
        "breaker_trips": breaker.failures if breaker else None,
        "tops": tops,
    }, ensure_ascii=False))


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child(sys.argv[2], sys.argv[3])
        return 0
    from dotenv import dotenv_values

    env_file = dotenv_values(PROJECT_DIR / ".env")
    url = env_file["SUPABASE_DB_URL"]
    parts = urlsplit(url)
    wrong_password = urlunsplit(parts._replace(netloc=f"{parts.username}:not-the-password@{parts.hostname}:{parts.port}"))
    unreachable = urlunsplit(parts._replace(netloc=f"{parts.username}:x@10.255.255.1:5432"))
    scenarios = {"local": {"SEARCH_BACKEND": "local"},
                 "supabase": {"SEARCH_BACKEND": "supabase", "SUPABASE_DB_URL": url},
                 "unreachable": {"SEARCH_BACKEND": "supabase", "SUPABASE_DB_URL": unreachable},
                 "refused": {"SEARCH_BACKEND": "supabase", "SUPABASE_DB_URL": wrong_password}}
    results = {}
    with tempfile.TemporaryDirectory(prefix="ragdog-fallback-", ignore_cleanup_errors=True) as directory:
        chroma_copy = Path(directory) / "chroma_db"
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", chroma_copy)
        for name, extra in scenarios.items():
            env = {**os.environ, **{k: v for k, v in env_file.items() if v is not None}, **extra, "PYTHONIOENCODING": "utf-8"}
            done = subprocess.run([sys.executable, __file__, "--child", name, str(chroma_copy)], env=env,
                                  capture_output=True, text=True, encoding="utf-8", timeout=900)
            line = [row for row in done.stdout.splitlines() if row.startswith("{")]
            if not line:
                print(name, "failed:", done.stderr[-2000:])
                return 1
            results[name] = json.loads(line[-1])
            print(name, {k: v for k, v in results[name].items() if k not in ("tops", "seconds")}, flush=True)
    local = results["local"]["tops"]
    for name, result in results.items():
        pairs = [(a, b) for a, b in zip(local, result.pop("tops"))]
        result["top3_same_as_local"] = round(sum(len(set(a) & set(b)) for a, b in pairs) / sum(len(a) for a, _ in pairs), 3)
    print(json.dumps(results, ensure_ascii=False, indent=1))
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
