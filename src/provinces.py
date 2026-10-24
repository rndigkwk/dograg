"""Province names from Korean addresses, for the data page and GET /stats (no Plotly)."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

PROVINCE_ALIASES: Mapping[str, str] = {
    "서울": "서울특별시",
    "부산": "부산광역시",
    "대구": "대구광역시",
    "인천": "인천광역시",
    "광주광역시": "전남광주통합특별시",
    "대전": "대전광역시",
    "울산": "울산광역시",
    "세종": "세종특별자치시",
    "경기": "경기도",
    "강원": "강원특별자치도",
    "충북": "충청북도",
    "충남": "충청남도",
    "전북": "전북특별자치도",
    "전남": "전남광주통합특별시",
    "경북": "경상북도",
    "경남": "경상남도",
    "제주": "제주특별자치도",
}


def normalize_province(address) -> str:
    if pd.isna(address):
        return "주소 없음"

    compact_address = "".join(str(address).split())
    for province in PROVINCE_ALIASES.values():
        if compact_address.startswith("".join(province.split())):
            return province

    for alias, province in PROVINCE_ALIASES.items():
        if compact_address.startswith(alias):
            return province

    return str(address).strip().split()[0]
