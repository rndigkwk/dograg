"""Small-talk replies (route none): do they present this service, and only this service? (real model calls)

    uv run python scripts/evaluate_general_replies.py

tests/data/general_questions.json (written before the change). Each question goes through the app's
chatbot. A reply is right when:
- it claims no other ability (CLAIMS: coding, translation, writing, summaries, "ChatGPT") and
  does no out-of-scope task (no code block, no numbered recommendations for scope questions);
- greeting, capability and scope replies point to what the service does (SERVICE_WORDS);
- thanks replies are short (at most 120 characters).
Also records the route (the reply only comes from the small-talk node when the route is none)
and the seconds per question. Results: output/experiments/general_replies.json.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

QUESTIONS = PROJECT_DIR / "tests" / "data" / "general_questions.json"
from src.tools.general import SERVICE_GUIDE  # noqa: E402
CLAIMS = ("코딩", "번역", "글쓰기", "요약", "ChatGPT", "chatgpt", "GPT")
SERVICE_WORDS = ("반려", "강아지", "동물병원")
DID_TASK = re.compile(r"```|sorted\(|\.sort\(|x\s*=\s*2|^\s*(?:\d+\.|-)\s", re.MULTILINE)


def right(kind: str, reply: str) -> tuple[bool, str]:
    if any(claim in reply for claim in CLAIMS):
        return False, "claims another ability"
    # The service guide's own bullet list is not a task done (src/tools/general.py SERVICE_GUIDE).
    if kind == "scope" and DID_TASK.search(reply.replace(SERVICE_GUIDE, "")):
        return False, "did the task"
    if kind == "thanks":
        return (len(reply) <= 120, "too long" if len(reply) > 120 else "")
    if not any(word in reply for word in SERVICE_WORDS):
        return False, "does not say what the service does"
    return True, ""


def main() -> int:
    os.environ["HF_HUB_OFFLINE"] = "1"
    from src import chatbot as app

    rows = []
    for item in json.loads(QUESTIONS.read_text(encoding="utf-8"))["items"]:
        started = time.perf_counter()
        result = app.chatbot(item["question"], crag=True)
        reply = result.get("answer", "")
        ok, why = right(item["kind"], reply)
        rows.append({"id": item["id"], "split": item["split"], "kind": item["kind"], "route": result.get("route"),
                     "ok": ok, "why": why, "seconds": round(time.perf_counter() - started, 1),
                     "reply": reply[:300]})
        print(item["id"], result.get("route"), "ok" if ok else f"WRONG {why}", "|", reply[:80].replace("\n", " "), flush=True)
    summary = defaultdict(dict)
    for kind in ("greeting", "thanks", "capability", "scope"):
        for split in ("dev", "holdout"):
            group = [r for r in rows if r["kind"] == kind and r["split"] == split]
            summary[kind][split] = f"{sum(r['ok'] for r in group)}/{len(group)}"
    none_rows = [r for r in rows if r["route"] == "none"]
    summary["route_none"] = f"{len(none_rows)}/{len(rows)}"
    summary["seconds_median_none"] = sorted(r["seconds"] for r in none_rows)[len(none_rows) // 2] if none_rows else None
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    output = PROJECT_DIR / "output" / "experiments" / "general_replies.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
