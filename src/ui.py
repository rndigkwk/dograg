"""Shared visual language for the PetCare Streamlit application."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st


NAVIGATION_GROUPS = (
    {
        "label": "소개 페이지",
        "items": (
            {"path": "app_pages/home.py", "title": "홈", "icon": "🏠", "default": True},
        ),
    },
    {
        "label": "데이터 둘러보기",
        "items": (
            {"path": "app_pages/data.py", "title": "데이터 소개", "icon": "📊"},
        ),
    },
    {
        "label": "서비스",
        "items": (
            {"path": "app_pages/rag.py", "title": "질병 문의", "icon": "💬"},
            {"path": "app_pages/hospital.py", "title": "시설 찾기", "icon": "🏥"},
            {"path": "app_pages/visit_prep.py", "title": "방문 준비 보고서", "icon": "📝"},
        ),
    },
)


HERO_IMAGE_SOURCES = (
    "https://images.unsplash.com/photo-1552053831-71594a27632d?auto=format&fit=crop&w=1200&q=88",
    "https://images.unsplash.com/photo-1517849845537-4d257902454a?auto=format&fit=crop&w=1200&q=88",
    "https://images.unsplash.com/photo-1548199973-03cce0bbc87b?auto=format&fit=crop&w=1200&q=88",
)


HOME_STATS = (
    {"label": "반려동물 가구", "value": "591만 가구", "detail": "전체 가구 중 26.7%"},
    {"label": "반려견", "value": "546만 마리", "detail": "건강 정보가 필요한 가족"},
)


APP_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700;800&display=swap');

:root {
    --ink: #17233f;
    --muted: #66728d;
    --soft-muted: #8a94aa;
    --line: #e9eaf5;
    --surface: #ffffff;
    --surface-soft: #f8f8ff;
    --brand-purple: #7b61ff;
    --brand-purple-dark: #5943d8;
    --brand-lilac: #eeebff;
    --brand-blue: #eef4ff;
    --accent-mint: #d9f5e9;
    --accent-yellow: #fff0bd;
    --shadow: 0 16px 44px rgba(40, 50, 91, 0.08);
}

html, body, [class*="css"] {
    font-family: "Noto Sans KR", "Pretendard", "Apple SD Gothic Neo", sans-serif;
    color: var(--ink);
}

[data-testid="stAppViewContainer"],
[data-testid="stMain"],
[data-testid="stMain"] [data-testid="stMarkdownContainer"],
[data-testid="stMain"] [data-testid="stCaptionContainer"],
[data-testid="stMain"] label {
    color: var(--ink) !important;
}

[data-testid="stMain"] [data-testid="stMarkdownContainer"] p,
[data-testid="stMain"] [data-testid="stMarkdownContainer"] li,
[data-testid="stMain"] [data-testid="stMarkdownContainer"] strong,
[data-testid="stMain"] [data-testid="stCaptionContainer"] p,
[data-testid="stMain"] h1,
[data-testid="stMain"] h2,
[data-testid="stMain"] h3,
[data-testid="stMain"] h4 {
    color: var(--ink) !important;
}

[data-testid="stMain"] [data-testid="stMarkdownContainer"] * {
    color: var(--ink) !important;
}

[data-testid="stMain"] [data-testid="stCaptionContainer"] * {
    color: var(--muted) !important;
}

[data-testid="stAppViewContainer"] {
    background:
        radial-gradient(circle at 78% 5%, rgba(232, 228, 255, 0.68), transparent 25rem),
        linear-gradient(135deg, #ffffff 0%, #fbfbff 53%, #f6f8ff 100%);
}

[data-testid="stHeader"] {
    background: transparent;
}

[data-testid="stMainBlockContainer"] {
    max-width: 1280px;
    padding-top: 3.2rem;
    padding-bottom: 5rem;
}

[data-testid="stSidebar"] {
    background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.96) 0%, rgba(249, 250, 255, 0.96) 100%);
    border-right: 1px solid var(--line);
}

[data-testid="stSidebar"] > div:first-child {
    padding: 1.65rem 1.05rem 1.2rem;
}

[data-testid="stSidebarNav"] {
    padding: 1.1rem 0.15rem 0.8rem;
}

[data-testid="stSidebarNav"] ul {
    gap: 0.35rem;
}

[data-testid="stSidebarNav"] li div {
    border-radius: 14px;
    min-height: 2.8rem;
    color: var(--ink);
    font-weight: 600;
    transition: background 160ms ease, color 160ms ease, transform 160ms ease;
}

[data-testid="stSidebarNav"] li div:hover {
    background: var(--surface-soft);
    color: var(--brand-purple-dark);
    transform: translateX(2px);
}

[data-testid="stSidebarNav"] li div[aria-current="page"] {
    background: linear-gradient(90deg, #f0edff, #f8f6ff);
    color: var(--brand-purple-dark);
    box-shadow: inset 3px 0 0 var(--brand-purple);
}

[data-testid="stSidebarNav"] section > div:first-child {
    color: var(--soft-muted);
    font-size: 0.74rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.pet-brand {
    display: flex;
    align-items: center;
    gap: 0.78rem;
    margin-bottom: 1.15rem;
    padding: 0.85rem 0.75rem;
    border: 1px solid rgba(232, 228, 255, 0.95);
    border-radius: 18px;
    background:
        linear-gradient(145deg, rgba(255, 255, 255, 0.95), rgba(246, 244, 255, 0.95));
    box-shadow: 0 14px 30px rgba(52, 62, 112, 0.08);
}

.pet-brand__mark {
    display: grid;
    width: 2.75rem;
    height: 2.75rem;
    place-items: center;
    border-radius: 15px;
    background:
        radial-gradient(circle at 35% 28%, #ffffff 0 16%, transparent 17%),
        linear-gradient(145deg, #ffe9bd, #f6bd8c);
    box-shadow: 0 10px 22px rgba(239, 169, 113, 0.26);
    font-size: 1.38rem;
}

.pet-brand__name {
    color: var(--ink);
    font-size: 1.05rem;
    font-weight: 800;
    letter-spacing: -0.04em;
}

.pet-brand__sub {
    margin-top: 0.1rem;
    color: var(--soft-muted);
    font-size: 0.7rem;
    font-weight: 600;
}

.sidebar-status {
    display: inline-flex;
    align-items: center;
    gap: 0.36rem;
    margin: 0 0.75rem 0.95rem;
    padding: 0.34rem 0.62rem;
    border: 1px solid #d8efe6;
    border-radius: 999px;
    background: #eefaf5;
    color: #277354;
    font-size: 0.68rem;
    font-weight: 800;
}

.sidebar-status__dot {
    width: 0.44rem;
    height: 0.44rem;
    border-radius: 999px;
    background: #37c785;
    box-shadow: 0 0 0 4px rgba(55, 199, 133, 0.16);
}

.sidebar-metrics {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.55rem;
    margin: 0 0.1rem 1.2rem;
}

.sidebar-metric {
    min-height: 4.1rem;
    padding: 0.82rem 0.72rem;
    border: 1px solid #ecebfa;
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.86);
}

.sidebar-metric__value {
    color: var(--ink);
    font-size: 0.9rem;
    font-weight: 850;
}

.sidebar-metric__label {
    margin-top: 0.24rem;
    color: var(--soft-muted);
    font-size: 0.66rem;
    font-weight: 700;
}

.sidebar-note {
    position: relative;
    overflow: hidden;
    margin: 1.25rem 0.1rem 0.35rem;
    padding: 1.15rem 1rem 1rem;
    border: 1px solid #e8e4ff;
    border-radius: 16px;
    background:
        linear-gradient(145deg, #ffffff 0%, #f8f7ff 62%, #fff8dc 100%);
    box-shadow: 0 14px 30px rgba(52, 62, 112, 0.07);
}

.sidebar-note::after {
    content: "";
    position: absolute;
    right: -1.9rem;
    bottom: -1.9rem;
    width: 5rem;
    height: 5rem;
    border-radius: 50%;
    background: rgba(217, 245, 233, 0.82);
}

.sidebar-note__title {
    position: relative;
    z-index: 1;
    color: var(--ink);
    font-size: 0.88rem;
    font-weight: 800;
    line-height: 1.45;
}

.sidebar-note__body {
    position: relative;
    z-index: 1;
    margin-top: 0.5rem;
    color: var(--muted);
    font-size: 0.72rem;
    line-height: 1.65;
}

.sidebar-note__tag {
    position: relative;
    z-index: 1;
    display: inline-flex;
    margin-top: 0.78rem;
    padding: 0.34rem 0.58rem;
    border-radius: 999px;
    background: rgba(123, 97, 255, 0.1);
    color: var(--brand-purple-dark);
    font-size: 0.66rem;
    font-weight: 800;
}

.page-kicker {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    margin-bottom: 0.9rem;
    padding: 0.5rem 0.78rem;
    border: 1px solid #e8e4ff;
    border-radius: 999px;
    background: rgba(246, 244, 255, 0.92);
    color: var(--brand-purple-dark);
    font-size: 0.78rem;
    font-weight: 700;
}

.page-kicker__dot {
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    background: var(--brand-purple);
    box-shadow: 0 0 0 4px #e9e5ff;
}

.page-header {
    margin-bottom: 2.1rem;
}

.page-header h1 {
    max-width: 820px;
    margin: 0;
    color: var(--ink);
    font-size: clamp(2rem, 4vw, 3.45rem);
    font-weight: 800;
    letter-spacing: -0.075em;
    line-height: 1.18;
}

.page-header__accent {
    display: block;
    margin-top: 0.55rem;
    color: var(--brand-purple);
    font-size: 1.02rem;
    font-weight: 700;
    letter-spacing: 0;
    line-height: 1.55;
}

.page-header p {
    max-width: 720px;
    margin: 1rem 0 0;
    color: var(--muted);
    font-size: 0.98rem;
    line-height: 1.8;
    white-space: pre-line;
}

.surface-card,
[data-testid="stExpander"],
[data-testid="stDataFrame"] {
    border: 1px solid var(--line);
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.9);
    box-shadow: var(--shadow);
}

[data-testid="stExpander"] {
    overflow: hidden;
}

[data-testid="stTabs"] button {
    color: var(--muted);
    font-weight: 700;
}

[data-testid="stTabs"] button[aria-selected="true"] {
    color: var(--brand-purple-dark);
}

[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
    background-color: var(--brand-purple);
}

[data-baseweb="select"] > div,
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stChatInput"] {
    border-color: var(--line);
    border-radius: 13px;
    background: rgba(255, 255, 255, 0.96);
}

[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stChatInput"] input,
[data-testid="stChatInput"] textarea {
    color: #17233f !important;
    -webkit-text-fill-color: #17233f !important;
    caret-color: #5943d8 !important;
}

[data-testid="stChatInputTextArea"] {
    color: #17233f !important;
    -webkit-text-fill-color: #17233f !important;
    caret-color: #5943d8 !important;
}

html body textarea[data-testid="stChatInputTextArea"] {
    color: #17233f !important;
    -webkit-text-fill-color: #17233f !important;
    caret-color: #5943d8 !important;
}

[data-testid="stChatInput"] input::placeholder,
[data-testid="stChatInput"] textarea::placeholder {
    color: #66728d !important;
    -webkit-text-fill-color: #66728d !important;
    opacity: 1 !important;
}

[data-testid="stButton"] button {
    border: 0;
    border-radius: 12px;
    background: linear-gradient(135deg, var(--brand-purple), #9885ff);
    color: #ffffff;
    font-weight: 800;
    box-shadow: 0 9px 18px rgba(123, 97, 255, 0.22);
}

[data-testid="stButton"] button:hover {
    border: 0;
    background: linear-gradient(135deg, var(--brand-purple-dark), var(--brand-purple));
    color: #ffffff;
}

[data-testid="stAlert"] {
    border-radius: 14px;
}

[data-testid="stChatMessage"] {
    border: 1px solid var(--line);
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.82);
}

.stat-card {
    min-height: 8.6rem;
    padding: 1.25rem 1.3rem;
    border: 1px solid var(--line);
    border-radius: 18px;
    background: linear-gradient(145deg, #ffffff, #fafaff);
    box-shadow: var(--shadow);
}

.stat-card__label {
    color: var(--muted);
    font-size: 0.78rem;
    font-weight: 700;
}

.stat-card__value {
    margin-top: 0.45rem;
    color: var(--ink);
    font-size: 1.65rem;
    font-weight: 800;
    letter-spacing: -0.06em;
}

.stat-card__detail {
    margin-top: 0.2rem;
    color: var(--soft-muted);
    font-size: 0.74rem;
}

.service-card {
    min-height: 9rem;
    padding: 1.15rem 1.2rem;
    border: 1px solid var(--line);
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.8);
    transition: transform 160ms ease, box-shadow 160ms ease;
}

.service-card:hover {
    transform: translateY(-3px);
    box-shadow: var(--shadow);
}

.service-card__icon {
    display: inline-grid;
    width: 2.2rem;
    height: 2.2rem;
    place-items: center;
    border-radius: 11px;
    background: var(--brand-lilac);
    color: var(--brand-purple-dark);
    font-size: 1.15rem;
}

.service-card__title {
    margin-top: 0.75rem;
    color: var(--ink);
    font-size: 0.93rem;
    font-weight: 800;
}

.service-card__body {
    margin-top: 0.35rem;
    color: var(--muted);
    font-size: 0.75rem;
    line-height: 1.55;
}

.app-footer {
    margin-top: 4rem;
    padding-top: 1.3rem;
    border-top: 1px solid var(--line);
    color: var(--soft-muted);
    font-size: 0.72rem;
    text-align: center;
}

.home-hero {
    display: grid;
    grid-template-columns: minmax(0, 1.08fr) minmax(20rem, 0.92fr);
    gap: 2.5rem;
    align-items: center;
    margin: 0 0 2.4rem;
}

.home-hero__copy {
    padding: 0.4rem 0;
}

.home-hero__title {
    margin: 0;
    color: var(--ink);
    font-size: clamp(2.3rem, 5vw, 4.25rem);
    font-weight: 800;
    letter-spacing: -0.085em;
    line-height: 1.16;
}

.home-hero__title span {
    color: var(--brand-purple);
}

.home-hero__body {
    max-width: 38rem;
    margin: 1.25rem 0 0;
    color: var(--muted);
    font-size: 1rem;
    line-height: 1.85;
}

.home-hero__chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.55rem;
    margin-top: 1.45rem;
}

.home-hero__chip {
    padding: 0.58rem 0.78rem;
    border: 1px solid #ebe9fa;
    border-radius: 12px;
    background: rgba(247, 246, 255, 0.94);
    color: var(--brand-purple-dark);
    font-size: 0.76rem;
    font-weight: 700;
}

.home-hero__visual {
    position: relative;
    min-height: 24rem;
    padding: 1rem;
    overflow: hidden;
    border: 1px solid #ebe9fa;
    border-radius: 28px;
    background:
        radial-gradient(circle at 22% 18%, rgba(255, 255, 255, 0.95), transparent 4rem),
        linear-gradient(145deg, #f3f0ff, #e7ecff);
    box-shadow: 0 24px 60px rgba(73, 72, 139, 0.14);
}

.home-hero__visual::before,
.home-hero__visual::after {
    position: absolute;
    z-index: 0;
    width: 6rem;
    height: 6rem;
    border: 1px dashed rgba(123, 97, 255, 0.22);
    border-radius: 50%;
    content: "";
}

.home-hero__visual::before {
    top: 1.2rem;
    right: 1.4rem;
}

.home-hero__visual::after {
    bottom: -2rem;
    left: -1.4rem;
}

.home-hero__image {
    position: relative;
    z-index: 1;
    display: block;
    width: 100%;
    height: 22rem;
    object-fit: cover;
    border-radius: 20px;
    box-shadow: 0 16px 34px rgba(62, 60, 112, 0.18);
}

.home-hero__image-meta {
    position: absolute;
    right: 1.7rem;
    bottom: 1.7rem;
    z-index: 2;
    padding: 0.5rem 0.72rem;
    border: 1px solid rgba(255, 255, 255, 0.72);
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.84);
    color: var(--ink);
    font-size: 0.7rem;
    font-weight: 800;
    backdrop-filter: blur(12px);
}

.home-hero__control {
    display: flex;
    justify-content: flex-end;
    margin-top: 0.7rem;
}

.home-section-title {
    margin: 2.1rem 0 0.9rem;
    color: var(--ink);
    font-size: 1.2rem;
    font-weight: 800;
    letter-spacing: -0.04em;
}

.home-service-card {
    min-height: 8.7rem;
    padding: 1.2rem;
    border: 1px solid var(--line);
    border-radius: 18px;
    background: rgba(255, 255, 255, 0.82);
    box-shadow: 0 12px 32px rgba(40, 50, 91, 0.06);
}

.home-service-card__icon {
    display: inline-grid;
    width: 2.35rem;
    height: 2.35rem;
    place-items: center;
    border-radius: 12px;
    background: var(--brand-lilac);
    color: var(--brand-purple-dark);
    font-size: 1.2rem;
}

.home-service-card__title {
    margin-top: 0.75rem;
    color: var(--ink);
    font-size: 0.92rem;
    font-weight: 800;
}

.home-service-card__body {
    margin-top: 0.35rem;
    color: var(--muted);
    font-size: 0.74rem;
    line-height: 1.55;
}

@media (max-width: 900px) {
    .home-hero {
        grid-template-columns: 1fr;
        gap: 1.4rem;
    }

    .home-hero__visual {
        min-height: 18rem;
    }

    .home-hero__image {
        height: 18rem;
    }
}

@media (max-width: 800px) {
    [data-testid="stMainBlockContainer"] {
        padding-top: 1.6rem;
    }

    .page-header h1 {
        font-size: 2.25rem;
    }
}
</style>
"""


