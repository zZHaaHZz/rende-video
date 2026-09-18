"""
app/ui/tab_publish.py — Publish Tab UI
"""
import streamlit as st
from pathlib import Path

def render_publish_tab(_SOCIAL_PUBLISHING_OK, _SOCIAL_STORE, render_social_publish_ui=None, **kw):
    """Render Publish tab."""
    if _SOCIAL_PUBLISHING_OK:
        # Gọi đúng function từ social_publisher_ui (không phải gọi chính mình)
        if render_social_publish_ui:
            render_social_publish_ui(st, _SOCIAL_STORE)
        else:
            try:
                from social_publisher_ui import render_publish_tab as _render_pub
                _render_pub(st, _SOCIAL_STORE)
            except Exception as e:
                st.error(f"❌ Không thể render publish UI: {e}")
    else:
        st.info("📢 Module xuất bản chưa được kết nối. Kiểm tra terminal để xem lỗi.")


