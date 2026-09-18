"""
app/project.py — Project state: load/save project JSON, get_proj_file.
Phụ thuộc vào app.config (atomic JSON write).
"""
import json
from pathlib import Path

import streamlit as st

from app.config import _atomic_json_write


def get_proj_file() -> Path:
    mode = st.session_state.get("proj_mode", "main")
    if mode == "veo3":
        return Path.home() / ".avc_project_veo3.json"
    return Path.home() / (".avc_project_shorts.json" if mode == "shorts" else ".avc_project.json")


def load_proj() -> dict:
    pf = get_proj_file()
    if pf.exists():
        try:
            return json.loads(pf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[project] Cannot read {pf}: {exc}")
    return {"script": None, "scenes": [], "step": 0}


def save_proj(p: dict):
    pf = get_proj_file()
    _atomic_json_write(pf, p, ensure_ascii=False)
