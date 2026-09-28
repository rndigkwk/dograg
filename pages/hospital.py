import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st
import pydeck as pdk
from pyproj import Transformer
from src.ui import apply_app_theme, render_page_header
from src.hospital_distance import nearest_hospitals
from src.location_component import render_location_control

apply_app_theme()


# =========================
# DB 경로 설정
# =========================

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "hospital.db"

con = sqlite3.connect(DB_PATH)
cursor = con.cursor()


# =========================
# 좌표계 설정
# =========================

SOURCE_CRS = "EPSG:5174"
TARGET_CRS = "EPSG:4326"

transformer = Transformer.from_crs(
    SOURCE_CRS,
    TARGET_CRS,
    always_xy=True
)


def render_selected_hospital():
    hospital_id = st.session_state.get("selected_hospital_id")
    if hospital_id is None:
        return False

    selected_df = pd.read_sql_query(
        "SELECT * FROM hospital WHERE ids = ?",
        con,
        params=[hospital_id],
    )
    if selected_df.empty:
        st.warning("선택한 병원을 찾지 못했습니다.")
        return True

    selected_df["x_coor"] = pd.to_numeric(selected_df["x_coor"], errors="coerce")
    selected_df["y_coor"] = pd.to_numeric(selected_df["y_coor"], errors="coerce")
    valid_df = selected_df.dropna(subset=["x_coor", "y_coor"]).copy()
    if valid_df.empty:
        st.warning("선택한 병원의 좌표 정보가 없습니다.")
        return True

    lon, lat = transformer.transform(
        valid_df["x_coor"].to_numpy(),
        valid_df["y_coor"].to_numpy(),
    )
    valid_df["lat"] = lat
    valid_df["lon"] = lon
    hospital = valid_df.iloc[0]

    st.title("선택한 병원 위치")
    st.subheader(hospital["name"])
    st.write(hospital["new_address"])
    if st.button("다른 병원 찾기", key="clear_selected_hospital"):
        st.session_state.pop("selected_hospital_id", None)
        st.rerun()
    st.pydeck_chart(
        pdk.Deck(
            layers=[pdk.Layer(
                "ScatterplotLayer",
                data=valid_df,
                get_position="[lon, lat]",
                get_radius=30,
                get_fill_color=[255, 0, 0, 180],
                pickable=True,
            )],
            initial_view_state=pdk.ViewState(
                latitude=hospital["lat"],
                longitude=hospital["lon"],
                zoom=16,
            ),
            tooltip={"text": "{name}\n{new_address}"},
        ),
        use_container_width=True,
    )
    return True


if render_selected_hospital():
    con.close()
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
    "지역별 동물 병원 찾기",
    eyebrow="가까운 병원 찾기",
    description="지역을 선택하면 가까운 동물병원 정보와 위치를 빠르게 확인할 수 있습니다.",
    accent="우리 동네의 든든한 진료 파트너",
)

st.subheader("현재 위치에서 가까운 병원")
st.caption("버튼을 누를 때만 위치 권한을 요청합니다. 거리는 직선거리이며 이동거리·소요시간이나 영업 상태를 뜻하지 않습니다.")
location, location_status = render_location_control("hospital_browser_location")
if location_status:
    st.info(f"{location_status} 아래 지역 검색은 계속 사용할 수 있습니다.")
if location:
    cursor.execute("SELECT ids, name, new_address, old_address, x_coor, y_coor FROM hospital")
    nearby = nearest_hospitals([dict(zip(("ids", "name", "new_address", "old_address", "x_coor", "y_coor"), row)) for row in cursor.fetchall()], *location)
    if nearby:
        st.dataframe(pd.DataFrame([{"병원명": row["name"], "주소": row["new_address"] or row["old_address"], "직선거리(km)": round(row["distance_km"], 2)} for row in nearby]), use_container_width=True)
        st.map(pd.DataFrame([{"lat": row["latitude"], "lon": row["longitude"]} for row in nearby]))
    else:
        st.warning("위치 좌표가 유효한 동물병원을 찾지 못했습니다.")

st.subheader("검색할 시와 구/군을 선택하세요.")

big = st.selectbox(
    "시/도를 고르세요",
    list(region_dict.keys())
)

small = st.selectbox(
    "시/군/구를 고르세요",
    region_dict[big]
)


# =========================
# 병원 조회
# =========================

if st.button("병원 조회"):

    cursor.execute(
    """
    SELECT *
    FROM hospital
    WHERE new_address LIKE ?
    AND new_address LIKE ?
    """,
    (
        f"{big}%",
        f"%{small}%"
    )
)

    rows = cursor.fetchall()

    df = pd.DataFrame(
        rows,
        columns=[
            "ids",
            "name",
            "new_address",
            "x_coor",
            "y_coor",
            "old_address"
        ]
    )


    # =========================
    # 검색 결과 없음
    # =========================

    if df.empty:

        st.warning(
            f"{big} {small} 지역의 병원을 찾지 못했습니다."
        )

    else:

        st.success(
            f"{big} {small} 지역에서 "
            f"{len(df)}개의 병원을 찾았습니다."
        )


        # =========================
        # 병원 목록
        # =========================

        st.subheader("병원 목록")

        st.dataframe(
            df[
                [
                    "name",
                    "new_address",
                    "old_address"
                ]
            ],
            use_container_width=True
        )


        # =========================
        # 좌표 숫자 변환
        # =========================

        df["x_coor"] = pd.to_numeric(
            df["x_coor"],
            errors="coerce"
        )

        df["y_coor"] = pd.to_numeric(
            df["y_coor"],
            errors="coerce"
        )


        valid_df = df.dropna(
            subset=[
                "x_coor",
                "y_coor"
            ]
        ).copy()


        # =========================
        # 지도 출력
        # =========================

        if valid_df.empty:

            st.warning(
                "지도에 표시할 수 있는 좌표 정보가 없습니다."
            )

        else:

            # 좌표 변환
            lon, lat = transformer.transform(
                valid_df["x_coor"].to_numpy(),
                valid_df["y_coor"].to_numpy()
            )

            valid_df["lat"] = lat
            valid_df["lon"] = lon


            st.subheader("병원 위치")


            # 지도 중심 위치
            center_lat = valid_df["lat"].mean()
            center_lon = valid_df["lon"].mean()


            # 병원 위치 원 표시
            hospital_layer = pdk.Layer(
                "ScatterplotLayer",
                data=valid_df,
                get_position="[lon, lat]",
                get_radius=10,
                get_fill_color=[255, 0, 0, 160],
                get_line_color=[255, 0, 0],
                line_width_min_pixels=1,
                pickable=True,
                stroked=True,
                filled=True
                )

            # 지도 기본 위치
            view_state = pdk.ViewState(
                latitude=center_lat,
                longitude=center_lon,

                # 숫자가 클수록 확대
                zoom=12,

                pitch=0
            )


            # 지도 출력
            st.pydeck_chart(
                pdk.Deck(
                    layers=[
                        hospital_layer
                    ],

                    initial_view_state=view_state,

                    tooltip={
                        "html": """
                        <b>병원명:</b> {name}<br/>
                        <b>주소:</b> {new_address}
                        """,

                        "style": {
                            "backgroundColor": "black",
                            "color": "white"
                        }
                    }
                ),

                use_container_width=True
            )
