"""Search small, answer from the whole page? (day46 Parent-Child, page as the parent)
Or keep only the sentences the question needs? (day48 context compression)

Report answers get the 6 nearest 1,000-character chunks. Tables and lists are often cut at a
chunk boundary, so the number a question asks for can sit in the half that was not retrieved.
This compares, on the 18 answerable report questions of tests/data/crag_eval_questions.json:

- chunks: the app today (top 6 chunks)
- pages:  the same top 6 chunks, each replaced by its whole PDF page (unique pages in rank
          order, rebuilt from the page's stored chunks), i.e. search by the child, answer from the parent
- compressed:   the same top 6 chunks, cut to the sentences the question needs (one extraction
                call over all chunks, sentences copied verbatim), then the same answer prompt
- compressed12: top 12 chunks, compressed: more candidates in about the same context

    uv run python scripts/evaluate_report_pages.py references   # reference answers from the gold pages
    uv run python scripts/evaluate_report_pages.py compare --repeats 2
    uv run python scripts/evaluate_report_pages.py compare --variants chunks compressed compressed12

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

from pydantic import BaseModel, Field

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


class Extract(BaseModel):
    chunk: int = Field(description="자료 번호")
    sentences: list[str] = Field(description="질문에 답하는 데 필요한 문장을 원문 그대로. 표는 필요한 행 그대로")


class Extraction(BaseModel):
    extracts: list[Extract] = Field(description="필요한 문장이 있는 자료만")


COMPRESS_PROMPT = ("질문에 답하는 데 필요한 문장만 각 자료에서 원문 그대로 옮기세요. 질문이 묻는 수치, 그 수치의 조건·대상·연도, "
                   "예외와 표의 해당 행은 빠뜨리지 마세요. 고쳐 쓰거나 요약하지 말고, 필요한 문장이 없는 자료는 빼세요.")


def _squash(text: str) -> str:
    return "".join(text.split())


def compress(question: str, docs: list, extractor) -> tuple[list, float]:
    """The docs cut to the sentences the question needs, in rank order, and the share of
    extracted sentences found verbatim in their chunk (a check that nothing was rewritten)."""
    from langchain_core.documents import Document

    numbered = "\n\n".join(
        f"[자료 {number}] ({doc.metadata.get('title', '보고서')} {doc.metadata.get('page', '?')}쪽)\n{doc.page_content}"
        for number, doc in enumerate(docs, start=1))
    result = extractor.invoke([("system", COMPRESS_PROMPT), ("user", f"[질문]\n{question}\n\n{numbered}")])
    kept, found, total = {}, 0, 0
    for extract in result.extracts:
        if not 1 <= extract.chunk <= len(docs) or not extract.sentences:
            continue
        source = _squash(docs[extract.chunk - 1].page_content)
        total += len(extract.sentences)
        found += sum(_squash(sentence) in source for sentence in extract.sentences)
        kept.setdefault(extract.chunk, []).extend(extract.sentences)
    out = [Document(page_content="\n".join(kept[number]), metadata=dict(docs[number - 1].metadata))
           for number in sorted(kept)]
    return out, (found / total if total else 1.0)


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


def has_gold(docs: list, item: dict) -> bool:
    """Is one of the question's gold pages among the docs? (metadata source is a path)"""
    gold = {(name, page) for name, page in item["gold_pages"]}
    return any((Path(str(doc.metadata.get("source", ""))).name, doc.metadata.get("page")) in gold for doc in docs)


# --- variants measured and not adopted (experiment 13) -------------------------------------
WINDOW_OVERLAP_CHARS = 200
FUSION_PROMPT = (
    ("system", """반려동물 보고서(한국 반려동물 보고서, 복지실태, 산업 실태조사, 의료·보험서비스, 장묘서비스)를 검색할 질의를 만듭니다.
사용자 질문과 같은 정보를 찾되 표현이 다른 검색어 2개를 한 줄에 하나씩 쓰세요. 보고서에 나올 법한 용어(항목명, 통계 이름, 조사 대상)를 쓰고, 설명은 쓰지 마세요."""),
    ("human", "{question}"),
)


def fusion_queries(question: str) -> list[str]:
    """Day54 RAG-Fusion: the question plus two rewrites (one low-effort model call)."""
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    from src import resources

    model = resources.load_chat_model()
    if model is None:
        return [question]
    text = (ChatPromptTemplate.from_messages(list(FUSION_PROMPT)) | model.bind(reasoning_effort="low") | StrOutputParser()).invoke({"question": question})
    rewrites = [line.strip(" -•\t") for line in text.splitlines() if line.strip(" -•\t")]
    return [question, *rewrites[:2]]


def search_reports_fusion(question: str, k: int = 6) -> list:
    """Dense search for each fusion query, merged by RRF."""
    from src import resources
    from src.hybrid_retrieval import reciprocal_rank_fusion

    report_db = resources.load_report_vector_db()
    if report_db is None:
        return []
    queries = fusion_queries(question)
    return reciprocal_rank_fusion([report_db.similarity_search(query, k=12) for query in queries], top_k=k)


def _chunk_order(report_db) -> tuple[list[str], dict[str, int], dict[str, tuple[str, dict]]]:
    stored = report_db.get(include=["documents", "metadatas"])
    rows = sorted(zip(stored["ids"], stored["documents"], stored["metadatas"]),
                  key=lambda row: (row[2].get("source", ""), row[2].get("page", 0), row[2].get("chunk_index", 0)))
    ids = [row[0] for row in rows]
    return ids, {chunk_id: position for position, chunk_id in enumerate(ids)}, {row[0]: (row[1], row[2]) for row in rows}


