"""
app/ui/tab_settings.py — Settings Tab UI
Auto-generated from tool.py — wraps original tab body into a render function.
"""
import asyncio, json, os, re, uuid, base64, subprocess, shutil, time, tempfile, random, math
from typing import Optional
from pathlib import Path
import streamlit as st

def render_settings_tab(cfg, save_cfg, _VEO3_OK, _veo3, _SOCIAL_PUBLISHING_OK, _SOCIAL_STORE, render_connection_settings, reset_groq_cache, ENV_FILE, FFMPEG):
    """Render Settings tab."""
    # ── Ensure stdlib imports available (Streamlit hot-reload safe) ──────────
    import asyncio, json, os, re, uuid, base64, subprocess, shutil, time, tempfile, random, math
    from pathlib import Path
    from typing import Optional

    st.header("⚙️ API Keys")
    st.caption(f"API keys được lưu cục bộ trong file `{ENV_FILE}` (không commit lên Git).")
    changed = False

    if _SOCIAL_PUBLISHING_OK:
        render_connection_settings(st, _SOCIAL_STORE)
    else:
        st.warning("Module xuất bản chưa tải được. Xem terminal để biết lỗi cấu hình.")

    st.subheader("✨ Gemini Keys")
    new_g = st.text_input("Thêm Gemini key", placeholder="AIza... hoặc AQ...", type="password", key="g_in")
    if st.button("➕ Thêm Gemini") and new_g.strip():
        cfg.setdefault("gemini", []).append(new_g.strip()); changed = True
    for i, k in enumerate(cfg.get("gemini", [])):
        c1, c2 = st.columns([5,1])
        c1.code(k[:8] + "..." + k[-4:])
        if c2.button("✕", key=f"dg{i}"): cfg["gemini"].pop(i); changed = True

    st.subheader("⚡ Groq Keys (LLM + TTS)")
    new_q = st.text_input("Thêm Groq key", placeholder="gsk_...", type="password", key="q_in")
    if st.button("➕ Thêm Groq") and new_q.strip():
        cfg.setdefault("groq", []).append(new_q.strip()); changed = True; reset_groq_cache()
    for i, k in enumerate(cfg.get("groq", [])):
        c1, c2 = st.columns([5,1])
        c1.code(k[:8] + "..." + k[-4:])
        if c2.button("✕", key=f"dq{i}"): cfg["groq"].pop(i); changed = True; reset_groq_cache()

    st.subheader("🎥 Pexels Keys (footage CC0)")
    new_p = st.text_input("Thêm Pexels key", placeholder="Pexels API key...", type="password", key="p_in")
    if st.button("➕ Thêm Pexels") and new_p.strip():
        cfg.setdefault("pexels", []).append(new_p.strip()); changed = True
    for i, k in enumerate(cfg.get("pexels", [])):
        c1, c2 = st.columns([5,1])
        c1.code(k[:8] + "..." + k[-4:])
        if c2.button("✕", key=f"dp{i}"): cfg["pexels"].pop(i); changed = True

    st.subheader("🎵 Pixabay Key (nhạc nền - tùy chọn)")
    pix = st.text_input("Pixabay key", value=cfg.get("pixabay",""), type="password", key="pix_in")
    if pix != cfg.get("pixabay",""): cfg["pixabay"] = pix; changed = True

    st.subheader("🎬 Coverr (Free — Không cần API key)")
    st.success("✅ Coverr.co đã được tích hợp sẵn — không cần cấu hình gì!")
    st.caption("Hàng nghìn video stock 16:9 & 9:16 miễn phí, tự động dùng khi Pexels/Pixabay hết kết quả.")

    st.divider()
    used_count = len(cfg.get("used_videos", []))
    st.markdown(f"**🗂️ Lịch sử video đã dùng:** `{used_count}` URL (tránh lặp lại)")
    st.caption("Hệ thống tự động tránh dùng lại video cũ. Xóa lịch sử nếu muốn cho phép dùng lại.")
    if st.button(f"🗑️ Xóa lịch sử video đã dùng ({used_count})", type="secondary"):
        cfg["used_videos"] = []
        save_cfg(cfg)
        st.success("✅ Đã xóa lịch sử! Hệ thống sẽ có thể dùng lại video cũ.")
        st.rerun()

    st.subheader("🎨 OpenAI Key (DALL-E 3 Thumbnail)")
    st.caption("Dùng để tạo kịch bản AI + thumbnail DALL-E 3. Lấy key tại platform.openai.com/api-keys")
    oai = st.text_input("OpenAI key (dùng cho cả script + thumbnail)", value=cfg.get("openai",""), placeholder="sk-...", type="password", key="oai_in")
    if oai != cfg.get("openai",""): cfg["openai"] = oai; changed = True

    # ── VEO3 AI VIDEO GENERATION ─────────────────────────────────────────────
    st.divider()
    st.subheader("🤖 Veo3 AI Video Generation (Google)")
    st.caption(
        "Generate video AI cho từng scene bằng Google Veo3 thay vì stock footage.  \n"
        "Dùng chung Gemini API key ở trên — không cần key riêng.  \n"
        "⚠️ Mỗi video mất ~60–120s và tiêu tốn quota. Dùng chế độ **Fallback** nếu chưa chắc."
    )

    _veo3_provider = st.radio(
        "🔌 Nguồn tạo video",
        options=["stock", "gemini_web", "api", "google_flow"],
        format_func=lambda value: {
            "stock": "Stock/ảnh — không tạo Veo, không tốn credit",
            "gemini_web": "Gemini Web — KHÔNG gọi API, dùng gói Pro/Ultra",
            "api": "Veo API — tự động hoàn toàn, CÓ dùng API credit",
            "google_flow": "Google Flow (UseAPI) — tạo video tự động qua UseAPI.net",
        }[value],
        index=["stock", "gemini_web", "api", "google_flow"].index(cfg.get("veo3_provider", "stock") if cfg.get("veo3_provider", "stock") in ["stock", "gemini_web", "api", "google_flow"] else "stock"),
        horizontal=True,
        key="veo3_provider_radio",
    )
    if _veo3_provider != cfg.get("veo3_provider", "stock"):
        cfg["veo3_provider"] = _veo3_provider
        changed = True

    if _veo3_provider == "api":
        _veo3_enabled = st.toggle(
            "💳 Bật Veo API (sẽ tiêu tốn API credit)",
            value=cfg.get("veo3_enabled", False),
            key="veo3_toggle",
            help="Chỉ bật nếu bạn chấp nhận sử dụng credit của Gemini/Veo API",
        )
        if _veo3_enabled != cfg.get("veo3_enabled", False):
            cfg["veo3_enabled"] = _veo3_enabled
            changed = True
    elif _veo3_provider == "google_flow":
        _veo3_enabled = True
        if not cfg.get("veo3_enabled", False):
            cfg["veo3_enabled"] = True
            changed = True
    else:
        _veo3_enabled = False
        if cfg.get("veo3_enabled", False):
            cfg["veo3_enabled"] = False
            changed = True

    if _veo3_enabled or _veo3_provider == "gemini_web":

        if _veo3_provider == "google_flow":
            st.write("🔧 **Cấu hình Google Flow (UseAPI.net)**")
            useapi_tok = st.text_input("UseAPI.net API Token", value=cfg.get("useapi_token", ""), type="password", key="useapi_token_in", help="Lấy token tại api.useapi.net")
            if useapi_tok != cfg.get("useapi_token", ""):
                cfg["useapi_token"] = useapi_tok
                changed = True

            useapi_em = st.text_input("Google Flow Email (optional)", value=cfg.get("useapi_email", ""), placeholder="your_email@gmail.com", key="useapi_email_in", help="Email của account Google Flow. Để trống để tự động chọn account.")
            if useapi_em != cfg.get("useapi_email", ""):
                cfg["useapi_email"] = useapi_em
                changed = True

            useapi_mod = st.selectbox("Model", options=["veo-3.1-fast", "veo-3.1-quality", "veo-3.1-lite", "omni-flash"], index=["veo-3.1-fast", "veo-3.1-quality", "veo-3.1-lite", "omni-flash"].index(cfg.get("useapi_model", "veo-3.1-fast")), key="useapi_model_in")
            if useapi_mod != cfg.get("useapi_model", "veo-3.1-fast"):
                cfg["useapi_model"] = useapi_mod
                changed = True

        _veo3_mode = st.radio(
            "🎯 Chế độ Veo3/Flow",
            options=["fallback", "all"],
            format_func=lambda x: (
                {
                    "fallback": "🔄 Stock trước — chỉ chuẩn bị prompt khi thiếu footage",
                    "all": "🌐 All Scenes — chờ video sinh từ AI, không dùng Stock",
                } if _veo3_provider in ("gemini_web", "google_flow") else {
                    "fallback": "🔄 Fallback — chỉ gọi Veo API khi stock không có",
                    "all": "💳 All Scenes — mọi cảnh gọi Veo API và dùng credit",
                }
            ).get(x, x),
            index=0 if cfg.get("veo3_mode", "fallback") == "fallback" else 1,
            key="veo3_mode_radio",
            horizontal=True,
        )
        if _veo3_mode != cfg.get("veo3_mode", "fallback"):
            cfg["veo3_mode"] = _veo3_mode
            changed = True

        # Resolution (chỉ dùng cho api chính thức)
        if _veo3_provider != "google_flow":
            _veo3_res = st.radio(
                "🖥️ Resolution",
                options=["720p", "1080p", "4k"],
                index=["720p", "1080p", "4k"].index(cfg.get("veo3_resolution", "720p")),
                key="veo3_res_radio",
                horizontal=True,
                help="720p = nhanh hơn, tốn ít quota | 1080p/4k = chất lượng cao hơn, chậm hơn",
            )
            if _veo3_res != cfg.get("veo3_resolution", "720p"):
                cfg["veo3_resolution"] = _veo3_res
                changed = True

        if _veo3_provider == "gemini_web":
            st.info(
                "Gemini Web sẽ không gọi Veo API. App chuẩn bị prompt; bạn mở Gemini, "
                "tạo video, tải MP4 và nhập lại ngay trong editor từng cảnh."
            )

        _gem_keys = cfg.get("gemini", [])
        if _veo3_provider == "gemini_web":
            st.success("✅ Không cần Veo API key; dùng phiên đăng nhập Gemini trên trình duyệt.")
        elif _veo3_provider == "google_flow":
            if cfg.get("useapi_token"):
                st.success("✅ Sẵn sàng: Đã cấu hình UseAPI Token cho Google Flow.")
            else:
                st.error("❌ Chưa cấu hình UseAPI Token! Hãy điền token để sử dụng.")
        elif _gem_keys:
            st.success(f"✅ Sẵn sàng: {len(_gem_keys)} Gemini key(s) sẽ được thử lần lượt cho Veo3")
        else:
            st.error("❌ Chưa có Gemini key! Thêm Gemini key bên trên để dùng Veo3.")

        if _VEO3_OK:
            _cache_files = list(_veo3.VEO_CACHE_DIR.glob("*.mp4"))
            _cache_mb = sum(f.stat().st_size for f in _cache_files) / 1_000_000
            col_a, col_b = st.columns([3, 1])
            col_a.info(
                f"📁 Veo3 cache: `{len(_cache_files)}` video — `{_cache_mb:.1f}` MB  \n"
                f"   📂 `{_veo3.VEO_CACHE_DIR}`"
            )
            if col_b.button("🗑️ Xóa cache", type="secondary", key="veo3_clear"):
                for _cf in _cache_files:
                    _cf.unlink(missing_ok=True)
                st.success("✅ Đã xóa cache Veo3!")
                st.rerun()
        else:
            st.warning("⚠️ Module veo3_video chưa load — kiểm tra file veo3_video.py")

        st.markdown("**📋 Models theo thứ tự ưu tiên:**")
        st.code(
            "1. veo-3.1-fast-generate-preview  → Veo 3.1 Fast (Tốc độ cao)\n"
            "2. veo-3.1-generate-preview       → Veo 3.1 Standard (Chất lượng cao)\n"
            "3. veo-3.1-lite-generate-preview   → Veo 3.1 Lite (Nhẹ, ổn định)",
            language="text"
        )
        st.caption("💡 Tip: Veo3 mất 60–120s/video. Phải sử dụng API key trả phí (Paid Tier) có bật Billing mới chạy được Veo3.")

        if st.button("🔍 Kiểm tra Quyền & Quota Veo3 của các API key", key="check_veo3_keys"):
            st.session_state.veo3_check_results = []
            with st.spinner("Đang kiểm tra kết nối tới Google AI Studio..."):
                for ki, api_key in enumerate(_gem_keys):
                    res = _veo3.check_veo3_support(api_key)
                    st.session_state.veo3_check_results.append((ki+1, api_key[:8] + "...", res))
            st.rerun()

        # Hiển thị kết quả kiểm tra từ session state (nếu có)
        if "veo3_check_results" in st.session_state:
            st.markdown("### 📋 Kết quả kiểm tra:")
            for index_num, key_prefix, res in st.session_state.veo3_check_results:
                if res["ok"]:
                    if res["veo_supported"]:
                        st.success(f"🔑 Key {index_num} ({key_prefix}): Hoạt động tốt & có hỗ trợ Veo3!")
                    else:
                        st.warning(f"🔑 Key {index_num} ({key_prefix}): Kết nối được nhưng KHÔNG hỗ trợ Veo3 (Có thể là Key Free Tier hoặc tài khoản của bạn chưa kích hoạt billing/whitelist).")
                    with st.expander(f"Xem danh sách models được hỗ trợ của Key {index_num}"):
                        st.write(res["models"])
                else:
                    st.error(f"🔑 Key {index_num} ({key_prefix}) lỗi kết nối: {res['error']}")


    if changed:
        save_cfg(cfg)
        st.success("✅ Đã lưu!")

    st.divider()
    if not FFMPEG:
        st.error("❌ Không tìm thấy FFmpeg! Cài: `brew install ffmpeg`")
    else:
        st.success(f"✅ FFmpeg: `{FFMPEG}`")

    # ════════════════════════════════════════════════════════════
    # MAIN PIPELINE TAB
    # ════════════════════════════════════════════════════════════
