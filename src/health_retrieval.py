"""Deterministic lexical candidate reranking and offline retrieval metrics."""


def _grams(value: str) -> set[str]:
    compact = "".join(value.lower().split())
    return {compact[index:index + size] for size in (2, 3) for index in range(max(0, len(compact) - size + 1))}


def rerank_candidates(question: str, docs: list, top_k: int) -> list:
    query = _grams(question)
    def score(doc):
        grams = _grams(getattr(doc, "page_content", "") or "")
        return len(query & grams) / max(1, len(query))
    return sorted(docs, key=lambda doc: -score(doc))[:max(0, top_k)]


def summarize_retrieval(records: list[dict]) -> dict:
    def summarize(items):
        count = len(items)
        ranks = [item.get("hit_rank") for item in items]
        hits = [rank for rank in ranks if rank is not None and 1 <= rank <= 3]
        return {"count": count, "hit@3": len(hits) / count if count else 0.0,
                "mrr@3": sum(1 / rank for rank in hits) / count if count else 0.0,
                "misses": count - len(hits)}
    return {"overall": summarize(records),
            "other": summarize([item for item in records if item["group"] == "기타"]),
            "non_other": summarize([item for item in records if item["group"] != "기타"])}
