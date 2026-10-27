"""Is what serves in production the same release as this checkout? Read-only.

    uv run python scripts/release_check.py            # all checks; exit 1 if one fails
    uv run python scripts/release_check.py --skip-api # before the deploy has finished

A data change here takes four steps by hand: a new private data revision (src/private_data.py),
its upload to Hugging Face, the merge (Cloud Run builds the image with that revision), and the
Supabase tables refilled from the same files. On 2026-10-18 the Supabase step once ran from a
checkout that had not pulled the merge yet, so the OCR chunks stayed old while every other check
passed. This compares each piece against the checkout and prints the command that fixes a mismatch:

1. git: on main, level with origin/main, no uncommitted change under src/, scripts/ or api/
2. private data: the code's REVISION is on Hugging Face, and the local files are that revision
3. Supabase report table: the same chunk ids as the local exact store, and the same text for every
   chunk (text_sha256), so stale OCR chunks show up
4. Supabase health table: the same ids and text (hashed in the database) as the local exact store,
   and for 20 rows the same vectors: a row count alone passed a table with the right number of rows
   and other text or another model's vectors (2026-10-27)
5. API: /health reports this commit

Nothing is written anywhere. SUPABASE_DB_URL and HF_TOKEN come from .env (never printed).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

API_URL = "https://ragdog-api-892238791473.asia-northeast3.run.app"
STORE = PROJECT_DIR / "data" / "vector_store"
VECTOR_SAMPLE = 20
FIX = {
    "git": "git checkout main && git pull --ff-only",
    "revision": 'uv run python -c "from src import private_data; private_data.upload(revision=\'{revision}\')"',
    "local data": "uv run python -m src.private_data",
    "report table": "uv run python scripts/add_kb_ocr_chunks.py --supabase --replace",
    "health table": "uv run --with \"psycopg[binary]\" python scripts/export_supabase_store.py",
    "api": "wait for the Deploy to Cloud Run workflow, or run it (workflow_dispatch)",
}


def run(*args: str) -> str:
    return subprocess.run(args, cwd=PROJECT_DIR, capture_output=True, text=True, check=True).stdout.strip()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def local_rows(name: str) -> dict[str, str]:
    """Chunk id -> text hash of the exact store's documents."""
    rows = {}
    with (STORE / name / "documents.jsonl").open(encoding="utf-8") as file:
        for line in file:
            row = json.loads(line)
            rows[row["id"]] = text_hash(row["text"])
    return rows


def check_git() -> tuple[bool, str]:
    run("git", "fetch", "-q", "origin", "main")
    branch = run("git", "rev-parse", "--abbrev-ref", "HEAD")
    head, remote = run("git", "rev-parse", "HEAD"), run("git", "rev-parse", "origin/main")
    # Changed tracked files only: new files nobody committed (another session's) are not the release.
    dirty = run("git", "status", "--porcelain", "--untracked-files=no", "--", "src", "scripts", "api")
    ok = branch == "main" and head == remote and not dirty
    return ok, f"branch {branch}, HEAD {head[:8]}, origin/main {remote[:8]}" + (", uncommitted changes" if dirty else "")


def check_revision() -> list[tuple[str, bool, str]]:
    from huggingface_hub import HfApi

    from src import private_data, settings

    refs = HfApi(token=settings.get_setting("HF_TOKEN")).list_repo_refs(private_data.REPO_ID, repo_type="dataset")
    branches = {ref.name for ref in refs.branches}
    on_hub = private_data.REVISION in branches
    local = private_data.downloaded_revision()
    return [
        ("revision", on_hub, f"code {private_data.REVISION}, on Hugging Face: {'yes' if on_hub else 'no'}"),
        ("local data", local == private_data.REVISION, f"local files {local or 'none'}"),
    ]


def compare_rows(local: dict[str, str], remote: dict[str, str]) -> tuple[bool, str]:
    """Chunk id -> text hash on both sides: the same ids and the same text for each."""
    missing, extra = local.keys() - remote.keys(), remote.keys() - local.keys()
    changed = [chunk for chunk in local.keys() & remote.keys() if local[chunk] != remote[chunk]]
    detail = f"{len(remote)} rows; missing {len(missing)}, extra {len(extra)}, different text {len(changed)}"
    if changed:
        detail += f" (e.g. {min(changed)})"
    return not (missing or extra or changed), detail


def check_tables() -> list[tuple[str, bool, str]]:
    import numpy as np

    from src import resources, settings
    from src.supabase_store import connector

    report, health = local_rows("report"), local_rows("health")
    # The same text with another model's vectors passes a text check: a few rows' vectors too.
    # vectors.npy holds documents.jsonl's rows in order (src/vector_store.py).
    vectors = np.load(STORE / "health" / "vectors.npy")
    ids = list(health)
    sample = ids[::max(1, len(ids) // VECTOR_SAMPLE)][:VECTOR_SAMPLE]
    with connector(settings.get_setting("SUPABASE_DB_URL"))() as conn:
        remote_report = {row[0]: text_hash(row[1]) for row in
                         conn.execute(f"select id, body from {resources.SUPABASE_REPORT_TABLE}").fetchall()}
        # Hashed in the database: 19,206 consultations are 17 MB of text.
        remote_health = dict(conn.execute(
            f"select id, encode(sha256(convert_to(body, 'UTF8')), 'hex') from {resources.SUPABASE_HEALTH_TABLE}").fetchall())
        remote_vectors = dict(conn.execute(
            f"select id, embedding::text from {resources.SUPABASE_HEALTH_TABLE} where id = any(%s)", [sample]).fetchall())
    report_ok, report_detail = compare_rows(report, remote_report)
    health_ok, health_detail = compare_rows(health, remote_health)
    position = {chunk: i for i, chunk in enumerate(ids)}
    # halfvec keeps float16: the local vector rounded the same way, within float16's step near 1.
    differ = [chunk for chunk in sample if chunk not in remote_vectors or not np.allclose(
        np.asarray(json.loads(remote_vectors[chunk]), dtype=np.float32),
        vectors[position[chunk]].astype(np.float16).astype(np.float32), atol=1e-3)]
    health_detail += f", vectors differ {len(differ)}/{len(sample)}" + (f" (e.g. {differ[0]})" if differ else "")
    return [("report table", report_ok, report_detail), ("health table", health_ok and not differ, health_detail)]


def check_api() -> tuple[bool, str]:
    with urllib.request.urlopen(f"{API_URL}/health", timeout=20) as response:
        serving = json.loads(response.read()).get("commit", "")
    head = run("git", "rev-parse", "HEAD")
    return serving == head, f"serving {serving[:8] or 'unknown'}, HEAD {head[:8]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-api", action="store_true", help="do not compare the deployed API's commit")
    args = parser.parse_args(argv)
    from src import private_data

    results = [("git", *check_git()), *check_revision(), *check_tables()]
    if not args.skip_api:
        results.append(("api", *check_api()))
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:13} {detail}")
    failed = [name for name, ok, _ in results if not ok]
    for name in failed:
        print(f"  fix {name}: {FIX[name].format(revision=private_data.REVISION)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
