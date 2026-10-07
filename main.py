import os

from src.memory_limits import block_torch_imports, limit_native_memory

os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")
limit_native_memory()  # before any native library starts its threads
block_torch_imports()  # the chatbot embeds with ONNX Runtime, not torch

import streamlit as st

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
