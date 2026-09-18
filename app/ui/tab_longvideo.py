"""
app/ui/tab_longvideo.py — Long Video Tab UI
Auto-generated from tool.py — wraps original tab body into a render function.
"""
import asyncio, json, os, re, uuid, base64, subprocess, shutil, time, tempfile, random, math
from typing import Optional
from pathlib import Path
import streamlit as st

def render_longvideo_tab(cfg, save_cfg, load_proj, save_proj, tts, ffmpeg, FFMPEG, **kw):
    """Render Long Video tab."""
    # ── Ensure stdlib imports available (Streamlit hot-reload safe) ──────────
    import asyncio, json, os, re, uuid, base64, subprocess, shutil, time, tempfile, random, math
    from pathlib import Path
    from typing import Optional

    st.header("📹 Video Dài — Auto Pipeline")
    st.caption("Tạo video dài từ 100+ cảnh hoàn toàn tự động. Độc lập với Pipeline chính.")

    # ── Helper: extract scene number from filename ────────────────────────────
    def _lv_scene_num(fname: str):
        """Trả về số cảnh từ tên file dạng scene_001_xxx.jpg → 1. None nếu không có."""
        m = re.search(r'scene[_\-]?(\d+)', fname, re.IGNORECASE)
        return int(m.group(1)) if m else None

    def _lv_match_images(uploaded_files, n_scenes):
        """
        Phân phối ảnh upload vào đúng cảnh dựa trên scene_NNN trong tên file.
        Fallback: gán theo thứ tự nếu không có số.
        Trả về dict {scene_idx (0-based): UploadedFile or None}
        """
        result = {i: None for i in range(n_scenes)}
        no_num = []
        for f in uploaded_files:
            n = _lv_scene_num(f.name)
            if n is not None:
                idx = n - 1  # 0-based
                if 0 <= idx < n_scenes:
                    result[idx] = f
            else:
                no_num.append(f)
        # Fallback: ảnh không có số → gán vào cảnh chưa có ảnh theo thứ tự
        leftover_slots = [i for i in range(n_scenes) if result[i] is None]
        for f, slot in zip(no_num, leftover_slots):
            result[slot] = f
        return result

    # ── Session state keys (tất cả prefix lv_) ───────────────────────────────
    if "lv_scenes" not in st.session_state:
        st.session_state.lv_scenes = []
    if "lv_title" not in st.session_state:
        st.session_state.lv_title = ""
    if "lv_lang" not in st.session_state:
        st.session_state.lv_lang = "Korean"
    if "lv_aspect" not in st.session_state:
        st.session_state.lv_aspect = "16:9"
    if "lv_tts_rate" not in st.session_state:
        st.session_state.lv_tts_rate = "1.3"
    if "lv_render_log" not in st.session_state:
        st.session_state.lv_render_log = []
    if "lv_final_path" not in st.session_state:
        st.session_state.lv_final_path = None

    # ════════ A. IMPORT JSON ═════════════════════════════════════════════════
    st.subheader("① Nhập JSON kịch bản")
    lv_json_raw = st.text_area(
        "Paste JSON (có field scenes[]):",
        height=150,
        placeholder='{"video_config": {...}, "scenes": [{"id":1,"text":"...","duration":5,...}]}',
        key="lv_json_input"
    )
    col_load, col_clear = st.columns([1, 1])
    with col_load:
        if st.button("📥 Load JSON", key="lv_btn_load", use_container_width=True):
            try:
                _lv_data = json.loads(lv_json_raw)
                _lv_sc = _lv_data.get("scenes") or _lv_data.get("Scenes") or []
                if not _lv_sc:
                    st.error("Không tìm thấy field 'scenes' trong JSON.")
                else:
                    st.session_state.lv_scenes = _lv_sc
                    _vc = _lv_data.get("video_config", {})
                    st.session_state.lv_title = _lv_data.get("title", _vc.get("topic", "video_dai"))
                    st.session_state.lv_lang  = _vc.get("language", "Korean")
                    st.session_state.lv_aspect = _vc.get("aspect_ratio", "16:9")
                    _spd = str(_vc.get("tts_speed") or _vc.get("tts_rate") or "1.3")
                    st.session_state.lv_tts_rate = _spd
                    st.session_state.lv_final_path = None
                    st.session_state.lv_render_log = []
                    st.success(f"✅ Đã load {len(_lv_sc)} cảnh — tổng ~{sum(s.get('duration',5) for s in _lv_sc)}s")
            except Exception as _e:
                st.error(f"❌ Lỗi parse JSON: {_e}")
    with col_clear:
        if st.button("🗑️ Xóa", key="lv_btn_clear", use_container_width=True):
            st.session_state.lv_scenes = []
            st.session_state.lv_final_path = None
            st.session_state.lv_render_log = []
            st.rerun()

    lv_scenes = st.session_state.lv_scenes
    n_lv = len(lv_scenes)

    if n_lv > 0:
        # Preview bảng cảnh
        with st.expander(f"📋 Preview {n_lv} cảnh (tổng ~{sum(s.get('duration',5) for s in lv_scenes)}s = {sum(s.get('duration',5) for s in lv_scenes)//60}m{sum(s.get('duration',5) for s in lv_scenes)%60}s)", expanded=False):
            _tbl_data = []
            for _si, _sc in enumerate(lv_scenes):
                _ie = (_sc.get("imageEffect") or _sc.get("image_effect") or "random")
                _tbl_data.append({
                    "#": _si + 1,
                    "Text (40 chars)": str(_sc.get("text",""))[:40],
                    "Dur": _sc.get("duration", 5),
                    "Effect": _ie,
                    "imagePrompt": str(_sc.get("imagePrompt",""))[:50],
                })
            st.dataframe(_tbl_data, use_container_width=True, height=300)

        st.divider()

        # ════════ B. UPLOAD ẢNH ══════════════════════════════════════════════
        st.subheader("② Upload ảnh cho các cảnh")
        st.caption("Đặt tên file dạng `scene_001_xxx.jpg`, `scene_002_xxx.jpg`... Tool sẽ tự phân phối đúng cảnh.")

        # Khởi tạo counter để reset uploader
        if "lv_img_uploader_key" not in st.session_state:
            st.session_state["lv_img_uploader_key"] = 0

        _lv_up_col1, _lv_up_col2 = st.columns([6, 1])
        with _lv_up_col1:
            lv_uploaded_imgs = st.file_uploader(
                f"Upload ảnh (tối đa {n_lv} file, đặt tên scene_NNN_...):",
                type=["jpg","jpeg","png","webp"],
                accept_multiple_files=True,
                key=f"lv_img_uploader_{st.session_state['lv_img_uploader_key']}"
            )
        with _lv_up_col2:
            st.write("")
            st.write("")
            if st.button("🗑️ Xóa hết", key="lv_clear_imgs", help="Xóa toàn bộ ảnh đã upload", use_container_width=True):
                st.session_state["lv_img_uploader_key"] += 1
                st.rerun()

        lv_img_map = {}
        if lv_uploaded_imgs:
            lv_img_map = _lv_match_images(lv_uploaded_imgs, n_lv)
            matched   = sum(1 for v in lv_img_map.values() if v is not None)
            unmatched = n_lv - matched
            st.success(f"✅ Khớp {matched}/{n_lv} cảnh với ảnh.")
            if unmatched > 0:
                st.warning(f"⚠️ {unmatched} cảnh chưa có ảnh → sẽ tạo tự động bằng Imagen 3 (cần API key Gemini).")

            # Bảng mapping xác nhận
            with st.expander("📌 Xem bảng phân phối ảnh → cảnh", expanded=False):
                _map_rows = []
                for _mi in range(n_lv):
                    _f = lv_img_map.get(_mi)
                    _map_rows.append({
                        "Cảnh": _mi + 1,
                        "Text": str(lv_scenes[_mi].get("text",""))[:30],
                        "File ảnh": _f.name if _f else "—",
                        "Status": "✅ Khớp" if _f else "🤖 Imagen/đen"
                    })
                st.dataframe(_map_rows, use_container_width=True)
        else:
            st.info("ℹ️ Chưa upload ảnh → toàn bộ cảnh sẽ dùng Imagen 3 (imagePrompt). Cần Gemini API key.")

        st.divider()

        # ════════ C. CONFIG ═══════════════════════════════════════════════════
        st.subheader("③ Cấu hình")
        _lv_c1, _lv_c2, _lv_c3 = st.columns(3)
        with _lv_c1:
            _lv_lang_flag = {"Vietnamese": "🇻🇳", "English": "🇺🇸", "Korean": "🇰🇷", "Japanese": "🇯🇵"}.get(st.session_state.lv_lang, "🇻🇳")
            _lv_voice_opts = []
            # ── ZeroTTS (ưu tiên đầu danh sách — local, offline, WER 1.03%) ─────
            if _ZEROTTS_OK and _lv_lang_flag == "🇻🇳":
                _lv_voice_opts.extend(_zt.list_display_voices())
            # ── CapCut TTS ────────────────────────────────────────────────────────
            if _CAPCUT_OK:
                _lv_voice_opts.extend([k for k in _cc.CAPCUT_VOICES if _lv_lang_flag in k])
            if _lv_lang_flag == "🇰🇷":
                _lv_voice_opts.extend(KOREAN_EDGE_VOICES)
            else:
                _lv_voice_opts.extend(list(EDGE_VOICES.keys()))

            # Default: ZeroTTS Mai Chi nếu có, không thì CapCut cũ
            _lv_def_idx = 0
            _lv_zt_default = "🇻🇳 Mai Chi — Nữ · Trẻ · Kể chuyện · Nhẹ nhàng · Thân thiện"
            if _lv_zt_default in _lv_voice_opts:
                _lv_def_idx = _lv_voice_opts.index(_lv_zt_default)
            elif "🇻🇳 Giọng Nam Trầm" in _lv_voice_opts:
                _lv_def_idx = _lv_voice_opts.index("🇻🇳 Giọng Nam Trầm")

            lv_voice_key = st.selectbox(
                "🎙️ Giọng TTS:",
                options=_lv_voice_opts,
                index=_lv_def_idx,
                key="lv_voice",
                help="⚡ ZeroTTS: offline · WER 1.03% · 8 giọng Việt có tag rõ ràng"
            )
        with _lv_c2:
            lv_tts_rate = st.selectbox(
                "⚡ Tốc độ TTS:",
                options=["0.8","0.9","1.0","1.1","1.2","1.3","1.4","1.5","1.6","1.7","1.8","2.0"],
                index=["0.8","0.9","1.0","1.1","1.2","1.3","1.4","1.5","1.6","1.7","1.8","2.0"].index(
                    st.session_state.lv_tts_rate
                ) if st.session_state.lv_tts_rate in ["0.8","0.9","1.0","1.1","1.2","1.3","1.4","1.5","1.6","1.7","1.8","2.0"] else 5,
                key="lv_tts_rate_sel",
                on_change=lambda: st.session_state.update({"lv_tts_rate": st.session_state["lv_tts_rate_sel"]})
            )
        with _lv_c3:
            lv_aspect = st.selectbox(
                "📐 Tỉ lệ:",
                options=["16:9", "9:16", "1:1"],
                index=["16:9","9:16","1:1"].index(st.session_state.lv_aspect) if st.session_state.lv_aspect in ["16:9","9:16","1:1"] else 0,
                key="lv_aspect_sel"
            )

        # BGM
        lv_bgm_file = st.file_uploader("🎵 Nhạc nền BGM (mp3/wav, tùy chọn):", type=["mp3","wav","m4a"], key="lv_bgm")
        if lv_bgm_file:
            lv_bgm_vol = st.slider("🔊 Volume BGM:", 0, 100, 20, key="lv_bgm_vol")
        else:
            lv_bgm_vol = 20

        lv_out_name = st.text_input(
            "💾 Tên file output:",
            value=output_file_stem(st.session_state.lv_title) or "video_dai",
            key="lv_out_name"
        )
        lv_out_dir = st.text_input(
            "📂 Thư mục lưu video:",
            value="/Users/zeworkcomputer/Documents/99999",
            key="lv_out_dir",
            help="Tool tự tạo nếu chưa có."
        )

        _lv_sub_c1, _lv_sub_c2, _lv_sub_c3 = st.columns([1, 2, 1])
        with _lv_sub_c1:
            lv_show_sub = st.checkbox("📝 Hiện subtitle", value=True, key="lv_show_sub")
        with _lv_sub_c2:
            lv_sub_style = st.selectbox(
                "Style sub:",
                options=list(SUB_STYLES.keys()),
                index=0,
                key="lv_sub_style",
                disabled=not lv_show_sub
            ) if lv_show_sub else list(SUB_STYLES.keys())[0]
        with _lv_sub_c3:
            lv_xfade_dur = st.slider("⏱️ Xfade (s):", 0.0, 1.0, 0.35, 0.05, key="lv_xfade_dur")

        st.divider()

        # ════════ D. RENDER ═══════════════════════════════════════════════════
        st.subheader("④ Render Video")
        _lv_total_dur = sum(s.get("duration", 5) for s in lv_scenes)
        st.caption(f"Tổng thời lượng ước tính: **{_lv_total_dur}s = {_lv_total_dur//60}m{_lv_total_dur%60}s** | {n_lv} cảnh")

        lv_do_render = st.button(
            f"▶️ Tạo Video Dài ({n_lv} cảnh)",
            key="lv_btn_render",
            type="primary",
            use_container_width=True,
            disabled=(n_lv == 0)
        )

        if lv_do_render:
            st.session_state.lv_render_log = []
            st.session_state.lv_final_path = None

            _lv_W, _lv_H = (1080, 1920) if "9:16" in lv_aspect else ((1080, 1080) if "1:1" in lv_aspect else (1920, 1080))
            _lv_work_dir = AUDIO_DIR / f"lv_{uuid.uuid4().hex[:8]}"
            _lv_work_dir.mkdir(parents=True, exist_ok=True)

            # Save BGM nếu có
            _lv_bgm_path = None
            if lv_bgm_file:
                _lv_bgm_path = _lv_work_dir / f"bgm_{lv_bgm_file.name}"
                _lv_bgm_path.write_bytes(lv_bgm_file.read())

            _lv_log_area = st.empty()
            _lv_prog = st.progress(0, text="Đang chuẩn bị...")
            _lv_scene_clips = []
            _lv_transitions = []  # transition per boundary
            _lv_errors = []

            # ── Alias normalize image effect ─────────────────────────────────
            _lv_ie_alias = {
                "slide_right":"pan_right","slide_left":"pan_left",
                "slide_up":"pan_up","slide_down":"pan_down",
                "ken_burns":"zoom_in","ken_burns_in":"zoom_in",
                "ken_burns_out":"zoom_out","zoomin":"zoom_in","zoomout":"zoom_out","zoom":"zoom_in"
            }
            _lv_ie_valid = {"zoom_in","zoom_out","pan_right","pan_left","pan_up","pan_down"}

            def _lv_log(msg):
                st.session_state.lv_render_log.append(msg)
                _lv_log_area.text_area("📋 Log:", "\n".join(st.session_state.lv_render_log[-30:]), height=200, key=f"lv_log_{len(st.session_state.lv_render_log)}")

            # ── Per-scene render loop ─────────────────────────────────────────
            for _lv_i, _lv_sc in enumerate(lv_scenes):
                _lv_pct = int((_lv_i) / n_lv * 90)
                _lv_prog.progress(_lv_pct, text=f"Cảnh {_lv_i+1}/{n_lv}...")
                _lv_log(f"━━ Cảnh {_lv_i+1}/{n_lv}: {str(_lv_sc.get('text',''))[:40]}...")

                _lv_s_dir = _lv_work_dir / f"scene_{_lv_i:04d}"
                _lv_s_dir.mkdir(exist_ok=True)
                _lv_clip_out = _lv_s_dir / "clip.mp4"

                try:
                    # Step 1: TTS + SRT → words
                    _lv_text = str(_lv_sc.get("text", "")).strip()
                    _lv_dur  = float(_lv_sc.get("duration", 5))
                    # UI global rate luôn được ưu tiên; per-scene tts_speed trong JSON chỉ dùng khi UI rate = default
                    _lv_sc_rate = lv_tts_rate
                    _lv_audio_path = _lv_s_dir / "tts.mp3"
                    _lv_srt_path   = _lv_s_dir / "tts.srt"
                    _lv_log(f"  🎙️ TTS ({_lv_sc_rate}x)...")
                    _lv_words = []
                    try:
                        _tts_ret = tts(_lv_text, voice_cfg=lv_voice_key, srt_out=str(_lv_srt_path), rate=_lv_sc_rate)
                        if _tts_ret and Path(_tts_ret).exists():
                            shutil.move(_tts_ret, str(_lv_audio_path))
                        if _lv_srt_path.exists() and _lv_srt_path.stat().st_size > 10:
                            _lv_words = srt_to_words(str(_lv_srt_path))
                            _lv_log(f"  ✅ TTS OK — {len(_lv_words)} words")
                    except Exception as _te:
                        _lv_log(f"  ⚠️ TTS lỗi: {_te} — dùng silence")
                        ffmpeg("-f","lavfi","-i",f"anullsrc=r=44100:cl=mono","-t",str(_lv_dur),
                               "-acodec","libmp3lame","-y",str(_lv_audio_path))

                    # Fallback words từ text + duration
                    if not _lv_words and _lv_text and _lv_audio_path.exists():
                        try:
                            _lv_pb = subprocess.run([FFMPEG,"-i",str(_lv_audio_path),"-f","null","-"],
                                                    capture_output=True, text=True)
                            _lv_ad = 0.0
                            for _ll in _lv_pb.stderr.split("\n"):
                                if "Duration:" in _ll:
                                    _lts = _ll.split("Duration:")[1].split(",")[0].strip()
                                    _lh,_lm,_ls = _lts.split(":")
                                    _lv_ad = int(_lh)*3600+int(_lm)*60+float(_ls)
                                    break
                            if _lv_ad > 0:
                                # Detect leading silence — find when speech actually starts
                                _lv_speech_start = 0.0
                                try:
                                    _lv_sil = subprocess.run(
                                        [FFMPEG, "-i", str(_lv_audio_path),
                                         "-af", "silencedetect=noise=-35dB:d=0.05",
                                         "-f", "null", "-"],
                                        capture_output=True, text=True
                                    )
                                    for _sil_ln in _lv_sil.stderr.split("\n"):
                                        if "silence_end:" in _sil_ln:
                                            _lv_speech_start = float(_sil_ln.split("silence_end:")[1].split("|")[0].strip())
                                            break
                                except Exception:
                                    pass
                                _lv_speech_dur = max(0.1, _lv_ad - _lv_speech_start)
                                _lv_toks = _lv_text.split()
                                _lv_td = _lv_speech_dur / max(len(_lv_toks),1)
                                _lv_words = [{"word":w,"start":_lv_speech_start+i*_lv_td,"end":_lv_speech_start+(i+1)*_lv_td} for i,w in enumerate(_lv_toks)]
                                _lv_log(f"  📝 Fallback words: {len(_lv_words)} từ (speech_start={_lv_speech_start:.2f}s, speech_dur={_lv_speech_dur:.2f}s)")
                        except Exception:
                            pass

                    # Step 1b: Subtitle ASS
                    _lv_ass_path = None
                    if lv_show_sub and HAS_SUB and _lv_words:
                        try:
                            _lv_ass_c = make_ass(_lv_words, W=_lv_W, H=_lv_H, style_name=lv_sub_style)
                            if _lv_ass_c:
                                _lv_ass_path = _lv_s_dir / "sub.ass"
                                _lv_ass_path.write_text(_lv_ass_c, encoding="utf-8")
                                _lv_log(f"  📝 Sub OK ({len(_lv_words)} words)")
                        except Exception as _lv_asse:
                            _lv_log(f"  ⚠️ Sub lỗi: {_lv_asse}")

                    def _lv_ass_vf(ap):
                        p = str(ap).replace("\\","\\\\").replace(":","\\:")
                        return f",format=yuv420p,ass='{p}'"
                    _lv_sub_vf = _lv_ass_vf(_lv_ass_path) if _lv_ass_path else ""

                    # Step 2: Ảnh
                    _lv_img_path = None
                    _lv_up_f = lv_img_map.get(_lv_i) if lv_img_map else None
                    if _lv_up_f is not None:
                        # Dùng ảnh upload
                        _lv_img_save = _lv_s_dir / f"img_{_lv_up_f.name}"
                        _lv_img_save.write_bytes(_lv_up_f.read())
                        _lv_img_path = _lv_img_save
                        _lv_log(f"  🖼️ Ảnh: {_lv_up_f.name}")
                    else:
                        # Thử Imagen 3
                        _lv_ip = (_lv_sc.get("imagePrompt") or _lv_sc.get("image_prompt") or "").strip()
                        if _lv_ip and cfg.get("gemini_api_key","").strip():
                            try:
                                _lv_log(f"  🤖 Imagen 3...")
                                _lv_img_url = generate_scene_image_ai(
                                    keyword=_lv_sc.get("keyword",""),
                                    image_prompt=_lv_ip,
                                    aspect="16:9" if _lv_W > _lv_H else ("9:16" if _lv_H > _lv_W else "1:1")
                                )
                                if _lv_img_url:
                                    _lv_img_dl = _lv_s_dir / "ai_img.jpg"
                                    download_url(_lv_img_url, str(_lv_img_dl))
                                    _lv_img_path = _lv_img_dl
                                    _lv_log(f"  ✅ Imagen OK")
                            except Exception as _ie2:
                                _lv_log(f"  ⚠️ Imagen lỗi: {_ie2} — nền đen")
                        else:
                            _lv_log(f"  ⬛ Không có ảnh — nền đen")

                    # Step 3: FFmpeg render cảnh (có sub)
                    _lv_ie_raw = (_lv_sc.get("imageEffect") or _lv_sc.get("image_effect") or "").strip()
                    _lv_ie_raw = _lv_ie_alias.get(_lv_ie_raw, _lv_ie_raw)
                    _lv_effect = _lv_ie_raw if _lv_ie_raw in _lv_ie_valid else None

                    if _lv_img_path and _lv_img_path.exists():
                        _lv_scale_f = make_image_effect_filter(_lv_W, _lv_H, _lv_dur, effect=_lv_effect)
                        _lv_vf = _lv_scale_f + _lv_sub_vf
                        _lv_cmd = [
                            "-i", str(_lv_img_path),
                            "-i", str(_lv_audio_path),
                            "-vf", _lv_vf,
                            "-t", str(_lv_dur),
                            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                            "-af", f"apad=whole_dur={_lv_dur}",
                            "-pix_fmt", "yuv420p",
                            "-map", "0:v", "-map", "1:a",
                            "-y", str(_lv_clip_out)
                        ]
                    else:
                        _lv_color = f"color=c=black:s={_lv_W}x{_lv_H}:r=30"
                        _lv_cmd = [
                            "-f", "lavfi", "-i", _lv_color,
                            "-i", str(_lv_audio_path),
                            "-vf", f"fps=30{_lv_sub_vf}",
                            "-t", str(_lv_dur),
                            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                            "-af", f"apad=whole_dur={_lv_dur}",
                            "-pix_fmt", "yuv420p",
                            "-map", "0:v", "-map", "1:a",
                            "-y", str(_lv_clip_out)
                        ]
                    ffmpeg(*_lv_cmd)
                    if _lv_clip_out.exists() and _lv_clip_out.stat().st_size > 1000:
                        _lv_scene_clips.append(_lv_clip_out)
                        # Lưu transition cho boundary này
                        _lv_tr_raw = str(_lv_sc.get("transition","fade")).strip().lower()
                        _lv_xfade_valid = {
                            "fade","dissolve","wipeleft","wiperight","wipeup","wipedown",
                            "slideleft","slideright","slideup","slidedown",
                            "smoothleft","smoothright","smoothup","smoothdown",
                        }
                        _lv_tr = _lv_tr_raw if _lv_tr_raw in _lv_xfade_valid else "fade"
                        _lv_transitions.append(_lv_tr)
                        _lv_log(f"  ✅ Render OK ({_lv_dur}s) | transition: {_lv_tr}")
                    else:
                        raise RuntimeError("Output file empty or missing")

                except Exception as _lv_err:
                    _lv_log(f"  ❌ Cảnh {_lv_i+1} lỗi: {_lv_err} — skip")
                    _lv_errors.append(_lv_i + 1)

            # ── Concat với xfade per-scene ─────────────────────────────────
            _lv_prog.progress(92, text="Ghép video với xfade...")
            _lv_log(f"\n🎬 Ghép {len(_lv_scene_clips)} clip...")

            if _lv_scene_clips:
                _lv_xd = float(lv_xfade_dur)
                _lv_out_dir_p = Path(lv_out_dir.strip()) if lv_out_dir.strip() else AUDIO_DIR
                _lv_out_dir_p.mkdir(parents=True, exist_ok=True)
                _lv_stem = output_file_stem(lv_out_name) or "video_dai"
                _lv_final = _lv_out_dir_p / f"{_lv_stem}.mp4"

                if len(_lv_scene_clips) == 1 or _lv_xd == 0:
                    # Concat thô nếu chỉ 1 clip hoặc xfade=0
                    _lv_concat_list = _lv_work_dir / "concat.txt"
                    with open(_lv_concat_list, "w") as _cf:
                        for _cp in _lv_scene_clips:
                            _cf.write(f"file '{_cp.as_posix()}'\n")
                    ffmpeg("-f","concat","-safe","0","-i",str(_lv_concat_list),"-c","copy","-y",str(_lv_final))
                else:
                    # Xfade filter_complex per-boundary
                    def _lv_probe_dur(path):
                        try:
                            pb = subprocess.run([FFMPEG,"-i",str(path),"-f","null","-"],capture_output=True,text=True)
                            for ln in pb.stderr.split("\n"):
                                if "Duration:" in ln:
                                    ts = ln.split("Duration:")[1].split(",")[0].strip()
                                    hh,mm,ss = ts.split(":")
                                    return int(hh)*3600+int(mm)*60+float(ss)
                        except Exception:
                            pass
                        return 0.0

                    _lv_n = len(_lv_scene_clips)
                    _lv_durs = [max(_lv_probe_dur(c), 1.0) for c in _lv_scene_clips]
                    _lv_inputs = []
                    for _cp in _lv_scene_clips:
                        _lv_inputs.extend(["-i", str(_cp)])

                    _lv_fparts = []
                    for _j in range(_lv_n):
                        _lv_fparts.append(f"[{_j}:v]copy[v{_j}]")

                    _lv_offset = _lv_durs[0] - _lv_xd
                    _lv_cur_v = "[v0]"
                    for _j in range(1, _lv_n):
                        _lv_nv = f"[xv{_j}]" if _j < _lv_n-1 else "[vout]"
                        _lv_tr_j = _lv_transitions[_j-1] if (_j-1) < len(_lv_transitions) else "fade"
                        _lv_fparts.append(f"{_lv_cur_v}[v{_j}]xfade=transition={_lv_tr_j}:duration={_lv_xd}:offset={_lv_offset:.3f}{_lv_nv}")
                        _lv_cur_v = _lv_nv
                        if _j < _lv_n-1:
                            _lv_offset += _lv_durs[_j] - _lv_xd

                    # Audio: trim xfade_dur cuối mỗi clip trung gian → tổng audio = tổng video
                    for _j in range(_lv_n):
                        if _j < _lv_n - 1:
                            _lv_trim_end = max(0.1, _lv_durs[_j] - _lv_xd)
                            _lv_fparts.append(f"[{_j}:a]atrim=0:{_lv_trim_end:.3f},asetpts=PTS-STARTPTS[la{_j}]")
                        else:
                            _lv_fparts.append(f"[{_j}:a]acopy[la{_j}]")
                    _lv_a_inputs = "".join(f"[la{_j}]" for _j in range(_lv_n))
                    _lv_fparts.append(f"{_lv_a_inputs}concat=n={_lv_n}:v=0:a=1[aout]")

                    _lv_xfade_out = _lv_work_dir / "xfade_out.mp4"
                    try:
                        ffmpeg(*_lv_inputs,"-filter_complex",";".join(_lv_fparts),
                               "-map","[vout]","-map","[aout]",
                               "-c:v","libx264","-preset","fast","-crf","20",
                               "-c:a","aac","-b:a","128k","-ar","44100",
                               "-movflags","+faststart","-y",str(_lv_xfade_out))
                        if _lv_xfade_out.exists() and _lv_xfade_out.stat().st_size > 10000:
                            import shutil as _shu; _shu.copy2(str(_lv_xfade_out), str(_lv_final))
                            _lv_log("✅ Xfade concat OK")
                        else:
                            raise RuntimeError("output rỗng")
                    except Exception as _lv_xe:
                        _lv_log(f"⚠️ Xfade lỗi: {_lv_xe} — fallback concat thô")
                        _lv_concat_list = _lv_work_dir / "concat.txt"
                        with open(_lv_concat_list,"w") as _cf:
                            for _cp in _lv_scene_clips: _cf.write(f"file '{_cp.as_posix()}'\n")
                        ffmpeg("-f","concat","-safe","0","-i",str(_lv_concat_list),"-c","copy","-y",str(_lv_final))

                # ── Mix BGM nếu có ───────────────────────────────────────────
                if _lv_bgm_path and _lv_bgm_path.exists() and _lv_final.exists():
                    _lv_prog.progress(96, text="Mix nhạc nền...")
                    _lv_log("🎵 Mix BGM...")
                    _lv_bgm_vol_f = lv_bgm_vol / 100.0
                    _lv_bgm_out = _lv_out_dir_p / f"{_lv_stem}_bgm.mp4"
                    try:
                        ffmpeg("-i",str(_lv_final),
                               "-stream_loop","-1","-i",str(_lv_bgm_path),
                               "-filter_complex",
                               f"[0:a]volume=1.0[tts];"
                               f"[1:a]volume={_lv_bgm_vol_f}[bgm];"
                               f"[tts][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                               "-map","0:v","-map","[aout]",
                               "-c:v","copy","-c:a","aac","-b:a","192k",
                               "-shortest","-y",str(_lv_bgm_out))
                        if _lv_bgm_out.exists():
                            import shutil as _shu2; _shu2.move(str(_lv_bgm_out), str(_lv_final))
                            _lv_log("✅ Mix BGM OK")
                    except Exception as _bg: _lv_log(f"⚠️ BGM lỗi: {_bg}")

                _lv_prog.progress(100, text="✅ Hoàn tất!")
                st.session_state.lv_final_path = str(_lv_final)
                _lv_log(f"\n🎉 XONG! File: {_lv_final}")
                if _lv_errors:
                    _lv_log(f"⚠️ Cảnh lỗi/skip: {_lv_errors}")
            else:
                _lv_log("❌ Không có clip nào render thành công.")
                st.error("Render thất bại — xem log bên dưới.")

        # ── Log hiển thị sau render ───────────────────────────────────────────
        if st.session_state.lv_render_log and not lv_do_render:
            st.text_area("📋 Log lần render trước:", "\n".join(st.session_state.lv_render_log), height=200, key="lv_log_prev")

        # ── Download ─────────────────────────────────────────────────────────
        if st.session_state.lv_final_path and Path(st.session_state.lv_final_path).exists():
            _lv_fp = Path(st.session_state.lv_final_path)
            _lv_mb = _lv_fp.stat().st_size / 1024 / 1024
            st.success(f"🎉 Video hoàn tất! ({_lv_mb:.1f} MB) — {_lv_fp.name}")
            st.video(_lv_fp.read_bytes())
            st.download_button(
                label=f"⬇️ Tải xuống {_lv_fp.name}",
                data=_lv_fp.read_bytes(),
                file_name=_lv_fp.name,
                mime="video/mp4",
                use_container_width=True,
                key="lv_download"
            )

    # ════════════════════════════════════════════════════════════
    # SHORT VIDEO TAB — Import JSON → Upload ảnh → Render nhanh
    # ════════════════════════════════════════════════════════════
