import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd
import streamlit as st

from src import resources
from src.data_charts import (
    build_department_figure,
    build_disease_figure,
    build_province_figure,
    normalize_province,
)
from src.places_data import KIND_LABELS
from src.ui import apply_app_theme, render_page_header

apply_app_theme()

BASE_DIR = Path(__file__).resolve().parents[1]
PLOTLY_CONFIG = {
    "displaylogo": False,
    "responsive": True,
    "toImageButtonOptions": {"format": "png", "filename": "petcare-chart"},
}

render_page_header(
    "데이터 소개",
    eyebrow="신뢰할 수 있는 데이터",
    description="반려동물 건강과 동물병원 데이터를 한눈에 확인하고, 필요한 인사이트를 찾아보세요.",
    accent="데이터로 살펴보는 반려동물 생활",
)

df_path = BASE_DIR / "data" / "df.csv"

if not df_path.exists() or df_path.stat().st_size <= 2:
    st.warning(f"그래프 데이터 파일이 비어 있습니다: {df_path}")
    st.stop()

try:
    df = pd.read_csv(df_path)
except pd.errors.EmptyDataError:
    st.warning(f"그래프 데이터 파일을 읽을 수 없습니다: {df_path}")
    st.stop()
required_columns = {"meta.disease", "meta.department"}
missing_columns = required_columns.difference(df.columns)
if missing_columns:
    st.warning(f"데이터에 필요한 컬럼이 없습니다: {', '.join(sorted(missing_columns))}")
    st.stop()

tab1, tab2, tab3, tab4 = st.tabs(
    ["기타를 제외한 질병 순위", "진료과 별 분포", "지역별 동물병원 수", "반려동물 시설 데이터"]
)

with tab1:
    disease_counts = (
        df.loc[df["meta.disease"] != "기타", "meta.disease"]
        .value_counts()
        .head(10)
    )
    st.plotly_chart(
        build_disease_figure(disease_counts),
        width="stretch",
        config=PLOTLY_CONFIG,
    )

with tab2:
    department_counts = (
        df["meta.department"]
        .astype("string")
        .str.strip()
        .fillna("결측")
        .value_counts()
    )
    st.plotly_chart(
        build_department_figure(department_counts),
        width="stretch",
        config=PLOTLY_CONFIG,
    )

with tab3:
    with closing(sqlite3.connect(f"file:{resources.DB_PATH.as_posix()}?mode=ro", uri=True)) as connection:
        hospital_df = pd.read_sql_query(
            "SELECT road_address, lot_address FROM place WHERE kind = 'hospital'", connection
        )
    province_counts = (
        hospital_df["road_address"]
        .fillna(hospital_df["lot_address"])
        .map(normalize_province)
        .value_counts()
        .sort_values(ascending=False)
    )
    st.plotly_chart(
        build_province_figure(province_counts),
        width="stretch",
        config=PLOTLY_CONFIG,
    )

with tab4:
    with closing(sqlite3.connect(f"file:{resources.DB_PATH.as_posix()}?mode=ro", uri=True)) as connection:
        sources = pd.read_sql_query("SELECT * FROM source", connection)
    sources["order"] = sources["kind"].map(list(KIND_LABELS).index)
    sources = sources.sort_values("order")
    st.markdown(
        f"공공데이터 {len(sources)}종을 하나의 시설 DB로 정리했습니다. "
        f"원본 {sources['source_rows'].sum():,}행 중 **{sources['rows'].sum():,}곳**을 서비스에 사용합니다."
    )
    st.dataframe(
        pd.DataFrame({
            "종류": sources["kind"].map(KIND_LABELS),
            "출처": sources["title"],
            "원본 행": sources["source_rows"],
            "사용": sources["rows"],
            "좌표 보유": (sources["with_location"] / sources["rows"]).map("{:.0%}".format),
            "전화번호 보유": (sources["with_phone"] / sources["rows"]).map("{:.0%}".format),
            "데이터 기준일": sources["updated"].str[:10],
        }),
        hide_index=True,
        width="stretch",
    )
    st.markdown("##### 정제 과정")
    for row in sources.to_dict("records"):
        steps = " · ".join(json.loads(row["notes"] or "[]"))
        st.markdown(f"- **{KIND_LABELS[row['kind']]}**: {steps}")
    st.caption(
        "좌표는 EPSG:5174(중부원점 TM)에서 WGS84로 변환하고 대한민국 범위(위도 33~39, 경도 124~132)를 벗어난 값은 버렸습니다. "
        "주소의 시·도 이름은 현재 행정구역 이름으로 통일했습니다. 재생성: `uv run python scripts/build_places_db.py`"
    )