def plain_tildes(text: str) -> str:
    """Model and table text for st.markdown/st.write with "~" shown as written.

    Streamlit's Markdown reads a single "~" pair as strikethrough, so a range written twice in one
    paragraph ("15,000~110,000원 ... 5,000~50,000원") lost both tildes and struck out the text
    between them (visit report on the deployed app, 2026-10-10)."""
    return str(text).replace("~", "\\~")


def _resolve_streamlit(st_module: Any | None) -> Any:
    return st if st_module is None else st_module


def next_hero_index(current_index: int, total_items: int) -> int:
    """Return the next image index while safely handling an empty collection."""
    if total_items <= 0:
        return 0
    return (current_index + 1) % total_items


def apply_app_theme(st_module: Any | None = None) -> None:
    """Inject the shared CSS theme into the current Streamlit page."""
    _resolve_streamlit(st_module).markdown(APP_CSS, unsafe_allow_html=True)


def render_sidebar(st_module: Any | None = None) -> None:
    """Render the shared brand block and supportive sidebar card."""
    streamlit = _resolve_streamlit(st_module)
    streamlit.sidebar.markdown(
        """
        <div class="pet-brand">
            <div class="pet-brand__mark">🐾</div>
            <div>
                <div class="pet-brand__name">라그도그</div>
                <div class="pet-brand__sub">반려동물 건강 정보 플랫폼</div>
            </div>
        </div>
        <div class="sidebar-status">
            <span class="sidebar-status__dot"></span>
            데이터 기반 상담 준비 완료
        </div>
        <div class="sidebar-metrics">
            <div class="sidebar-metric">
                <div class="sidebar-metric__value">591만</div>
                <div class="sidebar-metric__label">반려동물 가구</div>
            </div>
            <div class="sidebar-metric">
                <div class="sidebar-metric__value">546만</div>
                <div class="sidebar-metric__label">반려견</div>
            </div>
        </div>
        <div class="sidebar-note">
            <div class="sidebar-note__title">반려동물의 건강한 삶을 위한 첫걸음</div>
            <div class="sidebar-note__body">증상 정보, 병원 위치, 반려동물 통계를 한곳에서 확인합니다.</div>
            <span class="sidebar-note__tag">PetCare AI</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_page_header(
    title: str,
    *,
    eyebrow: str = "반려동물 건강 정보 플랫폼",
    description: str = "데이터를 바탕으로 반려동물의 건강한 일상을 함께 살펴봅니다.",
    accent: str | None = None,
    st_module: Any | None = None,
) -> None:
    """Render a consistent page header with the product's visual hierarchy."""
    streamlit = _resolve_streamlit(st_module)
    safe_eyebrow = escape(eyebrow)
    safe_title = escape(title)
    safe_description = escape(description)
    accent_markup = (
        f'<div class="page-header__accent">{escape(accent)}</div>'
        if accent
        else ""
    )
    streamlit.markdown(
        f"""
        <div class="page-header">
            <div class="page-kicker"><span class="page-kicker__dot"></span>{safe_eyebrow}</div>
            <h1>{safe_title}</h1>
            {accent_markup}
            <p>{safe_description}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_stat_cards(stats: list[dict[str, str]], st_module: Any | None = None) -> None:
    """Render compact metric cards for overview pages."""
    streamlit = _resolve_streamlit(st_module)
    columns = streamlit.columns(len(stats))
    for column, stat in zip(columns, stats):
        with column:
            streamlit.markdown(
                f"""
                <div class="stat-card">
                    <div class="stat-card__label">{escape(stat['label'])}</div>
                    <div class="stat-card__value">{escape(stat['value'])}</div>
                    <div class="stat-card__detail">{escape(stat.get('detail', ''))}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_footer(st_module: Any | None = None) -> None:
    """Render the small product footer shared by all pages."""
    _resolve_streamlit(st_module).markdown(
        '<div class="app-footer">🐾 라그도그 · 데이터와 기술로 더 나은 반려동물 케어를 만듭니다.</div>',
        unsafe_allow_html=True,
    )
