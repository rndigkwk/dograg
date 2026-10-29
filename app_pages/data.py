import pandas as pd
import streamlit as st

from src import data_stats
from src.data_charts import (
    build_department_figure,
    build_disease_figure,
    build_province_figure,
)
from src.ui import apply_app_theme, render_page_header

apply_app_theme()

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

try:
    data_stats.department_counts()  # reads and checks the consultation file once
except data_stats.StatsUnavailable as error:
    st.warning(str(error))
    st.stop()

tab1, tab2, tab3, tab4 = st.tabs(
    ["기타를 제외한 질병 순위", "진료과 별 분포", "지역별 동물병원 수", "반려동물 시설 데이터"]
)

with tab1:
    st.plotly_chart(
        build_disease_figure(data_stats.disease_counts()),
        width="stretch",
        config=PLOTLY_CONFIG,
    )

with tab2:
    st.plotly_chart(
        build_department_figure(data_stats.department_counts()),
        width="stretch",
        config=PLOTLY_CONFIG,
    )

with tab3:
    st.plotly_chart(
        build_province_figure(data_stats.hospitals_by_province()),
        width="stretch",
        config=PLOTLY_CONFIG,
    )

with tab4:
    sources = pd.DataFrame(data_stats.place_sources())
    st.markdown(
        f"공공데이터 {len(sources)}종을 하나의 시설 DB로 정리했습니다. "
        f"원본 {sources['source_rows'].sum():,}행 중 **{sources['rows'].sum():,}곳**을 서비스에 사용합니다."
    )
    st.dataframe(
        pd.DataFrame({
            "종류": sources["label"],
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
        steps = " · ".join(row["notes"])
        st.markdown(f"- **{row['label']}** ({row['title']}): {steps}")
    st.caption(
        "좌표는 EPSG:5174(중부원점 TM)에서 WGS84로 변환하고 대한민국 범위(위도 33~39, 경도 124~132)를 벗어난 값은 버렸습니다. "
        "주소의 시·도 이름은 현재 행정구역 이름으로 통일했습니다. 재생성: `uv run python scripts/build_places_db.py`"
    )
