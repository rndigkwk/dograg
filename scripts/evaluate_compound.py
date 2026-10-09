"""Facility questions that also describe a symptom (day54 Adaptive) and night-care follow-ups.

    uv run python scripts/evaluate_compound.py

Runs each question through the chatbot as deployed (CRAG on) twice: as before (facility search
only) and now (facility search + the health path). Records the route, the places found, whether
a health part was added and whether it abstained, and the time. Night-care questions check that
only hospitals whose name says 24시/응급/야간 are listed. Results: output/experiments/compound.json.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

COMPOUND = [
    "강아지가 토하는데 강남구 동물병원 알려줘",
    "설사가 이틀째인데 마포구 동물병원 어디 있어?",
    "다리를 절뚝거리는데 송파구 동물병원 추천해줘",
    "눈곱이 많이 끼는데 서초구 동물병원 찾아줘",
    "기침을 계속 하는데 수원 동물병원 목록 보여줘",
    "혈변을 봤어요 은평구 동물병원 주소 알려줘",
    "잇몸이 부었는데 노원구 동물병원 추천해줘",
    "고양이가 구토하는데 부산 동물병원 알려줘",
]
NIGHT = [
    ([], "강남구 24시 동물병원 알려줘"),
    ([], "밤에 진료하는 마포구 동물병원 있어?"),
    (["강남구 동물병원 알려줘"], "그중에 24시간 하는 곳도 있어?"),
    (["송파구 동물병원 찾아줘"], "야간에 여는 곳만 보여줘"),
]


def main() -> int:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from src.chatbot import chatbot
    from app_pages.rag import places_first
    from src.tools import places, router

    rows = []
    for question in COMPOUND:
        for variant in ("before", "now"):
            started = time.perf_counter()
            shown: dict[str, float] = {}

            def on_step(node, update, shown=shown, started=started):
                if "places" not in shown and places_first(node, update):
                    shown["places"] = round(time.perf_counter() - started, 2)

            def on_token(text, shown=shown, started=started):
                shown.setdefault("token", round(time.perf_counter() - started, 2))

            if variant == "before":
                with patch.object(router, "describes_symptom", return_value=False):
                    result = chatbot(question, crag=True)
            else:
                result = chatbot(question, crag=True, on_step=on_step, on_token=on_token)
            seconds = round(time.perf_counter() - started, 1)
            answer = result["answer"]
            rows.append({"question": question, "variant": variant, "route": result["route"],
                         "places": len(result.get("hospital_rows") or []), "health_part": "**증상에 대해**" in answer,
                         "health_abstained": result.get("abstained", False), "health_evidence": len(result.get("evidence_rows") or []),
                         "seconds": seconds, "answer": answer})
            if variant == "now":
                # When the app can put the place list on screen (app_pages/rag.py places_first);
                # before that change it appeared with the finished answer, at `seconds`.
                rows[-1]["places_shown_s"] = shown.get("places")
                rows[-1]["first_token_s"] = shown.get("token")
            print(variant, result["route"], rows[-1]["places"], rows[-1]["health_part"], rows[-1]["health_abstained"],
                  f"{seconds}s", question, flush=True)
    night_rows = []
    for earlier, question in NIGHT:
        history = [message for text in earlier
                   for message in ({"role": "user", "content": text}, {"role": "assistant", "content": "병원 목록"})]
        result = chatbot(question, chat_history=history, crag=True)
        found = result.get("hospital_rows") or []
        night_rows.append({"question": question, "earlier": earlier, "route": result["route"], "places": len(found),
                           "all_night_named": all(any(w in row["name"] for w in places.EMERGENCY_NAME_WORDS) for row in found),
                           "names": [row["name"] for row in found][:5], "answer": result["answer"][:300]})
        print("night", result["route"], len(found), night_rows[-1]["all_night_named"], night_rows[-1]["names"][:3], question, flush=True)
    summary = {}
    for variant in ("before", "now"):
        mine = [row for row in rows if row["variant"] == variant]
        summary[variant] = {"questions": len(mine), "sql_route": sum(r["route"] == "sql" for r in mine),
                            "with_places": sum(r["places"] > 0 for r in mine),
                            "with_health_part": sum(r["health_part"] for r in mine),
                            "health_abstained": sum(r["health_part"] and r["health_abstained"] for r in mine),
                            "seconds_p50": statistics.median(r["seconds"] for r in mine)}
    now = [row for row in rows if row["variant"] == "now" and row.get("places_shown_s") is not None]
    summary["now"]["places_shown_p50"] = statistics.median(r["places_shown_s"] for r in now) if now else None
    summary["now"]["places_shown_max"] = max((r["places_shown_s"] for r in now), default=None)
    summary["now"]["first_token_p50"] = statistics.median(r["first_token_s"] for r in now if r["first_token_s"]) if now else None
    summary["night"] = {"questions": len(night_rows), "with_places": sum(r["places"] > 0 for r in night_rows),
                        "only_night_named": sum(r["places"] > 0 and r["all_night_named"] for r in night_rows)}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    out = PROJECT_DIR / "output" / "experiments" / "compound.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows, "night": night_rows}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
