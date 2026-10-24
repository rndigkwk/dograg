"""Plotly chart builders for the data page."""

from __future__ import annotations

import pandas as pd
import plotly.express as px

from src.provinces import PROVINCE_ALIASES, normalize_province  # noqa: F401  (re-exported)


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
