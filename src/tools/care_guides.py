"""Public care guides (동물사랑배움터) searched next to the health consultations.

The AI Hub consultations are mostly about symptoms; everyday care (grooming, nail trims, walks,
disasters, old age and loss) is thin there (docs/wiki/retrieval-experiments.md, basic care questions).
scripts/build_care_guides.py cuts four education guides into short pieces with their vectors (the
health search's own model, so no other model is loaded). A health question gets at most GUIDE_K of
them, only when one is as close as GUIDE_FLOOR; the evidence grader then keeps or drops them like
the consultations, and the answer names the guide it used.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache

import numpy as np
from langchain_core.documents import Document

from src import resources, settings
from src.untrusted import drop_instructed

logger = logging.getLogger(__name__)

GUIDE_DIR = settings.PROJECT_DIR / "data" / "care_guides"
GUIDE_KIND = "care_guide"
GUIDE_K = 2
# Cosine similarity of the closest piece. On 12 probe questions (2026-10-19) the guide answering
# the question scored 0.56-0.71 (nail trims 0.67, disaster kit 0.71, after a death 0.62), the
# unrelated best pieces 0.31-0.53 (diarrhoea 0.31, heatstroke 0.53, an old dog pacing at night 0.47).
# 0.55 -> 0.52 (2026-10-20): g11 "발이나 귀 만지는 걸 싫어하는데" missed the etiquette guide's touching
# lesson at 0.522; 0.52 also brings the guide to deworming, flea and tick medicine, foods to avoid,
# temperature and obesity questions (basic care 13 -> 18 of 30), while 0.50 would reach u20, a
# question to decline. Chosen looking at g11, so judged on the basic care set and the merge gate.
GUIDE_FLOOR = 0.52


@lru_cache(maxsize=1)
def load_guides() -> tuple[list[dict], np.ndarray] | None:
    """The pieces and their vectors, or None when the private data has no guides."""
    chunks_path, vectors_path = GUIDE_DIR / "chunks.json", GUIDE_DIR / "vectors.npy"
    if not (chunks_path.is_file() and vectors_path.is_file()):
        logger.info("no care guides at %s", GUIDE_DIR)
        return None
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    vectors = np.load(vectors_path)
    if len(chunks) != len(vectors):
        logger.warning("care guides: %d pieces but %d vectors; not used", len(chunks), len(vectors))
        return None
    return chunks, vectors


def _scores(query: str) -> tuple[list[dict], np.ndarray] | None:
    guides = load_guides()
    if guides is None or not query.strip():
        return None
    chunks, vectors = guides
    vector = np.asarray(resources.load_health_embeddings().embed_query(query), dtype=np.float32)
    return chunks, vectors @ (vector / np.linalg.norm(vector))


def guide_top_similarity(query: str) -> float | None:
    found = _scores(query)
    return float(found[1].max()) if found is not None else None


def retrieve_care_guides(query: str, k: int = GUIDE_K) -> list[Document]:
    """The closest guide pieces at or above GUIDE_FLOOR, one per page, as evidence documents."""
    try:
        found = _scores(query)
    except Exception:  # noqa: BLE001 - the guides add to the consultations; without them the answer goes on
        logger.warning("care guide search failed", exc_info=True)
        return []
    if found is None:
        return []
    chunks, scores = found
    docs, pages = [], set()
    for index in np.argsort(-scores):
        if scores[index] < GUIDE_FLOOR or len(docs) >= k:
            break
        chunk = chunks[index]
        page = (chunk["title"], chunk["page"])
        if page in pages:
            continue
        pages.add(page)
        docs.append(Document(page_content=chunk["context"], id=chunk["id"], metadata={
            "kind": GUIDE_KIND, "source_id": chunk["id"], "title": chunk["title"], "page": chunk["page"],
            "organization": chunk["organization"], "url": chunk["url"], "piece": chunk["text"],
            "similarity": round(float(scores[index]), 3),
        }))
    return drop_instructed(docs, "care guide")  # the retrieval rail (src/untrusted.py)


def is_guide(doc) -> bool:
    return doc.metadata.get("kind") == GUIDE_KIND
