"""Search small, answer from the whole page? (day46 Parent-Child, page as the parent)

Report answers get the 6 nearest 1,000-character chunks. Tables and lists are often cut at a
chunk boundary, so the number a question asks for can sit in the half that was not retrieved.
This compares, on the 18 answerable report questions of tests/data/crag_eval_questions.json:

- chunks: the app today (top 6 chunks)
- pages:  the same top 6 chunks, each replaced by its whole PDF page (unique pages in rank
          order, rebuilt from the page's stored chunks), i.e. search by the child, answer from the parent

    uv run python scripts/evaluate_report_pages.py references   # reference answers from the gold pages
    uv run python scripts/evaluate_report_pages.py compare --repeats 2

References are written by a model reading only the gold page(s) and saved to
tests/data/report_reference_answers.json (review them; they are the yardstick). Each answer is
then graded against its reference: correct, partial, wrong, or abstained.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

QUESTIONS = PROJECT_DIR / "tests" / "data" / "crag_eval_questions.json"
REFERENCES = PROJECT_DIR / "tests" / "data" / "report_reference_answers.json"
OUT = PROJECT_DIR / "output" / "report_pages_eval.json"
PAGE_CHARS = 6000
OVERLAP = 200


def answerable_items() -> list[dict]:
    items = json.loads(QUESTIONS.read_text(encoding="utf-8"))["items"]
    return [item for item in items if item["group"] == "report_answerable"]


def page_text(source_name: str, page: int) -> str:
    import pymupdf

    with pymupdf.open(PROJECT_DIR / "data" / "source" / source_name) as pdf:
        return pdf[page - 1].get_text().strip()


def model(effort: str | None = None):
    from langchain_openai import ChatOpenAI

    from src import resources, settings

    return ChatOpenAI(model=resources.CHAT_MODEL_NAME, api_key=settings.get_openai_api_key(),
                      **({"reasoning_effort": effort} if effort else {}))


class Reference(BaseModel):
    answerable: bool
    answer: str


class Grade(BaseModel):
    verdict: Literal["correct", "partial", "wrong", "abstained"]
    reason: str


def references() -> None:
    writer = model("medium").with_structured_output(Reference)
    out = []
    for item in answerable_items():
        pages = "\n\n".join(f"[{name} {page}쪽]\n{page_text(name, page)}" for name, page in item["gold_pages"])
        ref = writer.invoke([
            ("system", ("아래 보고서 페이지만 보고 질문에 대한 정답을 1~2문장으로 쓰세요. 질문이 묻는 수치는 모두 포함하고, "
                        "페이지에 없는 내용은 쓰지 마세요. 페이지에 답이 없으면 answerable=false.")),
            ("user", f"[질문]\n{item['question']}\n\n{pages}"),
        ])
        out.append({"id": item["id"], "question": item["question"], "gold_pages": item["gold_pages"],
                    "answerable": ref.answerable, "reference": ref.answer})
        print(item["id"], ref.answerable, ref.answer[:150], flush=True)
    REFERENCES.write_text(json.dumps({"description": "Reference answers written from the gold pages only "
                                      "(scripts/evaluate_report_pages.py references); reviewed by hand.",
                                      "items": out}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def as_pages(db, docs: list) -> list:
    """The retrieved chunks' pages, in rank order, as whole-page documents. A page is rebuilt from
    all of its stored chunks (PDF text extraction is empty on some image-based KB pages), with
    the 200-character overlap between neighbouring chunks removed."""
    from langchain_core.documents import Document

    seen, pages = set(), []
    for doc in docs:
        key = (doc.metadata.get("source"), doc.metadata.get("page"))
        if key in seen:
            continue
        seen.add(key)
        stored = db.get(where={"$and": [{"source": key[0]}, {"page": key[1]}]}, include=["documents", "metadatas"])
        chunks = sorted(zip(stored["metadatas"], stored["documents"]), key=lambda pair: pair[0].get("chunk_index", 0))
        text = ""
        for _, chunk in chunks:
            overlap = next((n for n in range(min(len(text), len(chunk), OVERLAP), 0, -1) if text.endswith(chunk[:n])), 0)
            text += ("" if overlap else "\n") + chunk[overlap:]
        pages.append(Document(page_content=text.strip()[:PAGE_CHARS], metadata=dict(doc.metadata)))
    return pages


def compare(repeats: int, workers: int) -> None:
    from src import resources
    from src.tools import report

    refs = {item["id"]: item for item in json.loads(REFERENCES.read_text(encoding="utf-8"))["items"]}
    items = [item for item in answerable_items() if refs[item["id"]]["answerable"]]
    grader = model("medium").with_structured_output(Grade)
    with tempfile.TemporaryDirectory(prefix="ragdog-pages-", ignore_cleanup_errors=True) as directory:
        resources.CHROMA_DIR = Path(directory) / "chroma_db"
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", resources.CHROMA_DIR)
        db = resources.load_report_vector_db()
        contexts = {}
        for item in items:
            chunks = db.similarity_search(item["question"], k=report.REPORT_ANALYSIS_TOP_K)
            contexts[item["id"]] = {"chunks": chunks, "pages": as_pages(db, chunks)}

        def run(job):
            item, variant, _ = job
            docs = contexts[item["id"]][variant]
            started = time.perf_counter()
            answer = report.generate_report_answer(item["question"], docs)
            seconds = time.perf_counter() - started
            grade = grader.invoke([
                ("system", ("보고서 질문에 대한 답변을 정답과 비교해 판정하세요. correct: 질문이 묻는 수치·사실이 정답과 모두 맞음. "
                            "partial: 일부만 맞거나 일부 빠짐. wrong: 틀린 수치·사실을 말함. abstained: 자료에 없다며 답하지 않음.")),
                ("user", f"[질문]\n{item['question']}\n\n[정답]\n{refs[item['id']]['reference']}\n\n[답변]\n{answer}"),
            ])
            return {"id": item["id"], "variant": variant, "verdict": grade.verdict, "reason": grade.reason,
                    "seconds": round(seconds, 1), "context_chars": sum(len(d.page_content) for d in docs)}

        jobs = [(item, variant, r) for r in range(repeats) for item in items for variant in ("chunks", "pages")]
        with ThreadPoolExecutor(workers) as pool:
            rows = list(pool.map(run, jobs))
    summary = {}
    for variant in ("chunks", "pages"):
        mine = [row for row in rows if row["variant"] == variant]
        summary[variant] = {
            **{v: sum(row["verdict"] == v for row in mine) for v in ("correct", "partial", "wrong", "abstained")},
            "runs": len(mine),
            "correct_rate": round(sum(row["verdict"] == "correct" for row in mine) / len(mine), 3),
            "context_chars_mean": round(statistics.mean(row["context_chars"] for row in mine)),
            "answer_seconds_p50": statistics.median(row["seconds"] for row in mine),
        }
    OUT.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("references", "compare"))
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    references() if args.command == "references" else compare(args.repeats, args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
