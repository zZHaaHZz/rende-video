"""
app/ui/tab_creative.py — Creative Studio Tab UI
"""
import streamlit as st

def render_creative_tab(
    _CREATIVE_OK, _creative,
    call_ai=None, parse_json_robust=None, FFMPEG="ffmpeg",
    _veo3=None, _VEO3_OK=False, cfg=None,
    **kw,
):
    """Render Creative Studio tab."""
    if _CREATIVE_OK and _creative:
        try:
            _creative.render_creative_studio(
                call_ai, parse_json_robust, FFMPEG,
                veo_engine=_veo3 if _VEO3_OK else None,
                cfg=cfg or {},
            )
        except Exception as e:
            st.error(f"❌ Creative Studio lỗi: {e}")
    else:
        st.info("🎨 Creative Studio chưa load được. Kiểm tra file `creative_studio.py`.")