def with_neighbors(report_db, docs: list) -> list:
    """Day46 Sentence Window at chunk level: each retrieved chunk with the chunks right before
    and after it in the same report (a table cut at a chunk boundary comes back whole). The
    200-character overlap between neighbours is removed; the hit's metadata is kept."""
    from langchain_core.documents import Document

    ids, position, chunks = _chunk_order(report_db)
    out = []
    for doc in docs:
        index = position.get(doc.id)
        if index is None:
            out.append(doc)
            continue
        source = chunks[doc.id][1].get("source")
        text = ""
        for neighbour in ids[max(index - 1, 0): index + 2]:
            body, metadata = chunks[neighbour]
            if metadata.get("source") != source:
                continue
            overlap = next((n for n in range(min(len(text), len(body), WINDOW_OVERLAP_CHARS), 0, -1)
                            if text.endswith(body[:n])), 0)
            text += ("" if overlap else "\n") + body[overlap:]
        out.append(Document(id=doc.id, page_content=text.strip(), metadata=dict(doc.metadata)))
    return out



def compare(repeats: int, workers: int, variants: list[str]) -> None:
    from src import resources
    from src.tools import report

    refs = {item["id"]: item for item in json.loads(REFERENCES.read_text(encoding="utf-8"))["items"]}
    items = [item for item in answerable_items() if refs[item["id"]]["answerable"]]
    grader = model("medium").with_structured_output(Grade)
    extractor = model("low").with_structured_output(Extraction)
    with tempfile.TemporaryDirectory(prefix="ragdog-pages-", ignore_cleanup_errors=True) as directory:
        resources.CHROMA_DIR = Path(directory) / "chroma_db"
        shutil.copytree(PROJECT_DIR / "data" / "chroma_db", resources.CHROMA_DIR)
        db = resources.load_report_vector_db()
        contexts, search_seconds = {}, {}
        for item in items:
            question = item["question"]
            chunks12 = db.similarity_search(question, k=12)
            chunks = chunks12[: report.REPORT_ANALYSIS_TOP_K]
            contexts[item["id"]] = {"chunks": chunks, "compressed": chunks, "compressed12": chunks12}
            if "pages" in variants:
                contexts[item["id"]]["pages"] = as_pages(db, chunks)
            for variant, search in (("hybrid", report.search_reports_hybrid), ("fusion", search_reports_fusion)):
                if variant in variants or f"{variant}_window" in variants:
                    started = time.perf_counter()
                    contexts[item["id"]][variant] = search(question)
                    search_seconds[(item["id"], variant)] = time.perf_counter() - started
            if "window" in variants:
                contexts[item["id"]]["window"] = with_neighbors(db, chunks)
            if "hybrid_window" in variants:
                contexts[item["id"]]["hybrid_window"] = with_neighbors(db, contexts[item["id"]]["hybrid"])

        def run(job):
            item, variant, _ = job
            docs = contexts[item["id"]][variant]
            started = time.perf_counter()
            verbatim = None
            if variant.startswith("compressed"):
                docs, verbatim = compress(item["question"], docs, extractor)
            compress_seconds = time.perf_counter() - started
            answer = report.generate_report_answer(item["question"], docs)
            seconds = time.perf_counter() - started
            grade = grader.invoke([
                ("system", ("보고서 질문에 대한 답변을 정답과 비교해 판정하세요. correct: 질문이 묻는 수치·사실이 정답과 모두 맞음. "
                            "partial: 일부만 맞거나 일부 빠짐. wrong: 틀린 수치·사실을 말함. abstained: 자료에 없다며 답하지 않음.")),
                ("user", f"[질문]\n{item['question']}\n\n[정답]\n{refs[item['id']]['reference']}\n\n[답변]\n{answer}"),
            ])
            return {"id": item["id"], "variant": variant, "verdict": grade.verdict, "reason": grade.reason,
                    "seconds": round(seconds, 1), "compress_seconds": round(compress_seconds, 1),
                    "context_chars": sum(len(d.page_content) for d in docs), "verbatim": verbatim,
                    "search_seconds": round(search_seconds.get((item["id"], variant.removesuffix("_window")), 0.0), 2),
                    "gold_in_context": has_gold(docs, item)}

        jobs = [(item, variant, r) for r in range(repeats) for item in items for variant in variants]
        with ThreadPoolExecutor(workers) as pool:
            rows = list(pool.map(run, jobs))
    summary = {}
    for variant in variants:
        mine = [row for row in rows if row["variant"] == variant]
        summary[variant] = {
            **{v: sum(row["verdict"] == v for row in mine) for v in ("correct", "partial", "wrong", "abstained")},
            "runs": len(mine),
            "correct_rate": round(sum(row["verdict"] == "correct" for row in mine) / len(mine), 3),
            "context_chars_mean": round(statistics.mean(row["context_chars"] for row in mine)),
            "answer_seconds_p50": statistics.median(row["seconds"] for row in mine),
            "gold_in_context": round(sum(row["gold_in_context"] for row in mine) / len(mine), 3),
            "search_seconds_p50": statistics.median(row["search_seconds"] for row in mine),
        }
        if variant.startswith("compressed"):
            summary[variant]["verbatim_mean"] = round(statistics.mean(row["verbatim"] for row in mine), 3)
            summary[variant]["compress_seconds_p50"] = statistics.median(row["compress_seconds"] for row in mine)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("references", "compare"))
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--variants", nargs="+", default=["chunks", "pages"],
                        choices=("chunks", "pages", "compressed", "compressed12", "hybrid", "fusion", "window",
                                 "hybrid_window"))
    args = parser.parse_args()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    references() if args.command == "references" else compare(args.repeats, args.workers, args.variants)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
