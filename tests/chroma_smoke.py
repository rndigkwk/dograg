"""Run local vector-search smoke checks on a disposable Chroma copy.

Usage: .venv/Scripts/python.exe tests/chroma_smoke.py
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CHROMA_DIR = PROJECT_DIR / "data" / "chroma_db"


def run_searches(copy_path: Path) -> int:
    sys.path.insert(0, str(PROJECT_DIR))
    from pages import rag

    with patch.object(rag, "CHROMA_DIR", copy_path):
        health_hits = rag.load_vector_db().similarity_search("강아지 구토", k=1)
        report_hits = rag.load_report_vector_db().similarity_search(
            "반려동물 양육 현황", k=1
        )
    print(f"health_hits={len(health_hits)} report_hits={len(report_hits)}")
    return 0 if health_hits and report_hits else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_CHROMA_DIR)
    parser.add_argument("--check-copy-only", action="store_true")
    parser.add_argument("--worker-copy", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.worker_copy is not None:
        return run_searches(args.worker_copy)

    source = args.source.resolve(strict=True)
    if not (source / "chroma.sqlite3").is_file():
        parser.error(f"Chroma database not found: {source}")

    with tempfile.TemporaryDirectory(prefix="dograg-chroma-smoke-") as temp_dir:
        copy_path = Path(temp_dir) / "chroma_db"
        shutil.copytree(source, copy_path)

        if args.check_copy_only:
            with (copy_path / "chroma.sqlite3").open("ab") as file:
                file.write(b"-copy-probe")
            if (source / "chroma.sqlite3").read_bytes() == (
                copy_path / "chroma.sqlite3"
            ).read_bytes():
                raise AssertionError("The test copy must be independent of the source")
            print("isolated copy verified")
            return 0

        env = os.environ.copy()
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker-copy", str(copy_path)],
            cwd=PROJECT_DIR,
            env=env,
            check=False,
        )
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
