"""Health Q&A answers, looked up from the source CSV by Chroma document id.

Answers are not stored as Chroma metadata: Chroma indexes every string metadata
value, so long answers inflated chroma.sqlite3 (docs/wiki/deployment-resources.md).
The `pet_care` document id is the CSV's unnamed row-number column.
"""

import csv
from pathlib import Path


def load_health_answers(csv_path: Path) -> dict[str, str]:
    with open(csv_path, encoding="utf-8", newline="") as file:
        return {
            row[""]: (row.get("qa.output") or "").replace("\r", "")
            for row in csv.DictReader(file)
        }


def attach_health_answers(docs: list, answers: dict[str, str]) -> list:
    """Fill `qa.output` in place for documents whose metadata lacks it."""
    for doc in docs:
        answer = answers.get(str(getattr(doc, "id", None)))
        if answer is not None and "qa.output" not in doc.metadata:
            doc.metadata["qa.output"] = answer
    return docs
