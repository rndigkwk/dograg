"""Write tests/data/crag_grader_labels.json: what the CRAG grader kept, for the distilled grader's test.

    uv run python scripts/make_grader_labels.py

Source: output/llm_rerank_100.json from scripts/evaluate_llm_rerank.py --sample 100 (2026-10-05), the
CRAG v2 grader (GRADE_PROMPT, 5 candidates, 400 characters each) on the first 5 hybrid candidates of
100 validation questions. Only ids are kept: the question is df_val.csv row `row` and a candidate is
df.csv row `id`, both in the private dataset (src/private_data.py). The grader then ran with the
model's default reasoning; the app now uses none, which kept the same answer/abstain decisions on the
40 health questions (src/resources.py REVIEW_REASONING_EFFORT).
"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_DIR / "output" / "llm_rerank_100.json"
OUT = PROJECT_DIR / "tests" / "data" / "crag_grader_labels.json"
POOL = 5


def main() -> None:
    records = json.loads(SOURCE.read_text(encoding="utf-8"))["records"]
    items = []
    for record in records:
        if record["llm5"]["error"]:
            continue
        candidates = record["ids"][:POOL]
        selected = [value.strip("[] \t\r\n") for value in record["llm5"]["useful_ids"]]
        items.append({"row": record["row"], "candidates": candidates,
                      "useful_ids": [value for value in dict.fromkeys(selected) if value in candidates]})
    OUT.write_text(json.dumps({
        "source": "scripts/evaluate_llm_rerank.py --sample 100 (2026-10-05), CRAG v2 grader on the first 5 hybrid candidates",
        "question": "df_val.csv row", "candidate": "df.csv row",
        "items": items,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    empty = sum(not item["useful_ids"] for item in items)
    kept = sum(len(item["useful_ids"]) for item in items)
    print(f"{OUT}: {len(items)} questions, {kept}/{POOL * len(items)} candidates kept, {empty} with none")


if __name__ == "__main__":
    main()
