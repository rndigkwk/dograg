"""Plotly chart builders and address normalization for the data page."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd
import plotly.express as px


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


def _apply_common_layout(figure, title: str):
    figure.update_layout(
        title={"text": title, "x": 0.02, "xanchor": "left"},
        template="simple_white",
        height=520,
        margin={"l": 32, "r": 24, "t": 72, "b": 72},
        hoverlabel={"bgcolor": "#17233f", "font": {"color": "white"}},
    )
    return figure


def build_disease_figure(disease_counts: pd.Series):
    figure = px.bar(
        x=disease_counts.index,
        y=disease_counts.values,
        labels={"x": "질병 분류", "y": "데이터 개수"},
        text_auto=True,
        color_discrete_sequence=["#7b61ff"],
    )
    figure.update_traces(
        hovertemplate="질병: %{x}<br>데이터 개수: %{y:,}건<extra></extra>",
        marker_line_width=0,
    )
    figure.update_xaxes(tickangle=-35)
    return _apply_common_layout(figure, "기타를 제외한 질병 분류 TOP 10")


def build_department_figure(department_counts: pd.Series):
    figure = px.pie(
        names=department_counts.index,
        values=department_counts.values,
        hole=0.48,
        color_discrete_sequence=px.colors.qualitative.Set3,
    )
    figure.update_traces(
        textposition="inside",
        textinfo="label+percent",
        hovertemplate="진료과: %{label}<br>데이터 개수: %{value:,}건<extra></extra>",
        marker={"line": {"color": "white", "width": 2}},
    )
    return _apply_common_layout(figure, "진료과별 데이터 비율")


def build_province_figure(province_counts: pd.Series):
    figure = px.bar(
        x=province_counts.index,
        y=province_counts.values,
        labels={"x": "시·도", "y": "동물병원 수"},
        text_auto=True,
        color_discrete_sequence=["#20a879"],
    )
    figure.update_traces(
        hovertemplate="시·도: %{x}<br>동물병원 수: %{y:,}곳<extra></extra>",
        marker_line_width=0,
    )
    figure.update_xaxes(tickangle=-35)
    return _apply_common_layout(figure, "도로명주소 기준 시·도별 동물병원 수")


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
