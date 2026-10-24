"""GET /places: the facility search of the place page as JSON (ADR-0008, P1). No model calls.

    GET /places/kinds                                  kinds, labels, whether they have coordinates, sources
    GET /places/regions                                provinces and their cities, counties, districts
    GET /places/search?kind=&province=&city=&limit=    in a region, by name (total + the first `limit`)
    GET /places/nearby?kind=&lat=&lon=&limit=          nearest by straight-line distance (`distance_km`)
    GET /places/emergency?lat=&lon=                    an urgent warning's hospitals, as /chat sends them
    GET /places/{id}                                   one place

Queries and region names come from src/places_search.py, which the Streamlit page uses too.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src import places_search
from src.places_data import KIND_LABELS, NO_LOCATION_KINDS
from src.tools.places import emergency_hospitals

router = APIRouter(prefix="/places", tags=["places"])

MAX_SEARCH = 1000
MAX_NEARBY = 50


def _kind(kind: str) -> str:
    if kind not in KIND_LABELS:
        raise HTTPException(422, f"kind는 {', '.join(KIND_LABELS)} 중 하나여야 합니다.")
    return kind


@router.get("/kinds")
def kinds() -> list[dict]:
    sources = places_search.sources()
    return [{"kind": kind, "label": label, "has_location": kind not in NO_LOCATION_KINDS,
             "source": sources.get(kind)} for kind, label in KIND_LABELS.items()]


@router.get("/regions")
def regions() -> dict[str, list[str]]:
    return places_search.REGIONS


@router.get("/search")
def search(kind: str, province: str, city: str | None = None,
           limit: int = Query(default=200, ge=1, le=MAX_SEARCH)) -> dict:
    _kind(kind)
    if province not in places_search.REGIONS:
        raise HTTPException(422, "알 수 없는 시/도입니다.")
    if city is not None and city not in places_search.REGIONS[province]:
        raise HTTPException(422, f"{province}에 없는 시/군/구입니다.")
    found = places_search.in_region(kind, province, city)
    return {"total": len(found), "places": [places_search.public(row) for row in found[:limit]]}


@router.get("/nearby")
def nearby(kind: str, lat: float, lon: float, limit: int = Query(default=10, ge=1, le=MAX_NEARBY)) -> dict:
    _kind(kind)
    try:
        found = places_search.nearest(kind, lat, lon, limit=limit)
    except ValueError as error:  # no coordinates for this kind, or a location outside Korea
        raise HTTPException(422, str(error)) from error
    return {"places": [places_search.public(row) for row in found]}


@router.get("/emergency")
def emergency(lat: float, lon: float) -> dict:
    """The nearest hospitals and the nearest named 24시/응급/야간: the urgent box fills itself when the
    guardian shares the location after the warning (web components/Chat.tsx), without asking again."""
    try:
        return emergency_hospitals((lat, lon))
    except ValueError as error:  # a location outside Korea
        raise HTTPException(422, str(error)) from error


@router.get("/{place_id}")
def place(place_id: str) -> dict:
    row = places_search.by_id(place_id)
    if row is None:
        raise HTTPException(404, "그 장소를 찾지 못했습니다.")
    return places_search.public(row)
