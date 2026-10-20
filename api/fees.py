"""GET /fees: regional animal-clinic fees for the fee page (2026-10-17). Table lookups, no model calls.

    GET /fees/items                      the 34 surveyed items (item + weight/species), by category
    GET /fees?item=...&detail=...        that item nationally, per si/do and per si/gun/gu:
                                         mean, median, minimum, maximum in won
    GET /fees/region?province=&city=     five common items' medians there and nationally, for the
                                         hospital list (a place-search region, src/places_search.py)

Data: data/vet_fees/vet_fees.csv (src/tools/fees.py, scripts/collect_vet_fees.py), the government's
2025 survey as published on animalclinicfee.or.kr. Every response carries the source, the collection
date and the notice that these are regional statistics, not a hospital's price.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.tools import fees

router = APIRouter(prefix="/fees", tags=["fees"])

CATEGORY_ORDER = ("진찰료", "예방접종비", "혈액검사비용", "영상검사비용", "입원비", "투약/조제비")


def _rows():
    rows = fees.load_fee_rows()
    if not rows:
        raise HTTPException(503, "진료비 자료를 불러오지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
    return rows


def _values(row: dict) -> dict:
    return {key: int(row[key]) for key in ("mean", "median", "min", "max")}


@router.get("/items")
def items() -> dict:
    found = {}  # in the survey site's order (the collector kept it): 초진 before 재진, 5kg before 10kg
    for row in _rows():
        if row["level"] == "national":
            found[(row["item"], row["detail"])] = row["category"]
    ordered = sorted(found.items(), key=lambda pair: (
        CATEGORY_ORDER.index(pair[1]) if pair[1] in CATEGORY_ORDER else len(CATEGORY_ORDER)))
    return {"items": [{"category": category, "item": item, "detail": detail, "label": fees._label(item, detail)}
                      for (item, detail), category in ordered],
            "source": fees.SOURCE, "notice": fees.NOTICE}


@router.get("/region")
def region(province: str = Query(max_length=20), city: str = Query(default="", max_length=20)) -> dict:
    _rows()
    found = fees.region_fees(province, city)
    if not any(row["median"] for row in found):
        raise HTTPException(404, "이 지역의 진료비 조사 자료가 없습니다.")
    return {"province": province, "city": city, "basis": "개, 체중 5kg 기준", "items": found,
            "source": fees.SOURCE, "notice": fees.NOTICE}


@router.get("")
def item_fees(item: str = Query(max_length=60), detail: str = Query(default="", max_length=30)) -> dict:
    rows = [row for row in _rows() if row["item"] == item and row["detail"] == detail]
    national = next((row for row in rows if row["level"] == "national"), None)
    if national is None:
        raise HTTPException(404, "조사하지 않은 진료 항목입니다.")
    return {
        "item": item, "detail": detail, "category": national["category"], "label": fees._label(item, detail),
        "national": _values(national),
        "sido": [{"sido": row["sido"], **_values(row)} for row in rows if row["level"] == "sido"],
        # Provinces with no figure for this item (the survey omits regions with one clinic or none)
        "no_data": sorted({row["sido"] for row in _rows() if row["level"] == "sido"}
                          - {row["sido"] for row in rows if row["level"] == "sido"}),
        "sigungu": [{"sido": row["sido"], "sigungu": row["sigungu"], **_values(row)}
                    for row in rows if row["level"] == "sigungu"],
        "collected": max(row["collected_utc"] for row in rows)[:10],
        "source": fees.SOURCE, "source_url": national["source"], "notice": fees.NOTICE,
    }
