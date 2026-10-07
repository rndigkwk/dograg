"""Pet places (data/places.db): nearest to the browser's location, or by region."""

import json
import sqlite3
from contextlib import closing

import pandas as pd
import pydeck as pdk
import streamlit as st

from src import resources
from src.location_component import render_location_control
from src.places_data import (
    INFO_LABELS,
    KIND_LABELS,
    NO_LOCATION_KINDS,
    describe_info,
    nearest_places,
)
from src.ui import apply_app_theme, render_page_header

apply_app_theme()

SELECTED_PLACE_ID_STATE_KEY = "selected_place_id"
RESULT_COLUMNS = "id, kind, name, road_address, lot_address, phone, homepage, category, info, latitude, longitude"
# pet_friendly details worth a column; the rest stay in the place view.
TABLE_INFO_KEYS = ("size", "restrictions", "extra_fee", "hours")


def query_places(sql: str, parameters=()) -> pd.DataFrame:
    with closing(sqlite3.connect(f"file:{resources.DB_PATH.as_posix()}?mode=ro", uri=True)) as connection:
        return pd.read_sql_query(sql, connection, params=list(parameters))


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
    selected = query_places(f"SELECT {RESULT_COLUMNS} FROM place WHERE id = ?", [place_id])
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
# 지역 목록
# =========================

region_dict = {

    "서울특별시": [
            "종로구", "중구", "용산구", "성동구", "광진구", "동대문구",
            "중랑구", "성북구", "강북구", "도봉구", "노원구", "은평구",
            "서대문구", "마포구", "양천구", "강서구", "구로구", "금천구",
            "영등포구", "동작구", "관악구", "서초구", "강남구", "송파구",
            "강동구"
        ],

    "경기도": [
        "수원시", "성남시", "의정부시", "안양시", "부천시", "광명시",
        "평택시", "동두천시", "안산시", "고양시", "과천시", "구리시",
        "남양주시", "오산시", "시흥시", "군포시", "의왕시", "하남시",
        "용인시", "파주시", "이천시", "안성시", "김포시", "연천군",
        "가평군", "양평군", "화성시", "광주시", "양주시", "포천시",
        "여주시"
    ],

    "부산광역시": [
        "중구", "서구", "동구", "영도구", "부산진구", "동래구",
        "남구", "북구", "해운대구", "사하구", "금정구", "강서구",
        "연제구", "수영구", "사상구", "기장군"
    ],

    "경상남도": [
        "진주시", "통영시", "사천시", "김해시", "밀양시", "거제시",
        "양산시", "의령군", "함안군", "창녕군", "고성군", "남해군",
        "하동군", "산청군", "함양군", "거창군", "합천군", "창원시"
    ],

    "전남광주통합특별시": [
        "목포시", "여수시", "순천시", "나주시", "광양시",
        "동구", "서구", "남구", "북구", "광산구",
        "담양군", "곡성군", "구례군", "고흥군", "보성군",
        "화순군", "장흥군", "강진군", "해남군", "영암군",
        "무안군", "함평군", "영광군", "장성군", "완도군",
        "진도군", "신안군"
    ],

    "인천광역시": [
        "중구", "영종구", "제물포구", "미추홀구", "연수구",
        "남동구", "부평구", "계양구", "서해구", "검단구", "강화군"
    ],

    "경상북도": [
        "포항시", "경주시", "김천시", "안동시", "구미시", "영주시",
        "영천시", "상주시", "문경시", "경산시", "의성군", "청송군",
        "영양군", "영덕군", "청도군", "고령군", "성주군", "칠곡군",
        "예천군", "봉화군", "울진군", "울릉군"
    ],

    "대구광역시": [
        "중구", "동구", "서구", "남구", "북구",
        "수성구", "달서구", "달성군", "군위군"
    ],

    "충청남도": [
        "천안시", "공주시", "보령시", "아산시", "서산시",
        "논산시", "금산군", "부여군", "서천군", "청양군",
        "홍성군", "예산군", "태안군", "계룡시", "당진시"
    ],

    "전북특별자치도": [
        "전주시", "군산시", "익산시", "정읍시", "남원시",
        "김제시", "완주군", "진안군", "무주군", "장수군",
        "임실군", "순창군", "고창군", "부안군"
    ],

    "충청북도": [
        "충주시", "제천시", "보은군", "옥천군", "영동군",
        "진천군", "괴산군", "음성군", "단양군", "증평군",
        "청주시"
    ],

    "강원특별자치도": [
        "춘천시", "원주시", "강릉시", "동해시", "태백시", "속초시",
        "삼척시", "홍천군", "횡성군", "영월군", "평창군", "정선군",
        "철원군", "화천군", "양구군", "인제군", "고성군", "양양군"
    ],

    "대전광역시": [
        "동구", "중구", "서구", "유성구", "대덕구"
    ],

    "울산광역시": [
        "중구", "남구", "동구", "북구", "울주군"
    ],

    "제주특별자치도": [
        "제주시", "서귀포시"
    ],

    "세종특별자치시": [
        "한누리대로", "새롬중앙로", "조치원읍", "마음로", "다정중앙로",
        "장군면", "나성로", "보람로", "집현북로", "해밀3로", "금남면",
        "아름서1길", "도움3로", "보듬3로", "연서면", "다정1길", "노을1로"
    ]
}

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
sources = query_places("SELECT kind, title, url, rows, updated FROM source").set_index("kind")
if kind in sources.index:
    source = sources.loc[kind]
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
        located = query_places(
            f"SELECT {RESULT_COLUMNS} FROM place WHERE kind = ? AND latitude IS NOT NULL", [kind]
        )
        nearby = pd.DataFrame(nearest_places(located.to_dict("records"), *location))
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
    conditions = ["kind = ?", "(road_address LIKE ? OR lot_address LIKE ?)"]
    parameters = [kind, f"{big}%", f"{big}%"]
    if small:
        conditions.append("(road_address LIKE ? OR lot_address LIKE ?)")
        parameters += [f"%{small}%", f"%{small}%"]
    found = query_places(
        f"SELECT {RESULT_COLUMNS} FROM place WHERE {' AND '.join(conditions)} ORDER BY name", parameters
    )
    area = f"{big} {small}" if small else big
    if found.empty:
        st.warning(f"{area} 지역의 {label} 정보를 찾지 못했습니다.")
    else:
        st.success(f"{area} 지역에서 {label} {len(found):,}곳을 찾았습니다.")
        render_place_table(found)
        render_place_map(found)
