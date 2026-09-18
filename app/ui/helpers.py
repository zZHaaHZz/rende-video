"""
app/ui/helpers.py — Shared UI utilities dùng chung giữa các tab.
"""
import streamlit as st

from app.project import load_proj, save_proj


def save_and_next_scene(idx_val, n_text, n_kw, n_dur, n_mode, n_start=0.0):
    """Lưu scene hiện tại và chuyển sang scene tiếp theo."""
    proj = load_proj()
    if idx_val < len(proj.get("scenes", [])):
        proj["scenes"][idx_val]["text"] = n_text
        proj["scenes"][idx_val]["keyword"] = n_kw
        proj["scenes"][idx_val]["duration"] = n_dur
        proj["scenes"][idx_val]["videoTrimMode"] = n_mode
        if n_mode == "custom":
            proj["scenes"][idx_val]["videoTrimStart"] = n_start
        proj["scenes"][idx_val]["completed"] = True

        if idx_val < len(proj["scenes"]) - 1:
            st.session_state.selectbox_scene_active = idx_val + 1
            proj["active_scene_idx"] = idx_val + 1
        save_proj(proj)
