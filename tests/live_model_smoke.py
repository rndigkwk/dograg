"""Opt-in, minimal real-model smoke check; never prints retrieved passages."""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HEALTH_QUESTION = "강아지가 기침을 해요. 일반적으로 무엇을 관찰해야 하나요?"
REPORT_QUESTION = "2025 반려동물 보고서의 양육비 현황을 요약해줘."
PII = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|01[016789][- ]?\d{3,4}[- ]?\d{4}|\d{6}[- ]?[1-4]\d{6}", re.I)


class _FixedDB:
    def __init__(self, docs):
        self.docs = docs

    def similarity_search(self, *args, **kwargs):
        return self.docs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-external-corpus", action="store_true")
    parser.add_argument("--worker-copy", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.allow_external_corpus:
        parser.error("Model calls need --allow-external-corpus")
    if args.worker_copy is None:
        with tempfile.TemporaryDirectory(prefix="dograg-live-smoke-") as directory:
            copy_path = Path(directory) / "chroma_db"
            shutil.copytree(ROOT / "data" / "chroma_db", copy_path)
            return subprocess.run([sys.executable, str(Path(__file__).resolve()), "--allow-external-corpus", "--worker-copy", str(copy_path)], cwd=ROOT, check=False).returncode
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from pages import rag

    if not rag.get_openai_api_key():
        print("health=unverified reason=missing_api_key")
        print("report=unverified reason=missing_api_key")
        return 2
    with patch.object(rag, "CHROMA_DIR", args.worker_copy):
            health_docs = rag.load_vector_db().similarity_search(HEALTH_QUESTION, k=3)
            topics = rag.get_report_analysis_topics(REPORT_QUESTION)
            report_docs = rag.load_report_vector_db().similarity_search(f"{' '.join(topics)}\n{REPORT_QUESTION}", k=rag.REPORT_ANALYSIS_TOP_K)
            if not health_docs or not report_docs:
                print(f"health=unverified evidence={len(health_docs)} reason=empty_retrieval")
                print(f"report=unverified evidence={len(report_docs)} reason=empty_retrieval")
                return 2
            for doc in health_docs + report_docs:
                if PII.search(doc.page_content) or PII.search(str(doc.metadata.get("qa.output", ""))):
                    print("model=unverified reason=possible_personal_information")
                    return 2
            try:
                with patch.object(rag, "initialize_rag", return_value=(_FixedDB(health_docs), rag.load_rag_chain())):
                    health = rag.ask_rag(HEALTH_QUESTION)
                print(f"health={'ok' if health['answer'] and health['evidence_rows'] else 'unverified'} evidence={len(health['evidence_rows'])} nonempty_answer={bool(health['answer'])}")
            except Exception as exc:
                print(f"health=unverified reason={type(exc).__name__}")
                return 2
            with patch.object(rag, "load_report_vector_db", return_value=_FixedDB(report_docs)):
                report = rag.analyze_report(REPORT_QUESTION)
            report_ok = bool(report["evidence_rows"] and report["answer"] and "실패" not in report["answer"])
            print(f"report={'ok' if report_ok else 'unverified'} evidence={len(report['evidence_rows'])} nonempty_answer={bool(report['answer'])}")
            return 0 if report_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
