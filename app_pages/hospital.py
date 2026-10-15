"""Pet places (data/places.db): nearest to the browser's location, or by region."""

import json

import pandas as pd
import pydeck as pdk
import streamlit as st

from src import places_search
from src.location_component import render_location_control
from src.places_data import (
    INFO_LABELS,
    KIND_LABELS,
    NO_LOCATION_KINDS,
    describe_info,
)
from src.places_search import REGIONS as region_dict
from src.ui import apply_app_theme, render_page_header

apply_app_theme()

SELECTED_PLACE_ID_STATE_KEY = "selected_place_id"
# pet_friendly details worth a column; the rest stay in the place view.
TABLE_INFO_KEYS = ("size", "restrictions", "extra_fee", "hours")


def address_of(row) -> str:
    return row.get("road_address") or row.get("lot_address") or "주소 없음"


def render_place_table(places: pd.DataFrame, *, with_distance: bool = False) -> None:
    records = places.to_dict("records")
    table = pd.DataFrame({"이름": places["name"]})
    if places["category"].notna().any():
        table["분류"] = places["category"].fillna("")
    table["주소"] = [address_of(row) for row in records]
    table["전화번호"] = places["phone"].fillna("")
    if places["kind"].eq("pet_friendly").any():
        details = [json.loads(row["info"]) if isinstance(row.get("info"), str) else {} for row in records]
        for key in TABLE_INFO_KEYS:
            table[INFO_LABELS[key]] = [detail.get(key, "") for detail in details]
    if with_distance:
        table["직선거리(km)"] = places["distance_km"].round(2)
    if places["homepage"].notna().any():
        table["홈페이지"] = places["homepage"].fillna("")
    st.dataframe(table, hide_index=True, width="stretch")


def render_place_map(places: pd.DataFrame, *, zoom: int = 12) -> None:
    located = places.dropna(subset=["latitude", "longitude"]).copy()
    if located.empty:
        st.caption("지도에 표시할 수 있는 좌표 정보가 없습니다.")
        return
    located["address"] = [address_of(row) for row in located.to_dict("records")]
    st.pydeck_chart(
        pdk.Deck(
            layers=[pdk.Layer(
                "ScatterplotLayer",
                data=located,
                get_position="[longitude, latitude]",
                get_radius=12 if len(located) > 1 else 30,
                radius_min_pixels=5,
                get_fill_color=[255, 0, 0, 170],
                pickable=True,
            )],
            initial_view_state=pdk.ViewState(
                latitude=located["latitude"].mean(),
                longitude=located["longitude"].mean(),
                zoom=zoom,
            ),
            tooltip={"text": "{name}\n{address}"},
        ),
        width="stretch",
    )


def render_selected_place() -> bool:
    place_id = st.session_state.get(SELECTED_PLACE_ID_STATE_KEY)
    if place_id is None:
        return False
    row = places_search.by_id(place_id)
    selected = pd.DataFrame([row] if row else [])
    if st.button("다른 장소 찾기", key="clear_selected_place"):
        st.session_state.pop(SELECTED_PLACE_ID_STATE_KEY, None)
        st.rerun()
    if selected.empty:
        st.warning("선택한 장소를 찾지 못했습니다.")
        return True
    place = selected.iloc[0].to_dict()
    st.title(place["name"])
    st.write(address_of(place))
    if place.get("category"):
        st.caption(f"{KIND_LABELS[place['kind']]} · {place['category']}")
    if place.get("phone"):
        st.write(f"전화번호: {place['phone']}")
    for line in describe_info(place.get("info")):
        st.write(line)
    render_place_map(selected, zoom=16)
    return True


if render_selected_place():
    st.stop()


# =========================
# 화면 구성
# =========================

render_page_header(
    "반려동물 시설 찾기",
    eyebrow="가까운 반려동물 시설 찾기",
    description="동물병원, 동물약국, 반려견과 함께 갈 수 있는 곳, 미용·위탁·장묘업체를 지역이나 현재 위치로 찾아볼 수 있습니다.",
    accent="우리 동네의 든든한 반려 생활 지도",
)

kind = st.radio(
    "찾을 곳",
    list(KIND_LABELS),
    format_func=KIND_LABELS.get,
    horizontal=True,
    key="place_kind",
)
label = KIND_LABELS[kind]
sources = places_search.sources()
if kind in sources:
    source = sources[kind]
    st.caption(
        f"출처: [{source['title']}]({source['url']}) · {source['rows']:,}곳 · 데이터 기준 {str(source['updated'])[:10]}. "
        "공공데이터라서 실제 영업 여부·영업시간·이용 조건은 방문 전 전화로 확인해 주세요."
    )

if kind in NO_LOCATION_KINDS:
    st.info(f"{label} 목록에는 좌표가 없어 현재 위치 검색은 지원하지 않고, 지역으로만 찾을 수 있습니다.")
else:
    st.subheader(f"현재 위치에서 가까운 {label}")
    st.caption("버튼을 누를 때만 위치 권한을 요청합니다. 거리는 직선거리이며 이동거리·소요시간과 다릅니다.")
    location, location_status = render_location_control("hospital_browser_location")
    if location_status:
        st.info(f"{location_status} 아래 지역 검색은 계속 사용할 수 있습니다.")
    if location:
        nearby = pd.DataFrame(places_search.nearest(kind, *location))
        if nearby.empty:
            st.warning(f"위치 좌표가 유효한 {label} 정보를 찾지 못했습니다.")
        else:
            render_place_table(nearby, with_distance=True)
            render_place_map(nearby, zoom=13)

st.subheader("검색할 지역을 선택하세요.")
big = st.selectbox("시/도를 고르세요", list(region_dict.keys()))
small = None
if kind != "funeral":
    small = st.selectbox("시/군/구를 고르세요", region_dict[big])

if st.button("조회", key="place_search"):
    found = pd.DataFrame(places_search.in_region(kind, big, small))
    area = f"{big} {small}" if small else big
    if found.empty:
        st.warning(f"{area} 지역의 {label} 정보를 찾지 못했습니다.")
    else:
        st.success(f"{area} 지역에서 {label} {len(found):,}곳을 찾았습니다.")
        render_place_table(found)
        render_place_map(found)
