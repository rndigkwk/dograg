"""What the guardians asked that our material does not cover, collected to decide what to add.

The answer prompt makes the model say what is missing ("검색된 자료에는 ○○은 없습니다", rule 5 of
src/tools/health.py). Those sentences name the gap better than any keyword: in 200 health answers to
real consultations, 144 had one ("초콜릿 종류별 위험도", "구체적인 치료비 금액", "집에서 할 피부 관리법").
After each answer on a deployed app, up to MAX_PER_ANSWER such sentences (personal data masked,
src/pii.py) go to the Supabase table ragdog_data_gaps, closed to the public REST API; an answer the
app abstained from adds one row of kind "abstained" without text. The question itself is not stored.

Only on the deployments (settings.deployed()) with SUPABASE_DB_URL: local runs, tests and the
evaluation runs in CI would fill the table with the evaluation sets. The deployment check
(scripts/check_deployed_app.py, every few hours) asks a health question too; its browser adds
CHECK_AGENT to its user agent and those answers are left out. The insert runs in a background
thread so it never slows or breaks an answer. scripts/report_data_gaps.py lists what was collected.
"""

from __future__ import annotations

import logging
import re
import threading

from src import settings
from src.pii import mask_pii

logger = logging.getLogger(__name__)

TABLE = "ragdog_data_gaps"
MAX_PER_ANSWER = 3
MAX_CHARS = 200
GAP_ROUTES = ("rag", "analysis")
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")
# "자료에(는) ... 없습니다 / 나와 있지 않습니다 / 다루지 않습니다". Not "없어도", "않거나": in
# "자료에서는 ... 호전되지 않거나 악화되면 병원에 가라고 안내합니다" the material does cover it.
# "자료에 따르면 ... 할 수 없습니다" is what the material says, not a gap either.
_GAP = re.compile(r"자료(?:에는|에서는|엔|에(?! 따르면))[^.?!]*?(?:(?<!수 )없(?:습니다|고|어(?!도)|으며|는데|다)|"
                  r"(?:나와|설명되어|언급되어|포함되어|담겨|제시되어) 있지 않|다루지 않|확인되지 않)")
CHECK_AGENT = "RagDogCheck"
_ready = threading.Event()


def gap_sentences(answer: str) -> list[str]:
    """The sentences of an answer that say the material lacks something, cleaned and masked."""
    found: list[str] = []
    for sentence in _SENTENCES.split(answer or ""):
        text = " ".join(sentence.replace("**", "").split())
        if text and _GAP.search(text) and text not in found:
            found.append(mask_pii(text)[:MAX_CHARS])
        if len(found) == MAX_PER_ANSWER:
            break
    return found


def enabled() -> bool:
    return settings.deployed() and bool(settings.get_setting("SUPABASE_DB_URL"))


def from_check() -> bool:
    """Whether this question came from the deployment check's browser (its user agent)."""
    try:
        import streamlit as st

        return CHECK_AGENT in (st.context.headers.get("User-Agent") or "")
    except Exception:  # noqa: BLE001 - outside a Streamlit session there are no headers
        return False


def rows_for(result: dict) -> list[tuple[str, str, str | None]]:
    """(route, kind, sentence) rows for one chatbot result."""
    route = result.get("route")
    if route not in GAP_ROUTES:
        return []
    if result.get("abstained"):
        return [(route, "abstained", None)]
    return [(route, "missing", sentence) for sentence in gap_sentences(result.get("answer", ""))]


def _insert(rows: list[tuple[str, str, str | None]]) -> None:
    from src.supabase_store import connector, lock_from_data_api

    try:
        with connector(settings.get_setting("SUPABASE_DB_URL"))() as conn:
            if not _ready.is_set():
                conn.execute(f"""create table if not exists {TABLE} (
                    id bigint generated always as identity primary key,
                    created_at timestamptz not null default now(),
                    route text not null, kind text not null, sentence text)""")
                lock_from_data_api(conn, TABLE)
                _ready.set()
            with conn.cursor() as cursor:
                cursor.executemany(f"insert into {TABLE} (route, kind, sentence) values (%s, %s, %s)", rows)
    except Exception:  # noqa: BLE001 - collecting gaps must never affect the chat
        logger.warning("data gaps not saved", exc_info=True)


def record(result: dict) -> threading.Thread | None:
    """Save the gaps of one answer in the background (deployments only); the thread, for tests."""
    if not enabled() or from_check():
        return None
    rows = rows_for(result)
    if not rows:
        return None
    thread = threading.Thread(target=_insert, args=(rows,), name="data-gaps", daemon=True)
    thread.start()
    return thread
