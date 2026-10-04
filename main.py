import os

from src.memory_limits import limit_native_memory

os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")
limit_native_memory()  # before torch is imported by the chatbot page

import streamlit as st

from src.ui import (
    NAVIGATION_GROUPS,
    apply_app_theme,
    render_footer,
    render_sidebar,
)

st.set_page_config(page_title="라그도그", page_icon=":material/pets:", layout="wide")
apply_app_theme()
render_sidebar()

navigation = {
    group["label"]: [
        st.Page(
            item["path"],
            title=item["title"],
            icon=item["icon"],
            default=item.get("default", False),
        )
        for item in group["items"]
    ]
    for group in NAVIGATION_GROUPS
}

pg = st.navigation(navigation)
pg.run()
render_footer()
