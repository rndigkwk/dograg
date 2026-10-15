"""Automatic pet memory: does a health question's new fact get offered for saving, and does a stored
fact reach a later answer? (tests/data/profile_memory_questions.json, written before the change)

    uv run python scripts/evaluate_profile_memory.py offer --mode before   # the app before (detection only on an empty profile)
    uv run python scripts/evaluate_profile_memory.py offer --mode after    # src/tools/profile.suggest_memory
    uv run python scripts/evaluate_profile_memory.py use                   # answers without / with the stored facts

offer: per item, the facts the app would offer to save. A list fact counts as found when an offered
item of that field contains the expected keyword; an offered fact matching nothing expected is a
false offer (symptoms, another dog's illness, a plan, a general question, an already stored fact).
use: the same question in a new conversation with only the dog's name stored, then with the full
profile; an answer "uses" the memory when it mentions one of must_mention. The unrelated cases
check the other side: a stored fact that has nothing to do with the question stays out of the answer.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))
SET_PATH = PROJECT_DIR / "tests" / "data" / "profile_memory_questions.json"
OUT_DIR = PROJECT_DIR / "output" / "experiments"
LIST_FIELDS = ("conditions", "medications", "allergies", "procedures")


def load() -> dict:
    return json.loads(SET_PATH.read_text(encoding="utf-8"))


def stored(raw: dict | None):
    from src.storage.models import PetProfile

    return None if raw is None else PetProfile.model_validate(raw)


def offered_before(profile, question: str) -> dict:
    """The app before this change: detection only while no profile is stored, the whole profile offered."""
    from src.tools.profile import detect_profile

    if profile is not None and not profile.is_empty():
        return {}
    detected = detect_profile(question)
    return {} if detected is None else detected.model_dump(exclude_defaults=True, mode="json")


def offered_after(profile, question: str) -> dict:
    from src.tools.profile import suggest_memory

    suggestion = suggest_memory(profile, question)
    return {} if suggestion is None else suggestion.new_facts


def score(item: dict, offered: dict) -> dict:
    expect = item["expect"]
    found = missed = false = 0
    for field in LIST_FIELDS:
        items = [str(value) for value in offered.get(field, [])]
        keys = expect.get(field, [])
        for key in keys:
            if any(key in value for value in items):
                found += 1
            else:
                missed += 1
        false += sum(not any(key in value for key in keys) for value in items)
    for field in ("weight_kg", "neutered"):
        if field in expect:
            if offered.get(field) == expect[field]:
                found += 1
            else:
                missed += 1
        elif offered.get(field) is not None:
            false += 1
    return {"found": found, "missed": missed, "false": false}


def offer(mode: str) -> dict:
    from src.tools import profile as profile_tool

    data = load()
    gate = getattr(profile_tool, "may_have_memory", None)
    fn = offered_before if mode == "before" else offered_after

    def one(item):
        offered = fn(stored(item["profile"]), item["question"])
        return {"id": item["id"], "split": item["split"], "offered": offered, **score(item, offered),
                "gate": None if gate is None else gate(item["question"])}

    with ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(one, data["items"]))
    summary = {}
    for split in ("dev", "holdout"):
        part = [r for r in rows if r["split"] == split]
        expected = sum(r["found"] + r["missed"] for r in part)
        summary[split] = {
            "facts_found": f"{sum(r['found'] for r in part)}/{expected}",
            "items_with_false_offer": f"{sum(r['false'] > 0 for r in part)}/{len(part)}",
            "gate_passed": None if gate is None else f"{sum(bool(r['gate']) for r in part)}/{len(part)}",
        }
    out = {"mode": mode, "summary": summary, "rows": rows}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"profile_memory_offer_{mode}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return out


def use() -> dict:
    from src.chatbot import chatbot

    data = load()

    def answer(case, full):
        profile = case["profile"] if full else {"name": case["profile"]["name"]}
        result = chatbot(case["question"], pet_profile=stored(profile))
        text = result.get("answer", "")
        return {"answer": text, "uses": any(word in text for word in case["must_mention"]), "route": result.get("route")}

    jobs = [(case, full) for case in data["use"] for full in (False, True)]
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda job: answer(*job), jobs))
    rows = [{"id": case["id"], "without": results[2 * i], "with": results[2 * i + 1]} for i, case in enumerate(data["use"])]

    def unrelated(case):
        text = chatbot(case["question"], pet_profile=stored(case["profile"])).get("answer", "")
        return {"id": case["id"], "answer": text, "mentions": [w for w in case["must_not_mention"] if w in text]}

    with ThreadPoolExecutor(4) as pool:
        extra = list(pool.map(unrelated, data.get("unrelated", [])))
    summary = {"without_memory": f"{sum(r['without']['uses'] for r in rows)}/{len(rows)}",
               "with_memory": f"{sum(r['with']['uses'] for r in rows)}/{len(rows)}",
               "unrelated_fact_mentioned": f"{sum(bool(r['mentions']) for r in extra)}/{len(extra)}"}
    out = {"summary": summary, "rows": rows, "unrelated": extra}
    (OUT_DIR / "profile_memory_use.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("offer", "use"))
    parser.add_argument("--mode", choices=("before", "after"), default="after")
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    sys.stdout.reconfigure(encoding="utf-8")
    out = offer(args.mode) if args.command == "offer" else use()
    print(json.dumps(out["summary"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
