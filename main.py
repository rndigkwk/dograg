import os

from src.memory_limits import block_torch_imports, limit_native_memory

os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")
limit_native_memory()  # before any native library starts its threads
block_torch_imports()  # the chatbot embeds with ONNX Runtime, not torch

import streamlit as st

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
