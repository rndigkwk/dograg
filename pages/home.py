import base64
import os
from pathlib import Path

import requests
import streamlit as st

from src.ui import (
    HERO_IMAGE_SOURCES,
    HOME_STATS,
    apply_app_theme,
    next_hero_index,
    render_stat_cards,
)


os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")

AUTO_HERO_REFRESH_INTERVAL = "5s"
HOME_HERO_INDEX_KEY = "home_hero_index"
LOCAL_HERO_IMAGE = Path(__file__).with_name("hero_fallback.svg")
HERO_IMAGE_LABELS = (
    "따뜻한 반려동물의 하루",
    "함께 자라는 건강한 일상",
    "소중한 가족을 위한 돌봄",
)


@st.cache_data(show_spinner=False)
def fetch_remote_image(url: str) -> bytes | None:
    """Fetch a remote hero image once and return None when the network is unavailable."""
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        if not response.content:
            return None
        return response.content
    except requests.RequestException:
        return None


def load_hero_image(index: int) -> tuple[bytes, str]:
    """Load the selected image and fall back to the repository image if needed."""
    selected_url = HERO_IMAGE_SOURCES[index % len(HERO_IMAGE_SOURCES)]
    remote_image = fetch_remote_image(selected_url)
    if remote_image is not None:
        return remote_image, "image/jpeg"

    return LOCAL_HERO_IMAGE.read_bytes(), "image/svg+xml"


def as_data_uri(image_bytes: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def render_service_cards() -> None:
    services = (
        ("💬", "질병 문의", "반려견의 증상과 질병에 대해 근거 있는 정보를 확인해보세요."),
        ("📍", "지역별 동물 병원 찾기", "내 위치를 기준으로 가까운 동물병원을 빠르게 찾아보세요."),
        ("▥", "통계 대시보드", "반려동물 관련 최신 통계와 트렌드를 한눈에 살펴보세요."),
    )
    columns = st.columns(len(services))
    for column, (icon, title, body) in zip(columns, services):
        with column:
            st.markdown(
                f"""
                <div class="home-service-card">
                    <div class="home-service-card__icon">{icon}</div>
                    <div class="home-service-card__title">{title}</div>
                    <div class="home-service-card__body">{body}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


@st.fragment(run_every=AUTO_HERO_REFRESH_INTERVAL)
def render_auto_hero_image() -> None:
    hero_index = st.session_state.get(HOME_HERO_INDEX_KEY, 0)
    image_index = hero_index % len(HERO_IMAGE_SOURCES)
    image_bytes, mime_type = load_hero_image(image_index)
    image_uri = as_data_uri(image_bytes, mime_type)
    image_label = HERO_IMAGE_LABELS[image_index % len(HERO_IMAGE_LABELS)]

    st.markdown(
        f"""
        <div class="home-hero__visual">
            <img class="home-hero__image" src="{image_uri}" alt="반려동물 히어로 이미지">
            <div class="home-hero__image-meta">{image_label}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.session_state[HOME_HERO_INDEX_KEY] = next_hero_index(
        image_index,
        len(HERO_IMAGE_SOURCES),
    )


def render_home_page() -> None:
    apply_app_theme()

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if HOME_HERO_INDEX_KEY not in st.session_state:
        st.session_state[HOME_HERO_INDEX_KEY] = 0

    copy_column, image_column = st.columns([1.08, 0.92], gap="large")
    with copy_column:
        st.markdown(
            """
            <div class="home-hero__copy">
                <div class="page-kicker"><span class="page-kicker__dot"></span>반려동물 건강 정보 플랫폼</div>
                <h1 class="home-hero__title">반려동물의 건강,<br>데이터로 지키는 <span>따뜻한 동행</span></h1>
                <p class="home-hero__body">
                    라그도그는 반려견 보호자가 건강 정보를 찾고 가까운 동물 병원을
                    확인할 수 있도록 돕는 데이터 기반 반려동물 케어 서비스입니다.
                    591만 반려동물 가구 시대, 필요한 정보를 더 빠르게 확인해보세요.
                </p>
                <div class="home-hero__chips">
                    <span class="home-hero__chip">◷ 신뢰할 수 있는 데이터</span>
                    <span class="home-hero__chip">⌖ 지역 기반 맞춤 정보</span>
                    <span class="home-hero__chip">✦ 빠르고 쉬운 접근</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with image_column:
        render_auto_hero_image()

    render_stat_cards(
        list(HOME_STATS)
    )

    st.markdown('<div class="home-section-title">주요 서비스</div>', unsafe_allow_html=True)
    render_service_cards()
    st.caption("자료 출처: KB경영연구소 · 사이드바에서 원하는 화면을 선택해 자세한 정보를 확인해보세요.")


render_home_page()
