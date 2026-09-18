"""
app/ui/tab_shortvideo.py — Short Video Tab UI
Auto-generated from tool.py — wraps original tab body into a render function.
"""
import asyncio, json, os, re, uuid, base64, subprocess, shutil, time, tempfile, random, math
from typing import Optional
from pathlib import Path
import streamlit as st

def render_shortvideo_tab(cfg, save_cfg, load_proj, save_proj, tts, ffmpeg, FFMPEG, **kw):
    """Render Short Video tab."""
    # ── Ensure stdlib imports available (Streamlit hot-reload safe) ──────────
    import asyncio, json, os, re, uuid, base64, subprocess, shutil, time, tempfile, random, math
    from pathlib import Path
    from typing import Optional

    st.header("⚡ Video Ngắn — Import JSON")
    st.caption("Paste JSON kịch bản → Upload ảnh (scene_001.jpg...) → Render video ngắn với hiệu ứng per-scene.")

    # ── Session state (prefix sv_) ───────────────────────────────────────────
    if "sv_scenes" not in st.session_state:
        st.session_state.sv_scenes = []
    if "sv_video_config" not in st.session_state:
        st.session_state.sv_video_config = {}
    if "sv_title" not in st.session_state:
        st.session_state.sv_title = ""
    if "sv_tts_rate" not in st.session_state:
        st.session_state.sv_tts_rate = "1.4"
    if "sv_aspect" not in st.session_state:
        st.session_state.sv_aspect = "9:16"
    if "sv_render_log" not in st.session_state:
        st.session_state.sv_render_log = []
    if "sv_final_path" not in st.session_state:
        st.session_state.sv_final_path = None

    # ── Helper: match ảnh theo prefix scene_NNN ──────────────────────────────
    def _sv_scene_num(fname: str):
        m = re.search(r'scene[_\-]?(\d+)', fname, re.IGNORECASE)
        return int(m.group(1)) if m else None

    def _sv_match_images(uploaded_files, n_scenes):
        result = {i: None for i in range(n_scenes)}
        no_num = []
        for f in uploaded_files:
            n = _sv_scene_num(f.name)
            if n is not None:
                idx = n - 1
                if 0 <= idx < n_scenes:
                    result[idx] = f
            else:
                no_num.append(f)
        leftover = [i for i in range(n_scenes) if result[i] is None]
        for f, slot in zip(no_num, leftover):
            result[slot] = f
        return result

    # ── Image effect alias map ────────────────────────────────────────────────
    _SV_IE_ALIAS = {
        "slide_right":"pan_right", "slide_left":"pan_left",
        "slide_up":"pan_up",       "slide_down":"pan_down",
        "ken_burns":"zoom_in",     "ken_burns_in":"zoom_in",
        "ken_burns_out":"zoom_out","zoomin":"zoom_in",
        "zoomout":"zoom_out",      "zoom":"zoom_in",
    }
    _SV_IE_VALID = {"zoom_in", "zoom_out", "pan_right", "pan_left", "pan_up", "pan_down"}

    # Valid xfade transitions FFmpeg hỗ trợ
    _SV_XFADE_VALID = {
        "fade", "dissolve", "wipeleft", "wiperight", "wipeup", "wipedown",
        "slideleft", "slideright", "slideup", "slidedown",
        "smoothleft", "smoothright", "smoothup", "smoothdown",
        "circlecrop", "rectcrop", "distance", "radial",
        "horzopen", "horzclose", "vertopen", "vertclose",
        "diagtl", "diagtr", "diagbl", "diagbr",
        "hlslice", "hrslice", "vuslice", "vdslice",
        "pixelize", "squeezeh", "squeezev", "zoomin",
    }

    # ════════ A. IMPORT JSON ═══════════════════════════════════════════════
    st.subheader("① Nhập JSON kịch bản")
    sv_json_raw = st.text_area(
        "Paste JSON:",
        height=180,
        placeholder='{"video_config":{"aspect_ratio":"9:16","tts_speed":1.4},"scenes":[{"id":1,"text":"...","duration":3,"image_effect":"slide_left","transition":"wipeleft","soundEffect":"fast_whoosh"}]}',
        key="sv_json_input"
    )

    _sv_col_load, _sv_col_clear = st.columns([1, 1])
    with _sv_col_load:
        if st.button("📥 Load JSON", key="sv_btn_load", use_container_width=True):
            try:
                _sv_data = json.loads(sv_json_raw)
                _sv_sc = _sv_data.get("scenes") or _sv_data.get("Scenes") or []
                if not _sv_sc:
                    st.error("Không tìm thấy field 'scenes' trong JSON.")
                else:
                    st.session_state.sv_scenes = _sv_sc
                    _sv_vc = _sv_data.get("video_config", {})
                    st.session_state.sv_video_config = _sv_vc
                    st.session_state.sv_title = _sv_data.get("title", _sv_vc.get("topic", "video_ngan"))
                    _sv_spd = str(_sv_vc.get("tts_speed") or _sv_vc.get("tts_rate") or "1.4")
                    st.session_state.sv_tts_rate = _sv_spd
                    st.session_state.sv_aspect = _sv_vc.get("aspect_ratio", "9:16")
                    st.session_state.sv_final_path = None
                    st.session_state.sv_render_log = []
                    _sv_total = sum(s.get("duration", 3) for s in _sv_sc)
                    st.success(f"✅ Đã load {len(_sv_sc)} cảnh — tổng ~{_sv_total:.1f}s")
            except Exception as _sve:
                st.error(f"❌ Lỗi parse JSON: {_sve}")
    with _sv_col_clear:

        if st.button("🗑️ Xóa", key="sv_btn_clear", use_container_width=True):
            st.session_state.sv_scenes = []
            st.session_state.sv_final_path = None
            st.session_state.sv_render_log = []
            st.rerun()

    sv_scenes = st.session_state.sv_scenes
    n_sv = len(sv_scenes)

    if n_sv > 0:
        # Preview bảng scenes
        _sv_total_dur = sum(s.get("duration", 3) for s in sv_scenes)
        with st.expander(f"📋 Preview {n_sv} cảnh (tổng ~{_sv_total_dur:.1f}s)", expanded=True):
            _sv_tbl = []
            for _svi, _svsc in enumerate(sv_scenes):
                _sv_ie_raw = (_svsc.get("imageEffect") or _svsc.get("image_effect") or "—")
                _sv_tr = _svsc.get("transition", "fade")
                _sv_sfx = _svsc.get("soundEffect", "none")
                _sv_tbl.append({
                    "#": _svi + 1,
                    "Text (50 chars)": str(_svsc.get("text", ""))[:50],
                    "Dur (s)": _svsc.get("duration", 3),
                    "image_effect": _sv_ie_raw,
                    "transition": _sv_tr,
                    "soundEffect": _sv_sfx,
                    "tts_speed": _svsc.get("tts_speed", "—"),
                })
            st.dataframe(_sv_tbl, use_container_width=True, height=300)

        st.divider()

        # ════════ B. UPLOAD ẢNH ══════════════════════════════════════════
        st.subheader("② Upload ảnh cho các cảnh")
        st.caption("Đặt tên file: `scene_001.jpg`, `scene_002.jpg`... Tool tự map đúng cảnh.")

        # Khởi tạo counter để reset uploader
        if "sv_img_uploader_key" not in st.session_state:
            st.session_state["sv_img_uploader_key"] = 0

        _sv_up_col1, _sv_up_col2 = st.columns([6, 1])
        with _sv_up_col1:
            sv_uploaded_imgs = st.file_uploader(
                f"Upload ảnh ({n_sv} cảnh — scene_NNN_...jpg):",
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True,
                key=f"sv_img_uploader_{st.session_state['sv_img_uploader_key']}"
            )
        with _sv_up_col2:
            st.write("")
            st.write("")
            if st.button("🗑️ Xóa hết", key="sv_clear_imgs", help="Xóa toàn bộ ảnh đã upload", use_container_width=True):
                st.session_state["sv_img_uploader_key"] += 1
                st.rerun()

        sv_img_map = {}
        if sv_uploaded_imgs:
            sv_img_map = _sv_match_images(sv_uploaded_imgs, n_sv)
            _sv_matched = sum(1 for v in sv_img_map.values() if v is not None)
            _sv_unmatched = n_sv - _sv_matched
            st.success(f"✅ Khớp {_sv_matched}/{n_sv} cảnh với ảnh.")
            if _sv_unmatched > 0:
                st.warning(f"⚠️ {_sv_unmatched} cảnh chưa có ảnh → sẽ dùng nền đen.")

            with st.expander("📌 Bảng phân phối ảnh → cảnh", expanded=False):
                _sv_map_rows = []
                for _smi in range(n_sv):
                    _svf = sv_img_map.get(_smi)
                    _sv_map_rows.append({
                        "Cảnh": _smi + 1,
                        "Text": str(sv_scenes[_smi].get("text", ""))[:35],
                        "File ảnh": _svf.name if _svf else "—",
                        "Status": "✅ Khớp" if _svf else "⬛ Nền đen"
                    })
                st.dataframe(_sv_map_rows, use_container_width=True)
        else:
            st.info("ℹ️ Chưa upload ảnh → toàn bộ cảnh sẽ dùng nền đen.")

        st.divider()

        # ════════ C. CẤU HÌNH ════════════════════════════════════════════
        st.subheader("③ Cấu hình")
        _sv_c1, _sv_c2, _sv_c3 = st.columns(3)
        with _sv_c1:
            _sv_voice_opts = []
            # ── ZeroTTS (ưu tiên đầu danh sách — local, offline, WER 1.03%) ─────
            if _ZEROTTS_OK:
                _sv_voice_opts.extend(_zt.list_display_voices())
            # ── CapCut TTS ────────────────────────────────────────────────────────
            if _CAPCUT_OK:
                _sv_voice_opts.extend([k for k in _cc.CAPCUT_VOICES if "🇻🇳" in k])
            _sv_voice_opts.extend(list(EDGE_VOICES.keys()))

            # Default: ZeroTTS Hà My (biểu cảm, phù hợp video ngắn)
            _sv_def_idx = 0
            _sv_zt_default = "🇻🇳 Hà My — Nữ · Trẻ · Hoạt hình · Cao · Biểu cảm"
            if _sv_zt_default in _sv_voice_opts:
                _sv_def_idx = _sv_voice_opts.index(_sv_zt_default)
            elif "🇻🇳 Giọng Nam Trầm" in _sv_voice_opts:
                _sv_def_idx = _sv_voice_opts.index("🇻🇳 Giọng Nam Trầm")

            sv_voice_key = st.selectbox(
                "🎙️ Giọng TTS:",
                options=_sv_voice_opts,
                index=_sv_def_idx,
                key="sv_voice",
                help="⚡ ZeroTTS: offline · WER 1.03% · 8 giọng Việt có tag rõ ràng"
            )
        with _sv_c2:
            _sv_speed_opts = ["0.8","0.9","1.0","1.1","1.2","1.3","1.4","1.5","1.6","1.7","1.8","2.0"]
            sv_tts_rate = st.selectbox(
                "⚡ Tốc độ TTS (mặc định):",
                options=_sv_speed_opts,
                index=_sv_speed_opts.index(st.session_state.sv_tts_rate) if st.session_state.sv_tts_rate in _sv_speed_opts else 6,
                key="sv_tts_rate_sel",
                on_change=lambda: st.session_state.update({"sv_tts_rate": st.session_state["sv_tts_rate_sel"]})
            )
        with _sv_c3:
            sv_aspect = st.selectbox(
                "📐 Tỉ lệ:",
                options=["9:16", "16:9", "1:1"],
                index=["9:16","16:9","1:1"].index(st.session_state.sv_aspect) if st.session_state.sv_aspect in ["9:16","16:9","1:1"] else 0,
                key="sv_aspect_sel"
            )

        _sv_c4, _sv_c5 = st.columns(2)
        with _sv_c4:
            sv_xfade_dur = st.slider("⏱️ Xfade duration (giây):", 0.1, 1.0, 0.35, 0.05, key="sv_xfade_dur")
        with _sv_c5:
            sv_fade_scene = st.slider("🌒 Fade in/out mỗi cảnh (giây):", 0.0, 0.6, 0.35, 0.05, key="sv_fade_scene")

        _sv_sub_c1, _sv_sub_c2 = st.columns([1, 2])
        with _sv_sub_c1:
            sv_show_sub = st.checkbox("📝 Hiện subtitle", value=True, key="sv_show_sub")
        with _sv_sub_c2:
            sv_sub_style = st.selectbox(
                "Style sub:",
                options=list(SUB_STYLES.keys()),
                index=0,
                key="sv_sub_style",
                disabled=not sv_show_sub
            ) if sv_show_sub else list(SUB_STYLES.keys())[0]

        sv_bgm_file = st.file_uploader("🎵 Nhạc nền BGM (mp3/wav, tùy chọn):", type=["mp3","wav","m4a"], key="sv_bgm")
        sv_bgm_vol = st.slider("🔊 Volume BGM:", 0, 100, 20, key="sv_bgm_vol") if sv_bgm_file else 20

        sv_out_name = st.text_input(
            "💾 Tên file output:",
            value=output_file_stem(st.session_state.sv_title) or "video_ngan",
            key="sv_out_name"
        )
        sv_out_dir = st.text_input(
            "📂 Thư mục lưu video:",
            value="/Users/zeworkcomputer/Documents/99999",
            placeholder="/Users/zeworkcomputer/Documents/99999",
            key="sv_out_dir",
            help="Video final sẽ được lưu vào thư mục này. Tool tự tạo nếu chưa có."
        )

        st.divider()

        # ════════ D. RENDER ═══════════════════════════════════════════════
        st.subheader("④ Render Video Ngắn")
        st.caption(f"Tổng thời lượng ước tính: **{_sv_total_dur:.1f}s** | {n_sv} cảnh | Xfade: {sv_xfade_dur}s per-scene")

        # ── Gợi ý số từ/cảnh theo tốc độ TTS hiện tại ───────────────────
        try:
            _sv_rate_calc = float(st.session_state.get("sv_tts_rate", sv_tts_rate) or "1.0")
        except Exception:
            _sv_rate_calc = 1.0
        _sv_xd_calc = float(sv_xfade_dur)
        _sv_base_wps = 3.2  # Vietnamese ZeroTTS ~3.2 từ/giây ở 1x
        _sv_eff_wps = _sv_base_wps * _sv_rate_calc
        _avg_dur = (_sv_total_dur / max(n_sv, 1)) if n_sv > 0 else 5.0
        _sv_words_rec = max(1, int((_avg_dur - _sv_xd_calc) * _sv_eff_wps))
        with st.expander(f"💡 Gợi ý số từ/cảnh (rate={_sv_rate_calc}x)", expanded=False):
            st.markdown(f"""
    **Công thức:** `từ/cảnh = (duration − xfade) × 3.2 × rate`

    | Duration cảnh | Rate {_sv_rate_calc}x | Từ tối đa |
    |---|---|---|
    | 3s | {_sv_rate_calc}x | **{max(1,int((3-_sv_xd_calc)*_sv_eff_wps))} từ** |
    | 4s | {_sv_rate_calc}x | **{max(1,int((4-_sv_xd_calc)*_sv_eff_wps))} từ** |
    | 5s | {_sv_rate_calc}x | **{max(1,int((5-_sv_xd_calc)*_sv_eff_wps))} từ** |
    | 6s | {_sv_rate_calc}x | **{max(1,int((6-_sv_xd_calc)*_sv_eff_wps))} từ** |

    → Với cảnh trung bình **{_avg_dur:.1f}s** hiện tại: tối đa **~{_sv_words_rec} từ/cảnh**
    """)


        sv_do_render = st.button(
            f"▶️ Render Video Ngắn ({n_sv} cảnh)",
            key="sv_btn_render",
            type="primary",
            use_container_width=True,
            disabled=(n_sv == 0)
        )

        if sv_do_render:
            st.session_state.sv_render_log = []
            st.session_state.sv_final_path = None

            _sv_W, _sv_H = (1080, 1920) if "9:16" in sv_aspect else ((1080, 1080) if "1:1" in sv_aspect else (1920, 1080))
            _sv_work = AUDIO_DIR / f"sv_{uuid.uuid4().hex[:8]}"
            _sv_work.mkdir(parents=True, exist_ok=True)

            # Save BGM
            _sv_bgm_path = None
            if sv_bgm_file:
                _sv_bgm_path = _sv_work / f"bgm_{sv_bgm_file.name}"
                _sv_bgm_path.write_bytes(sv_bgm_file.read())

            _sv_log_area = st.empty()
            _sv_prog = st.progress(0, text="Đang chuẩn bị...")
            _sv_clips = []          # list of Path
            _sv_is_img = []          # list of bool (luôn True vì toàn ảnh)
            _sv_transitions = []     # list of transition string per boundary
            _sv_actual_durs = []     # actual TTS audio dur per clip (before buffer)
            _sv_errors = []


            def _sv_log(msg):
                st.session_state.sv_render_log.append(msg)
                _sv_log_area.text_area(
                    "📋 Log:",
                    "\n".join(st.session_state.sv_render_log[-40:]),
                    height=220,
                    key=f"sv_log_{len(st.session_state.sv_render_log)}"
                )

            # Log debug info
            _sv_log(f"🔧 HAS_SUB={HAS_SUB} | show_sub={sv_show_sub} | FFMPEG={FFMPEG}")

            # ── Probe duration helper ─────────────────────────────────────
            def _sv_probe_dur(path):
                try:
                    pb = subprocess.run(
                        [FFMPEG, "-i", str(path), "-f", "null", "-"],
                        capture_output=True, text=True
                    )
                    for ln in pb.stderr.split("\n"):
                        if "Duration:" in ln:
                            ts = ln.split("Duration:")[1].split(",")[0].strip()
                            hh, mm, ss = ts.split(":")
                            return int(hh)*3600 + int(mm)*60 + float(ss)
                except Exception:
                    pass
                return 0.0

            # ── Per-scene render loop ─────────────────────────────────────
            for _svi, _svsc in enumerate(sv_scenes):
                _sv_pct = int(_svi / n_sv * 88)
                _sv_prog.progress(_sv_pct, text=f"Cảnh {_svi+1}/{n_sv}...")
                _sv_log(f"━━ Cảnh {_svi+1}/{n_sv}: {str(_svsc.get('text',''))[:45]}")

                _sv_s_dir = _sv_work / f"scene_{_svi:04d}"
                _sv_s_dir.mkdir(exist_ok=True)
                _sv_clip_out = _sv_s_dir / "clip.mp4"

                try:
                    # ── Step 1: TTS ───────────────────────────────────────
                    _sv_text = str(_svsc.get("text", "")).strip()
                    _sv_dur  = float(_svsc.get("duration", 3))
                    # Per-scene tts_speed ưu tiên; fallback về global sv_tts_rate
                    # UI global rate luôn được ưu tiên; per-scene tts_speed trong JSON chỉ dùng khi UI rate = default
                    _sv_sc_rate = sv_tts_rate
                    _sv_audio = _sv_s_dir / "tts.mp3"
                    _sv_srt   = _sv_s_dir / "tts.srt"
                    _sv_log(f"  🎙️ TTS '{_sv_text[:30]}' (speed={_sv_sc_rate}x)...")
                    _sv_words = []
                    try:
                        _sv_tts_result = tts(
                            _sv_text, voice_cfg=sv_voice_key, srt_out=str(_sv_srt), rate=_sv_sc_rate
                        )
                        if _sv_tts_result and Path(_sv_tts_result).exists():
                            shutil.move(_sv_tts_result, str(_sv_audio))
                        # Lấy words từ SRT file nếu tạo được
                        if _sv_srt.exists() and _sv_srt.stat().st_size > 10:
                            _sv_words = srt_to_words(str(_sv_srt))
                            _sv_log(f"  ✅ TTS OK — {len(_sv_words)} words từ SRT")
                        else:
                            _sv_log("  ⚠️ SRT rỗng — tạo words từ text + duration")
                    except Exception as _svte:
                        _sv_log(f"  ⚠️ TTS lỗi: {_svte} — dùng silence")
                        ffmpeg("-f","lavfi","-i",f"anullsrc=r=44100:cl=mono",
                               "-t",str(_sv_dur),"-acodec","libmp3lame","-y",str(_sv_audio))

                    # Fallback: nếu không có words từ SRT, tạo timing đều từ text
                    if not _sv_words and _sv_text and _sv_audio.exists():
                        try:
                            _sv_probe_audio = subprocess.run(
                                [FFMPEG, "-i", str(_sv_audio), "-f", "null", "-"],
                                capture_output=True, text=True
                            )
                            _sv_aud_dur = 0.0
                            for _svln in _sv_probe_audio.stderr.split("\n"):
                                if "Duration:" in _svln:
                                    _svts = _svln.split("Duration:")[1].split(",")[0].strip()
                                    _svh, _svm, _svs = _svts.split(":")
                                    _sv_aud_dur = int(_svh)*3600 + int(_svm)*60 + float(_svs)
                                    break
                            if _sv_aud_dur > 0:
                                # Detect leading silence — find when speech actually starts
                                _sv_speech_start = 0.0
                                try:
                                    _sv_sil = subprocess.run(
                                        [FFMPEG, "-i", str(_sv_audio),
                                         "-af", "silencedetect=noise=-35dB:d=0.05",
                                         "-f", "null", "-"],
                                        capture_output=True, text=True
                                    )
                                    for _sil_ln in _sv_sil.stderr.split("\n"):
                                        if "silence_end:" in _sil_ln:
                                            _sv_speech_start = float(_sil_ln.split("silence_end:")[1].split("|")[0].strip())
                                            break
                                except Exception:
                                    pass
                                _sv_speech_dur = max(0.1, _sv_aud_dur - _sv_speech_start)
                                _sv_toks = _sv_text.split()
                                _sv_td = _sv_speech_dur / max(len(_sv_toks), 1)
                                _sv_words = [
                                    {"word": w, "start": _sv_speech_start + i*_sv_td, "end": _sv_speech_start + (i+1)*_sv_td}
                                    for i, w in enumerate(_sv_toks)
                                ]
                                _sv_log(f"  📝 Fallback words: {len(_sv_words)} từ (speech_start={_sv_speech_start:.2f}s, speech_dur={_sv_speech_dur:.2f}s)")
                        except Exception as _svwe:
                            _sv_log(f"  ⚠️ Fallback words lỗi: {_svwe}")

                    # ── Step 1b: Tạo subtitle ASS nếu cần ───────────────────────
                    _sv_ass_path = None
                    _sv_log(f"  🔍 sub check: show={sv_show_sub} HAS_SUB={HAS_SUB} words={len(_sv_words)}")
                    if sv_show_sub and HAS_SUB and _sv_words:
                        try:
                            _sv_ass_content = make_ass(
                                _sv_words, W=_sv_W, H=_sv_H,
                                style_name=sv_sub_style
                            )
                            if _sv_ass_content:
                                _sv_ass_path = _sv_s_dir / "sub.ass"
                                _sv_ass_path.write_text(_sv_ass_content, encoding="utf-8")
                                _sv_log(f"  📝 Sub ASS OK ({len(_sv_words)} words) → {_sv_ass_path.name}")
                            else:
                                _sv_log("  ⚠️ make_ass trả về rỗng")
                        except Exception as _sv_asse:
                            _sv_log(f"  ⚠️ Sub lỗi: {_sv_asse} — bỏ phụ đề")
                    elif sv_show_sub and not HAS_SUB:
                        _sv_log("  ⚠️ FFmpeg thiếu libass — bỏ phụ đề")
                    elif sv_show_sub and not _sv_words:
                        _sv_log("  ⚠️ words rỗng — không có timing để tạo sub")

                    # ── Step 2: Ảnh ───────────────────────────────────────
                    _sv_img_path = None
                    _sv_upf = sv_img_map.get(_svi) if sv_img_map else None
                    if _sv_upf is not None:
                        _sv_img_save = _sv_s_dir / f"img_{_sv_upf.name}"
                        _sv_img_save.write_bytes(_sv_upf.read())
                        _sv_img_path = _sv_img_save
                        _sv_log(f"  🖼️ Ảnh: {_sv_upf.name}")
                    else:
                        _sv_log(f"  ⬛ Không có ảnh — nền đen")

                    # ── Step 3: Resolve image_effect ─────────────────────
                    _sv_ie_raw = (_svsc.get("imageEffect") or _svsc.get("image_effect") or "").strip()
                    _sv_ie_raw = _SV_IE_ALIAS.get(_sv_ie_raw, _sv_ie_raw)
                    _sv_effect = _sv_ie_raw if _sv_ie_raw in _SV_IE_VALID else None
                    _sv_log(f"  🎨 image_effect: {_sv_effect or 'random'}")

                    # ── Step 4: FFmpeg render cảnh ────────────────────────
                    # Probe audio thực tế sau TTS — dùng làm clip duration
                    # để sub/video sync đúng dù TTS chạy ở tốc độ bất kỳ
                    _sv_actual_dur = _sv_dur  # default = JSON duration
                    if _sv_audio.exists() and _sv_audio.stat().st_size > 1000:
                        try:
                            _sv_ap = subprocess.run(
                                [FFMPEG, "-i", str(_sv_audio), "-f", "null", "-"],
                                capture_output=True, text=True
                            )
                            for _svl in _sv_ap.stderr.split("\n"):
                                if "Duration:" in _svl:
                                    _svt = _svl.split("Duration:")[1].split(",")[0].strip()
                                    _svh2, _svm2, _svs2 = _svt.split(":")
                                    _sv_actual_dur = int(_svh2)*3600 + int(_svm2)*60 + float(_svs2)
                                    _sv_log(f"  ⏱️ Audio thực tế: {_sv_actual_dur:.2f}s (JSON: {_sv_dur}s)")
                                    break
                        except Exception as _svdp:
                            _sv_log(f"  ⚠️ Probe audio dur lỗi: {_svdp} — dùng {_sv_dur}s")

                    # Clip duration = audio thực tế + buffer xfade_dur
                    # Buffer = silence padding sau voice → atrim sau này chỉ cắt silence, không cắt voice
                    _sv_xfade_buf = float(sv_xfade_dur)
                    _sv_clip_dur = _sv_actual_dur + _sv_xfade_buf

                    _sv_fd = float(sv_fade_scene)
                    _sv_fade_vf = f",fade=t=in:st=0:d={_sv_fd},fade=t=out:st={max(0.0, _sv_clip_dur - _sv_fd):.3f}:d={_sv_fd}" if _sv_fd > 0 else ""

                    # Subtitle ASS filter — cần format=yuv420p trước ass=
                    # vì libass cần yuv420p, mà zoompan output có thể khác
                    def _sv_ass_filter(ass_path):
                        p = str(ass_path).replace("\\", "\\\\").replace(":", "\\:")
                        return f",format=yuv420p,ass='{p}'"

                    _sv_sub_vf = _sv_ass_filter(_sv_ass_path) if _sv_ass_path else ""

                    if _sv_img_path and _sv_img_path.exists():
                        _sv_scale_f = make_image_effect_filter(_sv_W, _sv_H, _sv_clip_dur, effect=_sv_effect)
                        _sv_vf = _sv_scale_f + _sv_fade_vf + _sv_sub_vf
                        _sv_log(f"  🔧 vf: {_sv_vf[:100]}{'...' if len(_sv_vf)>100 else ''}")
                        _sv_cmd = [
                            "-i", str(_sv_img_path),
                            "-i", str(_sv_audio),
                            "-vf", _sv_vf,
                            "-t", str(_sv_clip_dur),
                            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                            "-af", f"apad=whole_dur={_sv_clip_dur}",
                            "-pix_fmt", "yuv420p",
                            "-map", "0:v", "-map", "1:a",
                            "-y", str(_sv_clip_out)
                        ]
                    else:
                        _sv_color = f"color=c=black:s={_sv_W}x{_sv_H}:r=30"
                        _sv_cmd = [
                            "-f", "lavfi", "-i", _sv_color,
                            "-i", str(_sv_audio),
                            "-vf", f"fps=30{_sv_fade_vf}{_sv_sub_vf}",
                            "-t", str(_sv_clip_dur),
                            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                            "-af", f"apad=whole_dur={_sv_clip_dur}",
                            "-pix_fmt", "yuv420p",
                            "-map", "0:v", "-map", "1:a",
                            "-y", str(_sv_clip_out)
                        ]
                    ffmpeg(*_sv_cmd)

                    if not (_sv_clip_out.exists() and _sv_clip_out.stat().st_size > 1000):
                        raise RuntimeError("Clip output rỗng hoặc không tồn tại")

                    # ── Step 5: Sound Effect mix ──────────────────────────
                    # Map fast_whoosh / bright_chime → key trong SOUND_EFFECTS
                    _sv_sfx_raw = str(_svsc.get("soundEffect", "none")).strip().lower()
                    _sv_sfx_map = {
                        "fast_whoosh": "whoosh",
                        "bright_chime": "chime",
                        "whoosh": "whoosh",
                        "chime": "chime",
                        "click": "click",
                        "deep_hit": "deep_hit",
                        "none": "none",
                    }
                    _sv_sfx = _sv_sfx_map.get(_sv_sfx_raw, "none")
                    if _sv_sfx and _sv_sfx != "none" and _sv_sfx in SOUND_EFFECTS:
                        _sv_clip_sfx = _sv_s_dir / "clip_sfx.mp4"
                        _sv_ok = apply_sound_effect_to_scene(_sv_clip_out, _sv_sfx, _sv_clip_sfx)
                        if _sv_ok:
                            _sv_clip_out = _sv_clip_sfx
                            _sv_log(f"  🔊 SFX '{_sv_sfx}' OK")
                        else:
                            _sv_log(f"  ⚠️ SFX '{_sv_sfx}' thất bại — bỏ qua")

                    _sv_clips.append(_sv_clip_out)
                    _sv_actual_durs.append(_sv_actual_dur)  # lưu TTS dur thực (trước buffer)
                    _sv_is_img.append(True)  # luôn True vì toàn ảnh

                    # Lưu transition của cảnh này (dùng cho boundary i → i+1)
                    _sv_tr_raw = str(_svsc.get("transition", "fade")).strip().lower()
                    _sv_tr = _sv_tr_raw if _sv_tr_raw in _SV_XFADE_VALID else "fade"
                    _sv_transitions.append(_sv_tr)

                    _sv_log(f"  ✅ Cảnh {_svi+1} OK ({_sv_dur}s) | transition→next: {_sv_tr}")

                except Exception as _sverr:
                    _sv_log(f"  ❌ Cảnh {_svi+1} lỗi: {_sverr}")
                    _sv_errors.append(_svi + 1)

            # ── Concat với xfade per-scene ────────────────────────────────
            _sv_prog.progress(90, text="Ghép video với xfade...")
            _sv_log(f"\n🎬 Ghép {len(_sv_clips)} clip (xfade per-scene)...")

            _sv_raw_out = None
            if len(_sv_clips) == 0:
                _sv_log("❌ Không có clip nào render thành công.")
                st.error("Render thất bại — xem log bên dưới.")
            elif len(_sv_clips) == 1:
                _sv_raw_out = _sv_clips[0]
            else:
                # ── Build xfade filter_complex ────────────────────────────
                _sv_concat_out = _sv_work / "xfade_concat.mp4"
                _sv_n = len(_sv_clips)
                _sv_xd = float(sv_xfade_dur)

                # Probe duration của từng clip
                _sv_durs = []
                for _cp in _sv_clips:
                    _d = _sv_probe_dur(_cp)
                    _sv_durs.append(max(_d, 1.0))

                # Build FFmpeg inputs
                _sv_inputs = []
                for _cp in _sv_clips:
                    _sv_inputs.extend(["-i", str(_cp)])

                # Build filter_complex với xfade video + concat audio thẳng
                # Audio dùng concat (không acrossfade) để từ đầu cảnh mới rõ 100%
                _sv_fparts = []
                for _j in range(_sv_n):
                    _sv_fparts.append(f"[{_j}:v]copy[v{_j}]")

                _sv_offset = _sv_durs[0] - _sv_xd
                _sv_cur_v = "[v0]"

                for _j in range(1, _sv_n):
                    _sv_nv = f"[xv{_j}]" if _j < _sv_n - 1 else "[vout]"
                    _sv_tr_j = _sv_transitions[_j - 1] if (_j - 1) < len(_sv_transitions) else "fade"
                    _sv_fparts.append(
                        f"{_sv_cur_v}[v{_j}]xfade=transition={_sv_tr_j}:duration={_sv_xd}:offset={_sv_offset:.3f}{_sv_nv}"
                    )
                    _sv_cur_v = _sv_nv
                    if _j < _sv_n - 1:
                        _sv_offset += _sv_durs[_j] - _sv_xd

                # Audio: atrim đến _sv_actual_durs[j] (TTS thực) — chỉ cắt buffer silence
                # Mỗi clip được render với actual_dur + xfade_buf → buffer là silence sau voice
                # atrim cắt đúng buffer silence, KHÔNG cắt voice content
                _sv_adurs_safe = (
                    _sv_actual_durs if len(_sv_actual_durs) == _sv_n
                    else [max(0.1, d - _sv_xd) for d in _sv_durs]
                )
                for _j in range(_sv_n):
                    _trim_end = max(0.1, _sv_adurs_safe[_j])
                    _sv_fparts.append(f"[{_j}:a]atrim=0:{_trim_end:.3f},asetpts=PTS-STARTPTS[a{_j}]")
                _sv_a_inputs = "".join(f"[a{_j}]" for _j in range(_sv_n))
                _sv_fparts.append(f"{_sv_a_inputs}concat=n={_sv_n}:v=0:a=1[aout]")

                _sv_fc = ";".join(_sv_fparts)
                _sv_total_adur = sum(_sv_adurs_safe)  # tổng audio thực = giới hạn video

                try:
                    ffmpeg(
                        *_sv_inputs,
                        "-filter_complex", _sv_fc,
                        "-map", "[vout]", "-map", "[aout]",
                        "-t", f"{_sv_total_adur:.3f}",  # trim trailing silence buffer clip cuối
                        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                        "-movflags", "+faststart",
                        "-y", str(_sv_concat_out)
                    )

                    if _sv_concat_out.exists() and _sv_concat_out.stat().st_size > 10000:
                        _sv_raw_out = _sv_concat_out
                        _sv_log("✅ Xfade concat OK")
                    else:
                        raise RuntimeError("Xfade output rỗng")
                except Exception as _svxe:
                    _sv_log(f"⚠️ Xfade lỗi: {_svxe} — fallback concat thô")
                    # Fallback: concat thô
                    _sv_concat_txt = _sv_work / "concat.txt"
                    _sv_concat_txt.write_text("\n".join(f"file '{p.as_posix()}'" for p in _sv_clips))
                    _sv_concat_fb = _sv_work / "concat_fallback.mp4"
                    ffmpeg("-f","concat","-safe","0","-i",str(_sv_concat_txt),"-c","copy","-y",str(_sv_concat_fb))
                    _sv_raw_out = _sv_concat_fb if _sv_concat_fb.exists() else None

            # ── Mix BGM nếu có ────────────────────────────────────────────
            if _sv_raw_out and _sv_raw_out.exists():
                _sv_stem = output_file_stem(sv_out_name) or "video_ngan"
                _sv_out_dir_p = Path(sv_out_dir.strip()) if sv_out_dir.strip() else AUDIO_DIR
                _sv_out_dir_p.mkdir(parents=True, exist_ok=True)
                _sv_final = _sv_out_dir_p / f"{_sv_stem}.mp4"

                if _sv_bgm_path and _sv_bgm_path.exists():
                    _sv_prog.progress(96, text="Mix nhạc nền...")
                    _sv_log("🎵 Mix BGM...")
                    _sv_bgm_volf = sv_bgm_vol / 100.0
                    try:
                        ffmpeg(
                            "-i", str(_sv_raw_out),
                            "-stream_loop", "-1", "-i", str(_sv_bgm_path),
                            "-filter_complex",
                            f"[0:a]volume=1.0[tts];"
                            f"[1:a]volume={_sv_bgm_volf}[bgm];"
                            f"[tts][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                            "-map", "0:v", "-map", "[aout]",
                            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                            "-shortest", "-y", str(_sv_final)
                        )
                        _sv_log("✅ Mix BGM OK")
                    except Exception as _svbgme:
                        _sv_log(f"⚠️ BGM lỗi: {_svbgme} — dùng video không nhạc")
                        import shutil as _shutil
                        _shutil.copy2(str(_sv_raw_out), str(_sv_final))
                else:
                    import shutil as _shutil
                    _shutil.copy2(str(_sv_raw_out), str(_sv_final))

                _sv_prog.progress(100, text="✅ Hoàn tất!")
                st.session_state.sv_final_path = str(_sv_final)
                _sv_log(f"\n🎉 XONG! {_sv_final}")
                if _sv_errors:
                    _sv_log(f"⚠️ Cảnh bị lỗi/skip: {_sv_errors}")
            else:
                _sv_log("❌ Không tạo được video cuối.")
                st.error("Render thất bại — xem log.")

        # ── Log lần render trước ──────────────────────────────────────────
        if st.session_state.sv_render_log and not sv_do_render:
            st.text_area("📋 Log lần render trước:", "\n".join(st.session_state.sv_render_log), height=200, key="sv_log_prev")

        # ── Download ──────────────────────────────────────────────────────
        if st.session_state.sv_final_path and Path(st.session_state.sv_final_path).exists():
            _sv_fp = Path(st.session_state.sv_final_path)
            _sv_mb = _sv_fp.stat().st_size / 1024 / 1024
            st.success(f"🎉 Video ngắn hoàn tất! ({_sv_mb:.1f} MB) — {_sv_fp.name}")
            st.video(_sv_fp.read_bytes())
            st.download_button(
                label=f"⬇️ Tải xuống {_sv_fp.name}",
                data=_sv_fp.read_bytes(),
                file_name=_sv_fp.name,
                mime="video/mp4",
                use_container_width=True,
                key="sv_download"
            )

    # ════════════════════════════════════════════════════════════
    # SOCIAL PUBLISHING TAB — schedules and prior rendered videos
    # ════════════════════════════════════════════════════════════
