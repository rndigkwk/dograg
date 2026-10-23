import os

from src.memory_limits import block_torch_imports, limit_native_memory

os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")
limit_native_memory()  # before any native library starts its threads
block_torch_imports()  # the chatbot embeds with ONNX Runtime, not torch

from pathlib import Path

import streamlit as st

from src import settings

# P5 (2026-10-23): the old Streamlit address only points to the web app now, so a UI change is made
# once (Next.js). The pages stay in app_pages/ and come back with STREAMLIT_FULL_APP=1, e.g. to show
# the two front ends side by side after cutting the app's memory. The notice loads no data or model.
WEB_APP = "https://ragdog-rndigkwks-projects.vercel.app"
if not settings.setting_enabled("STREAMLIT_FULL_APP"):
    from src.ui import NAVIGATION_GROUPS

    st.set_page_config(page_title="라그도그", page_icon=":material/pets:")

    def moved_notice() -> None:
        st.title("🐾 라그도그가 새 주소로 옮겼어요")
        st.write("반려견 건강 상담, 동물병원·약국 찾기, 지역별 진료비, 방문 준비 보고서를 새 웹 앱에서 이어서 쓸 수 있어요. "
                 "로그인하면 대화와 반려견 정보도 그대로 이어집니다.")
        st.link_button("새 라그도그 열기", WEB_APP, type="primary")
        st.caption(f"새 주소: {WEB_APP}")

    # Every old page address (/rag, /hospital, ...) shows the same notice instead of "page not found".
    st.navigation([st.Page(moved_notice, title=item["title"], url_path=Path(item["path"]).stem,
                           default=item.get("default", False))
                   for group in NAVIGATION_GROUPS for item in group["items"]], position="hidden").run()
    st.stop()

from src import private_data
from src.conversation_ui import (
    render_conversation_sidebar,
    render_profile_sidebar,
    sync_conversations,
)
from src.ui import (
    NAVIGATION_GROUPS,
    apply_app_theme,
    render_footer,
    render_sidebar,
)

CHAT_PAGE = "app_pages/rag.py"

st.set_page_config(page_title="라그도그", page_icon=":material/pets:", layout="wide")
apply_app_theme()


@st.cache_resource(show_spinner="상담 데이터를 내려받고 있습니다(서버 시작 후 한 번)…")
def download_private_data() -> tuple[str, ...]:
    # AI Hub data may not be redistributed, so it is not in the public repository (src/private_data.py).
    return tuple(private_data.ensure())


if still_missing := download_private_data():
    download_private_data.clear()  # try again on the next visit (e.g. after HF_TOKEN is added)
    st.error("상담 데이터를 불러오지 못했습니다. 관리자가 `HF_TOKEN` 설정을 확인해야 합니다. "
             f"(없는 파일: {', '.join(still_missing)})")
    st.stop()

pages = {
    item["path"]: st.Page(
        item["path"],
        title=item["title"],
        icon=item["icon"],
        default=item.get("default", False),
    )
    for group in NAVIGATION_GROUPS
    for item in group["items"]
}
navigation = {
    group["label"]: [pages[item["path"]] for item in group["items"]]
    for group in NAVIGATION_GROUPS
}

pg = st.navigation(navigation)
# Stored conversations and the pet profile, on every page, right under the navigation.
session = sync_conversations()
render_conversation_sidebar(session, chat_page=pages[CHAT_PAGE])
render_profile_sidebar(session)
render_sidebar()
pg.run()
render_footer()
if session.pending_values() is not None:
    st.rerun()  # e.g. the storage notice was just shown on this page: save "seen" now, not on the next click
