"""Refuse a production write from a checkout that is not the merged main (2026-11-05).

The KB OCR corrections reached Supabase late once: `add_kb_ocr_chunks.py --supabase --replace`
ran in a checkout still at an older main, so it rebuilt the OCR chunks from the previous
correction table and replaced the newer rows in production. The scripts that write production
tables call `unmerged_reason()` first and stop when it returns a reason.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

FETCH_SECONDS = 60


def git(project_dir: Path, *args: str, timeout: float = 30) -> str:
    return subprocess.run(["git", "-C", str(project_dir), *args], capture_output=True, text=True,
                          encoding="utf-8", timeout=timeout, check=True).stdout.strip()


def unmerged_reason(project_dir: Path, paths: Sequence[str] = ("scripts", "src")) -> str | None:
    """None when HEAD is the freshly fetched origin/main and `paths` have no local changes;
    otherwise what is wrong and how to fix it."""
    try:
        git(project_dir, "fetch", "-q", "origin", "main", timeout=FETCH_SECONDS)
        head = git(project_dir, "rev-parse", "HEAD")
        main = git(project_dir, "rev-parse", "origin/main")
        changed = git(project_dir, "status", "--porcelain", "--untracked-files=no", "--", *paths)
    except (OSError, subprocess.SubprocessError) as error:
        return f"could not check the checkout against origin/main ({error})"
    if head != main:
        return (f"HEAD {head[:8]} is not origin/main {main[:8]}; "
                "update first: git switch main, then git merge --ff-only origin/main")
    if changed:
        files = ", ".join(line.split(maxsplit=1)[-1] for line in changed.splitlines())
        return f"local changes in {files}; the write would not match main"
    return None
