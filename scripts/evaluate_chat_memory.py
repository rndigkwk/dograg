"""Long-conversation summary (day52) and the abstention notice (day53), with real model calls.

    uv run python scripts/evaluate_chat_memory.py memory    # 6 long conversations, window vs summary
    uv run python scripts/evaluate_chat_memory.py abstain   # the 22 questions the chatbot should not answer

memory: each conversation in tests/data/long_conversations.json states a fact in its first turn,
then 9 unrelated turns, then a question that depends on the fact. The chatbot answers it twice:
with the last 6 turns only (the app before) and with the summary of older turns + recent turns
(the app now). A grader checks whether each answer takes the fact into account.

abstain: runs the CRAG questions marked "abstain" and checks that each abstention says what was
searched and what the evidence did not cover.

Results go to output/experiments/chat_memory_<command>.json.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

from pydantic import BaseModel, Field

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
OUT_DIR = PROJECT_DIR / "output" / "experiments"


class UsesFact(BaseModel):
    uses_fact: bool = Field(description="답변이 그 사실을 알고 그에 맞춰 답했는가")
    specific: bool = Field(description="그 상태에 맞춘 구체적 안내(주의할 음식·운동·관리·시기 등)가 있는가. "
                                       "'자료에 없다'와 수의사 확인 권고뿐이면 false")
    reason: str


JUDGE_PROMPT = ("반려견 보호자가 앞서 말한 사실이 있습니다. 챗봇 답변이 그 사실을 알고 그에 맞춰 답했는지 판정하세요. "
                "사실을 언급하거나 그 사실에 맞춘 주의를 주면 true, 사실과 무관한 일반 답변이면 false.")


def grader():
    from langchain_openai import ChatOpenAI

    from src import resources, settings

    return ChatOpenAI(model=resources.CHAT_MODEL_NAME, api_key=settings.get_openai_api_key(),
                      reasoning_effort="low").with_structured_output(UsesFact)


def conversation(data: dict, item: dict) -> list[dict]:
    turns = [item["first"], *data["filler"]]
    return [message for user, assistant in turns
            for message in ({"role": "user", "content": user}, {"role": "assistant", "content": assistant})]


def memory() -> dict:
    from unittest.mock import patch

    from src.chatbot import chatbot
    from src.tools import history
    from src.tools.history import (
        format_chat_history,
        get_recent_chat_history,
        history_with_summary,
    )

    data = json.loads((PROJECT_DIR / "tests" / "data" / "long_conversations.json").read_text(encoding="utf-8"))
    judge = grader()
    rows = []
    for item in data["items"]:
        messages = conversation(data, item)
        started = time.perf_counter()
        summarized = history_with_summary(messages, {})
        summary_seconds = time.perf_counter() - started
        variants = (("window", get_recent_chat_history(messages), False), ("summary", summarized, False),
                    ("summary_query", summarized, True))
        for variant, chat_history, rewrite in variants:
            started = time.perf_counter()
            # crag=True as on the deployed app (ENABLE_CRAG): the query rewrite feeds that path
            if rewrite:  # the app now: the summary also shapes the health search query
                result = chatbot(item["question"], chat_history=chat_history, crag=True)
            else:  # before: the search query is the plain one
                with patch.object(history, "memory_search_query", history.build_rag_search_query):
                    result = chatbot(item["question"], chat_history=chat_history, crag=True)
            seconds = time.perf_counter() - started
            # Health evidence rows carry the case's answer text (qa.output), not the question
            evidence = " ".join(str(row.get("qa.output", "")) for row in result.get("evidence_rows", []))
            verdict = judge.invoke([
                ("system", JUDGE_PROMPT),
                ("user", f"[보호자가 앞서 말한 사실]\n{item['fact']}\n\n[질문]\n{item['question']}\n\n[챗봇 답변]\n{result['answer']}"),
            ])
            rows.append({"id": item["id"], "variant": variant, "route": result["route"], "answer": result["answer"],
                         "uses_fact": verdict.uses_fact, "specific": verdict.specific,
                         "evidence_mentions_condition": any(word in evidence for word in item["condition_keywords"]),
                         "abstained": result.get("abstained", False),
                         "reason": verdict.reason, "seconds": round(seconds, 1),
                         "history_chars": len(format_chat_history(chat_history)),
                         "summary": summarized[0]["content"] if variant == "summary" else None,
                         "summary_seconds": round(summary_seconds, 1) if variant == "summary" else None})
            print(item["id"], variant, result["route"], verdict.uses_fact, verdict.specific,
                  rows[-1]["evidence_mentions_condition"], f"{seconds:.1f}s", flush=True)
    summary = {}
    for variant in ("window", "summary", "summary_query"):
        mine = [row for row in rows if row["variant"] == variant]
        summary[variant] = {"uses_fact": sum(row["uses_fact"] for row in mine), "of": len(mine),
                            "specific": sum(row["specific"] for row in mine),
                            "evidence_mentions_condition": sum(row["evidence_mentions_condition"] for row in mine),
                            "abstained": sum(row["abstained"] for row in mine),
                            "history_chars_mean": round(statistics.mean(row["history_chars"] for row in mine)),
                            "answer_seconds_p50": statistics.median(row["seconds"] for row in mine)}
    summary["summary"]["summary_seconds_p50"] = statistics.median(
        row["summary_seconds"] for row in rows if row["variant"] == "summary")
    return {"summary": summary, "rows": rows}


def abstain() -> dict:
    from src.chatbot import chatbot

    items = json.loads((PROJECT_DIR / "tests" / "data" / "crag_eval_questions.json").read_text(encoding="utf-8"))["items"]
    rows = []
    for item in [item for item in items if item["expected"] == "abstain"]:
        result = chatbot(item["question"], crag=True, crag_reports=False)
        answer = result["answer"]
        rows.append({"id": item["id"], "abstained": result["abstained"], "answer": answer,
                     "says_searched": "찾아본 것:" in answer, "says_missing": "확인하지 못한 것:" in answer})
        print(item["id"], result["abstained"], rows[-1]["says_missing"], flush=True)
    abstained = [row for row in rows if row["abstained"]]
    return {"summary": {"questions": len(rows), "abstained": len(abstained),
                        "says_searched": sum(row["says_searched"] for row in abstained),
                        "says_missing": sum(row["says_missing"] for row in abstained)},
            "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("memory", "abstain"))
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    result = memory() if args.command == "memory" else abstain()
    print(json.dumps(result["summary"], ensure_ascii=False, indent=1))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"chat_memory_{args.command}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                                             encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
