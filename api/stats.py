"""GET /stats: the data page's numbers as JSON (ADR-0008, P1). Counts only, no model calls.

    GET /stats/overview    diseases (top 10 without "기타"), departments, hospitals per province,
                           and the public sources of the place database with their cleaning steps
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src import data_stats

router = APIRouter(prefix="/stats", tags=["stats"])


def _counts(series) -> list[dict]:
    return [{"label": str(label), "count": int(count)} for label, count in series.items()]


@router.get("/overview")
def overview() -> dict:
    try:
        return {"diseases": _counts(data_stats.disease_counts()),
                "departments": _counts(data_stats.department_counts()),
                "hospitals_by_province": _counts(data_stats.hospitals_by_province()),
                "place_sources": [{key: value for key, value in row.items() if key != "file"}  # a build-time file name
                                  for row in data_stats.place_sources()]}
    except data_stats.StatsUnavailable as error:
        raise HTTPException(503, str(error)) from error
