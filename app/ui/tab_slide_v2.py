"""
app/ui/tab_slide_v2.py — UI Tab cho Video Slide Renderer v2

2-Layer architecture:
  Layer 1 = video câm với xfade transitions
  Layer 2 = audio + ASS subtitle liên tục, không bị ảnh hưởng bởi transition
"""
import asyncio
import json
import os
import random
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

import streamlit as st


def render_slide_v2_tab(cfg: dict, save_cfg, FFMPEG: str, tts, TMP: Path, AUDIO_DIR: Path, **kw):
    """Render tab Video Slide v2."""
    from app.renderer_v2 import (
        SceneV2, RendererV2Options, render_video_v2, scene_from_dict,
        IMAGE_EFFECTS_V2, _SUB_STYLES,
    )

    st.header("🎞️ Video Slide v2 — 2-Layer Renderer")
    st.caption(
        "**Layer 1:** Video nền + xfade transitions (câm)  |  "
        "**Layer 2:** Audio TTS + Subtitle chạy liên tục — **không bao giờ lệch dù có transition**"
    )

    # ── Unpack helpers từ kw ──────────────────────────────────────────────────
    EDGE_VOICES  = kw.get("EDGE_VOICES", {})
    _ZEROTTS_OK  = kw.get("_ZEROTTS_OK", False)
    _zt          = kw.get("_zt", None)
    _CAPCUT_OK   = kw.get("_CAPCUT_OK", False)
    _cc          = kw.get("_cc", None)
    SUB_STYLES   = kw.get("SUB_STYLES", {"Default": {}})

    # ── Session state init ────────────────────────────────────────────────────
    if "sv2_scenes" not in st.session_state:
        st.session_state.sv2_scenes = []
    if "sv2_log" not in st.session_state:
        st.session_state.sv2_log = []
    if "sv2_output" not in st.session_state:
        st.session_state.sv2_output = ""
    if "sv2_proj_meta" not in st.session_state:
        st.session_state.sv2_proj_meta = {}
    if "sv2_tts_rate" not in st.session_state:
        st.session_state.sv2_tts_rate = "1.25"
    if "sv2_aspect" not in st.session_state:
        st.session_state.sv2_aspect = "9:16"

    # ── Helper: parse project JSON ────────────────────────────────────────────
    def _build_sv2_scenes_from_data(data):
        """Chuyển project JSON → list scene dict cho Slide v2."""
        if isinstance(data, dict):
            if "video_config" in data or "title" in data:
                st.session_state.sv2_proj_meta = {
                    "title":        data.get("title", ""),
                    "description":  data.get("description", ""),
                    "tags":         data.get("tags", []),
                    "video_config": data.get("video_config", {}),
                }
            raw = data.get("scenes", data)
        else:
            raw = data
        if not isinstance(raw, list):
            return []
        out = []
        for s in raw:
            dur = float(s.get("duration") or s.get("target_duration") or 0)
            out.append({
                "text":          s.get("text", ""),
                "audio_path":    s.get("audioPath") or s.get("audio_path") or "",
                "video_url":     s.get("videoUrl") or s.get("video_url") or "",
                "image_url":     s.get("imageUrl") or s.get("image_url") or "",
                "image_prompt":  s.get("imagePrompt") or s.get("image_prompt") or "",
                "veo3_prompt":   s.get("veo3_prompt") or s.get("veo3Prompt") or "",
                "onscreen_text": s.get("onscreen_text") or s.get("onscreenText") or "",
                "veo3_path":     s.get("veo3Path") or s.get("veo3_path") or "",
                "custom_vid":    s.get("customVid") or s.get("custom_vid") or "",
                "custom_img":    s.get("customImg") or s.get("custom_img") or "",
                "keyword":       s.get("keyword", ""),
                "duration":      dur,
                "words":         s.get("words", []) or [],
                "transition":    s.get("transition", "fade"),
                "effect":        s.get("effect") or s.get("imageEffect") or "",
                "section":       s.get("section", ""),
                "tts_speed":     float(s.get("tts_speed") or 1.0),
            })
        return out

    # ════════════════════════════════════════════════════════════════════════
    # ① NHẬP JSON KỊCH BẢN — giống hệt tab Video Ngắn
    # ════════════════════════════════════════════════════════════════════════
    st.subheader("① Nhập JSON kịch bản")
    sv2_json_raw = st.text_area(
        "Paste JSON:",
        height=180,
        placeholder=(
            '{"video_config":{"aspect_ratio":"9:16","tts_speed":1.25},'
            '"title":"...","scenes":[{"id":1,"text":"...","target_duration":5,'
            '"imagePrompt":"...","veo3_prompt":"...","transition":"fade"}]}'
        ),
        key="sv2_json_input",
    )

    _col_load, _col_pipeline, _col_clear = st.columns([2, 2, 1])
    with _col_load:
        if st.button("📥 Load JSON", key="sv2_btn_load",
                     use_container_width=True, type="primary"):
            try:
                _d = json.loads(sv2_json_raw)
                _built = _build_sv2_scenes_from_data(_d)
                if not _built:
                    st.error("❌ Không tìm thấy field 'scenes' trong JSON.")
                else:
                    st.session_state.sv2_scenes = _built
                    # Auto-fill aspect + tts_rate từ video_config
                    _vc = st.session_state.sv2_proj_meta.get("video_config", {})
                    _ar = _vc.get("aspect_ratio", "")
                    if _ar in ["9:16", "16:9", "1:1"]:
                        st.session_state.sv2_aspect = _ar
                    _spd = str(_vc.get("tts_speed") or _vc.get("tts_rate") or "")
                    _valid_spd = ["0.8","0.9","1.0","1.1","1.2","1.25","1.3","1.4","1.5","1.6","1.8","2.0"]
                    if _spd in _valid_spd:
                        st.session_state.sv2_tts_rate = _spd
                    st.session_state.sv2_log = []
                    st.session_state.sv2_output = ""
                    _tot = sum(float(s.get("duration") or s.get("target_duration") or 0) for s in _built)
                    st.success(f"✅ Đã load {len(_built)} cảnh — tổng ~{_tot:.1f}s")
                    st.rerun()
            except Exception as _e:
                st.error(f"❌ Lỗi parse JSON: {_e}")

    with _col_pipeline:
        # load_proj() = đọc file project .json đang mở ở tab Pipeline
        if st.button("📋 Lấy từ Pipeline", key="sv2_btn_pipeline",
                     use_container_width=True,
                     help="Lấy scenes từ project JSON đang mở ở tab Pipeline hiện tại"):
            _proj = kw.get("load_proj", lambda: {})()
            _raw  = _proj.get("scenes", [])
            if _raw:
                _extra = {k: _proj[k] for k in ["title","description","tags","video_config"] if k in _proj}
                _built2 = _build_sv2_scenes_from_data({"scenes": _raw, **_extra})
                st.session_state.sv2_scenes = _built2
                st.success(f"✅ Đã load {len(_built2)} cảnh từ Pipeline!")
                st.rerun()
            else:
                st.warning("⚠️ Pipeline chưa có cảnh nào. Hãy load project ở tab Pipeline trước.")

    with _col_clear:
        if st.button("🗑️ Xóa", key="sv2_btn_clear", use_container_width=True):
            st.session_state.sv2_scenes     = []
            st.session_state.sv2_proj_meta  = {}
            st.session_state.sv2_log        = []
            st.session_state.sv2_output     = ""
            st.rerun()

    scenes = st.session_state.sv2_scenes
    n_sv2  = len(scenes)

    # ── Bảng preview scenes ───────────────────────────────────────────────────
    if n_sv2 > 0:
        _meta = st.session_state.sv2_proj_meta
        if _meta.get("title"):
            st.caption(f"📌 **{_meta['title']}**")
            _vc2 = _meta.get("video_config", {})
            if _vc2:
                st.caption(
                    f"🎬 {_vc2.get('aspect_ratio','?')} · "
                    f"⏱ {_vc2.get('total_duration','?')}s · "
                    f"🗣 x{_vc2.get('tts_speed','?')} · "
                    f"🎨 {str(_vc2.get('style',''))[:60]}"
                )
        _total_dur2 = sum(float(s.get("duration") or s.get("target_duration") or 0) for s in scenes)
        with st.expander(f"📋 Preview {n_sv2} cảnh (tổng ~{_total_dur2:.1f}s)", expanded=True):
            st.dataframe(
                [{
                    "#": i + 1,
                    "Section":     s.get("section", "—"),
                    "Text (50ch)": str(s.get("text", ""))[:50],
                    "Dur (s)":     s.get("duration") or s.get("target_duration") or 0,
                    "Transition":  s.get("transition", "fade"),
                    "Effect":      s.get("effect") or "—",
                    "imagePrompt": "✅" if s.get("image_prompt") else "—",
                    "veo3Prompt":  "✅" if s.get("veo3_prompt") else "—",
                } for i, s in enumerate(scenes)],
                use_container_width=True,
                height=250,
            )

        st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # ③ UPLOAD ẢNH CHO CÁC CẢNH — giống hệt tab Video Ngắn
    # ══════════════════════════════════════════════════════════════════════════
    import re as _re
    sv2_img_map = {}   # default — sẽ được ghi đè nếu user upload ảnh

    def _sv2_scene_num(fname: str):
        m = _re.search(r'scene[_\-]?(\d+)', fname, _re.IGNORECASE)
        return int(m.group(1)) if m else None

    def _sv2_match_images(uploaded_files, n):
        result = {i: None for i in range(n)}
        no_num = []
        for f in uploaded_files:
            num = _sv2_scene_num(f.name)
            if num is not None:
                idx = num - 1
                if 0 <= idx < n:
                    result[idx] = f
            else:
                no_num.append(f)
        leftover = [i for i in range(n) if result[i] is None]
        for f, slot in zip(no_num, leftover):
            result[slot] = f
        return result

    if n_sv2 > 0:
        st.subheader("② Upload ảnh cho các cảnh")
        st.caption("Đặt tên file: `scene_001.jpg`, `scene_002.jpg`... Tool tự map đúng cảnh. File không đánh số sẽ map theo thứ tự.")

        if "sv2_img_uploader_key" not in st.session_state:
            st.session_state["sv2_img_uploader_key"] = 0

        _img_col1, _img_col2 = st.columns([6, 1])
        with _img_col1:
            sv2_uploaded_imgs = st.file_uploader(
                f"Upload ảnh ({n_sv2} cảnh — scene_NNN_...jpg):",
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True,
                key=f"sv2_img_uploader_{st.session_state['sv2_img_uploader_key']}",
            )
        with _img_col2:
            st.write("")
            st.write("")
            if st.button("🗑️ Xóa hết", key="sv2_clear_imgs",
                         help="Xóa toàn bộ ảnh đã upload", use_container_width=True):
                st.session_state["sv2_img_uploader_key"] += 1
                st.rerun()

        sv2_img_map = {}
        if sv2_uploaded_imgs:
            sv2_img_map = _sv2_match_images(sv2_uploaded_imgs, n_sv2)
            _matched   = sum(1 for v in sv2_img_map.values() if v is not None)
            _unmatched = n_sv2 - _matched
            st.success(f"✅ Khớp {_matched}/{n_sv2} cảnh với ảnh.")
            if _unmatched > 0:
                st.warning(f"⚠️ {_unmatched} cảnh chưa có ảnh → sẽ dùng image_prompt hoặc nền đen.")
            with st.expander("📌 Bảng phân phối ảnh → cảnh", expanded=False):
                st.dataframe(
                    [{
                        "Cảnh": i + 1,
                        "Text": str(scenes[i].get("text", ""))[:40],
                        "File ảnh": sv2_img_map[i].name if sv2_img_map.get(i) else "—",
                        "Status": "✅ Khớp" if sv2_img_map.get(i) else "⬛ Nền đen / prompt",
                    } for i in range(n_sv2)],
                    use_container_width=True,
                )
        else:
            sv2_img_map = {}
            st.info("ℹ️ Chưa upload ảnh → sẽ dùng image_prompt (Imagen 3) hoặc nền đen.")

        st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # Layout 2-column: danh sách cảnh chi tiết (left) + render panel (right)
    # ══════════════════════════════════════════════════════════════════════════
    col_left, col_right = st.columns([1, 1], gap="large")

    # ── LEFT: Danh sách cảnh chi tiết ────────────────────────────────────────
    with col_left:
        st.subheader(f"📋 Danh sách cảnh ({n_sv2})")

        # Upload file JSON / lấy từ Pipeline (nâng cao, đã có nút chính ở trên)
        with st.expander("📥 Import nâng cao (Upload file JSON)", expanded=False):
            uploaded = st.file_uploader(
                "Upload file project JSON",
                type=["json"],
                key="sv2_json_upload",
            )
            if uploaded:
                try:
                    data = json.loads(uploaded.read())
                    built = _build_sv2_scenes_from_data(data)
                    st.session_state.sv2_scenes = built
                    st.success(f"✅ Đã import {len(built)} cảnh!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi đọc JSON: {e}")

        # ── Thêm cảnh thủ công ────────────────────────────────────────────────
        with st.expander("➕ Thêm cảnh mới", expanded=False):
            new_text = st.text_area("Lời thoại", key="sv2_new_text", height=80)
            new_audio = st.text_input("Đường dẫn audio (.mp3/.wav)", key="sv2_new_audio",
                                       placeholder="/path/to/audio.mp3")
            new_vid = st.text_input("Video / Ảnh nền (URL hoặc path)", key="sv2_new_vid",
                                     placeholder="https://... hoặc /path/to/video.mp4")
            new_tr = st.selectbox("Transition sang cảnh tiếp", key="sv2_new_tr",
                options=["fade", "wipeleft", "wiperight", "wipeup", "wipedown",
                         "slideleft", "slideright", "slideup", "slidedown",
                         "circlecrop", "rectcrop", "distance", "fadeblack",
                         "fadewhite", "radial", "smoothleft", "smoothright",
                         "smoothup", "smoothdown", "pixelize", "diagtl",
                         "diagtr", "diagbl", "diagbr", "hlslice", "hrslice",
                         "vuslice", "vdslice", "dissolve", "squeezeh", "squeezev"])
            if st.button("➕ Thêm cảnh", key="sv2_add"):
                ext = Path(new_vid).suffix.lower() if new_vid else ""
                is_img = ext in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
                sc = {
                    "text": new_text.strip(),
                    "audio_path": new_audio.strip(),
                    "video_url": "" if is_img else new_vid.strip(),
                    "image_url": new_vid.strip() if is_img else "",
                    "image_prompt": "", "veo3_prompt": "", "onscreen_text": "",
                    "veo3_path": "", "custom_vid": "", "custom_img": "",
                    "keyword": "", "duration": 0.0, "words": [],
                    "transition": new_tr, "effect": "", "section": "", "tts_speed": 1.0,
                }
                st.session_state.sv2_scenes.append(sc)
                st.rerun()

        # ── Hiển thị danh sách cảnh ──────────────────────────────────────────
        if not scenes:
            st.info("Chưa có cảnh nào. Paste JSON ở trên hoặc thêm thủ công.")
        else:
            for i, sc in enumerate(scenes):
                has_audio  = bool(sc.get("audio_path") and Path(sc["audio_path"]).exists())
                has_visual = bool(
                    sc.get("veo3_path") or sc.get("custom_vid") or sc.get("custom_img")
                    or sc.get("video_url") or sc.get("image_url")
                )
                has_prompt = bool(sc.get("image_prompt") or sc.get("veo3_prompt"))
                icon_a = "🔊" if has_audio else "🔇"
                icon_v = "🎬" if has_visual else ("🖼️" if has_prompt else "⬛")
                label = f"Scene {i+1} {icon_a}{icon_v} — {sc.get('text','')[:50]}..."

                with st.expander(label, expanded=False):
                    c1, c2 = st.columns([4, 1])
                    new_txt = c1.text_area("Lời thoại", value=sc.get("text", ""),
                                            key=f"sv2_txt_{i}", height=70)
                    if new_txt != sc.get("text", ""):
                        st.session_state.sv2_scenes[i]["text"] = new_txt

                    new_ap = st.text_input("Audio path", value=sc.get("audio_path", ""),
                                            key=f"sv2_ap_{i}")
                    if new_ap != sc.get("audio_path", ""):
                        st.session_state.sv2_scenes[i]["audio_path"] = new_ap

                    new_vurl = st.text_input("Video/Ảnh URL hoặc path",
                                              value=sc.get("video_url") or sc.get("image_url", ""),
                                              key=f"sv2_vurl_{i}")
                    if new_vurl:
                        ext = Path(new_vurl).suffix.lower()
                        if ext in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
                            st.session_state.sv2_scenes[i]["image_url"] = new_vurl
                            st.session_state.sv2_scenes[i]["video_url"] = ""
                        else:
                            st.session_state.sv2_scenes[i]["video_url"] = new_vurl
                            st.session_state.sv2_scenes[i]["image_url"] = ""

                    _tr_opts = ["fade","wipeleft","wiperight","wipeup","wipedown",
                                "slideleft","slideright","slideup","slidedown",
                                "circlecrop","fadeblack","fadewhite","dissolve","pixelize"]
                    _tr_cur = sc.get("transition", "fade")
                    new_tr = st.selectbox("Transition", key=f"sv2_tr_{i}",
                        options=_tr_opts,
                        index=_tr_opts.index(_tr_cur) if _tr_cur in _tr_opts else 0,
                    )
                    if new_tr != sc.get("transition", "fade"):
                        st.session_state.sv2_scenes[i]["transition"] = new_tr

                    # Hiển thị prompts nếu có
                    if sc.get("image_prompt"):
                        st.caption(f"🖼️ **imagePrompt:** {sc['image_prompt'][:80]}...")
                    if sc.get("veo3_prompt"):
                        st.caption(f"🎥 **veo3Prompt:** {sc['veo3_prompt'][:80]}...")
                    if sc.get("onscreen_text"):
                        st.caption(f"📌 **onscreen:** {sc['onscreen_text']}")

                    if c2.button("🗑️", key=f"sv2_del_{i}", help="Xóa cảnh"):
                        st.session_state.sv2_scenes.pop(i)
                        st.rerun()

            _col_clr2 = st.columns(1)[0]
            if _col_clr2.button("🗑️ Xóa tất cả cảnh", key="sv2_clear_all", type="secondary"):
                st.session_state.sv2_scenes = []
                st.rerun()

    # ── RIGHT: Cấu hình render + kết quả ─────────────────────────────────────
    with col_right:
        st.subheader("⚙️ Cấu hình Render")

        # ── Giọng + Tốc độ TTS ────────────────────────────────────
        _rv1, _rv2 = st.columns(2)
        with _rv1:
            _voice_opts = []
            if _ZEROTTS_OK and _zt:
                try: _voice_opts.extend(_zt.list_display_voices())
                except Exception: pass
            if _CAPCUT_OK and _cc:
                try: _voice_opts.extend([k for k in _cc.CAPCUT_VOICES if "🆻🇳" in k])
                except Exception: pass
            _voice_opts.extend(list(EDGE_VOICES.keys()))
            if not _voice_opts: _voice_opts = ["vi-VN-NamMinhNeural"]
            _dv = "🆻🇳 Hà My — Nữ · Trẻ · Hoạt hình · Cao · Biểu cảm"
            sv2_voice = st.selectbox(
                "🎤 Giọng TTS:",
                options=_voice_opts,
                index=_voice_opts.index(_dv) if _dv in _voice_opts else 0,
                key="sv2_voice",
            )
        with _rv2:
            _sp = ["0.8","0.9","1.0","1.1","1.2","1.25","1.3","1.4","1.5","1.6","1.8","2.0"]
            _rc = st.session_state.sv2_tts_rate
            if _rc not in _sp: _rc = "1.25"
            sv2_tts_rate = st.selectbox(
                "⚡ Tốc độ TTS:", options=_sp,
                index=_sp.index(_rc), key="sv2_tts_rate_sel",
            )
            st.session_state.sv2_tts_rate = sv2_tts_rate

        st.divider()

        # ── Tỉ lệ + Chất lượng + FPS ────────────────────────────────────────
        _rr1, _rr2, _rr3 = st.columns(3)
        with _rr1:
            _asp_default = st.session_state.get("sv2_aspect", "9:16")
            if _asp_default not in ["9:16", "16:9", "1:1"]:
                _asp_default = "9:16"
            sv2_aspect_r = st.selectbox(
                "📐 Tỉ lệ khung hình:",
                options=["9:16", "16:9", "1:1"],
                index=["9:16", "16:9", "1:1"].index(_asp_default),
                key="sv2_aspect_render",
            )
            st.session_state.sv2_aspect = sv2_aspect_r
        with _rr2:
            sv2_quality = st.selectbox(
                "🖥️ Chất lượng:",
                options=["1080p", "720p", "4K (2160p)"],
                index=0,
                key="sv2_quality",
            )
        with _rr3:
            fps = st.select_slider("FPS", options=[24, 25, 30, 60], value=30, key="sv2_fps")

        # Tính W×H từ tỉ lệ + chất lượng
        _dim_map = {
            ("9:16",  "1080p"):      (1080, 1920),
            ("9:16",  "720p"):       (720,  1280),
            ("9:16",  "4K (2160p)"): (2160, 3840),
            ("16:9",  "1080p"):      (1920, 1080),
            ("16:9",  "720p"):       (1280, 720),
            ("16:9",  "4K (2160p)"): (3840, 2160),
            ("1:1",   "1080p"):      (1080, 1080),
            ("1:1",   "720p"):       (720,  720),
            ("1:1",   "4K (2160p)"): (2160, 2160),
        }
        W, H = _dim_map.get((sv2_aspect_r, sv2_quality), (1080, 1920))
        st.caption(f"→ Độ phân giải: **{W}×{H}**")

        col_xf, col_sub = st.columns(2)
        xfade_dur  = col_xf.slider("⏱ Transition duration (s)", 0.0, 2.0, 0.5, 0.05, key="sv2_xfade")
        sub_window = col_sub.slider("📝 Số từ / nhóm sub", 2, 6, 4, key="sv2_subwin")

        sub_style = st.selectbox(
            "🎨 Subtitle Style",
            list(_SUB_STYLES.keys()),
            key="sv2_substyle",
        )
        burn_sub = st.checkbox("🔥 Burn subtitle vào video", value=True, key="sv2_burnsub")

        st.divider()

        bgm_file_right = st.file_uploader(
            "🎵 Nhạc nền BGM (mp3/wav, tùy chọn):",
            type=["mp3", "wav", "m4a"],
            key="sv2_bgm_right",
        )
        bgm_vol = st.slider("🔊 BGM Volume", 0, 50, 12, key="sv2_bgmvol",
                             help="% volume nhạc nền so với TTS") / 100.0 if bgm_file_right else 0.12

        out_dir  = st.text_input("📁 Thư mục lưu output",
                                  value=str(Path.home() / "Desktop"),
                                  key="sv2_outdir")
        out_name = st.text_input("📄 Tên file output",
                                  value="slide_v2",
                                  key="sv2_outname")

        st.divider()

        crf        = st.slider("Chất lượng video (CRF)", 15, 35, 20, key="sv2_crf")
        preset_opt = st.select_slider("Tốc độ encode",
            options=["ultrafast","superfast","veryfast","faster","fast","medium"],
            value="fast", key="sv2_preset")

        st.divider()

        # ── Render button ─────────────────────────────────────────────────────
        n_scenes    = len(st.session_state.sv2_scenes)
        btn_disabled = n_scenes == 0
        btn_label   = f"🚀 Render {n_scenes} cảnh" if n_scenes > 0 else "🚀 Render (chưa có cảnh)"

        if st.button(btn_label, type="primary", disabled=btn_disabled,
                     use_container_width=True, key="sv2_render"):

            st.session_state.sv2_log    = []
            st.session_state.sv2_output = ""
            log_area = st.empty()
            progress = st.progress(0, text="⏳ Chuẩn bị...")

            def _log(msg: str):
                st.session_state.sv2_log.append(msg)
                log_area.text_area("📋 Log", "\n".join(st.session_state.sv2_log),
                                    height=250)

            _log(f"🎬 Bắt đầu render {n_scenes} cảnh — {W}x{H} @ {fps}fps")

            # Lưu BGM upload ra temp file nếu có
            bgm_path_str = ""
            _bgm_tmp = None
            if bgm_file_right:
                import tempfile
                _bgm_suffix = Path(bgm_file_right.name).suffix or ".mp3"
                _bgm_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=_bgm_suffix)
                _bgm_tmp.write(bgm_file_right.read())
                _bgm_tmp.close()
                bgm_path_str = _bgm_tmp.name
                _log(f"🎵 BGM: {bgm_file_right.name}")

            try:
                from app.renderer_v2 import SceneV2
                scene_objs = []
                for i, sc in enumerate(st.session_state.sv2_scenes):
                    _txt = sc.get("text", "").strip()

                    # ── Bước 1: Sinh audio TTS nếu chưa có ──────────────────
                    _audio_path = sc.get("audio_path", "")
                    _words      = sc.get("words", []) or []

                    if _txt and (not _audio_path or not Path(_audio_path).exists()):
                        progress.progress(
                            (i + 1) / n_scenes * 0.5,
                            text=f"🎙️ TTS scene {i+1}/{n_scenes}...",
                        )
                        _log(f"  🎙️ Scene {i+1}: sinh TTS...")
                        try:
                            # tts ở đây = _tts_wrapper, đã bind sẵn cfg/capcut/zerotts
                            _tts_result = tts(
                                text=_txt,
                                voice_cfg=sv2_voice,
                                rate=sv2_tts_rate,
                                allow_edge_fallback=True,
                            )
                            if isinstance(_tts_result, (list, tuple)) and len(_tts_result) >= 2:
                                _audio_path, _words = _tts_result[0], _tts_result[1]
                            else:
                                _audio_path = str(_tts_result)
                            st.session_state.sv2_scenes[i]["audio_path"] = _audio_path
                            st.session_state.sv2_scenes[i]["words"]      = _words or []
                            _log(f"    ✅ {Path(_audio_path).name}")
                        except Exception as _tts_err:
                            import traceback as _tb
                            _log(f"    ❌ TTS scene {i+1} lỗi: {_tts_err}")
                            _log(_tb.format_exc())

                    # ── Bước 2: Ảnh upload ưu tiên hơn image_url ────────────
                    _uploaded_f = sv2_img_map.get(i) if sv2_img_map else None
                    _img_path_tmp = ""
                    if _uploaded_f:
                        import tempfile
                        _img_ext = Path(_uploaded_f.name).suffix or ".jpg"
                        _img_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=_img_ext)
                        _img_tmp.write(_uploaded_f.read())
                        _img_tmp.close()
                        _img_path_tmp = _img_tmp.name
                        _log(f"  🖼️ Scene {i+1}: ảnh {_uploaded_f.name}")

                    scene_objs.append(SceneV2(
                        text=_txt,
                        audio_path=_audio_path,
                        video_url=sc.get("video_url", ""),
                        image_url=_img_path_tmp or sc.get("image_url", ""),
                        veo3_path=sc.get("veo3_path", ""),
                        custom_vid=sc.get("custom_vid", ""),
                        custom_img=sc.get("custom_img", ""),
                        keyword=sc.get("keyword", ""),
                        duration=float(sc.get("duration", 0) or 0),
                        words=_words or sc.get("words", []) or [],
                        transition=sc.get("transition", "fade"),
                        effect=sc.get("effect") or None,
                        sub_style=sub_style,
                    ))
                    progress.progress(
                        0.5 + (i + 1) / n_scenes * 0.1,
                        text=f"Chuẩn bị scene {i+1}/{n_scenes}...",
                    )

                opts = RendererV2Options(
                    width=W, height=H, fps=fps,
                    xfade_dur=xfade_dur,
                    crf=crf, preset=preset_opt,
                    audio_bitrate="192k",
                    burn_subtitles=burn_sub,
                    sub_style=sub_style,
                    sub_window=sub_window,
                    bgm_path=bgm_path_str,
                    bgm_volume=bgm_vol,
                    ffmpeg_bin=FFMPEG or "ffmpeg",
                    log_cb=_log,
                )

                out_dir_p = Path(out_dir.strip()) if out_dir.strip() else Path.home() / "Desktop"
                out_dir_p.mkdir(parents=True, exist_ok=True)
                stem = out_name.strip() or "slide_v2"
                out_path = out_dir_p / f"{stem}.mp4"
                n = 2
                while out_path.exists():
                    out_path = out_dir_p / f"{stem}_{n}.mp4"
                    n += 1

                progress.progress(0.12, text="🎬 Đang render (xem log)...")
                result = render_video_v2(scene_objs, out_path, opts)
                progress.progress(1.0, text="✅ Hoàn tất!")
                st.session_state.sv2_output = str(result)
                _log(f"\n🎉 XONG! {result}")

            except Exception as e:
                import traceback
                _log(f"\n❌ Lỗi: {e}")
                _log(traceback.format_exc())
                st.error(f"Render thất bại: {e}")

        # ── Log cũ ────────────────────────────────────────────────────────────
        if st.session_state.sv2_log:
            st.text_area("📋 Log lần render trước:",
                          "\n".join(st.session_state.sv2_log),
                          height=200, key="sv2_log_prev")

        # ── Download kết quả ──────────────────────────────────────────────────
        if st.session_state.sv2_output and Path(st.session_state.sv2_output).exists():
            fp = Path(st.session_state.sv2_output)
            mb = fp.stat().st_size / 1_048_576
            st.success(f"🎉 **{fp.name}** — {mb:.1f} MB")
            with open(fp, "rb") as fh:
                st.download_button(
                    label=f"⬇️ Tải xuống {fp.name}",
                    data=fh,
                    file_name=fp.name,
                    mime="video/mp4",
                    use_container_width=True,
                    key="sv2_download",
                )
            st.video(fp.read_bytes())

    # ── Giải thích kỹ thuật ───────────────────────────────────────────────────
    with st.expander("ℹ️ Tại sao v2 không bị lệch subtitle?", expanded=False):
        st.markdown("""
**Vấn đề của v1 (renderer cũ):**
- Mỗi cảnh render thành 1 clip `video+audio`
- `xfade` nối 2 clip với overlap `xfade_dur` giây → **audio 2 cảnh chồng nhau**
- Subtitle timestamp tính theo từng cảnh riêng → **lệch khi ghép**

**Giải pháp v2 (2-layer):**
```
Layer 1 (VIDEO):  clip1 ──xfade──▶ clip2 ──xfade──▶ clip3   (câm)
Layer 2 (AUDIO):  audio1 ────────▶ audio2 ────────▶ audio3  (liên tục, concat thẳng)
Layer 2 (SUB):    word0...word1...word2...                   (timestamp tuyệt đối)
```

- Transition chỉ ảnh hưởng **video** — audio và sub **không bao giờ bị overlap**
- Subtitle dùng `timeline_offset` tích lũy = tổng duration audio thực của các cảnh trước
- `xfade_dur` tự động giảm nếu cảnh quá ngắn
        """)
