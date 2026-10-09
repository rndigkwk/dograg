"""Data the public repository does not carry, kept in a private Hugging Face dataset.

AI Hub's policy allows publishing models and services trained on its data (with the dataset
name and aihub.or.kr credited) but not sharing the original data or lightly processed copies.
So the AI Hub corpus and every file holding its text (the CSVs, the Chroma database, the BM25
token cache, an evaluation set and an old notebook output), the synthetic queries derived from it
and the report PDFs (publishers' copyright) live in `blanden77/dograg-data`, a private dataset
whose paths mirror this repository. The app, CI and scripts download what is missing with
HF_TOKEN (read access) into the same paths, which .gitignore keeps out of Git.

    uv run python -m src.private_data            # download what is missing
    uv run python -m src.private_data --upload   # maintainer: push local files to the dataset
"""

from __future__ import annotations

import argparse
import fnmatch
import logging
from pathlib import Path

from src import settings

logger = logging.getLogger(__name__)

REPO_ID = "blanden77/dograg-data"
# Repository-relative paths and patterns held in the private dataset.
PRIVATE_PATTERNS = (
    "data/df.csv",
    "data/df_val.csv",
    "data/bm25_health_tokens.json.gz",
    "data/chroma_db/*",
    "data/chroma_db/*/*",
    "data/source/*.pdf",
    "data/finetune/queries.jsonl",
    "tests/data/crag_eval_questions.json",
    "notebooks/outputs/rag_answer_similarity_eval_results.csv",
)
# Without these the chatbot cannot answer health or report questions.
REQUIRED = (
    "data/df.csv",
    "data/df_val.csv",
    "data/bm25_health_tokens.json.gz",
    "data/chroma_db/chroma.sqlite3",
)


def missing(project_dir: Path = settings.PROJECT_DIR) -> list[str]:
    return [path for path in REQUIRED if not (project_dir / path).is_file()]


def needs_private_data(test):
    """unittest decorator: skip a test that reads the private data when it is not downloaded
    (a fork or a checkout without HF_TOKEN). CI downloads it, so there the test runs."""
    import unittest

    return unittest.skipIf(missing(), "private data not downloaded: uv run python -m src.private_data")(test)


def ensure(project_dir: Path = settings.PROJECT_DIR) -> list[str]:
    """Download the private files when a required one is missing; return what is still missing.

    Nothing is downloaded when everything is present (a local checkout that already has the
    data, or a server that downloaded it before)."""
    if not missing(project_dir):
        return []
    token = settings.get_setting("HF_TOKEN")
    if not token:
        logger.warning("HF_TOKEN is not set; private data (%s) cannot be downloaded", REPO_ID)
        return missing(project_dir)
    from huggingface_hub import snapshot_download

    snapshot_download(repo_id=REPO_ID, repo_type="dataset", token=token, local_dir=project_dir,
                      allow_patterns=list(PRIVATE_PATTERNS))
    return missing(project_dir)


def local_private_files(project_dir: Path = settings.PROJECT_DIR) -> list[str]:
    """Files under the project that match PRIVATE_PATTERNS (for --upload)."""
    found = []
    for path in sorted(project_dir.rglob("*")):
        relative = path.relative_to(project_dir).as_posix()
        if path.is_file() and any(fnmatch.fnmatchcase(relative, pattern) for pattern in PRIVATE_PATTERNS):
            found.append(relative)
    return found


def upload(project_dir: Path = settings.PROJECT_DIR) -> None:
    from huggingface_hub import CommitOperationAdd, HfApi

    token = settings.get_setting("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN (write access) is needed in .env")
    api = HfApi(token=token)
    api.create_repo(REPO_ID, repo_type="dataset", private=True, exist_ok=True)
    files = local_private_files(project_dir)
    api.create_commit(
        REPO_ID, repo_type="dataset", commit_message="Private data split from rndigkwk/dograg",
        operations=[CommitOperationAdd(path_in_repo=path, path_or_fileobj=str(project_dir / path)) for path in files],
    )
    info = api.dataset_info(REPO_ID, files_metadata=True)
    print(f"{REPO_ID}: private={info.private}, {len(info.siblings)} files, "
          f"{sum(s.size or 0 for s in info.siblings) / 1e6:.0f} MB")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload", action="store_true")
    args = parser.parse_args()
    if args.upload:
        upload()
        return 0
    still = ensure()
    print("all private data present" if not still else f"still missing: {still}")
    return 1 if still else 0


if __name__ == "__main__":
    raise SystemExit(main())
