"""
app/ui/tab_pipeline.py — Main Pipeline Tab UI (5000+ lines).
Auto-generated from tool.py — wraps original tab body into a render function.
"""
import asyncio, json, os, re, uuid, base64, subprocess, shutil, time, tempfile, random, math
from typing import Optional
from pathlib import Path
import streamlit as st

def render_pipeline_tab(
    cfg, save_cfg, load_proj, save_proj,
    tts, ffmpeg, FFMPEG,
    call_ai, call_ai_script, parse_json_robust,
    fetch_stock_video, fetch_video_with_veo3,
    search_stock_videos, search_stock_photos,
    fetch_stock_photo, build_visual_prompts_batch,
    make_ass, make_srt, srt_from_audio,
    generate_thumbnail, generate_scene_image_ai,
    generate_scene_video_with_veo3, attach_veo3_video,
    make_image_effect_filter, make_video_intro_filter,
    apply_sound_effect_to_scene, probe_audio_duration, is_valid_audio,
    download_url, is_image_file,
    inject_region_into_keyword, enrich_keyword_with_context,
    clean_keyword, optimize_query_for_region,
    save_and_next_scene,
    IMAGE_EFFECTS, VIDEO_INTRO_EFFECTS, SOUND_EFFECTS, SUB_STYLES,
    EDGE_VOICES, KOREAN_EDGE_VOICES,
    HAS_SUB, _VEO3_OK, _veo3, TMP, AUDIO_DIR,
    **kw
):
    """Render Pipeline tab — main video creation workflow."""
    # ── Ensure stdlib imports available (Streamlit hot-reload safe) ──────────
    import asyncio, json, os, re, uuid, base64, subprocess, shutil
    import time, tempfile, random, math
    import requests
    from pathlib import Path
    from typing import Optional
    # ── App module imports ────────────────────────────────────────────────────
    from app.config import load_cfg, output_file_stem, available_output_path
    from app.project import get_proj_file
    from app.subtitle import make_srt, make_ass, srt_to_words, SUB_STYLES
    from app.media_fetch import (
        search_pexels_videos, search_pixabay_videos, search_coverr_videos,
        search_pexels_photos_only, search_pixabay_photos_only,
        _translate_keyword_to_en, clean_keyword, inject_region_into_keyword,
        optimize_query_for_region, fetch_stock_video, fetch_stock_photo,
        search_stock_videos, search_stock_photos, is_image_file,
    )
    from app.ffmpeg_utils import probe_audio_duration, download_url, is_valid_audio
    from app.effects import (
        make_image_effect_filter, make_video_intro_filter,
        apply_sound_effect_to_scene,
        IMAGE_EFFECTS, VIDEO_INTRO_EFFECTS, SOUND_EFFECTS,
    )
    from app.image_gen import generate_scene_image_ai, generate_thumbnail
    from app.tts_engine import tts_edge_with_timing
    from vietnamese_tts import normalize_vietnamese_tts
    # ── Unpack tool.py globals passed via **kw (với safe defaults) ───────────
    _SOCIAL_PUBLISHING_OK = kw.get("_SOCIAL_PUBLISHING_OK", False)
    _SOCIAL_STORE         = kw.get("_SOCIAL_STORE", None)
    _VEO3_OK              = kw.get("_VEO3_OK", False)
    _veo3                 = kw.get("_veo3", None)
    HAS_SUB               = kw.get("HAS_SUB", False)
    render_post_render_publish  = kw.get("render_post_render_publish", None)
    render_connection_settings  = kw.get("render_connection_settings", None)
    srt_from_audio              = kw.get("srt_from_audio", None)
    save_and_next_scene         = kw.get("save_and_next_scene", None)
    enrich_keyword_with_context = kw.get("enrich_keyword_with_context", lambda kw, **_: kw)
    build_visual_prompts_batch  = kw.get("build_visual_prompts_batch", None)
    fetch_video_with_veo3       = kw.get("fetch_video_with_veo3", None)
    generate_scene_video_with_veo3 = kw.get("generate_scene_video_with_veo3", None)
    attach_veo3_video           = kw.get("attach_veo3_video", None)
    EDGE_VOICES                 = kw.get("EDGE_VOICES", [])
    KOREAN_EDGE_VOICES          = kw.get("KOREAN_EDGE_VOICES", [])
    # CapCut / ZeroTTS
    _CAPCUT_OK   = kw.get("_CAPCUT_OK", False)
    _CAPCUT_SKIP = kw.get("_CAPCUT_SKIP", False)
    _cc          = kw.get("_cc", None)
    _ZEROTTS_OK  = kw.get("_ZEROTTS_OK", False)
    _zt          = kw.get("_zt", None)
    # Misc callbacks
    normalize_import_video_config = kw.get("normalize_import_video_config", None)
    build_veo3_prompt             = kw.get("build_veo3_prompt", None)
    _SOCIAL_STORE_obj = _SOCIAL_STORE  # alias dùng trong render_connection_settings


    # ── Loại video (trên cùng, ngoài sub-tab) ───────────────────────────────
    default_mode_idx = 1 if st.session_state.proj_mode == "shorts" else 0
    mode_selection = st.radio(
        "📂 Loại Video:",
        ["🎞️ Video Chính (Dài)", "⚡ Video Shorts (Độc lập)"],
        index=default_mode_idx,
        horizontal=True,
        help="Shorts = video độc lập, nội dung riêng, không liên quan đến video chính."
    )
    new_mode = "shorts" if "Shorts" in mode_selection or "⚡" in mode_selection else "main"
    if st.session_state.get("proj_mode") != new_mode:
        st.session_state.proj_mode = new_mode
        cfg["last_proj_mode"] = new_mode
        save_cfg(cfg)
        st.session_state.proj = load_proj()
        st.rerun()

    proj = st.session_state.proj

    # An imported video_config is applied before widgets are created. Streamlit
    # does not allow changing a widget's state after that widget rendered.
    _pending_import_cfg = proj.pop("pending_import_video_config", None)
    if _pending_import_cfg:
        if _pending_import_cfg.get("topic"):
            st.session_state[f"{new_mode}_custom_input"] = _pending_import_cfg["topic"]
        if "total_duration" in _pending_import_cfg:
            st.session_state[f"{new_mode}_total_duration"] = _pending_import_cfg["total_duration"]
        if "target_seconds_per_scene" in _pending_import_cfg:
            st.session_state[f"{new_mode}_seconds_per_scene"] = _pending_import_cfg["target_seconds_per_scene"]
        if "subtitles" in _pending_import_cfg:
            st.session_state[f"{new_mode}_show_subtitles"] = _pending_import_cfg["subtitles"]
        if _pending_import_cfg.get("tts_rate"):
            st.session_state["tts_rate_slider"] = _pending_import_cfg["tts_rate"]
            cfg["tts_rate"] = _pending_import_cfg["tts_rate"]
            save_cfg(cfg)
        save_proj(proj)

    col_left, col_right = st.columns([1, 1.6])

    with col_left:
        st.subheader("⚙️ Cấu hình")

        niche = st.selectbox("🎯 Chủ đề", [
            "technology","finance","health","science","motivation",
            "business","history","psychology","travel","food"
        ])
        if new_mode in ("shorts", "veo3"):
            custom = st.text_area(
                "🎥 Nội dung Video (mô tả càng cụ thể càng tốt)",
                placeholder=(
                    "Ví dụ:\n"
                    "Luận điểm chính: [1 câu cụ thể, có thể kiểm chứng]\n"
                    "Ví dụ hay: '90% người Việt thua lỗ chứng khoán không phải vì kém, mà vì 1 tâm lý cụ thể'\n"
                    "Ví dụ hay: 'Vì sao làm lương 30tr/tháng vẫn không dư được đồng nào — 2 nguyên nhân thực tế'\n"
                    "Thị trường: [Việt Nam / Korea / US]\n"
                    "Tone: [Thực tế gần gũi / Sốc & Gây tranh cãi / Giáo dục có dẫn chứng]"
                ),
                height=130,
                key=f"{new_mode}_custom_input"
            )
        else:
            custom = st.text_area("Hoặc nhập mô tả chi tiết (tùy chỉnh)", placeholder="Ví dụ:\nChủ đề: 한국 집값\nNội dung chính:\n- ...\nTôn màu: ...", height=150, key=f"{new_mode}_custom_input")
        default_dur = 60 if new_mode in ("shorts", "veo3") else 600
        duration = st.number_input("⏱️ Tổng thời lượng (giây)", min_value=15, max_value=18000, value=default_dur, step=30, key=f"{new_mode}_total_duration", help="Nhập thời lượng video tính bằng giây (VD: 600 = 10 phút, 1800 = 30 phút)")
        # Shorts: 5s/cảnh tối ưu cho nhịp độ TikTok/Reels; video dài: 7s/cảnh
        _default_sec_per_scene = 5 if new_mode in ("shorts", "veo3") else 7
        target_sec_per_scene = st.number_input("⏳ Nhịp độ 1 cảnh (giây)", min_value=3, max_value=30, value=_default_sec_per_scene, key=f"{new_mode}_seconds_per_scene", help="Shorts: 4–6s/cảnh để nhịp nhanh. Video dài: 7–10s/cảnh để câu thoại đủ ý.")
        style = st.selectbox("🎭 Phong cách", ["educational","storytelling","listicle","documentary","motivational"])

        st.markdown("**🪝 Kiểu Hook (3 giây đầu)**")
        hook_style = st.selectbox(
            "Chọn chiến thuật hook",
            [
                "🤯 Shock & Awe — Con số / sự thật gây sốc",
                "❓ Curiosity Gap — Câu hỏi bỏ lửng tạo tò mò",
                "🔥 Controversial — Phát biểu gây tranh cãi",
                "⚠️ Warning / Fear — Cảnh báo, nguy cơ",
                "🤫 Secret / Insider — Bí mật ít người biết",
                "🎭 Story / Relatable — Câu chuyện cá nhân",
                "📣 Bold Claim — Tuyên bố mạnh mẽ",
                "🎲 Random — AI tự chọn tốt nhất",
            ],
            index=7,
            help="Hook quyết định người xem có xem tiếp sau 3 giây đầu không!"
        )

        with st.expander("⚙️ Nâng cao: Retention Settings"):
            pattern_interrupt = st.checkbox(
                "🔀 Pattern Interrupt (thay đổi cảnh / twist mỗi 7-10s)",
                value=True,
                help="Tạo sự bất ngờ định kỳ để giữ chân người xem lâu hơn"
            )
            add_loop_teaser = st.checkbox(
                "🔄 Loop Teaser (kết video dẫn dắt xem lại)",
                value=True,
                help="Kết thúc video nhắc lại hook đầu để tạo loop tâm lý"
            )
            cta_style = st.selectbox(
                "📢 Call-to-Action",
                ["none", "follow", "comment", "share"],
                format_func=lambda x: {
                    "none":    "Không có",
                    "follow":  "Follow / Subscribe",
                    "comment": "Bình luận ý kiến",
                    "share":   "Share cho bạn bè",
                }.get(x, x),
                index=1
            )
            enable_transition = st.checkbox(
                "🎬 Hiệu ứng chuyển cảnh (Fade in/out)",
                value=False,
                help="Hiệu ứng mờ dần (Fade) có thể làm video bị đen khoảng 0.5s ở giữa các cảnh. Khuyên dùng: Tắt (cắt cảnh nhanh sẽ cuốn hút hơn)."
            )

        _saved_lang = proj.get("lang", "Vietnamese" if new_mode in ("shorts", "veo3") else "English")
        _lang_opts = ["English", "Vietnamese", "Korean", "Japanese"]
        _lang_idx = _lang_opts.index(_saved_lang) if _saved_lang in _lang_opts else 0
        lang = st.selectbox("🌍 Ngôn ngữ", _lang_opts, index=_lang_idx)
        if lang != proj.get("lang"):
            proj["lang"] = lang
            save_proj(proj)

        # ── Voice selector: CapCut voices if available, else Edge fallback ───
        if lang == "Korean":
            # Cả 9 ID CapCut Hàn cũ đều lỗi. Đây là toàn bộ voice ko-KR được
            # Edge công bố và đã tạo audio thành công ngày 2026-08-10.
            _ko_voice_opts = KOREAN_EDGE_VOICES or ["🇰🇷 SunHi (Nữ)", "🇰🇷 InJoon (Nam)", "🇰🇷 HyunSu (Nam)"]
            _ko_saved = proj.get("voice_cfg_key")
            _ko_default = _ko_saved if _ko_saved in _ko_voice_opts else _ko_voice_opts[0]
            voice = st.selectbox(
                "🔊 Giọng đọc tiếng Hàn (Edge TTS)",
                _ko_voice_opts,
                index=_ko_voice_opts.index(_ko_default) if _ko_default in _ko_voice_opts else 0,
                key="voice_edge_ko",
            )
            voice_cfg_key = voice
            if voice_cfg_key != proj.get("voice_cfg_key"):
                proj["voice_cfg_key"] = voice_cfg_key
                save_proj(proj)

            _valid_rates = ["0.8", "0.9", "1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "2.0"]
            # Korean TTS đọc chậm hơn tiếng Anh — mặc định 1.5x cho Shorts, 1.3x cho video dài
            _ko_default_rate = "1.5" if new_mode in ("shorts", "veo3") else "1.3"
            _default_rate = st.session_state.get("tts_rate_slider") or cfg.get("tts_rate", _ko_default_rate)
            if _default_rate not in _valid_rates:
                _default_rate = _ko_default_rate
            tts_rate = st.select_slider(
                "⚡ Tốc độ đọc",
                options=_valid_rates,
                value=_default_rate,
                key="tts_rate_slider",
            )
            if tts_rate != cfg.get("tts_rate"):
                cfg["tts_rate"] = tts_rate
                save_cfg(cfg)
            _force_edge = True
            _allow_voice_fallback = False
            st.info("🔒 Khóa giọng Hàn: chọn giọng nào dùng đúng giọng đó; TTS lỗi sẽ dừng render.")
        elif _ZEROTTS_OK and lang == "Vietnamese":
            # ── ZeroTTS local engine ── ưu tiên khi available ────────────────
            _zt_voices = _zt.list_display_voices()
            _saved_voice = proj.get("voice_cfg_key")
            _default_zt = _saved_voice if _saved_voice in _zt_voices else _zt_voices[0]
            voice = st.selectbox(
                "🔊 Giọng đọc (ZeroTTS — Local Offline)",
                _zt_voices,
                index=_zt_voices.index(_default_zt),
                key="voice_zerotts_sel",
                help="ZeroTTS: WER 1.03%, nhanh gấp 2× realtime, không cần internet sau khi tải model"
            )
            _valid_rates = ["0.8", "0.9", "1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "2.0"]
            _default_rate = st.session_state.get("tts_rate_slider") or cfg.get("tts_rate", "1.0")
            if _default_rate not in _valid_rates:
                _default_rate = "1.0"
            tts_rate = st.select_slider(
                "⚡ Tốc độ đọc",
                options=_valid_rates,
                value=_default_rate,
                key="tts_rate_slider",
                help="ZeroTTS không điều chỉnh tốc độ nội tại — giá trị này dùng cho metadata cache"
            )
            if tts_rate != cfg.get("tts_rate"):
                cfg["tts_rate"] = tts_rate
                save_cfg(cfg)
            voice_cfg_key = voice
            if voice_cfg_key != proj.get("voice_cfg_key"):
                proj["voice_cfg_key"] = voice_cfg_key
                save_proj(proj)
            _force_edge = False
            _allow_voice_fallback = False
            st.caption("🔒 Khóa giọng ZeroTTS: lỗi sẽ dừng, không tự đổi voice")
            st.info("⚡ ZeroTTS: offline · WER 1.03% · ~2× faster than realtime · 8 giọng Việt")
        elif _CAPCUT_OK:
            _lang_flag = {"Vietnamese": "🇻🇳", "English": "🇺🇸", "Korean": "🇰🇷", "Japanese": "🇯🇵"}.get(lang, "🇺🇸")
            _lang_code  = {"Vietnamese": "vi", "English": "en", "Korean": "ko", "Japanese": "ja"}.get(lang, "en")
            _voice_opts = [k for k in _cc.CAPCUT_VOICES if _lang_flag in k]

            # Khôi phục giọng đọc đã lưu nếu hợp lệ cho ngôn ngữ hiện tại
            _saved_voice = proj.get("voice_cfg_key")
            _default_voice = _saved_voice if _saved_voice in _voice_opts else _cc.CAPCUT_VOICE_DEFAULTS.get(_lang_code, _voice_opts[0])
            _default_idx   = _voice_opts.index(_default_voice) if _default_voice in _voice_opts else 0

            voice = st.selectbox(
                "🔊 Giọng đọc (CapCut)",
                _voice_opts,
                index=_default_idx,
                # Mỗi ngôn ngữ có state riêng; tránh đổi Vietnamese ↔ Korean
                # nhưng Streamlit vẫn giữ giọng của ngôn ngữ trước.
                key=f"voice_capcut_sel_{_lang_code}",
                help="Giọng CapCut AI chất lượng cao — không cần Edge TTS hay Groq"
            )
            # Rate slider — Shorts nên dùng 1.5x; video dài 1.0–1.2x
            _rate_key = "tts_rate_slider"
            _valid_rates = ["0.8", "0.9", "1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "2.0"]
            _default_rate = st.session_state.get(_rate_key) or cfg.get("tts_rate", "1.5" if new_mode == "shorts" else "1.0")
            if _default_rate not in _valid_rates:
                _default_rate = "1.5" if new_mode == "shorts" else "1.0"
            tts_rate = st.select_slider(
                "⚡ Tốc độ đọc",
                options=["0.8", "0.9", "1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "2.0"],
                value=_default_rate,
                key=_rate_key,
                help="Shorts: 1.3–1.6x để đọc nhanh, cuốn hút. Video dài: 1.0–1.2x nghe tự nhiên hơn."
            )
            # Persist rate vào cfg để không bị reset khi restart app
            if tts_rate != cfg.get("tts_rate"):
                cfg["tts_rate"] = tts_rate
                save_cfg(cfg)

            voice_cfg_key = voice  # CapCut key is passed directly
            if voice_cfg_key != proj.get("voice_cfg_key"):
                proj["voice_cfg_key"] = voice_cfg_key
                save_proj(proj)

            # Checkbox force Edge TTS — dùng khi CapCut bị stuck/timeout
            _force_edge = st.checkbox(
                "⚡ Bỏ CapCut → dùng Edge TTS thẳng (nhanh hơn, không bị stuck)",
                value=False,
                key="force_edge_tts",
                help="Bật khi CapCut TTS bị treo hoặc chậm. Edge TTS miễn phí, không cần poll."
            )
            if lang == "Vietnamese":
                # Một video Việt phải dùng đúng một engine/voice từ đầu đến cuối.
                # Fallback theo từng cảnh là nguyên nhân tạo đoạn nam/nữ/English lẫn nhau.
                _allow_voice_fallback = False
                st.caption("🔒 Khóa giọng Việt: CapCut lỗi sẽ dừng, không tự đổi voice ở riêng một cảnh.")
            else:
                _allow_voice_fallback = st.checkbox(
                    "Cho phép tự đổi sang giọng dự phòng khi CapCut lỗi",
                    value=False,
                    key="allow_voice_fallback",
                    help="Tắt để giữ đúng một giọng xuyên suốt video.",
                )
            if _force_edge:
                import sys as _sys2
                _mm2 = _sys2.modules.get("__main__") or _sys2.modules.get("tool")
                if _mm2:
                    _mm2._CAPCUT_SKIP = True
                st.info("✅ Đang dùng Edge TTS — bỏ qua CapCut hoàn toàn")
            st.caption(f"🔊 `{voice}` · ⚡ `{tts_rate}x` — hash sẽ thay đổi nếu bạn đổi giọng/tốc độ")

        else:
            st.warning("⚠️ CapCut TTS chưa sẵn sàng — dùng Edge TTS fallback")
            _edge_opts = [
                "en-US (Guy - Male)", "en-US (Jenny - Female)",
                "vi-VN (NamMinh)", "vi-VN (HoaiMy - Female)",
                "ko-KR (InJoon - Male)", "ko-KR (SunHi - Female)",
                "ja-JP (Keita - Male)", "ja-JP (Nanami - Female)",
            ]
            _legacy_map = {
                "en-US (Guy - Male)": "en-US",
                "en-US (Jenny - Female)": "en-female",
                "vi-VN (NamMinh)": "vi-VN",
                "vi-VN (HoaiMy - Female)": "vi-female",
                "ko-KR (InJoon - Male)": "ko-KR",
                "ko-KR (SunHi - Female)": "ko-female",
                "ja-JP (Keita - Male)": "ja-JP",
                "ja-JP (Nanami - Female)": "ja-female",
            }
            # Tìm kiếm giọng lưu từ project để đặt làm default
            _saved_voice = proj.get("voice_cfg_key")
            _default_edge_idx = 0
            if _saved_voice:
                for _k, _v in _legacy_map.items():
                    if _v == _saved_voice and _k in _edge_opts:
                        _default_edge_idx = _edge_opts.index(_k)
                        break
            voice = st.selectbox("🔊 Giọng đọc", _edge_opts, index=_default_edge_idx)
            tts_rate = "1.0"
            voice_cfg_key = _legacy_map.get(voice, "en-US")
            if voice_cfg_key != proj.get("voice_cfg_key"):
                proj["voice_cfg_key"] = voice_cfg_key
                save_proj(proj)
            _force_edge = True
            _allow_voice_fallback = True

        # Khôi phục aspect đã chọn trước đó; fallback theo mode nếu chưa có
        _saved_aspect = proj.get("aspect", "")
        if _saved_aspect in ["16:9 (YouTube)", "9:16 (Shorts/TikTok)"]:
            default_aspect = ["16:9 (YouTube)", "9:16 (Shorts/TikTok)"].index(_saved_aspect)
        else:
            default_aspect = 1 if new_mode in ("shorts", "veo3") else 0
        aspect = st.radio("📐 Tỉ lệ", ["16:9 (YouTube)","9:16 (Shorts/TikTok)"], index=default_aspect, horizontal=True)
        if aspect != proj.get("aspect"):
            proj["aspect"] = aspect
            save_proj(proj)
        show_sub = st.checkbox("💬 Thêm phụ đề (sub từng chữ)", value=True, key=f"{new_mode}_show_subtitles")
        if show_sub:
            sub_style = st.selectbox(
                "🎨 Style phụ đề",
                list(SUB_STYLES.keys()),
                index=0,
                help="Chọn màu highlight cho từ đang nói — kiểu TikTok/Shorts viral"
            )
        else:
            sub_style = "🟡 TikTok Yellow (Viral)"

        st.markdown("**🎵 Nhạc nền (Tùy chọn)**")
        bgm_file = st.file_uploader("Tải lên file nhạc (.mp3, .wav, .m4a)", type=["mp3", "wav", "m4a", "aac"])

        # ── Local BGM path: thay thế cho file uploader khi không muốn upload ──
        # Quét thư mục project để gợi ý file nhạc có sẵn
        _bgm_local_opts = ["(Không dùng)"]
        _bgm_scan_dirs  = [
            Path.home() / "Documents" / "99999" / "music",
        ]
        _bgm_found = {}
        for _d in _bgm_scan_dirs:
            if _d.exists():
                for _f in sorted(_d.glob("*.mp3")) + sorted(_d.glob("*.wav")) + sorted(_d.glob("*.m4a")):
                    _label = f"{_f.name}  [{_d.name}/]"
                    _bgm_found[_label] = str(_f)
                    _bgm_local_opts.append(_label)
        _bgm_local_sel = st.selectbox(
            "📂 Hoặc chọn nhạc từ máy (project / Downloads / Music)",
            _bgm_local_opts,
            key="bgm_local_sel",
            help="Quét tự động các file nhạc trong thư mục project, Downloads, Music, Desktop"
        )
        _bgm_local_path = _bgm_found.get(_bgm_local_sel) if _bgm_local_sel != "(Không dùng)" else None

        _has_bgm = bgm_file or _bgm_local_path
        bgm_vol = st.slider("🔊 Âm lượng nhạc nền", min_value=0.01, max_value=0.5, value=0.1, step=0.01) if _has_bgm else 0.1

        tts_vol = st.slider(
            "🎤 Âm lượng giọng đọc (TTS)",
            min_value=1.0, max_value=3.0, value=1.5, step=0.1,
            help="Tăng âm lượng giọng đọc toàn video. 1.0 = bình thường, 1.5 = to hơn 50%, 2.0 = gấp đôi. Nếu video nghe nhỏ, hãy tăng lên 1.8–2.0.",
            key=f"{new_mode}_tts_vol"
        )

        intro_vol_boost = st.slider(
            "📢 Boost âm lượng Hook (cảnh 1)",
            min_value=1.0, max_value=3.0, value=1.5, step=0.1,
            help="Tăng âm lượng giọng đọc của cảnh đầu tiên để giật sự chú ý người xem ngay từ giây 0. Tính chỉnh lấy theo tts_vol × boost này.",
            key=f"{new_mode}_intro_vol_boost"
        )

        output_name = st.text_input(
            "📁 Tên file video đầu ra",
            value=proj.get("output_name", ""),
            placeholder="Ví dụ: video_bat_dong_san_thang_8 (bỏ trống để dùng tiêu đề)",
            key=f"{new_mode}_output_name",
            help="Không cần gõ .mp4. Nếu tên đã tồn tại, app tự thêm _2, _3 để không ghi đè video cũ.",
        )
        if output_name != proj.get("output_name", ""):
            proj["output_name"] = output_name
            save_proj(proj)

        # Dimensions
        if "9:16" in aspect:
            W, H = 1080, 1920
        else:
            W, H = 1920, 1080

        # ── Action buttons cuối cấu hình ────────────────────────────────────
        st.divider()
        # Checkbox được render ở đây khi chưa có kịch bản.
        # Khi đã có kịch bản, nó được render ngư trước nút Tạo Video (bên dưới) để gần ngắn hơn.
        if not proj.get("script"):
            use_ai_images = st.checkbox(
                "🎨 Dùng Ảnh tĩnh AI (100% Unique - Khuyên dùng)",
                value=True,
                key="use_ai_images_main",
                help="Tự động tạo ảnh bằng AI (Gemini) thay vì dùng video stock, giúp video không bao giờ bị đánh gậy Reused Content của YouTube."
            )
        else:
            # Chưa render checkbox ở đây, sẽ render ngắn ngay trước nút Tạo Video
            use_ai_images = st.session_state.get("use_ai_images_main", True)

        # ── Helper: build export prompt từ cấu hình hiện tại ────────────────
        def _build_export_prompt():
            _ep_topic  = custom.strip() or niche
            _ep_sc     = max(2, round(duration / target_sec_per_scene))
            _wps_map   = {"Vietnamese": 3.8, "Korean": 1.8, "English": 2.2}  # Korean: 1.8 eojeol/s — slower per unit than English
            _min_map   = {"Vietnamese": 35,  "Korean": 18,  "English": 18}
            _base_wps  = _wps_map.get(lang, 2.2)
            _wps       = _base_wps * float(tts_rate)
            _wpsc      = max(_min_map.get(lang, 18), round(target_sec_per_scene * _wps))
            _kw_ex     = {
                "Korean":     '"young Korean man stressed apartment"',
                "Vietnamese": '"Vietnamese street scene urban"',
            }.get(lang, '"person stressed desk office"')
            _lang_rule = {
                "Korean":     "Write 100% in natural Korean (해요체, Hangul only, NO Hanja, NO Chinese characters).",
                "Vietnamese": "Write 100% in natural Vietnamese with full diacritics (có dấu đầy đủ).",
                "English":    "Write in clear, punchy, natural English.",
            }.get(lang, "Write in the selected language.")
            return (
                f"[AI VIDEO SCRIPT — {lang.upper()}]\n"
                f"You are an elite short-form video scriptwriter. Generate a viral {style} script.\n\n"
                f"=== VIDEO SPECS ===\n"
                f"Topic: {_ep_topic}\n"
                f"Language: {lang} — {_lang_rule}\n"
                f"Total duration: {duration}s | Scenes: {_ep_sc} | Words/scene: ~{_wpsc}\n"
                f"Hook style: {hook_style}\n\n"
                f"=== LANGUAGE & GRAMMAR PURITY (HARD RULES — VIOLATIONS = REJECTED) ===\n"
                f"1. 100% native {lang}. ZERO mixing other languages (exception: OECD, GDP, FED etc.).\n"
                f"2. NO HALLUCINATION: Use only real, correctly-spelled words. NEVER invent nonexistent words.\n"
                f"   Korean example: use '치솟고' NOT '취속고'. Vietnamese: use 'tăng vọt' NOT 'tăng vọt vọt'.\n"
                f"3. NO STUTTERING: NEVER repeat a word consecutively.\n"
                f"   FORBIDDEN: '이를 이를', '그래서 그래서', 'của của', 'và và', 'the the'.\n"
                f"4. TONE: Aggressive, street-smart TikTok financial analyst. Punchy, NOT academic/robotic.\n\n"
                + (
                    "5. VIETNAMESE TTS TEXT: In every text field, spell out ALL numbers, "
                    "percentages and English terms exactly as natural Vietnamese speech. "
                    "Write 'chín mươi lăm phần trăm', never '95%'; write "
                    "'a phi li ét', 'tíc tốc shop', never 'Affiliate', 'TikTok Shop'.\n\n"
                    if lang == "Vietnamese" else ""
                )
                +
                f"=== HOOK (SCENE 1) ===\n"
                f"Style: {hook_style}\n"
                f"MUST trigger immediate emotion (shock/fear/curiosity) in max 1.5 seconds.\n"
                f"FORBIDDEN openers: 'Many people wonder...', '오늘은 ~에 대해', 'Hôm nay mình sẽ chia sẻ'.\n\n"
                f"=== FINAL SCENE CTA ===\n"
                f"MUST end with a provocative question forcing comments.\n"
                f"FORBIDDEN: 'Follow for more', '팔로우해주세요', 'Follow để biết thêm'.\n\n"
                f"=== ANTI-REPETITION ===\n"
                f"Each scene = 1 completely NEW idea. NEVER reuse the same concept across scenes.\n\n"
                f"=== VISUAL DESCRIPTION ===\n"
                f"For each scene, add one concise English veo3_prompt (80–160 words). "
                f"Describe subject, action and environment first, followed by camera, lighting, ambient audio and a short avoid list. "
                f"No brand-name cameras, fake resolution claims, narration or dialogue.\n\n"
                f"=== RETURN FORMAT (ONLY valid JSON — no markdown, no explanation) ===\n"
                f'{{\n'
                f'  "video_config": {{\n'
                f'    "topic": {json.dumps(_ep_topic, ensure_ascii=False)},\n'
                f'    "language": "{lang}",\n'
                f'    "total_duration": {duration},\n'
                f'    "target_seconds_per_scene": {target_sec_per_scene},\n'
                f'    "aspect_ratio": "{"9:16" if "9:16" in aspect else "16:9"}",\n'
                f'    "tts_rate": {float(tts_rate):.1f},\n'
                f'    "tts_speed": {float(tts_rate):.1f},\n'
                f'    "base_words_per_second": {_base_wps:.1f},\n'
                f'    "actual_words_per_second": {_wps:.2f},\n'
                f'    "target_words_per_scene": {_wpsc},\n'
                f'    "subtitles": {str(bool(show_sub)).lower()}\n'
                f'  }},\n'
                f'  "title": "viral title in {lang} (max 60 chars)",\n'
                f'  "description": "SEO description in {lang} (150-200 words)",\n'
                f'  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],\n'
                f'  "scenes": [\n'
                f'    {{\n'
                f'      "id": 1,\n'
                f'      "text": "narration in {lang} — exactly {_wpsc} words",\n'
                f'      "keyword": {_kw_ex},\n'
                f'      "duration": {target_sec_per_scene},\n'
                f'      "veo3_prompt": "Concise English visual prompt following the canonical format",\n'
                f'      "imagePrompt": "Short English image-gen prompt (20–60 words). Photorealistic, cinematic. Describe the SUBJECT + MOOD + LIGHTING. No text, no logos. Used to generate a still image via AI (Imagen/Flux/Midjourney).",\n'
                f'      "soundEffect": "none|whoosh|click|chime|deep_hit",\n'
                f'      "tts_speed": {float(tts_rate):.1f},\n'
                f'      "retention_note": "why viewer stays"\n'
                f'    }}\n'
                f'  ]\n'
                f'}}\n\n'
                f"soundEffect rules: \"whoosh\" = fast scene transition; \"click\" = slide/reveal; \"chime\" = positive/warm; \"deep_hit\" = shocking/tense; \"none\" = neutral/default. Pick the best match per scene mood.\n"
                f"imagePrompt rules: Short (20–60 words), English only, photorealistic cinematic still image. MUST describe a concrete visual: person/object/scene + dramatic lighting + mood. Example: 'A worried Vietnamese man staring at stock market screen, red candlestick charts, dark office, dramatic side lighting, cinematic, hyperrealistic.' NO abstract concepts, no text overlay, no logos.\n"
                f"tts_speed: reading speed for this scene (float 0.8–2.0). Use the global tts_rate ({float(tts_rate):.1f}) unless the scene needs a different pace (e.g. slower for emotional scenes, faster for rapid-fire facts).\n"
                f"Write EXACTLY {_ep_sc} scenes (id 1 to {_ep_sc}). Each narration ~{_wpsc} words.\n"
                f"Set \"duration\" = reading time in seconds (word_count / {round(_wps, 1):.1f} wps, min 3s, max {round(target_sec_per_scene * 1.5):.0f}s).\n"
                f"Return ONLY the JSON."
            )

        # ── 2 nút chính: Tự động | Thủ công ────────────────────────────────
        if not proj.get("script"):
            _btn_col1, _btn_col2 = st.columns(2)
            with _btn_col1:
                gen_script = st.button(
                    "📝 Tạo Kịch Bản\n(Tự động · AI viết luôn)",
                    type="primary", use_container_width=True,
                    help="AI tự tạo kịch bản và chạy toàn bộ pipeline"
                )
            with _btn_col2:
                _export_clicked = st.button(
                    "📤 Xuất Prompt\n(Thủ công · Copy vào ChatGPT)",
                    use_container_width=True,
                    help="Tạo prompt chuẩn để bạn tự copy vào ChatGPT/Claude rồi paste JSON trở lại"
                )
            if _export_clicked:
                st.session_state["_gpt_export_prompt"] = _build_export_prompt()
        else:
            gen_script     = None
            _export_clicked = False

        # ── Hiển thị prompt vừa xuất (nếu có) ──────────────────────────────
        if st.session_state.get("_gpt_export_prompt") and not proj.get("script"):
            st.markdown("---")
            st.markdown("**📋 Prompt — Ctrl+A → Ctrl+C để copy, rồi paste vào ChatGPT / Claude / Gemini:**")
            st.text_area(
                label="Prompt content",
                label_visibility="collapsed",
                value=st.session_state["_gpt_export_prompt"],
                height=300,
                key="export_prompt_display",
            )
            st.info("💡 Copy JSON kết quả → mở **▼ Nhập JSON từ ChatGPT** bên dưới để tiếp tục.")
            if st.button("🗑️ Xóa prompt", key="btn_clear_prompt"):
                del st.session_state["_gpt_export_prompt"]
                st.rerun()

        # ── Import JSON (expander gọn) ───────────────────────────────────────
        with st.expander("📥 Nhập JSON từ ChatGPT → tiếp tục STEP 2", expanded=False):
            # ── Hai cách nhập: Upload file hoặc Paste text ──────────────────
            _json_tab_upload, _json_tab_paste = st.tabs(["📂 Upload file .json", "📋 Paste JSON"])

            with _json_tab_upload:
                _json_uploaded = st.file_uploader(
                    "Chọn file JSON kịch bản:",
                    type=["json"],
                    key="import_json_file",
                    help="Upload file .json xuất từ ChatGPT / công cụ khác"
                )
                if _json_uploaded is not None:
                    _json_file_content = _json_uploaded.read().decode("utf-8")
                    st.session_state["_import_json_from_file"] = _json_file_content
                    st.caption(f"✅ Đã đọc: `{_json_uploaded.name}` ({len(_json_file_content):,} ký tự)")
                    try:
                        _preview_parsed = json.loads(_json_file_content)
                        _n_scenes = len(_preview_parsed.get("scenes", []))
                        _title_prev = _preview_parsed.get("title", "(chưa có tiêu đề)")
                        st.info(f"📄 **{_title_prev}** — {_n_scenes} cảnh")
                    except Exception:
                        st.warning("⚠️ Không parse được JSON — kiểm tra lại file.")

            with _json_tab_paste:
                # Nếu vừa upload file → pre-fill text area
                _prefill = st.session_state.pop("_import_json_from_file", "")
                _import_raw = st.text_area(
                    "Paste JSON kịch bản vào đây:",
                    value=_prefill,
                    placeholder='{"title": "...", "scenes": [{"id": 1, "text": "...", "keyword": "...", "veo3_prompt": "..."}]}',
                    height=180,
                    key="import_json_input",
                )

            # Nút apply chung cho cả hai mode
            # Lấy nội dung: ưu tiên từ text area (tab paste), fallback sang file đã upload
            _json_to_process = (
                _import_raw.strip()
                if "_import_raw" in dir() and _import_raw.strip()
                else (st.session_state.get("_import_json_from_file") or "").strip()
            )
            # Trong tab upload: lấy trực tiếp từ file nếu text area chưa có nội dung
            if not _json_to_process and _json_uploaded is not None:
                _json_to_process = _json_uploaded.getvalue().decode("utf-8").strip() if hasattr(_json_uploaded, "getvalue") else ""

            if st.button("✅ Nhập JSON → Bắt đầu STEP 2", key="btn_import_json", type="primary"):
                if not _json_to_process:
                    st.error("⚠️ Chưa có dữ liệu JSON — hãy upload file hoặc paste vào ô bên trên.")

                else:
                    try:
                        _imp = parse_json_robust(_json_to_process)
                        _import_cfg = normalize_import_video_config(_imp.get("video_config"))
                        _imp_topic = _import_cfg.get("topic", custom.strip() or niche)
                        _imp_lang = _import_cfg.get("language", lang)
                        _imp_rate = _import_cfg.get("tts_rate", str(tts_rate))
                        _imp_target = _import_cfg.get("target_seconds_per_scene", target_sec_per_scene)
                        _imp_scenes = _imp.get("scenes", [])
                        if not _imp_scenes:
                            st.error("❌ JSON thiếu trường 'scenes' — kiểm tra lại output của ChatGPT.")
                        else:
                            for _s in _imp_scenes:
                                _rt = _s.get("text", "")
                                _ct = re.sub(r'\b(\w+)( \1\b)+', r'\1', _rt)
                                _s["text"] = " ".join(_ct.split())
                                if not _s.get("keyword"):
                                    _s["keyword"] = _imp_topic
                                if not _s.get("veo3_prompt"):
                                    _s["veo3_prompt"] = f"Cảnh về {_imp_topic}, cinematic, 4K"
                            _imp_script = {
                                "title":       _imp.get("title", _imp_topic),
                                "description": _imp.get("description", ""),
                                "tags":        _imp.get("tags", []),
                                "video_config": _imp.get("video_config", {}),
                                "scenes":      _imp_scenes,
                            }
                            # ── Pre-populate proj["scenes"] để edit UI hoạt động ngay ──
                            _wps_map_imp = {"Vietnamese": 3.8, "Korean": 1.8, "English": 2.2, "Japanese": 1.8}
                            _wps_imp = _wps_map_imp.get(_imp_lang, 2.2) * float(_imp_rate)
                            _tgt_imp = float(_imp_target)
                            _imp_built_scenes = []
                            for _ii, _sc in enumerate(_imp_scenes):
                                _txt = _sc.get("text", "")
                                # External prompt schema uses target_duration;
                                # older exports used duration. Accept both.
                                _json_dur = _sc.get("target_duration") or _sc.get("duration")
                                if _json_dur and isinstance(_json_dur, (int, float)) and 1 <= float(_json_dur) <= 60:
                                    _dur = round(float(_json_dur), 1)
                                else:
                                    _is_korean = _imp_lang in ("Korean", "Japanese")
                                    if _is_korean or not any("A" <= c <= "z" for c in _txt[:20]):
                                        _dur_raw = max(len(_txt.replace(" ",""))/3.0, len(_txt.split())/max(_wps_imp,0.1))
                                    else:
                                        _dur_raw = len(_txt.split()) / max(_wps_imp, 0.1)
                                    _dur = round(min(max(_dur_raw + 0.4, 3.0), _tgt_imp * 1.5), 1)
                                # Đọc tốc độ đọc riêng của cảnh từ JSON (các alias phổ biến)
                                _sc_speed_raw = (_sc.get("tts_speed") or _sc.get("reading_speed")
                                                 or _sc.get("voice_speed"))
                                _valid_rates_imp = ["0.8","0.9","1.0","1.1","1.2","1.3","1.4","1.5","1.6","1.7","1.8","2.0"]
                                if _sc_speed_raw is not None:
                                    try:
                                        _sc_spd = float(_sc_speed_raw)
                                        _sc_tts_speed = f"{min([0.8,0.9,1.0,1.1,1.2,1.3,1.4,1.5,1.6,1.7,1.8,2.0], key=lambda x: abs(x - _sc_spd)):.1f}"
                                    except (TypeError, ValueError):
                                        _sc_tts_speed = None
                                else:
                                    _sc_tts_speed = None  # None = dùng tốc độ chung của dự án
                                # Đọc imagePrompt từ JSON nếu có (dùng cho Imagen thay vì keyword)
                                _img_prompt_raw = (_sc.get("imagePrompt") or _sc.get("image_prompt") or "").strip() or None
                                # Đọc imageEffect (alias: image_effect) + normalize tên khác nhau
                                _ie_raw = (_sc.get("imageEffect") or _sc.get("image_effect") or "").strip()
                                _ie_alias = {"slide_right":"pan_right","slide_left":"pan_left",
                                             "slide_up":"pan_up","slide_down":"pan_down",
                                             "ken_burns":"zoom_in","ken_burns_in":"zoom_in",
                                             "ken_burns_out":"zoom_out","zoomin":"zoom_in",
                                             "zoomout":"zoom_out","zoom":"zoom_in"}
                                _ie_valid = {"zoom_in","zoom_out","pan_right","pan_left","pan_up","pan_down"}
                                _ie_raw = _ie_alias.get(_ie_raw, _ie_raw)
                                _img_effect_imp = _ie_raw if _ie_raw in _ie_valid else None
                                _imp_built_scenes.append({
                                    "id":          _sc.get("id", _ii + 1),
                                    "section":     _sc.get("section", ""),
                                    "text":        _txt,
                                    "word_count":  _sc.get("word_count", len(_txt.split())),
                                    "keyword":     _sc.get("keyword", _imp_topic),
                                    "veo3_prompt": _sc.get("veo3_prompt", f"Cảnh về {_imp_topic}, cinematic, 4K"),
                                    "imagePrompt": _img_prompt_raw,
                                    "imageEffect": _img_effect_imp,
                                    "soundEffect": _sc.get("soundEffect", "none") if _sc.get("soundEffect") in ("none", "whoosh", "click", "chime", "deep_hit") else "none",
                                    "retention_note": _sc.get("retention_note", ""),
                                    "estimated_tts_duration": _sc.get("estimated_tts_duration"),
                                    "tts_speed":   _sc_tts_speed,
                                    "videoUrl":    None,
                                    "veo3Path":    None,
                                    "imageUrl":    None,
                                    "customVid":   None,
                                    "audioDone":   False,
                                    "targetDur":   _tgt_imp,
                                    "duration":    _dur,
                                })
                            st.session_state.proj["script"] = _imp_script
                            st.session_state.proj["step"]   = 1
                            st.session_state.proj["scenes"] = _imp_built_scenes
                            st.session_state.proj["lang"]   = _imp_lang
                            if _import_cfg.get("aspect"):
                                st.session_state.proj["aspect"] = _import_cfg["aspect"]
                            st.session_state.proj["video_config"] = _imp.get("video_config", {})
                            st.session_state.proj["pending_import_video_config"] = _import_cfg
                            st.session_state.proj["target_sec_per_scene"] = _tgt_imp
                            _pid = st.session_state.proj.get("id", "")
                            for _ci in range(len(_imp_built_scenes) + 5):
                                _dk = f"auto_vid_done_{_pid}{_ci}"
                                if _dk in st.session_state: del st.session_state[_dk]
                                for _k in list(st.session_state.keys()):
                                    if _k.startswith(f"kw_trans_{_ci}_"): del st.session_state[_k]
                                # Xóa widget keys để Streamlit đọc lại từ proj["scenes"] sau import
                                for _wk in [f"img_effect_{_ci}", f"img_prompt_{_ci}",
                                            f"veo3_{_ci}", f"kw_{_ci}", f"text_{_ci}"]:
                                    if _wk in st.session_state: del st.session_state[_wk]
                            save_proj(st.session_state.proj)
                            if "_gpt_export_prompt" in st.session_state:
                                del st.session_state["_gpt_export_prompt"]
                            st.success(f"✅ Đã nhập {len(_imp_scenes)} cảnh! Duyệt kịch bản bên dưới, chọn video nền (tùy chọn) → nhấn **🚀 Tạo Video** khi sẵn sàng.")
                            st.rerun()
                    except Exception as _ie:
                        st.error(f"❌ Lỗi parse JSON: {_ie}\n\nĐảm bảo output ChatGPT là JSON thuần — không có ```json``` bao quanh.")
        if proj.get("script"):
            # Hiển thị tùy chọn footage ngay trước nút Tạo Video
            # Giúp user thấy được dù luồng Import JSON hay luồng Tạo kịch bản
            _scenes_run = any(s.get("audioFile") for s in proj.get("scenes", []))
            if not _scenes_run:
                st.markdown("**🎬 Chọn nguồn footage:**")
                use_ai_images = st.checkbox(
                    "🎨 Dùng Ảnh tĩnh AI (100% Unique, tránh bị gậy Reused Content)",
                    value=st.session_state.get("use_ai_images_main", True),
                    key="use_ai_images_confirm",
                    help="Bật → AI tạo ảnh unique (Gemini Imagen). Tắt → tool tự tìm video stock Pexels/Pixabay."
                )
        run_all    = st.button("🚀 Tạo Video (Footage + TTS + Render)", type="primary", use_container_width=True) if proj.get("script") else None
        run_render = st.button("🎥 Chỉ Render Video", use_container_width=True) if proj.get("scenes") else None
        reset_btn  = st.button("🗑️ Xóa & làm lại", use_container_width=True) if proj.get("script") else None

        # ── Preview kịch bản + chọn video nền thủ công ───────────────────
        _scr = proj.get("script")
        _sc_list = (_scr.get("scenes") or []) if _scr else []
        if _sc_list and proj.get("step", 0) < 4:
            # Auto-mở preview khi vừa tạo kịch bản / vừa nhập JSON (step=1, pipeline chưa chạy)
            _scenes_have_audio = any(s.get("audioFile") for s in proj.get("scenes", []))
            _preview_auto_open = (proj.get("step", 0) == 1 and not _scenes_have_audio)
            with st.expander(f"🎬 Preview kịch bản ({len(_sc_list)} cảnh) — tùy chọn thay video nền", expanded=_preview_auto_open):
                _AUTO_MIX = 3  # giống AUTO_MIX_PHOTO_EVERY trong pipeline
                # Xác định loại footage dự kiến theo cùng logic pipeline
                _use_ai = st.session_state.get("use_ai_images_confirm",
                          st.session_state.get("use_ai_images_main", True))
                if _use_ai:
                    _badge_legend = "🤖 AI Image · 🎬 Video stock (cứ 3 cảnh AI → xen 1 ảnh stock)"
                else:
                    _badge_legend = "🎬 Video stock · 🖼️ Ảnh stock (cứ 3 cảnh video → xen 1 ảnh)"
                st.caption(f"💡 Để trống → tool tự tìm footage tự động ({_badge_legend}). Upload file → ưu tiên dùng video của bạn.")
                _custom_changed = False
                _vis_counter = 0  # đếm cảnh chưa có custom để tính xen kẽ
                for _si, _sc_item in enumerate(_sc_list):
                    _c1, _c2 = st.columns([3, 2])
                    # Lấy trạng thái thực từ proj["scenes"] nếu có
                    _proj_scenes = proj.get("scenes", [])
                    _proj_sc = _proj_scenes[_si] if _si < len(_proj_scenes) else {}
                    _has_custom = _proj_sc.get("customVid") or _proj_sc.get("videoUrl") or _proj_sc.get("imageUrl")
                    # Tính badge dự kiến (chỉ khi chưa có footage)
                    if not _has_custom:
                        _is_planned_photo = (_si > 0) and (_vis_counter % _AUTO_MIX == _AUTO_MIX - 1) and not _use_ai
                        _is_planned_ai    = _use_ai and not (_si > 0 and _vis_counter % _AUTO_MIX == _AUTO_MIX - 1)
                        if _is_planned_photo:
                            _footage_badge = "🖼️ *Ảnh stock (Ken Burns)*"
                        elif _use_ai:
                            _footage_badge = "🤖 *AI Image (Gemini)*"
                        else:
                            _footage_badge = "🎬 *Video stock (Pexels)*"
                        _vis_counter += 1
                    else:
                        _footage_badge = f"✅ *{'Custom' if _proj_sc.get('customVid') else ('Ảnh' if _proj_sc.get('imageUrl') else 'Video')}*"
                    with _c1:
                        _txt = _sc_item.get("text", "")
                        st.markdown(f"**Cảnh {_si+1}:** {_txt[:120]}{'...' if len(_txt) > 120 else ''}")
                        st.caption(f"🔍 Keyword: `{_sc_item.get('keyword', '')}` | {_footage_badge}")
                        _ip_preview = (_sc_item.get("imagePrompt") or "").strip()
                        if _ip_preview:
                            st.caption(f"🖼️ *Prompt ảnh:* {_ip_preview[:120]}{'...' if len(_ip_preview) > 120 else ''}")
                    with _c2:
                        _uploaded = st.file_uploader(
                            f"Video nền cảnh {_si+1}",
                            type=["mp4", "mov", "avi", "webm"],
                            key=f"custom_vid_{_si}",
                            label_visibility="collapsed",
                        )
                        if _uploaded is not None:
                            _save_dir = Path("/tmp/ai_video_custom")
                            _save_dir.mkdir(exist_ok=True)
                            _save_path = _save_dir / f"custom_scene_{_si}_{_uploaded.name}"
                            _save_path.write_bytes(_uploaded.read())
                            # Ghi vào proj["scenes"] để STEP 2 nhận customVid
                            if not proj.get("scenes"):
                                proj["scenes"] = [{} for _ in _sc_list]
                            while len(proj["scenes"]) <= _si:
                                proj["scenes"].append({})
                            proj["scenes"][_si].update({
                                "customVid":   str(_save_path),
                                "id":          _sc_item.get("id", _si + 1),
                                "text":        _sc_item.get("text", ""),
                                "keyword":     _sc_item.get("keyword", niche),
                                "veo3_prompt": _sc_item.get("veo3_prompt", ""),
                                "imagePrompt": _sc_item.get("imagePrompt", "") or "",
                                "videoUrl":    None,
                                "veo3Path":    None,
                                "imageUrl":    None,
                                "audioDone":   False,
                                "targetDur":   float(target_sec_per_scene),
                                "duration":    float(target_sec_per_scene),
                            })
                            _custom_changed = True
                            st.success(f"✅ Cảnh {_si+1}: `{_uploaded.name}`")
                        else:
                            _prev_scenes = proj.get("scenes") or []
                            _prev_cv = _prev_scenes[_si].get("customVid") if _si < len(_prev_scenes) else None
                            if _prev_cv:
                                st.info(f"♻️ Đang dùng: `{Path(_prev_cv).name}`")
                    st.divider()
                if _custom_changed:
                    save_proj(proj)

        # ── Trạng thái pipeline (inline) ────────────────
        steps_done = proj.get("step", 0)
        if steps_done > 0:
            _step_labels = [
                (1, "📝 Kịch bản"),
                (2, "🎬 Footage"),
                (3, "🎤 TTS"),
                (4, "🎥 Render"),
            ]
            _cols = st.columns(4)
            for idx, (n, label) in enumerate(_step_labels):
                with _cols[idx]:
                    if steps_done >= n:
                        st.success(f"✅ {label}")
                    elif steps_done == n - 1:
                        st.warning(f"▶️ {label}")
                    else:
                        st.info(f"⬜ {label}")

            if proj.get("output"):
                st.success(f"🎥 Output: `{proj['output']}`")


        # ── Upload Strategy (expander gọn) ─────────
        with st.expander("📡 Chiến lược Upload & Checklist", expanded=False):
            import datetime as _dt
            _now_utc = _dt.datetime.utcnow()

            st.markdown("### 📡 Chiến lược đăng video")

            # Khung giờ tối ưu theo thị trường (UTC)
            _UPLOAD_WINDOWS = {
                "🇰🇷 Thị trường Hàn": [
                    ("Sáng 07–09h KST",  "22:00–00:00 UTC", 22, 0),
                    ("Tối  19–21h KST",  "10:00–12:00 UTC", 10, 12),
                ],
                "🇻🇳 Thị trường VN": [
                    ("Sáng 07–09h ICT",  "00:00–02:00 UTC",  0,  2),
                    ("Tối  18–20h ICT",  "11:00–13:00 UTC", 11, 13),
                ],
                "🇺🇸 Thị trường US": [
                    ("Sáng 07–09h EST",  "12:00–14:00 UTC", 12, 14),
                    ("Chiều 14–16h EST", "19:00–21:00 UTC", 19, 21),
                ],
            }

            _mkt_keys = list(_UPLOAD_WINDOWS.keys())
            _mkt_default = {"Korean": 0, "Vietnamese": 1, "English": 2}.get(lang, 0)
            _sel_market = st.selectbox("🌏 Thị trường mục tiêu", _mkt_keys, index=_mkt_default, key="up_mkt")
            st.markdown("**⏰ Khung giờ đăng tối ưu:**")
            _cur_h = _now_utc.hour
            for (_wlabel, _wdesc, _hs, _he) in _UPLOAD_WINDOWS[_sel_market]:
                _in_win = (_cur_h >= _hs or _cur_h < _he) if _hs > _he else (_hs <= _cur_h < _he)
                _badge = "🟢 **ĐANG TRONG KHUNG GIỜ**" if _in_win else "⚪"
                st.markdown(f"{_badge} {_wlabel} — `{_wdesc}`")

            st.divider()
            st.markdown("**🧘 Bộ đếm kiên nhẫn thuật toán**")
            _lu_str = st.text_input(
                "📅 Ngày đăng video gần nhất (YYYY-MM-DD)",
                value=cfg.get("last_upload_date", ""),
                placeholder="VD: 2026-07-04",
                key="lu_date_inp"
            )
            if _lu_str:
                try:
                    _lu_dt = _dt.datetime.strptime(_lu_str.strip(), "%Y-%m-%d")
                    cfg["last_upload_date"] = _lu_str.strip()
                    save_cfg(cfg)
                    _hrs = (_now_utc - _lu_dt).total_seconds() / 3600
                    _days = _hrs / 24
                    if _hrs < 48:
                        st.warning(
                            f"⏳ **{_hrs:.0f}h kể từ khi đăng** — còn ~{48-_hrs:.0f}h nữa để qua ngưỡng 48h.  \n\n"
                            f"🚫 **Tuyệt đối không xóa & đăng lại** — YTB sẽ đánh dấu spam, giảm trust score vĩnh viễn."
                        )
                    elif _hrs < 72:
                        st.info(
                            f"🔍 **{_hrs:.0f}h** — Thuật toán đang tìm đúng tệp người xem.  \n"
                            f"View thường spike sau ~{72-_hrs:.0f}h nữa (mốc 72h).  \n"
                            f"📊 Xem Analytics → Audience tab để kiểm tra nhóm đang được test."
                        )
                    elif _days < 7:
                        st.success(
                            f"✅ **{_days:.1f} ngày** kể từ đăng — Đã qua sandbox phase.  \n"
                            f"CTR < 2% → cần cải thiện thumbnail/title cho video sau."
                        )
                    else:
                        st.success(f"📅 {_days:.0f} ngày từ video gần nhất — Kênh đang ổn định.")
                except ValueError:
                    st.error("Định dạng ngày không đúng — dùng YYYY-MM-DD")

            st.divider()
            st.markdown("**📋 Checklist trước khi đăng video tiếp theo:**")
            _ck_items = [
                "Hook 3s đầu: mặt người cảm xúc cực mạnh (không dùng cảnh thành phố)",
                "Thumbnail: close-up mặt, tương phản màu cao, text < 6 từ",
                "Title: dưới 60 ký tự, có con số hoặc từ cảm xúc mạnh",
                "Description: 200–300 từ tự nhiên (không copy-paste thẳng từ AI)",
                "Upload đúng khung giờ theo thị trường ở trên",
                "Đã đợi ≥48h từ video trước mới đăng tiếp",
                "Không xóa video cũ dù view thấp (giữ trust score kênh)",
            ]
            for _ck in _ck_items:
                st.checkbox(_ck, value=False, key=f"ck_{abs(hash(_ck))%99999}")



    with col_right:
        st.subheader("📊 Kết quả")

        log_box = st.empty()
        logs = []

        def log(msg):
            logs.append(msg)
            log_box.code("\n".join(logs[-30:]))

        # ── Reset ──────────────────────────────────────────────────────────
        if reset_btn:
            st.session_state.proj = {"script": None, "scenes": [], "step": 0}
            save_proj(st.session_state.proj)
            proj = st.session_state.proj
            st.rerun()

        # ── Full pipeline ──────────────────────────────────────────────────
        _auto_trigger = st.session_state.pop("_auto_run_all", False)  # clear ngay sau khi đọc
        if _auto_trigger:
            run_all = True  # force trigger pipeline sau khi import JSON
        if gen_script or run_all or run_render:

            topic = custom.strip() or niche
            # Với Shorts: ưu tiên nội dung riêng, fallback về niche nếu trống
            if new_mode == "shorts" and not topic:
                topic = niche + " (short-form, independent)"
            is_shorts_mode = (new_mode == "shorts")

            # Work dir cố định theo proj mode → cache scene.mp4 giữa các lần render
            _proj_mode_slug = st.session_state.get("proj_mode", "main")
            work = TMP / f"proj_{_proj_mode_slug}"
            work.mkdir(exist_ok=True)

            try:
                # STEP 1: Script
                if gen_script:
                    log("📝 Tạo kịch bản AI (retention-optimized)...")
                    sc = max(2, round(duration / target_sec_per_scene))
                    is_shorts = "9:16" in aspect  # video dọc Shorts/TikTok

                    # Seed chống trùng nội dung
                    import hashlib as _hs
                    _ts    = str(int(time.time() * 1000))
                    _uid   = uuid.uuid4().hex[:8]
                    _thash = _hs.md5(f"{topic}{lang}{style}".encode()).hexdigest()[:6]
                    seed   = f"{_ts}-{_uid}-{_thash}"

                    # ── CREATOR PERSONA: Randomize góc nhìn để phá pattern AI-detect ──
                    # Mỗi lần generate, AI đóng vai một "creator archetype" khác nhau
                    # → Cấu trúc câu, từ ngữ, góc nhìn thay đổi → YTB không cluster vào cùng 1 pattern
                    _PERSONA_POOL = {
                        "Korean": [
                            ("investigative journalist", "Bạn là PV điều tra kinh tế Hàn Quốc. Viết như đang phơi bày sự thật ẩn giấu. Dùng giọng khẩn cấp, dữ liệu cụ thể, và góc nhìn phản biện chính sách."),
                            ("empathetic advisor",       "Bạn là chuyên gia tư vấn tài chính cá nhân ở tuổi 35 đã từng mắc sai lầm tương tự. Viết như đang kể chuyện riêng, gần gũi, dùng 'chúng ta' thay vì 'bạn'."),
                            ("data analyst",             "Bạn là nhà phân tích dữ liệu. Mở đầu bằng con số gây sốc cụ thể. Mỗi cảnh = 1 thống kê chính xác + diễn giải ngắn gọn bằng ngôn ngữ đời thường."),
                            ("street-smart mentor",      "Bạn là người đi trước 10 năm trong lĩnh vực này. Nói thẳng, không đường vòng, dùng ví dụ từ thực tế cuộc sống hàng ngày người Hàn."),
                            ("contrarian thinker",       "Bạn luôn đặt câu hỏi ngược lại số đông. Bắt đầu bằng cách bác bỏ quan niệm phổ biến, sau đó dẫn chứng lý do tại sao mọi người nghĩ sai."),
                        ],
                        "Vietnamese": [
                            ("investigative journalist", "Bạn là phóng viên điều tra kinh tế. Viết như đang vạch trần sự thật bị che giấu. Giọng khẩn cấp, số liệu rõ ràng, phản biện chính sách."),
                            ("empathetic advisor",       "Bạn là người đã trải qua khó khăn tài chính và đang chia sẻ bài học. Gần gũi, dùng 'mình' và 'bạn', kể chuyện thật."),
                            ("data analyst",             "Bạn là chuyên gia số liệu. Mỗi cảnh = 1 con số cụ thể + giải thích bằng tiếng Việt đời thường, không học thuật."),
                            ("street-smart mentor",      "Bạn là người có 10 năm kinh nghiệm thực chiến. Nói thẳng, không vòng vo, ví dụ từ cuộc sống hàng ngày người Việt."),
                            ("contrarian thinker",       "Bạn phản biện quan điểm chủ lưu. Bắt đầu bằng cách lật ngược điều mọi người tưởng là đúng, rồi giải thích tại sao."),
                        ],
                        "Japanese": [
                            ("investigative journalist", "あなたは日本の経済調査記者です。隠された真実を暴くように書いてください。緊迫感があり、具体的なデータを使い、政策への批判的な視点を持ちます。"),
                            ("empathetic advisor",       "あなたは35歳のファイナンシャルアドバイザーで、同じ失敗を経験してきました。友人に打ち明けるように書き、'私たち'を使ってください。"),
                            ("data analyst",             "あなたはデータアナリストです。具体的な衝撃的な数字から始めてください。各シーン＝1つの正確な統計＋平易な言葉での解説。"),
                            ("street-smart mentor",      "あなたは10年先を行く友人です。無駄なく、専門用語なし。日常生活の実例を使います。"),
                            ("contrarian thinker",       "あなたは常に通説に異を唱えます。人々の思い込みを覆すことから始め、なぜ逆なのかを証明します。"),
                        ],
                        "English": [
                            ("investigative journalist", "You're an investigative financial journalist exposing what mainstream media won't cover. Urgent, data-driven, with a critical eye on policy."),
                            ("empathetic advisor",       "You're a 35-year-old financial advisor who made every mistake first. Write like you're confiding in a friend, use 'we' instead of 'you'."),
                            ("data analyst",             "You're a data analyst. Open with a specific shocking number. Each scene = 1 precise statistic + plain-language interpretation."),
                            ("street-smart mentor",      "You're the friend who's 10 years ahead. No fluff, no jargon. Real examples from everyday life."),
                            ("contrarian thinker",       "You always challenge the mainstream. Start by debunking a popular belief, then prove why most people have it backwards."),
                        ],
                    }
                    _lang_personas = _PERSONA_POOL.get(lang, _PERSONA_POOL["English"])
                    _persona_name, _persona_instruction = random.choice(_lang_personas)
                    log(f"  🎭 Creator persona: [{_persona_name}] — góc nhìn khác biệt để tránh AI pattern")

                    rate_val         = float(tts_rate)
                    # Words per second by language (actual TTS playback speed):
                    # Vietnamese Edge TTS reads very fast (~3.8 wps)
                    # Korean/English ~2.2 wps
                    _wps_map = {"Vietnamese": 3.8, "Korean": 1.8, "English": 2.2, "Japanese": 1.8}
                    words_per_sec    = _wps_map.get(lang, 2.2) * rate_val
                    # Minimum words per scene varies by language (Vietnamese needs more to fill time)
                    _min_words_map   = {"Vietnamese": 35, "Korean": 18, "English": 18, "Japanese": 16}
                    min_words_scene  = _min_words_map.get(lang, 18)
                    total_words      = max(40, round((duration + 2) * words_per_sec))
                    words_per_scene  = max(min_words_scene, round(target_sec_per_scene * words_per_sec))
                    log(f"  📊 Mục tiêu: {sc} cảnh × {words_per_scene} từ/cảnh (~{target_sec_per_scene}s/cảnh) = tổng ~{round(sc*target_sec_per_scene/60,1)}phút")

                    # ── HOOK VISUAL INTENSITY RULE: Scene 1 keyword phải là hình ảnh mạnh nhất ──
                    _HOOK_VISUAL_INSTRUCTION = (
                        "\n\n=== SCENE 1 VISUAL RULE (CRITICAL FOR ALGORITHM) ===\n"
                        "Scene 1 keyword MUST show a HUMAN FACE expressing extreme emotion, or a dramatic close-up moment.\n"
                        "The first visual decides if YouTube shows this video to more people.\n"
                        "✅ GOOD hook visuals: 'shocked young man face close-up', 'person gasping mouth open', "
                        "'stressed woman holding head hands', 'man staring at phone shocked expression'\n"
                        "❌ BAD hook visuals: 'city skyline', 'abstract background', 'apartment building exterior', 'graph chart screen'\n"
                        "Rule: If a viewer sees Scene 1 thumbnail in silence, they MUST feel an emotion immediately."
                    )

                    hook_map = {
                        "🤯 Shock & Awe — Con số / sự thật gây sốc": (
                            "SCENE 1 = SHOCK FIRST — formula options (pick ONE that fits topic):\n"
                            "  Formula A — OUTRAGE NUMBER: '[Specific price/amount] 이게 말이 돼요?' → Viewer feels: 'That's insane!'\n"
                            "  Formula B — RHETORICAL SARCASM: '[Question that mocks the system/status quo]잖아요.' → Viewer feels: 'Wait, they're right...'\n"
                            "  Formula C — STRONG WARNING WORD: Start with '절망', '사기', '증발', '후회' or equivalent. → Viewer feels: 'Am I at risk?'\n"
                            "ABSOLUTELY FORBIDDEN: 'Nhiều người tò mò...', '많은 분들이 궁금해하시는...', 'Bạn có biết...', '혹시 X에 대해 아시나요?'\n"
                            "REQUIRED: The first 1.5 seconds MUST trigger one emotion: rage, shock, or fear of loss.\n"
                            "Example KO: '서울 아파트 전세금이 5년 만에 두 배가 됐잖아요. 근데 월급은요?'\n"
                            "Example VN: 'Giá thuê nhà tăng 80% trong 3 năm. Lương bạn tăng bao nhiêu?'"
                        ),
                        "❓ Curiosity Gap — Câu hỏi bỏ lửng tạo tò mò": (
                            "SCENE 1 = OPEN AN UNANSWERABLE LOOP. Ask a question so specific and unexpected that viewers MUST stay. "
                            "FORBIDDEN: generic questions like 'Do you know about X?' or 'What is Y?'. "
                            "REQUIRED: a question only THIS video answers. "
                            "Example: '한국의 부자들은 왜 집을 사지 않을까요?' — never answer in scene 1."
                        ),
                        "🔥 Controversial — Phát biểu gây tranh cãi": (
                            "SCENE 1 = DROP A BOMB. Directly contradict a mainstream belief. "
                            "Make it feel like the creator is saying something they 'shouldn't'. "
                            "FORBIDDEN: starting with context or history. "
                            "Example: '전세는 임차인을 돕는 제도가 아닙니다. 집주인을 위한 무이자 대출입니다.'"
                        ),
                        "⚠️ Warning / Fear — Cảnh báo, nguy cơ": (
                            "SCENE 1 = URGENT ALARM. Open with a specific danger the viewer is likely ALREADY experiencing. "
                            "FORBIDDEN: vague warnings. REQUIRED: specific, concrete consequence happening RIGHT NOW. "
                            "Example: '집주인이 지금 당신의 전세 보증금으로 빚을 갚고 있을 수도 있습니다.'"
                        ),
                        "🤫 Secret / Insider — Bí mật ít người biết": (
                            "SCENE 1 = INSIDER REVEAL. Position as leaking information the establishment hides. "
                            "Create instant in-group feeling. FORBIDDEN: explaining the concept from scratch. "
                            "Example: '은행들은 이 사실을 알고 있습니다. 그리고 당신이 절대 모르길 바라고 있죠.'"
                        ),
                        "🎭 Story / Relatable — Câu chuyện cá nhân": (
                            "SCENE 1 = IN THE MIDDLE OF THE STORY, at the most dramatic moment. "
                            "FORBIDDEN: 'Today I want to tell you...' or any scene-setting. "
                            "Example: '계약서에 서명한 순간, 3억이 사라졌습니다.'"
                        ),
                        "📣 Bold Claim — Tuyên bố mạnh mẽ": (
                            "SCENE 1 = THE MOST EXTREME defensible statement about this topic. "
                            "Must be specific, directly relevant to viewer's life. "
                            "FORBIDDEN: hedged language ('might', 'could', 'some say'). "
                            "Example: '이 결정 하나가 당신의 향후 10년을 결정합니다.'"
                        ),
                        "🎲 Random — AI tự chọn tốt nhất": (
                            "Choose the hook type creating the STRONGEST emotional reaction for this topic and audience. "
                            "ABSOLUTELY FORBIDDEN opening patterns for ALL hooks: "
                            "(1) Defining the topic ('X는 ~하는 시스템입니다'), "
                            "(2) Asking if viewer knows a basic concept ('혹시 X에 대해 아시나요?'), "
                            "(3) Welcoming or greeting, "
                            "(4) Announcing what the video covers ('오늘은 ~에 대해 알아보겠습니다'). "
                            "Start at the MOST GRIPPING moment of the entire story."
                        ),
                    }
                    _hook_base = hook_map.get(hook_style, hook_map["🎲 Random — AI tự chọn tốt nhất"])
                    # Universal anti-definition guard + visual hook rule appended to every hook type
                    hook_instruction = (
                        _hook_base +
                        " ANTI-DEFINITION GUARD: Scene 1 MUST NOT open with a definition, background explanation, "
                        "or any phrase that assumes the viewer is encountering this topic for the first time. "
                        "The viewer already knows the concept — hit them with the SHOCKING IMPLICATION immediately. "
                        "HOOK FORMULA REMINDER — use ONE of: "
                        "(A) Specific outrage-inducing number/price + 1-line personal implication, "
                        "(B) Rhetorical question with sarcastic tone hitting the viewer's wallet/time/dignity, "
                        "(C) Strong negative word (절망/사기/증발/후회/Tuyệt vọng/Cú lừa/Bốc hơi) as the opening word."
                        + _HOOK_VISUAL_INSTRUCTION
                    )

                    retention_rules = ""
                    if pattern_interrupt:
                        retention_rules += "\n- PATTERN INTERRUPT: Every 2-3 scenes insert a surprising twist or tonal shift."
                    if add_loop_teaser:
                        retention_rules += "\n- LOOP ENDING: The LAST scene must call back to the opening hook."
                    if cta_style != "none":
                        # CTA: ONLY 1 sentence, must force a CHOICE or DEBATE — không dùng generic
                        _cta_generic_example = {
                            "follow":  {
                                "Korean":     (
                                    "마지막 장면 나레이션 맨 끝에 딱 1문장 CTA. "
                                    "반드시 시청자가 '내 얘기다'라고 느끼고 댓글에 자기 입장을 쓰게 만드는 도발적인 선택지 질문으로 끝내세요. "
                                    "✅ REQUIRED FORMULA: '[현재 상황 A]인가요, [현재 상황 B]인가요? 댓글에서 싸워봐요!' "
                                    "✅ 예시: '월세파? 전세파? 지금 댓글로 싸워봐요!' "
                                    "✅ 예시: '300만 원으로 서울에 집 살 수 있다고 생각해요? 솔직히 댓글로 남겨주세요.' "
                                    "❌ ABSOLUTELY FORBIDDEN: '팔로우해주세요', '좋아요 눌러주세요', '구독 부탁드려요', '감사합니다', "
                                    "'이 영상 어떠셨나요?', '여러분 생각은요?' (너무 일반적) — 1문장만, 선택지 있어야 함."
                                ),
                                "Vietnamese": (
                                    "Kết thúc narration cảnh cuối bằng ĐÚNG 1 câu CTA. "
                                    "Câu đó PHẢI buộc người xem chọn phe hoặc tranh luận — không được hỏi chung chung. "
                                    "✅ REQUIRED FORMULA: '[Tình huống A] hay [Tình huống B]? Để lại bình luận!' "
                                    "✅ Ví dụ: 'Bạn đang thuê hay đang tích lũy mua nhà? Tranh luận ở dưới đi!' "
                                    "✅ Ví dụ: 'Lương bao nhiêu bạn mới dám nghĩ đến chuyện mua nhà? Nói thật đi!' "
                                    "❌ TUYỆT ĐỐI CẤM: 'Follow để biết thêm', 'Like và share nhé', 'Cảm ơn bạn đã xem', "
                                    "'Bạn nghĩ sao?' (quá chung chung) — Chỉ 1 câu, phải có 2 phe để chọn."
                                ),
                                "English": (
                                    "End the LAST scene narration with EXACTLY 1 CTA sentence. "
                                    "It MUST force the viewer to pick a side or reveal something personal — not a vague question. "
                                    "✅ REQUIRED FORMULA: '[Option A] or [Option B] right now? Fight it out below!' "
                                    "✅ Example: 'Team rent or team buy right now? Drop your honest answer below.' "
                                    "✅ Example: 'What salary do you need before you'd even think about buying? Be honest.' "
                                    "❌ ABSOLUTELY FORBIDDEN: 'Follow for more', 'Like and subscribe', 'Thanks for watching', "
                                    "'What do you think?' (too generic) — 1 sentence only, must create a debate."
                                ),
                            },
                            "comment": {
                                "Korean":     (
                                    "마지막 나레이션 끝: 딱 1문장, 시청자가 자기 현실을 댓글에 털어놓게 만드는 질문. "
                                    "✅ 예시: '지금 월급으로 5년 뒤 서울에 집 살 수 있을 것 같아요? 솔직하게 댓글로 알려주세요.' "
                                    "✅ 예시: '전세 보증금 떼인 적 있거나 주변에 있으면 댓글로 알려주세요. 얼마나 많은지 확인해볼게요.' "
                                    "❌ CẤM: '댓글로 의견 남겨주세요' (너무 공식적) — 반드시 구체적인 수치나 상황을 넣어야 함."
                                ),
                                "Vietnamese": (
                                    "Cuối narration scene cuối: đúng 1 câu hỏi khiến người xem phải thú nhận thực tế của họ. "
                                    "✅ Ví dụ: 'Tháng này bạn tiêu hết bao nhiêu % lương rồi? Nói thật ở dưới đi.' "
                                    "✅ Ví dụ: 'Bạn đã bao giờ dùng hết tiền trước ngày lương chưa? 1 là Có, 2 là Không.' "
                                    "❌ CẤM: 'Hãy để lại ý kiến', 'Bình luận bên dưới nhé' chung chung — phải có con số hoặc tình huống cụ thể."
                                ),
                                "English": (
                                    "End last narration with exactly 1 question forcing personal confession. "
                                    "✅ Example: 'Have you ever run out of money before payday? Reply: 1 for yes, 2 for never.' "
                                    "✅ Example: 'What percentage of your income goes to rent right now? Drop the number below.' "
                                    "❌ FORBIDDEN: 'Leave a comment', 'Share your thoughts' — must include specific number or situation."
                                ),
                            },
                            "share": {
                                "Korean":     (
                                    "마지막 나레이션 끝: 이 영상을 반드시 봐야 할 특정 사람을 콕 집어서 공유를 유도하세요. "
                                    "✅ 예시: '전세 계약 앞둔 친구 있으면 지금 당장 이 영상 보내주세요. 진짜로.' "
                                    "✅ 예시: '부모님이 전세 보증금 빌려주겠다고 하면 — 먼저 이 영상 보여드리세요.' "
                                    "❌ CẤM: '공유해주세요' 공식 문구 — 누구에게 왜 보내야 하는지 구체적이어야 함."
                                ),
                                "Vietnamese": (
                                    "Cuối narration: tag cụ thể người CẦN xem video này để tạo share tự nhiên. "
                                    "✅ Ví dụ: 'Bạn nào đang chuẩn bị ký hợp đồng thuê nhà — gửi video này cho họ đi. Thật sự đó.' "
                                    "✅ Ví dụ: 'Ai đang cho con mượn tiền đặt cọc — hãy cho họ xem video này trước.' "
                                    "❌ CẤM: 'Chia sẻ cho bạn bè' chung chung — phải nêu rõ ai và tại sao."
                                ),
                                "English": (
                                    "End narration by calling out the EXACT type of person who NEEDS this video right now. "
                                    "✅ Example: 'If you know someone about to sign a lease — send this to them right now. Seriously.' "
                                    "✅ Example: 'Got a friend who thinks renting is 'throwing money away'? This is for them.' "
                                    "❌ FORBIDDEN: Generic 'share with friends' — must name WHO and WHY they need it."
                                ),
                            },
                        }
                        _cta_instruction = _cta_generic_example.get(cta_style, {}).get(lang, "End the LAST scene with exactly 1 provocative question forcing viewers to pick a side in the comments.")
                        retention_rules += f'\n- CTA (STRICT — LAST SCENE ONLY): {_cta_instruction}'
                    retention_rules += '\n- NEVER end with "Thank you for watching", "감사합니다", or "Cảm ơn".'
                    retention_rules += (
                        '\n- ANTI-REPETITION (STRICT — ENFORCED): '
                        'NEVER repeat the same idea, phrase, or concept across ANY scenes. '
                        'Each scene MUST introduce 100% NEW information. '
                        'FORBIDDEN cross-scene patterns: '
                        '(1) Same causal statement restated differently (e.g. supply/demand → rewritten as price gap — SAME IDEA, forbidden). '
                        '(2) Same emotional hook used twice (e.g. "You might lose your deposit" in scene 2 AND scene 5). '
                        '(3) Any sentence where removing the scene number makes it indistinguishable from another scene. '
                        'ENFORCEMENT: Before writing scene N, mentally check: "Did I say anything like this in scenes 1 to N-1?" '
                        'If yes → replace it with a completely different angle (e.g. interest rates, tax policy, behavioral economics, real case study).'
                    )

                    if lang == 'Korean':
                        lang_style_instruction = (
                            "For scenes involving people/streets/lifestyle, prefer keywords with 'Korean', 'Korea', or 'Seoul'. "
                            "For universal topics (nature, science, data), use generic English visuals."
                        )
                        kw_example = '"elderly Korean man walking park"'
                        kw_bad = '"aging population", "Korean society", "Korea trend"'
                    elif lang == 'Japanese':
                        lang_style_instruction = (
                            "For scenes involving people/streets/lifestyle, prefer keywords with 'Japanese', 'Japan', or 'Tokyo'. "
                            "NEVER use 'Korean', 'Korea', 'Vietnam' unless the scene is literally about those countries. "
                            "For universal topics (nature, science, data), use generic English visuals."
                        )
                        kw_example = '"young Japanese woman looking at phone Tokyo"'
                        kw_bad = '"society", "Asian street", "concept", "Korea street"'
                    elif lang == 'Vietnamese':
                        lang_style_instruction = (
                            "For scenes with people/streets/lifestyle, prefer keywords with 'Vietnamese', 'Vietnam', 'Hanoi', or 'Ho Chi Minh'. "
                            "NEVER use 'Korean', 'Korea', 'Seoul', or 'Japan' unless the scene is literally about Korea/Japan. "
                            "For universal topics (nature, science, data), use generic English visuals."
                        )
                        kw_example = '"Vietnamese street food vendor"'
                        kw_bad = '"aging population", "Korean street", "Asian concept"'
                    else:
                        lang_style_instruction = "Match keywords to the topic's culture naturally. Prefer generic English stock visuals."
                        kw_example = '"office worker laptop desk"'
                        kw_bad = '"society change", "concept", "lifestyle"'

                    # ── VISUAL TAXONOMY: map scene type → approved keyword pool ──
                    # Ngăn AI lấy keyword sai ngữ cảnh (nhà khoa học cho "nghiên cứu", VR cho "chi phí")
                    VISUAL_TAXONOMY = {
                        "housing/rent": [
                            "studio apartment interior cozy", "small apartment living room",
                            "apartment building exterior urban", "young adult unpacking moving boxes",
                            "for rent sign apartment door", "real estate agent showing apartment",
                        ],
                        "finance/money": [
                            "person counting money stress", "calculator budget planning desk",
                            "bank statement documents table", "piggy bank saving coins",
                            "credit card payment cashless", "salary paycheck work",
                        ],
                        "government/policy": [
                            "city hall government building", "official document signing desk",
                            "politician press conference podium", "apartment subsidy voucher document",
                            "urban planning city model",
                        ],
                        "research/data": [
                            "person reading article laptop", "financial chart graph screen",
                            "analyst working data dashboard", "notebook pen planning desk",
                            "online search browser screen",
                        ],
                        "young person stress": [
                            "stressed young adult looking phone", "millennial sitting alone room",
                            "tired young person couch", "young man worried bills",
                            "young woman thinking alone cafe",
                        ],
                        "city life urban": [
                            "city street pedestrians daytime", "urban apartment tower skyline",
                            "crowded subway commute morning", "city traffic night aerial",
                            "busy crosswalk downtown workers",
                        ],
                        "abstract background safe": [
                            "minimalist abstract background loop", "blurred city lights bokeh",
                            "clean modern office background", "subtle gradient motion background",
                        ],
                        "online meeting / video call": [
                            "person video call laptop home office", "woman talking online meeting screen",
                            "man joining zoom call remote work", "online meeting multiple faces screen",
                            "person nervous before presentation laptop", "video conference call office",
                            "remote work laptop desk headphones", "person typing laptop professional",
                        ],
                        "communication / soft skills": [
                            "person speaking confidently team meeting", "professional woman presenting whiteboard",
                            "team discussion office table", "person giving speech microphone",
                            "man explaining idea whiteboard markers", "confident presenter audience",
                            "active listening conversation two people",
                        ],
                        "personal growth / self-improvement": [
                            "person writing journal morning routine", "focused individual reading self-help book",
                            "young adult meditating calm room", "person setting goals notebook pen",
                            "motivated individual running early morning",
                        ],
                    }

                    keyword_instruction = (
                        f"- keyword: A CONCRETE, VISUAL English search phrase (2-5 words) for stock VIDEO search.\n"
                        f"  The keyword = what a CAMERA physically sees. NOT what the narration talks about conceptually.\n"
                        f"\n"
                        f"  === EMOTION-FIRST MATCHING (most important rule) ===\n"
                        f"  Ask: 'What does a PERSON look like when experiencing this scene's emotion?'\n"
                        f"  Then describe THAT moment — not a symbol of the topic.\n"
                        f"  • Scene about 'appeal of cheap rent' → keyword: 'young couple happy new apartment' (NOT 'worker machine factory')\n"
                        f"  • Scene about 'financial risk' → keyword: 'person holding empty wallet stress' (NOT 'industrial crane')\n"
                        f"  • Scene about 'deposit contract' → keyword: 'couple signing lease document table' (NOT 'factory worker welding')\n"
                        f"\n"
                        f"  === CRITICAL ANTI-MISMATCH RULES ===\n"
                        f"  ❌ WRONG MAPPING (these destroy viewer retention):\n"
                        f"    - Narration: 'Jeonse is attractive' → keyword: 'industrial worker machinery' (WRONG — factory = 0 connection)\n"
                        f"    - Narration: 'research policy' → keyword: 'scientist lab' (WRONG — that's chemistry, not social policy)\n"
                        f"    - Narration: 'cost management' → keyword: 'VR headset technology' (WRONG — no connection)\n"
                        f"    - Narration: 'government housing support' → keyword: 'Gyeongbokgung palace tourism' (WRONG — tourist site)\n"
                        f"  ✅ CORRECT MAPPING (camera shows the HUMAN CONTEXT of the idea):\n"
                        f"    - Narration: 'Jeonse is attractive, live free for 2 years' → keyword: 'young Korean couple moving into apartment happy' ✓\n"
                        f"    - Narration: 'landlord investing your deposit' → keyword: 'man counting cash investment documents' ✓\n"
                        f"    - Narration: 'government support' → keyword: 'city hall government building' ✓\n"
                        f"    - Narration: 'financial stress of deposit' → keyword: 'young adult worried counting money' ✓\n"
                        f"\n"
                        f"  === PERMANENTLY BANNED FOOTAGE CATEGORIES ===\n"
                        f"  ❌ factory worker / industrial machinery / manufacturing plant — UNLESS the video is literally about factories\n"
                        f"  ❌ lab scientist / chemistry equipment — UNLESS literally about science\n"
                        f"  ❌ tourist landmarks / palaces / monuments — UNLESS literally about tourism\n"
                        f"  ❌ abstract tech (VR, robot, AI render) — UNLESS literally about technology\n"
                        f"\n"
                        f"  === VISUAL CATEGORY GUIDE (pick the CLOSEST match) ===\n"
                        f"  • Housing/Rent → young adult moving boxes apartment, rent sign building, couple apartment hunting\n"
                        f"  • Finance/Money → person counting money stress, budget spreadsheet close-up, piggy bank saving\n"
                        f"  • Contract/Legal → couple signing documents table, pen on contract paper, real estate agent handshake\n"
                        f"  • Government/Policy → city hall exterior, official press conference, government document desk\n"
                        f"  • Research/Data → person reading on laptop, financial chart screen, analyst dashboard\n"
                        f"  • Stress/Worry → young adult stressed desk, worried expression close-up (NOT 'holding head' unless head-holding IS the topic)\n"
                        f"  • Online Meeting / Video Call → person video call laptop, woman talking online meeting screen, remote work desk headphones\n"
                        f"  • Communication / Public Speaking → person speaking team meeting, professional woman presenting, confident presenter audience\n"
                        f"  • Personal Growth → person writing journal, focused individual reading, young adult meditating calm\n"
                        f"  • Optimism/Relief → person smiling new home, couple celebrating keys, happy family apartment\n"
                        f"  • City/Urban → apartment tower skyline, city street pedestrians, subway commute rush hour\n"
                        f"  • CRITICAL: Match the SCENE TOPIC, not the EMOTION. A scene about 'shy in online meeting' → 'person nervous video call laptop' NOT 'stressed woman holding head'.\n"
                        f"  • When unsure → 'minimalist abstract background' or 'blurred city lights bokeh'\n"
                        f"\n"
                        f"  {lang_style_instruction}\n"
                        f"  Example for this video: {kw_example}\n"
                        f"  ❌ NEVER use: {kw_bad}\n"
                        f"  ❌ NEVER single words. ❌ NEVER URLs. ❌ NEVER industrial/factory/lab unless the topic is literally those things.\n"
                        f"  ✅ ALWAYS ask: 'Does this footage make sense to a viewer who just heard the narration?' If NO → choose again.\n"
                        f"\n"

                        f"  === MÔ TẢ CẢNH QUAY (VEO3 PROMPT) ===\n"
                        f"  - veo3_prompt: Mô tả cảnh quay bằng tiếng Việt, rõ ràng, chi tiết để tạo video AI (Veo3/Sora/Kling).\n"
                        f"  Cấu trúc: [Chủ thể + quốc tịch] + [hành động/trạng thái] + [bối cảnh, ánh sáng] + [góc máy] + [cảm xúc] + [chất lượng].\n"
                        + (
                            f"  QUỐC TỊCH NHÂN VẬT (BẮT BUỘC): Video dành cho khán giả {lang}.\n"
                            f"  → Mọi nhân vật người trong cảnh PHẢI được chỉ rõ là "
                            + ("'người Hàn Quốc' hoặc 'người Seoul'.\n"
                               f"  → Ví dụ đúng: 'Cảnh quay gần mặt người đại lý bất động sản người Hàn đang giải thích cho cặp vợ chồng trẻ người Hàn'\n"
                               f"  → Ví dụ SAI: 'người đàn ông trẻ' (không rõ quốc tịch)\n"
                               if lang == "Korean" else
                               "'người Nhật Bản' hoặc 'người Tokyo'.\n"
                               f"  → Ví dụ đúng: 'Cảnh quay gần người đàn ông trẻ Nhật đang nhìn hóa đơn thuê nhà với vẻ lo lắng tại Tokyo'\n"
                               f"  → Ví dụ SAI: 'người đàn ông trẻ' (không rõ quốc tịch)\n"
                               if lang == "Japanese" else
                               "'người Việt Nam'.\n"
                               f"  → Ví dụ đúng: 'Cảnh quay gần cô gái trẻ người Việt đang nhìn bảng giá căn hộ với vẻ lo lắng'\n"
                               f"  → Ví dụ SAI: 'người phụ nữ trẻ' (không rõ quốc tịch)\n"
                               if lang == "Vietnamese" else
                               "'người phương Tây' hoặc chỉ rõ ethnicity nếu phù hợp chủ đề.\n"
                            )
                            if True else ""
                        )
                        + f"  Ví dụ mẫu ({lang}): "
                        + ("'Cảnh quay gần mặt người đàn ông Hàn Quốc trung niên đang xem hợp đồng thuê nhà với vẻ lo lắng, ánh đèn vàng văn phòng, nền mờ, slow-motion, 4K cinematic.'\n"
                           if lang == "Korean" else
                           "'Cảnh quay gần người đàn ông trẻ Nhật Bản đang nhìn hóa đơn thuê nhà tại căn hộ nhỏ Tokyo với vẻ lo lắng, ánh đèn vàng ấm, nền mờ, slow-motion, 4K cinematic.'\n"
                           if lang == "Japanese" else
                           "'Cảnh quay gần cô gái người Việt đang nhìn bảng giá căn hộ tại trung tâm thành phố, ánh sáng buổi chiều, nền mờ đường phố Sài Gòn, slow-motion, chất lượng 4K.'\n"
                           if lang == "Vietnamese" else
                           "'Close-up of a young Western man reviewing a rental contract with a worried expression, warm office light, blurred background, slow-motion, 4K cinematic.'\n"
                        )
                        + f"  TUYỆT ĐỐI KHÔNG ĐƯỢC DÙNG trong veo3_prompt:\n"
                        f"  ❌ Các từ nhạy cảm: quan chức, họp báo, hội nghị, cảnh sát, tòa án, chính trị, lãnh đạo chính phủ\n"
                        f"  ❌ Tên tổ chức cụ thể (WEF, IMF, OECD...)\n"
                        f"  ❌ Hình ảnh mạng, bạo lực, người nổi tiếng thật\n"
                        f"  ✅ Thay bằng: cảnh đường phố, con người đời thường, nội thất văn phòng trung lập, biểu đồ số liệu, đồ vật, bảng giá."
                    )


                    if custom.strip():
                        topic_instruction = (
                            f"based on the following detailed instructions:\n\n<USER_INSTRUCTIONS>\n{custom.strip()}\n</USER_INSTRUCTIONS>\n\n"
                            f"Please integrate these instructions while strictly adhering to the JSON format."
                        )
                        _custom_short = custom.strip()[:300].rsplit(' ', 1)[0] + "..." if len(custom.strip()) > 300 else custom.strip()
                        topic_instruction_short = f'following the topic/style: "{_custom_short}"'
                    else:
                        topic_instruction = f'about "{topic}"'
                        topic_instruction_short = topic_instruction
                    lang_upper = lang.upper()

                    # ── CHUNKED GENERATION ──
                    BATCH_SIZE          = 15
                    total_scenes_needed = sc
                    all_scene_data      = []
                    video_title         = ""
                    video_description   = ""
                    video_tags          = []
                    prev_summary        = ""
                    batch_num           = 0
                    scene_cursor        = 0

                    log(f"  📊 Tổng cảnh cần tạo: {total_scenes_needed} (~{math.ceil(total_scenes_needed / BATCH_SIZE)} batch)")

                    while scene_cursor < total_scenes_needed:
                        batch_start   = scene_cursor + 1
                        batch_end     = min(scene_cursor + BATCH_SIZE, total_scenes_needed)
                        batch_count   = batch_end - scene_cursor
                        is_first      = (scene_cursor == 0)
                        is_last       = (batch_end >= total_scenes_needed)
                        batch_num    += 1

                        log(f"  📋 Batch {batch_num}: cảnh {batch_start}–{batch_end} ({batch_count} cảnh)...")

                        lang_rule = (
                            "Write in natural Korean (해요체)." if lang == "Korean"
                            else "Write in natural Vietnamese (tiếng Việt)." if lang == "Vietnamese"
                            else "Write in natural Japanese (です・ます調 or spoken 〜だよね・〜じゃん style)." if lang == "Japanese"
                            else "Write in clear, engaging English."
                        )

                        # ── Ngôn ngữ tự nhiên theo từng thứ tiếng ──
                        if lang == "Vietnamese":
                            speech_rules = (
                                "VIETNAMESE SPEECH STYLE — ANTI-GENERIC RULES (CRITICAL):\n"
                                "- Speak like a REAL Vietnamese TikToker: opinionated, specific, punchy.\n"
                                "- EVERY scene MUST have at least 1 SPECIFIC element:\n"
                                "  A NUMBER ('70% nguoi Viet...', '3 loi pho bien'), OR\n"
                                "  A NAMED CONCEPT ('Parkinson Law', 'sunk cost fallacy', 'cashflow'), OR\n"
                                "  A CONCRETE SCENARIO ('lam 30 trieu/thang nhung chi het 31 trieu'), OR\n"
                                "  A CONTRARIAN CLAIM ('Cham chi khong giup ban giau — day la ly do')\n"
                                "\n"
                                "=== ABSOLUTE BANS — ANY of these = script REJECTED ===\n"
                                "BANNED OPENERS: 'Minh da tung...', 'Hanh trinh cua minh...', 'Minh muon chia se...'\n"
                                "BANNED PHRASES: 'bai hoc quy gia', 'kinh nghiem quy bau', 'ky nang quan trong'\n"
                                "BANNED GENERIC: 'Hay co ke hoach ro rang', 'Hay no luc hon', 'Khong bo cuoc'\n"
                                "BANNED FILLER: 'cung nhau', 'hanh trinh', 'no luc', 'tam quan trong'\n"
                                "BANNED CTA SCENE: 'Hay Follow de biet them' as a full scene = instant unsubscribe\n"
                                "BANNED: Any sentence that could apply to ANY topic (must be specific to THIS video)\n"
                                "\n"
                                "HOOKS THAT ACTUALLY WORK (use as inspiration — NO bare statistics in Scene 1):\n"
                                "  ✅ 'Ban biet cau tra loi, nhung van im lang trong cuoc hop. Khong phai vi so sai — vi so bi phan xet.'\n"
                                "  ✅ 'Lam 10 tieng moi ngay nhung thu nhap van dung im. Day la ly do that su.'\n"
                                "  ✅ 'Co 1 loi sai khien hau het startup Viet chet truoc nam thu 2 — va no khong lien quan den von.'\n"
                                "  ❌ BANNED hook: '90% nguoi Viet gap tinh trang nay' (so lieu o scene 1 = nghe nhu doc bao cao)\n"
                                "- Short punchy sentences. Max 10 words. Natural speech rhythm.\n"
                                "- OK to use: 'ban biet khong', 'that ra', 'nghe co ve nghich ly', 'nhung ma', 'dieu dien ro la'\n"
                                "- Rhetorical questions ONLY if answered in the SAME or NEXT scene.\n"
                                "\n"
                                "=== VIETNAMESE LANGUAGE & GRAMMAR PURITY (CRITICAL — HARD RULES) ===\n"
                                "1. TARGET LANGUAGE: 100% tiếng Việt có dấu đầy đủ. Không viết tắt dấu (ban → bạn).\n"
                                "2. NO HALLUCINATION: Dùng đúng từ chuẩn tiếng Việt. KHÔNG tự sáng tác từ không tồn tại.\n"
                                "   Ví dụ đúng: 'tăng vọt', 'tụt dốc' — KHÔNG viết 'tăng vọt vọt' hay 'tụt dốc dốc'.\n"
                                "3. NO STUTTERING: KHÔNG lặp từ liền kề do lỗi.\n"
                                "   TUYỆT ĐỐI CẤM: 'của của', 'và và', 'trong trong', 'này này' — mỗi từ chỉ xuất hiện 1 lần.\n"
                                "4. TONE: Nhà phân tích tài chính TikTok thật thà, đanh thép. Dùng: 'đó', 'nhé', 'thật ra', 'mà',\n"
                                "   'chứ', 'á', 'vậy đó'. KHÔNG dùng văn mẫu: 'hãy cùng tìm hiểu', 'đây là điều quan trọng'.\n"
                                "5. VĂN BẢN CHO GIỌNG ĐỌC: Trong mọi trường text, PHẢI viết số, phần trăm và từ tiếng Anh\n"
                                "   thành cách đọc tiếng Việt. Viết 'chín mươi lăm phần trăm', KHÔNG viết '95%'.\n"
                                "   Viết 'a phi li ét', 'tíc tốc shop', KHÔNG viết 'Affiliate', 'TikTok Shop'.\n"
                                "   Dùng câu ngắn và dấu phẩy chủ động để tạo nhịp; không nối từ thừa sau phần trăm.\n"
                                "\n"
                                "=== HOOK & CTA RULES (VIETNAMESE-SPECIFIC) ===\n"
                                "- SCENE 1 (HOOK): Phải là Tuyên bố gây sốc hoặc Câu hỏi kích thích. Tối đa 1.5 giây.\n"
                                "  CẤM mở đầu chung chung: 'Nhiều người thắc mắc...', 'Hôm nay mình sẽ chia sẻ...', 'Bạn có biết không?'.\n"
                                "  ✅ ĐÚNG: 'Giá thuê nhà tăng 80% trong 3 năm. Lương bạn tăng bao nhiêu?'\n"
                                "  ✅ ĐÚNG: 'Làm 10 tiếng/ngày nhưng thu nhập vẫn đứng im. Đây là lý do thật sự.'\n"
                                "- SCENE END (CTA): Cảnh cuối PHẢI kết bằng câu hỏi khiêu khích ép người xem bình luận.\n"
                                "  ✅ ĐÚNG: 'Bạn đang thuê hay đang tích lũy mua nhà? Chia sẻ phía dưới nhé!'\n"
                                "  CẤM: 'Follow để biết thêm', 'Like và share ủng hộ mình nhé'.\n"
                                "\n"
                                "=== ANTI-REPETITION (STRICT — VIETNAMESE) ===\n"
                                "Mỗi scene PHẢI đưa ra thông tin HOÀN TOÀN MỚI.\n"
                                "KHÔNG lặp lại cùng khái niệm (ví dụ 'cung cầu mất cân bằng') ở nhiều scene.\n"
                                "Nếu Scene 2 đề cập đến X, Scene 3 PHẢI nói về điều khác (ví dụ: lãi suất, thuế, chính sách)."
                            )
                        elif lang == "Korean":
                            speech_rules = (
                                "KOREAN SPEECH STYLE — PERSONA: 길거리 전문가 / 파이낸스 Vlogger (CRITICAL):\n"
                                "\n"
                                "=== 필수 사용 — SPOKEN KOREAN ENDINGS (최소 2개/scene) ===\n"
                                "~잖아요  → '비싸잖아요' (You know it's expensive, right?)\n"
                                "~죠?     → '이상하죠?' (Weird, right?)\n"
                                "~지 않을까요? → '문제가 되지 않을까요?' (Wouldn't that be a problem?)\n"
                                "~다는 사실!  → '오르고 있다는 사실!' (The fact that it's rising!)\n"
                                "~거든요  → '이게 핵심이거든요' (This is the key point, see)\n"
                                "~는데요  → '근데 여기서 반전이 있는데요' (But here's the twist)\n"
                                "\n"
                                "=== 감탄사 — RHYTHM BREAKERS (매 2–3 scene마다 1개) ===\n"
                                "'하...', '진짜로', '솔직히 말해서', '어이없죠?', '웃긴 건', '근데 이게'\n"
                                "\n"
                                "=== ABSOLUTE BANS ===\n"
                                "❌ '우리는 ... 해야 해요' (We must...)\n"
                                "❌ '단순한 문제가 아니에요' (It's not a simple issue)\n"
                                "❌ '중요한 것은' / '핵심은 바로' — clichéd openers\n"
                                "❌ 습니다체 endings in narration\n"
                                "❌ Any sentence that could apply to ANY topic without changing words\n"
                                "\n"
                                "=== LANGUAGE PURITY — HARD RULE (VIOLATIONS = OUTPUT REJECTED) ===\n"
                                "✅ 100% 순수 한국어 (Hangul) only.\n"
                                "✅ Economic terms ALLOWED in English ONLY: OECD, FED, LTV, GDP, DSR, RTI\n"
                                "❌ STRICTLY FORBIDDEN: Any Chinese character (Hanja: 真的, 正直, 方法...)\n"
                                "❌ STRICTLY FORBIDDEN: Any Japanese Hiragana or Katakana\n"
                                "❌ STRICTLY FORBIDDEN: Any Vietnamese or other non-Korean text\n"
                                "→ If you are unsure whether a word is pure Korean, write it in Hangul romanization instead.\n"
                                "\n"
                                "=== KOREAN LANGUAGE & GRAMMAR PURITY (CRITICAL — HARD RULES) ===\n"
                                "1. TARGET LANGUAGE: 100% Native, natural Korean (Hangul). Zero mixing.\n"
                                "2. NO HALLUCINATION: Ensure absolute grammatical correctness. Do NOT invent fake or misspelled words\n"
                                "   (e.g., use '치솟고' NOT the misspelled '취속고', use '이를' NOT '이를 이를').\n"
                                "3. NO CHINESE CHARACTERS: Absolutely NO Hanja (Chinese characters) anywhere in the output.\n"
                                "4. NO STUTTERING: Do NOT repeat any word consecutively by accident\n"
                                "   (e.g., NEVER write '이를 이를', '그래서 그래서', '사람 사람' — write each word ONCE).\n"
                                "5. TONE: Aggressive, street-smart financial analyst on TikTok. Use informal/polite punchy endings\n"
                                "   (~잖아요, ~죠, ~지 않나요?). DO NOT use robotic endings like '단순한 문제가 아니에요'.\n"
                                "\n"
                                "=== HOOK & CTA RULES (KOREAN-SPECIFIC) ===\n"
                                "- SCENE 1 (HOOK): Must be a Shocking Claim or Agitating Question. Max 1.5 seconds of speech.\n"
                                "  NO generic openers like '많은 사람들이 궁금해합니다' or '오늘은 ~에 대해 알아볼게요'.\n"
                                "  ✅ CORRECT: '서울 아파트 전세금이 5년 만에 두 배가 됐잖아요. 근데 월급은요?'\n"
                                "  ✅ CORRECT: '집주인이 지금 당신의 보증금으로 빚을 갚고 있을 수도 있습니다.'\n"
                                "- SCENE END (CTA): The final scene MUST end with a provocative question driving comments.\n"
                                "  ✅ CORRECT: '여러분은 어떻게 생각하세요? 댓글로 남겨주세요!'\n"
                                "  ✅ CORRECT: '월세파? 전세파? 댓글에서 싸워봐요.'\n"
                                "  NEVER use generic '팔로우해주세요' or '좋아요 눌러주세요'.\n"
                                "\n"
                                "=== SENTENCE ENDING DIVERSITY — '~어요/~아요 LULLABY' BAN (CRITICAL) ===\n"
                                "❌ ABSOLUTE BAN: Using '~어요' or '~아요' as the ending for MORE THAN 2 consecutive sentences.\n"
                                "   Real Korean TikTokers ROTATE their sentence endings constantly. Repeating the same ending 10+ times = 'lullaby effect' = viewers fall asleep and swipe away by second 20.\n"
                                "   RULE: After ANY 2 sentences ending in ~어요/~아요, the NEXT sentence MUST use a DIFFERENT ending:\n"
                                "   ✅ MANDATORY ROTATION — use these alternatives after every 2nd ~어요:\n"
                                "     ~잖아요  → '비싸잖아요' (conversational, 'you know it is')\n"
                                "     ~거든요  → '이게 문제거든요' (explanatory, 'the thing is')\n"
                                "     ~죠?    → '당연하죠?' (rhetorical check-in, 'right?')\n"
                                "     ~는데요  → '근데 여기가 반전인데요' (twist pivot)\n"
                                "     ~다는 거! → '두 배가 됐다는 거!' (exclamation punch)\n"
                                "     ~대요   → '정부가 규제한다대요' (hearsay = sounds natural)\n"
                                "     ~더라고요 → '실제로 해보니까 달랐더라고요' (experience-based)\n"
                                "   ❌ BANNED PATTERN: ...있어요. ...해요. ...있어요. ...해요. (monotone loop)\n"
                                "   ✅ CORRECT PATTERN: ...있어요. ...거든요. ...죠? ...다는 거! (varied, alive)\n"
                                "\n"
                                "=== SHORTS LENGTH — '1 VIDEO, 1 THÔNG ĐIỆP' RULE (CRITICAL) ===\n"
                                "❌ FATAL ERROR: Cramming multiple macro-economic concepts into one Shorts video.\n"
                                "   Example of VIOLATION (what killed the view count): Writing ONE script covering ALL of:\n"
                                "   '공급 부족 → 저금리 → 갭투자 → 가계부채 → 청년 포기 → 정책 실패 → 일본 잃어버린 10년'\n"
                                "   That is 7 separate video topics — not one Shorts script. Viewers feel 'overwhelmed' and swipe at second 20-30.\n"
                                "   GOLDEN RULE: ONE Shorts video = ONE single, shocking, specific message. THAT'S IT.\n"
                                "   ✅ CORRECT SCOPE: 'Only about 갭투자 and household debt — nothing else'\n"
                                "   ✅ CORRECT SCOPE: 'Only the comparison between Seoul bubble and Japan 1990 — nothing else'\n"
                                "   ✅ CORRECT SCOPE: 'Only about young Koreans giving up on homeownership — nothing else'\n"
                                "   → If your topic is big, SHRINK the scope to ONE angle. Trust viewers to watch part 2.\n"
                                "   TARGET DURATION: For Shorts, the ENTIRE script MUST be deliverable in 35–45 seconds.\n"
                                "   If your script reads longer than 45 seconds at normal TTS speed → YOU HAVE TOO MANY CONCEPTS → DELETE until one remains.\n"
                                "\n"
                                "=== ANTI-REPETITION (STRICT — KOREAN) ===\n"
                                "Each scene MUST introduce completely NEW information.\n"
                                "Do NOT repeat the same concept (e.g., '수요와 공급의 불균형') across multiple scenes.\n"
                                "If Scene 2 mentions a concept, Scene 3 MUST cover something different (e.g., interest rates, taxes, policy).\n"
                                "\n"
                                "=== STRUCTURAL REPETITION BAN — '당신의 [X]는요?' PATTERN ===\n"
                                "❌ ABSOLUTELY FORBIDDEN: Using the rhetorical structure '당신의 [X]는요?' (or '~는요?' tagging a noun) MORE THAN ONCE across the entire script.\n"
                                "   This pattern (e.g., '예산은요?', '계약서는요?', '월급은요?', '보증금은요?') becomes INSTANTLY RECOGNIZABLE as AI-written after the 2nd use — viewers swipe away.\n"
                                "   RULE: If you use '~는요?' in ONE scene, ALL other scenes MUST use a COMPLETELY DIFFERENT sentence structure to express the same rhetorical contrast.\n"
                                "   ✅ ALTERNATIVES to '당신의 X는요?':\n"
                                "     - State the contrast directly: '근데 임금 인상률은 고작 2%잖아요.'\n"
                                "     - Use a sarcastic observation: '회사는 돈 버는데 직원 지갑은 그대로예요.'\n"
                                "     - Use an exclamation: '정작 세입자 손에 남는 건 없다는 거!'\n"
                                "     - Pivot with '그러면': '그러면 대출이자는 누가 내죠?'\n"
                                "\n"
                                "=== '당신' USAGE — NATURAL KOREAN RULE ===\n"
                                "❌ MINIMIZE '당신': Real Korean speakers almost NEVER say '당신' in everyday speech — it sounds like translated English ('you'). Overusing it = AI tell.\n"
                                "   RULE: Use '당신' MAX 1 time per entire script, ONLY in a high-impact line where it creates deliberate personal confrontation.\n"
                                "   ✅ INSTEAD of '당신', use these natural Korean alternatives:\n"
                                "     - Drop the subject entirely: '월급은 오를 생각이 없죠.' (not '당신의 월급은요?')\n"
                                "     - Use '여러분': '여러분 계좌에 남는 게 얼마예요?' (warmer, plural, natural)\n"
                                "     - Use implicit 2nd person via situation: '지금 월세 내고 나면 통장 잔고 보이죠?'\n"
                                "     - Use question without pronoun: '보증금은 돌려받을 수 있을까요?'\n"
                                "\n"
                                "=== NUMBER / STATISTIC CONSISTENCY — CRITICAL ===\n"
                                "❌ FORBIDDEN: Using DIFFERENT numbers for the SAME statistic in different scenes.\n"
                                "   Example of VIOLATION (destroys credibility instantly):\n"
                                "     Scene 1: '전세값이 50% 올랐어요.' → Scene 6: '20% 올랐다는 거 알고 계셨나요?' — CONTRADICTORY!\n"
                                "   RULE: If you introduce a specific number (%, price, year) in Scene X, that EXACT number MUST be used consistently in ALL scenes that reference the same fact.\n"
                                "   RULE: If you are unsure of the exact figure, pick ONE plausible number and LOCK IT for the entire script. DO NOT vary it.\n"
                                "   ✅ SAFE APPROACH: Before writing Scene 2+, mentally list all numbers used so far and treat them as FIXED constraints.\n"
                                "   ✅ FORMAT: Use specific Korean number phrasing: '50% 이상', '두 배', '3조 원' — pick ONE phrasing and reuse the SAME phrasing if the same stat recurs."
                            )
                        elif lang == "Japanese":
                            speech_rules = (
                                "JAPANESE SPEECH STYLE — PERSONA: 街の金融専門家 / ファイナンス Vlogger (CRITICAL):\n"
                                "\n"
                                "=== 必須使用 — SPOKEN JAPANESE ENDINGS (最低2個/scene) ===\n"
                                "~じゃないですか → '高すぎじゃないですか' (That's too expensive, right?)\n"
                                "~ですよね?    → 'おかしいですよね?' (That's strange, isn't it?)\n"
                                "~んですよ     → 'これが核心なんですよ' (This is the key point, you see)\n"
                                "~わけです     → 'そういうわけです' (That's how it is)\n"
                                "~って話です   → 'リスクがあるって話です' (The thing is, there's a risk)\n"
                                "~んですけど   → 'ここで反転があるんですけど' (But here's the twist)\n"
                                "\n"
                                "=== リズムブレーカー — RHYTHM WORDS (2〜3 sceneに1個) ===\n"
                                "'はあ...', '正直ね', 'ちょっと待って', 'これ笑えないですよ', 'でもね', 'ここが面白くて'\n"
                                "\n"
                                "=== ABSOLUTE BANS ===\n"
                                "❌ '皆さんも〜しなければなりません' (You all must...)\n"
                                "❌ '単純な問題ではありません' (It's not a simple issue)\n"
                                "❌ '重要なことは' / '大切なポイントは' — clichéd openers\n"
                                "❌ Any formal/written-style endings (〜であります、〜でございます) in narration\n"
                                "❌ Any sentence that could apply to ANY topic without changing words\n"
                                "\n"
                                "=== LANGUAGE PURITY — HARD RULE (VIOLATIONS = OUTPUT REJECTED) ===\n"
                                "✅ 100% 純粋な日本語 (Japanese: Hiragana + Katakana + Kanji mix) only.\n"
                                "✅ Economic terms ALLOWED in English ONLY: OECD, GDP, FED, IMF, ROI, ETF\n"
                                "❌ STRICTLY FORBIDDEN: Any Korean Hangul characters\n"
                                "❌ STRICTLY FORBIDDEN: Any Vietnamese or other non-Japanese text\n"
                                "❌ STRICTLY FORBIDDEN: Mixing Chinese Simplified characters NOT used in standard Japanese\n"
                                "→ Use standard Japanese kanji only (e.g., '住宅', '賃料', '収入' — all standard JA kanji).\n"
                                "\n"
                                "=== JAPANESE LANGUAGE & GRAMMAR PURITY (CRITICAL — HARD RULES) ===\n"
                                "1. TARGET LANGUAGE: 100% natural, native Japanese. Zero mixing.\n"
                                "2. NO HALLUCINATION: Ensure correct Japanese grammar. Do NOT invent non-existent words.\n"
                                "   (e.g., use '高騰している' NOT '高騰してる中'; use '分かる' NOT '分る').\n"
                                "3. NO STUTTERING: Do NOT repeat any word consecutively by accident.\n"
                                "   ABSOLUTELY FORBIDDEN: 'で、で、', 'この、この、', 'と、と、' — each word ONCE only.\n"
                                "4. TONE: Aggressive, street-smart financial analyst on Japanese TikTok. Use informal/polite punchy endings\n"
                                "   (~じゃないですか, ~ですよね, ~んですよ). DO NOT use stiff formal endings like '〜でございます'.\n"
                                "\n"
                                "=== HOOK & CTA RULES (JAPANESE-SPECIFIC) ===\n"
                                "- SCENE 1 (HOOK): Must be a Shocking Claim or Agitating Question. Max 1.5 seconds of speech.\n"
                                "  NO generic openers like '多くの人が疑問に思っています' or '今日は〜について話します'.\n"
                                "  ✅ CORRECT: '東京の家賃、5年で40%上がったじゃないですか。でも給料は?'\n"
                                "  ✅ CORRECT: '今、あなたの敷金で大家がローンを払ってるかもしれません。'\n"
                                "- SCENE END (CTA): The final scene MUST end with a provocative question driving comments.\n"
                                "  ✅ CORRECT: '賃貸派? 購入派? コメントで教えてください!'\n"
                                "  ✅ CORRECT: '今の手取りで5年後に家を買えると思いますか? 正直に教えて。'\n"
                                "  NEVER use generic 'フォローしてください' or 'いいね押してください'.\n"
                                "\n"
                                "=== '貴方(あなた)' USAGE — NATURAL JAPANESE RULE ===\n"
                                "❌ MINIMIZE 'あなた': Real Japanese TikTokers rarely address viewers directly as 'あなた' — it sounds stiff.\n"
                                "   RULE: Use 'あなた' MAX 1 time per script, only for high-impact direct confrontation.\n"
                                "   ✅ INSTEAD use:\n"
                                "     - Drop the subject: '手取りが増えない理由、分かりますか?' (no pronoun)\n"
                                "     - Use '皆さん': '皆さんは知らないかもしれないけど' (warmer, natural)\n"
                                "     - Use situation-based 2nd person: '毎月赤字になってませんか?'\n"
                                "\n"
                                "=== STRUCTURAL REPETITION BAN ===\n"
                                "❌ FORBIDDEN: Using the same question structure '〇〇はどうですか?' or '〇〇はどうでしょう?' more than ONCE.\n"
                                "   RULE: Each rhetorical question must use a DIFFERENT grammatical structure.\n"
                                "   ✅ ALTERNATIVES: 〜ですよね? / 〜じゃないですか / 〜って思いませんか / 〜気がしませんか\n"
                                "\n"
                                "=== NUMBER / STATISTIC CONSISTENCY — CRITICAL ===\n"
                                "❌ FORBIDDEN: Using DIFFERENT numbers for the SAME statistic in different scenes.\n"
                                "   Example of VIOLATION: Scene 1: '家賃が50%上がった' → Scene 6: '20%上がった' — CONTRADICTORY!\n"
                                "   RULE: Once you introduce a number (%, price, year), LOCK IT for the entire script.\n"
                                "   ✅ FORMAT: '40%以上', '2倍', '300万円' — pick ONE phrasing and keep it consistent.\n"
                                "\n"
                                "=== ANTI-REPETITION (STRICT — JAPANESE) ===\n"
                                "Each scene MUST introduce completely NEW information.\n"
                                "Do NOT repeat the same concept (e.g., '需要と供給のアンバランス') across multiple scenes.\n"
                                "If Scene 2 mentions a concept, Scene 3 MUST cover something different (e.g., interest rates, taxes, policy)."
                            )
                        else:
                            speech_rules = (
                                "ENGLISH SPEECH STYLE — ANTI-GENERIC RULES (CRITICAL):\n"
                                "- Write like a top TikTok narrator: conversational, punchy, direct.\n"
                                "- Use: 'Here's the thing', 'But wait', 'The crazy part is', 'Nobody talks about this', 'And that's when'\n"
                                "- Short sentences. Fragments OK for emphasis. 'Like this.'\n"
                                "- NEVER start with 'In this video' or 'Today I'm going to'.\n"
                                "\n"
                                "=== ENGLISH LANGUAGE & GRAMMAR PURITY (CRITICAL — HARD RULES) ===\n"
                                "1. TARGET LANGUAGE: 100% native, natural English. No mixing with other languages.\n"
                                "2. NO HALLUCINATION: Use only real, correctly-spelled English words. Do NOT invent words.\n"
                                "   (e.g., use 'skyrocketing' NOT 'skyrocketting', use 'occurred' NOT 'occured').\n"
                                "3. NO STUTTERING: Do NOT repeat any word consecutively by accident.\n"
                                "   ABSOLUTELY FORBIDDEN: 'the the', 'and and', 'that that' — each word ONCE only.\n"
                                "4. TONE: Aggressive, street-smart financial analyst on TikTok. Use punchy connectors:\n"
                                "   'Here's the thing', 'But wait', 'Think about it', 'Nobody tells you this'.\n"
                                "   DO NOT use: 'It is important to note', 'In conclusion', 'As you can see'.\n"
                                "\n"
                                "=== HOOK & CTA RULES (ENGLISH-SPECIFIC) ===\n"
                                "- SCENE 1 (HOOK): Must be a Shocking Claim or Agitating Question. Max 1.5 seconds of speech.\n"
                                "  NO generic openers like 'Many people wonder...' or 'Today we will discuss...'.\n"
                                "  ✅ CORRECT: 'Rent prices jumped 40% in 3 years. Your salary? Maybe 5%.'\n"
                                "  ✅ CORRECT: 'Your landlord is paying off their mortgage with YOUR deposit right now.'\n"
                                "- SCENE END (CTA): The final scene MUST end with a provocative question forcing comments.\n"
                                "  ✅ CORRECT: 'Team rent or team buy right now? Drop it below.'\n"
                                "  ✅ CORRECT: 'With your salary, when do you think you can afford a home? Be honest.'\n"
                                "  NEVER use: 'Follow for more', 'Like and subscribe', 'Share with your friends'.\n"
                                "\n"
                                "=== ANTI-REPETITION (STRICT — ENGLISH) ===\n"
                                "Each scene MUST introduce completely NEW information.\n"
                                "Do NOT repeat the same concept (e.g., 'supply and demand imbalance') across multiple scenes.\n"
                                "If Scene 2 mentions a concept, Scene 3 MUST cover something different (e.g., interest rates, taxes, policy)."
                            )

                        # ── Retention framework: Shorts có triết lý riêng với Long video ──
                        if is_shorts:
                            # Map scene index → H-R-V-C phase dựa trên tổng số scene
                            _h_scenes = 1                            # HOOK: scene 1
                            _r_scenes = max(1, round(total_scenes_needed * 0.15))  # RETAIN: ~15%
                            _cta_scenes = 1                          # CTA: scene cuối
                            _v_scenes = total_scenes_needed - _h_scenes - _r_scenes - _cta_scenes
                            retention_framework = (
                                "=== BỘ KHUNG H-R-V-C (HOOK → RETAIN → VALUE → CTA) ===\n"
                                f"Bạn viết {total_scenes_needed} scenes × {target_sec_per_scene}s ≈ {duration}s. Phân bổ theo khung sau:\n"
                                "\n"
                                f"━━ [H] HOOK — Scene 1 (0–3s) ━━\n"
                                "Mục tiêu: Khiến người xem NGỪNG LẠI ngay lập tức trong 3 giây đầu.\n"
                                "Công thức: Bắt đầu bằng TRẢI NGHIỆM CÁ NHÂN viewer NHẬN RA NGAY, KHÔNG dùng số liệu thống kê.\n"
                                "\n"
                                "  ❌ SAI — Mở bằng số liệu khô: '90% người Việt gặp tình trạng này...' (nghe như đọc báo cáo)\n"
                                "  ❌ SAI — Giới thiệu chủ đề: 'Hôm nay mình sẽ chia sẻ về kỹ năng giao tiếp...'\n"
                                "  ❌ SAI — Câu hỏi + thống kê cùng lúc: 'Bạn có biết 90% người Việt rụt rè không?' (cả 2 lỗi cùng lúc)\n"
                                "  ✅ ĐÚNG — Trải nghiệm quen thuộc: 'Bạn biết câu trả lời, nhưng trong cuộc họp, bạn vẫn im lặng. Tại sao?'\n"
                                "  ✅ ĐÚNG — Sự thật ngược đời: 'Làm việc chăm hơn không giúp bạn giàu — đây là lý do.'\n"
                                "  ✅ ĐÚNG — Nỗi đau cụ thể: 'Lương 15 triệu nhưng tháng nào cũng thiếu? Lỗi không phải do bạn tiêu hoang.'\n"
                                f"  → Hook style cho video này: {hook_instruction}\n"
                                "\n"
                                f"━━ [R] RETAIN — Scenes 2–{_h_scenes + _r_scenes} (3–10s) ━━\n"
                                "Mục tiêu: Chứng minh bạn HIỂU VẤN ĐỀ của họ. Đẩy sự tò mò lên đỉnh.\n"
                                "Công thức: ĐỒNG CẢM + TIẾT LỘ NGUYÊN NHÂN SÂU XA (ngôn ngữ bình dân)\n"
                                "  → Ví dụ: 'Đa số dân văn phòng mắc phải 1 cái bẫy tâm lý: Thích an toàn nhưng lại muốn x2 thu nhập.'\n"
                                "  → Câu RETAIN phải khiến viewer nghĩ: 'Ủa, mình cũng đang như vậy không?'\n"
                                "  → Mở 1 loop chưa đóng: 'Và đây là điều mà 90% không biết...' (đóng ở scene VALUE)\n"
                                "\n"
                                f"━━ [V] VALUE — Scenes {_h_scenes + _r_scenes + 1}–{total_scenes_needed - 1} (10–40s) ━━\n"
                                f"Mục tiêu: Cung cấp {_v_scenes} ĐIỂM GIÁ TRỊ nhanh, gọn, dồn dập.\n"
                                "Công thức: Mỗi scene = 1 gạch đầu dòng. Dùng 'Thứ nhất:', 'Thứ hai:', 'Thứ ba:'\n"
                                "  → Mỗi điểm phải CỤ THỂ và CÓ THỂ THỰC HIỆN NGAY:\n"
                                "     ĐÚNG: 'Đừng đợi chán mới tìm việc. Đi phỏng vấn ít nhất 6 tháng 1 lần để biết giá thị trường.'\n"
                                "     SAI: 'Hãy tìm cơ hội phát triển bản thân.'\n"
                                "  → Chuyển 100% thuật ngữ học thuật → tiếng Việt bình dân:\n"
                                "     'Sunk cost' → 'Tiền đã mất rồi thì đừng tiếp tục ném thêm vào'\n"
                                "     'Mindset' → 'Cách nhìn/suy nghĩ'\n"
                                "     'Opportunity cost' → 'Cơ hội bỏ lỡ'\n"
                                "\n"
                                f"━━ [C] CTA — Scene {total_scenes_needed} (40–{duration}s) ━━\n"
                                "Mục tiêu: KÍCH THÍCH COMMENT và SHARE → thuật toán phân phối rộng hơn.\n"
                                "Công thức: Câu hỏi MÀ NGƯỜI XEM BẮT BUỘC PHẢI CHỌN PHE (tranh cãi nhẹ)\n"
                                "  ✅ ĐÚNG (chọn phe): 'Bạn thuộc team cống hiến 5 năm 1 công ty hay team nhảy việc mỗi 2 năm? Cãi ở comment!'\n"
                                "  ✅ ĐÚNG (tag bạn bè): 'Tag ngay người bạn đang bị kẹt ở công ty 3 năm không lên lương!'\n"
                                "  ❌ SAI: 'Follow mình để xem thêm nhé!'\n"
                                "  ❌ SAI: 'Like và share để ủng hộ mình!'\n"
                                "\n"
                                "=== TỔNG KIỂM TRA TRƯỚC KHI XUẤT ===\n"
                                "  ✔️ Scene 1: Có đánh vào nỗi đau/tò mò trong 3 giây đầu không?\n"
                                "  ✔️ Mỗi scene VALUE: Có thể làm ngay hôm nay không?\n"
                                "  ✔️ Scene cuối: Có câu hỏi buộc viewer chọn phe không?\n"
                                "  ✔️ Mỗi câu: Tối đa 12 từ. Không có từ tiếng Anh không giải thích.\n"
                                "  ❌ LOẠI: Bất kỳ câu nào có thể dùng cho chủ đề KHÁC mà không cần sửa."
                            )
                        else:
                            retention_framework = (
                                "=== VIRAL RETENTION FRAMEWORK ===\n"
                                "You are writing for SHORT-FORM video (TikTok/Shorts). Every second counts.\n"
                                "The ONLY goal: make the viewer UNABLE to swipe away.\n\n"
                                "SCENE-BY-SCENE STRUCTURE:\n"
                                f"• Scene 1 (HOOK — 0–3s): {hook_instruction}\n"
                                "  → The FIRST SENTENCE is everything. Must create immediate emotion: shock, curiosity, or fear of missing out.\n"
                                "  → Viewer decides to stay or leave HERE. Make it IMPOSSIBLE to leave.\n\n"
                                "• Scenes 2–4 (AMPLIFY): Make the problem/topic feel URGENT and PERSONAL.\n"
                                "  → Use 'You probably didn't know...' / 'Most people get this wrong...'\n"
                                "  → Add 1 surprising statistic, counter-intuitive fact, or relatable scenario.\n"
                                "  → End each scene with an OPEN LOOP: a question or partial reveal ('...and the reason is shocking').\n\n"
                                "• Middle scenes (DELIVER VALUE — rapid-fire): Give real, specific, surprising information.\n"
                                "  → Each scene = 1 clear insight. No padding. No 'as we mentioned earlier'.\n"
                                "  → Alternate between: fact → story → fact → question → reveal.\n"
                                "  → Every 3rd scene: PATTERN INTERRUPT — shift tone, speed, or angle unexpectedly.\n\n"
                                "• Last 2 scenes (PAYOFF + CTA): Deliver the promised reveal. Make viewer feel rewarded.\n"
                                "  → Close the loops opened earlier. Give the 'aha' moment.\n"
                                "  → If loop ending enabled: last line MUST echo the opening hook.\n\n"
                                "PACING RULES (NON-NEGOTIABLE):\n"
                                "✅ Each sentence: MAX 12 words. Break long ideas into 2 sentences.\n"
                                "✅ Scene 1 (Hook): Start with a RELATABLE SITUATION or PROVOCATIVE QUESTION — NOT a statistic. Make it feel like someone speaking directly to you.\n"
                                "✅ Scenes 2+: Can use numbers, named concepts, or mechanisms for depth.\n"
                                "✅ Vary sentence length: short. Then medium length. Then SHORT again for punch.\n"
                                "❌ NEVER use filler: 'As you can see', 'It's worth noting', 'In conclusion', 'Furthermore'\n"
                                "❌ NEVER repeat a point from any previous scene. Fresh info every scene.\n"
                                "❌ NEVER end a scene with a generic summary. End with a hook to the next scene."
                            )

                        if is_first:
                            context_block = (
                                f"=== VIDEO OVERVIEW ===\n"
                                f"Topic: {topic_instruction}\n"
                                f"Language: {lang} | Style: {style}\n"
                                f"Total: {total_scenes_needed} scenes (~{duration}s)\n"
                                f"This is PART 1 (scenes {batch_start}–{batch_end} of {total_scenes_needed}).\n\n"
                                f"{retention_framework}\n\n"
                                f"{speech_rules}\n\n"
                                f"ADDITIONAL RULES:\n{retention_rules}"
                            )
                            format_str = (
                                f'{{"title":"viral title in {lang} (max 60 chars, curiosity-driven)","description":"SEO description in {lang}",'\
                                f'"tags":["t1","t2"],"scenes":[{{"id":1,"text":"narration STRICTLY in {lang}",'\
                                f'"keyword":{kw_example},"soundEffect":"none|whoosh|click|chime|deep_hit","tts_speed":{float(tts_rate):.1f},"retention_note":"why viewer stays"}}]}}'
                            )
                        else:
                            end_note = ("FINAL BATCH — close all loops, deliver the payoff, apply CTA." if is_last else "Keep 1 open loop at the end to pull viewer to the next scene.")
                            context_block = (
                                f"=== CONTINUATION (Batch {batch_num}) ===\n"
                                f"Writing scenes {batch_start}–{batch_end} of {total_scenes_needed} for a {style} video {topic_instruction_short} in {lang}.\n"
                                f"PREVIOUS SCENE ENDED: \"{prev_summary}\"\n"
                                f"Continue the narrative momentum. {end_note}\n"
                                f"PACING: Each scene = 1 new insight. No repetition. Punchy sentences.\n"
                                f"{retention_rules if is_last else ''}"
                            )
                            format_str = (
                                f'{{"scenes":[{{"id":{batch_start},"text":"narration STRICTLY in {lang}",'\
                                f'"keyword":{kw_example},"soundEffect":"none|whoosh|click|chime|deep_hit","tts_speed":{float(tts_rate):.1f},"retention_note":"why viewer stays"}}]}}'
                            )

                        if lang == "Vietnamese":
                            q_banned_1 = "'Chính sách là gì? Chính phủ làm gì? Hãy cùng tìm hiểu.'"
                            q_banned_2 = "'Hãy cùng tìm hiểu', 'cùng khám phá nhé', 'thử xem sao'"
                            q_banned_3 = "'Hôm nay chúng ta sẽ nói về...' / 'Bạn đã bao giờ nghĩ về chủ đề này chưa?'"
                            q_correct_1 = "'Năm 2023, thiệt hại lừa đảo nhà đất vượt 3.000 tỷ đồng. Tiền của bạn không an toàn.'"
                            q_correct_2 = "'Khi giá nhà tăng, chính phủ tăng thuế. Nhưng người thực trả là người thuê nhà, không phải chủ nhà.'"
                        elif lang == "Korean":
                            q_banned_1 = "'정책이란 무엇인가요? 정부는 무엇을 할까요? 지금부터 알아봅시다.'"
                            q_banned_2 = "'Let\\'s find out', '알아봅시다', '살펴봅시다'"
                            q_banned_3 = "'오늘은 ~에 대해 알아보겠습니다' / '이 주제에 대해 생각해보신 적 있나요?'"
                            q_correct_1 = "'2023년 전세 사기 피해액은 3조 원을 넘었잖아요. 보증금이 그냥 증발하는 거예요.'"
                            q_correct_2 = "'집값이 오를 때 정부는 세금을 올립니다. 그러나 실제로 집주인이 아닌 세입자가 그 비용을 냅니다.'"
                        elif lang == "Japanese":
                            q_banned_1 = "'政策とは何でしょうか? 政府は何をしているのでしょうか? 今日は一緒に考えましょう。'"
                            q_banned_2 = "'見てみましょう', '一緒に学びましょう', '確認してみましょう'"
                            q_banned_3 = "'今日は〜について話します' / 'このテーマについて考えたことはありますか?'"
                            q_correct_1 = "'2023年、家賃詐欺の被害額が300億円を超えたんですよ。敷金が消えちゃうって話です。'"
                            q_correct_2 = "'家賃が上がると政府は税金を上げます。でも実際に払うのは大家じゃなくて入居者なんですよ。'"
                        else:
                            q_banned_1 = "'What is a policy? What does the government do? Let\\'s find out.'"
                            q_banned_2 = "'Let\\'s find out', 'let\\'s explore', 'let\\'s dive in'"
                            q_banned_3 = "'Today we will talk about...' / 'Have you ever thought about this topic?'"
                            q_correct_1 = "'In 2023, real estate fraud losses exceeded $3 billion. Your deposit is not safe.'"
                            q_correct_2 = "'When house prices rise, the government raises taxes. But the tenant pays the cost, not the landlord.'"

                        progress_start = batch_start / total_scenes_needed
                        if progress_start <= 0.25:
                            current_arc = "PART 1 (Hook/Intro) - State the central claim/problem."
                        elif progress_start <= 0.6:
                            current_arc = "PART 2 (Pros/Benefits/Core Mechanisms) - Give concrete advantages or explain how it works with evidence."
                        elif progress_start <= 0.85:
                            current_arc = "PART 3 (Cons/Risks/Nuance) - Address real downsides honestly."
                        else:
                            current_arc = "PART 4 (Conclusion) - Synthesis and what the viewer should DO with this info."

                        recent_facts = ""
                        if all_scene_data:
                            recent_texts = " ".join([s["text"] for s in all_scene_data[-8:]])
                            recent_facts = f"RECENTLY USED FACTS (DO NOT REPEAT ANY CONCEPTS/NUMBERS FROM HERE):\n{recent_texts}\n\n"

                        batch_prompt = (
                            f"[seed:{seed}-b{batch_num}] You are an ELITE {'vertical Shorts/TikTok' if is_shorts else 'viral short-form'} video scriptwriter.\n"
                            f"Your content is SUBSTANTIVE: you use real numbers, named concepts, and provable mechanisms. Viewers learn something they didn't know before.\n"
                            f"\n"
                            f"=== YOUR CREATOR VOICE FOR THIS VIDEO ===\n"
                            f"{_persona_instruction}\n"
                            f"This voice MUST be consistent across ALL scenes. The viewer should feel this is a real person, not a template.\n"
                            f"\n"
                            f"=== DEPTH REQUIREMENT ===\n"
                            f"Scenes 2+ MUST contain at least ONE of these depth signals:\n"
                            f"  [NUMBER]    A specific statistic or percentage: '70%', '3 out of 4', '$2,000'\n"
                            f"  [NAMED]     A named concept, law, or effect: 'Parkinson\\'s Law', 'Dunning-Kruger', 'sunk cost'\n"
                            f"  [MECHANISM] A causal explanation: 'because...', 'this happens when...', 'the reason is...'\n"
                            f"  [SCENARIO]  A concrete situation the viewer recognizes: 'You make 30M/month but spend 31M'\n"
                            f"⚠️ HOOK EXCEPTION (Scene 1): The hook does NOT need a statistic. Its job is EMOTIONAL PULL.\n"
                            f"  → Hook depth = [SCENARIO] or [MECHANISM] only. Example: 'Bạn im lặng trong cuộc họp dù biết câu trả lời — không phải vì không biết, mà vì sợ.'\n"
                            f"If scenes 2+ have NONE of the above → it is filler → rewrite it.\n"
                            f"\n"
                            f"=== NARRATIVE STRUCTURE (NON-NEGOTIABLE) ===\n"
                            f"Video structure follows a 4-part arc (Hook -> Benefits -> Nuance -> Conclusion).\n"
                            f"For THIS specific batch (Scenes {batch_start} to {batch_end}), you are currently in:\n"
                            f"👉 {current_arc}\n"
                            f"Focus ONLY on this part of the arc for this batch.\n"
                            f"\n"
                            f"=== LANGUAGE PURITY (CRITICAL for {lang}) ===\n"
                            f"- Write in 100% pure {lang}. NO mixing in English words or phrases.\n"
                            f"- If a concept only exists in English (e.g. 'sunk cost fallacy'), ALWAYS explain it in {lang}: \n"
                            f"  ❌ WRONG: 'sunk cost fallacy khien ban...'\n"
                            f"  ✅ RIGHT: 'Chi phi chim (sunk cost) la khi ban tiep tuc vi da bo tien vao, khong phai vi no co gia tri'\n"
                            f"- 'available', 'mindset', 'update', 'skill set' → translate to {lang} always.\n"
                            f"CRITICAL: ALL \"text\" fields MUST be written in {lang} ({lang_upper}). {lang_rule}\n\n"
                            f"{recent_facts}"
                            f"{context_block}\n\n"
                            f"=== THIS BATCH ===\n"
                            f"Write EXACTLY {batch_count} scenes (IDs {batch_start} to {batch_end}).\n"
                            f"Each scene narration: EXACTLY {words_per_scene} words (±3). MINIMUM {min_words_scene} words — NEVER write less.\n"
                            f"SCENE FOCUS RULE (CRITICAL): Each scene = EXACTLY 1 clear point. ONE idea only.\n"
                            f"  If you have a strict word limit (e.g. 15-20 words), PRIORITIZE ONE STRONG DEPTH SIGNAL (a number or mechanism) over trying to fit multiple ideas.\n"
                            f"  - TRANSITION: The last sentence of scene N must naturally lead into the first sentence of scene N+1, creating a seamless storytelling flow.\n"
                            f"  - ANTI-REPETITION: You MUST NOT repeat any concepts, numbers, or facts from PREVIOUS SCENE ENDED or RECENTLY USED FACTS.\n"
                            f"\n"
                            f"=== NO-QUESTION-ONLY SCENES (ABSOLUTELY FORBIDDEN) ===\n"
                            f"A scene that only asks questions with NO concrete answer or fact = ZERO viewer value = instant swipe-away.\n"
                            f"  ❌ BANNED: {q_banned_1} (50 seconds of questions = channel killer)\n"
                            f"  ❌ BANNED: Any scene ending with: {q_banned_2}\n"
                            f"  ❌ BANNED: Generic scene openers: {q_banned_3}\n"
                            f"  ✅ REQUIRED: Every scene MUST contain at least 1 concrete fact, statistic, or specific revelation.\n"
                            f"  ✅ PATTERN: [Specific fact/number that surprises] → [One-line implication for the viewer's life]\n"
                            f"  ✅ CORRECT: {q_correct_1}\n"
                            f"  ✅ CORRECT: {q_correct_2}\n"
                            f"\n"
                            f"{keyword_instruction}\n\n"
                            f"=== FINAL SELF-AUDIT BEFORE RETURNING JSON ===\n"
                            f"1. Is every text field strictly in {lang} with no mixed English words?\n"
                            f"2. Does every scene have exactly 1 depth signal (number/mechanism)?\n"
                            f"3. Did you avoid ending any scene with a generic question?\n"
                            f"4. Does scene N naturally transition to scene N+1?\n"
                            f"5. Did you maintain the same Creator Voice Persona as the introduction?\n"
                            + (
                                f"6. [SHORTS ENDING DIVERSITY] Count consecutive sentences ending with ~ì°ì©/~ìì©. "
                                f"If ANY 3 or more consecutive endings are the same, REWRITE using ~ììì©, ~ê°ëì©, ~ì£ ?, ~ëë°ì©, ~ë¤ë ê±°!, ~ëì© before returning.\n"
                                f"7. [SHORTS SCOPE] Does this script cover MORE THAN ONE macro concept? "
                                f"If yes, DELETE all but the single strongest concept. ONE video = ONE message. Target: 35-45 seconds total.\n"
                                if is_shorts else ""
                            )
                            + f"\nReturn ONLY valid JSON (no markdown, no explanation, no trailing commas, escape all double quotes inside text fields, no line breaks inside string values):\n{format_str}"
                        )
                        raw_batch = call_ai_script(batch_prompt)

                        try:
                            parsed = parse_json_robust(raw_batch)
                        except (json.JSONDecodeError, ValueError) as _je:
                            log(f"  ⚠️ Batch {batch_num} JSON lỗi: {_je} — bỏ qua batch này")
                            scene_cursor += batch_count
                            continue

                        if is_first:
                            video_title       = parsed.get("title", topic)
                            video_description = parsed.get("description", "")
                            video_tags        = parsed.get("tags", [])

                        batch_scenes = parsed.get("scenes", [])
                        if batch_scenes:
                            for bi, bsc in enumerate(batch_scenes):
                                bsc["id"] = scene_cursor + bi + 1
                                # ── CLEANUP: xóa lặp từ liền kề và khoảng trắng thừa do AI lỗi ──
                                # Ví dụ: '이를 이를' → '이를', '  ' → ' '
                                _raw_text = bsc.get("text", "")
                                _cleaned  = re.sub(r'\b(\w+)( \1\b)+', r'\1', _raw_text)
                                _cleaned  = " ".join(_cleaned.split())
                                if _cleaned != _raw_text:
                                    print(f"[Cleanup] Scene {bsc['id']}: fixed repeated words — '{_raw_text[:80]}' → '{_cleaned[:80]}'")
                                bsc["text"] = _cleaned
                            all_scene_data.extend(batch_scenes)
                            last_text    = batch_scenes[-1].get("text", "")
                            prev_summary = last_text[:200] if last_text else ""
                            log(f"  ✅ Batch {batch_num}: +{len(batch_scenes)} cảnh (tổng: {len(all_scene_data)})")
                        else:
                            log(f"  ⚠️ Batch {batch_num} trả về 0 cảnh")

                        scene_cursor += batch_count

                        # Delay giữa các batch để tránh Groq rate limit (tokens/phút)
                        if scene_cursor < total_scenes_needed:
                            log(f"  ⏳ Đợi 12s trước batch tiếp theo (tránh rate limit)...")
                            time.sleep(12)

                    # ── POST-PROCESS: Dedup câu kết tương tự cấu trúc ──────────────
                    # Phát hiện và làm mờ câu kết ở các scene khác nhau nếu chúng có cùng cấu trúc
                    # (ví dụ: nhiều scene cùng kết bằng "Bạn nghĩ sao? Để lại bình luận nhé!")
                    def _dedup_similar_endings(scenes: list) -> list:
                        """Xóa bỏ câu kết bị trùng cấu trúc giữa các scene.
                        Nếu scene N và scene M (M < N) có câu kết cùng ≥ 70% từ khóa chung
                        thì câu kết của scene N bị xóa bỏ (giữ lại nội dung, bỏ câu cuối trùng).
                        KHÔNG áp dụng cho scene cuối (CTA scene được bảo vệ).
                        """
                        import re as _re2

                        def _normalize(s: str) -> set:
                            """Trả về tập từ khóa có nghĩa (loại stopword ngắn)."""
                            _stop = {"và", "hay", "hoặc", "là", "của", "trong", "với", "bạn", "mình",
                                     "the", "a", "an", "is", "are", "to", "of", "and", "or", "in",
                                     "이", "가", "을", "를", "은", "는", "의", "에", "로", "에서"}
                            tokens = set(_re2.sub(r'[^\w\s]', '', s.lower()).split())
                            return tokens - _stop

                        def _last_sentence(text: str) -> str:
                            """Lấy câu cuối cùng của text."""
                            # Tách theo dấu câu kết thúc
                            parts = _re2.split(r'(?<=[.!?])\s+', text.strip())
                            return parts[-1].strip() if parts else text.strip()

                        if len(scenes) <= 1:
                            return scenes

                        seen_endings: list = []  # list of (normalized_set, scene_idx)
                        SIMILARITY_THRESHOLD = 0.65  # ≥65% từ khóa chung = trùng

                        for idx, sc in enumerate(scenes[:-1]):  # Bảo vệ scene cuối (CTA)
                            text = sc.get("text", "")
                            last_sent = _last_sentence(text)
                            last_kws  = _normalize(last_sent)
                            if len(last_kws) < 3:
                                continue  # câu quá ngắn, bỏ qua

                            for prev_kws, prev_idx in seen_endings:
                                if not prev_kws:
                                    continue
                                intersection = len(last_kws & prev_kws)
                                union        = len(last_kws | prev_kws)
                                similarity   = intersection / union if union > 0 else 0
                                if similarity >= SIMILARITY_THRESHOLD:
                                    # Xóa câu cuối trùng: giữ phần còn lại
                                    sentences = _re2.split(r'(?<=[.!?])\s+', text.strip())
                                    if len(sentences) > 1:
                                        new_text = ' '.join(sentences[:-1]).strip()
                                        sc["text"] = new_text
                                        print(f"[Dedup] Scene {sc.get('id','?')}: removed similar ending "
                                              f"(sim={similarity:.0%} with scene {scenes[prev_idx].get('id','?')}): "
                                              f"'{last_sent[:60]}'")
                                    break  # Đã xử lý, không cần check tiếp

                            seen_endings.append((last_kws, idx))

                        return scenes

                    all_scene_data = _dedup_similar_endings(all_scene_data)
                    log(f"  🧹 Dedup endings: kiểm tra {len(all_scene_data)} cảnh (câu kết trùng sẽ bị xóa tự động)")

                    # Narration and visuals are separate concerns. Generate visual
                    # prompts only after the final narration is known, and only
                    # spend an extra AI call when Veo generation is actually on.
                    if cfg.get("veo3_enabled", False) or cfg.get("veo3_provider") == "gemini_web" or new_mode == "veo3":
                        log("  🎬 Đang tạo visual prompt theo batch (tối đa 10 cảnh/call)...")
                        all_scene_data = build_visual_prompts_batch(all_scene_data, lang, log)
                    else:
                        _nationality = {
                            "Korean": "South Korean", "Vietnamese": "Vietnamese",
                            "Japanese": "Japanese", "English": "Western",
                        }.get(lang, "local")
                        for _scene in all_scene_data:
                            _scene["veo3_prompt"] = build_veo3_prompt(
                                f"A realistic {_nationality} person",
                                "Natural movement matching the narration",
                                _scene.get("keyword", f"An authentic {_nationality} location"),
                                _nationality,
                            )

                    # ── Fallback: nếu AI batch 1 không trả title/desc/tags → gọi riêng ──
                    if not video_title.strip() or not video_description.strip() or not video_tags:
                        log("  ⚠️ Title/Description/Tags chưa có — đang gọi AI tạo SEO riêng...")
                        _first_scenes_text = " ".join([s.get("text","") for s in all_scene_data[:5]])
                        _seo_lang_note = {
                            "Korean":     "Write the title and description in Korean (한국어). Tags can be Korean or English.",
                            "Vietnamese": "Write the title and description in Vietnamese (tiếng Việt). Tags can be Vietnamese or English.",
                            "English":    "Write the title and description in English.",
                        }.get(lang, "Write the title and description in the same language as the script.")
                        _seo_prompt = (
                            f"You are a YouTube SEO expert. Based on this video script excerpt:\n\n"
                            f"\"{_first_scenes_text[:800]}\"\n\n"
                            f"Generate optimized YouTube metadata. {_seo_lang_note}\n"
                            f"Return ONLY valid JSON with these exact fields:\n"
                            f'{{"title":"viral title max 60 chars curiosity-driven","description":"SEO description 150-250 words with keywords","tags":["tag1","tag2","tag3","tag4","tag5","tag6","tag7","tag8","tag9","tag10"]}}'
                        )
                        try:
                            _seo_raw = call_ai(_seo_prompt)
                            _seo_raw = _seo_raw.strip()
                            import re as _re2
                            if _seo_raw.startswith("```"):
                                _seo_raw = _re2.sub(r"^```[a-zA-Z]*\n", "", _seo_raw)
                                _seo_raw = _re2.sub(r"\n```$", "", _seo_raw).strip()
                            _seo_parsed = json.loads(_seo_raw)
                            if not video_title.strip():
                                video_title = _seo_parsed.get("title", topic)
                            if not video_description.strip():
                                video_description = _seo_parsed.get("description", "")
                            if not video_tags:
                                video_tags = _seo_parsed.get("tags", [])
                            log(f"  ✅ SEO fallback: title='{video_title[:40]}...' | {len(video_tags)} tags")
                        except Exception as _seo_e:
                            log(f"  ⚠️ SEO fallback lỗi: {_seo_e} — dùng topic làm title")
                            video_title = video_title or topic
                            video_description = video_description or ""
                            video_tags = video_tags or []

                    if lang == "Vietnamese":
                        for scene_data in all_scene_data:
                            scene_data["text"] = normalize_vietnamese_tts(
                                str(scene_data.get("text", ""))
                            )

                    script = {
                        "title":       video_title,
                        "description": video_description,
                        "tags":        video_tags,
                        "scenes":      all_scene_data,
                    }

                    vid_orientation = "portrait" if "9:16" in aspect else "landscape"
                    scenes = []
                    used_pexels_urls = set()
                    used_photo_urls  = set()
                    # Tự động xen kẽ: cứ 3 cảnh video → 1 cảnh ảnh (Ken Burns)
                    AUTO_MIX_PHOTO_EVERY = 3
                    for sc_idx, sc_data in enumerate(script["scenes"]):
                        kw_clean = clean_keyword(sc_data["keyword"])
                        # Enrich keyword with niche context — tránh cảnh lạc đề (công nhân, cụ già đập gạch)
                        kw_clean = enrich_keyword_with_context(kw_clean, niche)
                        use_photo = (sc_idx > 0) and (sc_idx % AUTO_MIX_PHOTO_EVERY == 0) and (new_mode != "veo3")
                        img_url = None
                        vid_url = None
                        if use_photo:
                            img_url, _ = fetch_stock_photo(kw_clean, orientation=vid_orientation, used_urls=used_photo_urls)
                            if img_url:
                                used_photo_urls.add(img_url)
                                log(f"  🖼️ Cảnh {sc_idx+1}: xen ảnh stock (Ken Burns)")
                            else:
                                use_photo = False
                        if not use_photo:
                            _raw_vid = fetch_video_with_veo3(
                                kw_clean,
                                orientation=vid_orientation,
                                used_urls=used_pexels_urls,
                                scene_text=sc_data.get("text", ""),
                                veo3_prompt=sc_data.get("veo3_prompt", ""),
                                log_cb=log,
                                force_veo3=(new_mode == "veo3")
                            )
                            # phân biệt local path (Veo3) vs HTTP URL (stock)
                            if _raw_vid and (_raw_vid.startswith("/") or (len(_raw_vid) > 1 and _raw_vid[1] == ":")):
                                vid_url  = None        # không có stock URL
                                veo3_path = _raw_vid   # local file từ Veo3
                            else:
                                vid_url   = _raw_vid or None
                                veo3_path = None
                            if vid_url:
                                used_pexels_urls.add(vid_url)
                        else:
                            veo3_path = None
                        # Đọc tts_speed riêng của cảnh nếu AI trả về (ngược lại để None = dùng tốc độ chung)
                        _sc_speed_ai_raw = sc_data.get("tts_speed")
                        _sc_tts_speed_ai = None
                        if _sc_speed_ai_raw is not None:
                            try:
                                _spd = float(_sc_speed_ai_raw)
                                _sc_tts_speed_ai = f"{min([0.8,0.9,1.0,1.1,1.2,1.3,1.4,1.5,1.6,1.7,1.8,2.0], key=lambda x: abs(x - _spd)):.1f}"
                            except (TypeError, ValueError):
                                _sc_tts_speed_ai = None
                        _ip_ai = (sc_data.get("imagePrompt") or sc_data.get("image_prompt") or "").strip() or None
                        # Đọc imageEffect + normalize alias
                        _ie_ai_raw = (sc_data.get("imageEffect") or sc_data.get("image_effect") or "").strip()
                        _ie_ai_alias = {"slide_right":"pan_right","slide_left":"pan_left",
                                        "slide_up":"pan_up","slide_down":"pan_down",
                                        "ken_burns":"zoom_in","ken_burns_in":"zoom_in",
                                        "ken_burns_out":"zoom_out","zoomin":"zoom_in","zoomout":"zoom_out"}
                        _ie_ai_valid = {"zoom_in","zoom_out","pan_right","pan_left","pan_up","pan_down"}
                        _ie_ai_raw = _ie_ai_alias.get(_ie_ai_raw, _ie_ai_raw)
                        _img_effect_ai = _ie_ai_raw if _ie_ai_raw in _ie_ai_valid else None
                        scenes.append({
                            "id":          sc_data["id"],
                            "text":        sc_data["text"],
                            "keyword":     sc_data["keyword"],
                            "veo3_prompt": sc_data.get("veo3_prompt", ""),
                            "imagePrompt": _ip_ai,
                            "imageEffect": _img_effect_ai,
                            "soundEffect": sc_data.get("soundEffect", "none") if sc_data.get("soundEffect") in ("none", "whoosh", "click", "chime", "deep_hit") else "none",
                            "tts_speed":   _sc_tts_speed_ai,
                            "videoUrl":    vid_url,
                            "veo3Path":    veo3_path,
                            "imageUrl":    img_url,
                            "audioDone":   False,
                            "targetDur":   float(target_sec_per_scene),
                            "duration":    round(max(float(target_sec_per_scene), len(sc_data["text"].split()) / words_per_sec + 0.4), 1),
                        })
                    proj.update({"script": script, "scenes": scenes, "step": 1, "lang": lang})
                    save_proj(proj)
                    log(f'✅ Kịch bản: "{script["title"]}" — {len(scenes)} cảnh ({batch_num} batch)')

                    # ── Tạo Thumbnail (chỉ với video ngang 16:9) ──
                    if "9:16" not in aspect:
                        log("🖼️ Đang tạo thumbnail (OpenAI DALL-E 3)...")
                        gemini_key = (cfg.get("gemini") or [None])[0]
                        openai_key = cfg.get("openai", "") or None
                        thumb_path, thumb_err = generate_thumbnail(
                            script, gemini_key, W, H,
                            save_dir=Path.home() / "Desktop" / "AI_Videos",
                            openai_key=openai_key
                        )
                        if thumb_path:
                            proj["thumbnailPath"] = str(thumb_path)
                            save_proj(proj)
                            log(f"✅ Thumbnail: {thumb_path.name}")
                        else:
                            log(f"⚠️ Thumbnail thất bại: {thumb_err}")
                    else:
                        log("⏭️ Video Shorts 9:16 — bỏ qua thumbnail")

                    st.rerun()
                else:
                    script = proj["script"]
                    scenes = proj.get("scenes") or []

                    # ── FIX: Nếu scenes rỗng (do Import JSON từ ChatGPT) → build từ script ──
                    # Luồng tự động (gen_script) đã build scenes trong STEP 1.
                    # Luồng Import JSON chỉ set proj["script"] chứ không build scenes.
                    # → Cần rebuild ở đây để STEP 2 (Footage) có dữ liệu để chạy.
                    if not scenes and script and script.get("scenes"):
                        log("🔄 Phát hiện JSON imported — đang khởi tạo scenes từ kịch bản...")
                        _wps_map       = {"Vietnamese": 3.8, "Korean": 1.8, "English": 2.2, "Japanese": 1.8}
                        _words_per_sec = _wps_map.get(lang, 2.2) * float(tts_rate)

                        for sc_data in script["scenes"]:
                            _scene_text = str(sc_data.get("text", ""))
                            if lang == "Vietnamese":
                                _scene_text = normalize_vietnamese_tts(_scene_text)
                                sc_data["text"] = _scene_text
                            _ip_raw = (sc_data.get("imagePrompt") or sc_data.get("image_prompt") or "").strip() or None
                            _ie_rb = (sc_data.get("imageEffect") or sc_data.get("image_effect") or "").strip()
                            _ie_rb_alias = {"slide_right":"pan_right","slide_left":"pan_left",
                                            "slide_up":"pan_up","slide_down":"pan_down",
                                            "ken_burns":"zoom_in","ken_burns_in":"zoom_in",
                                            "ken_burns_out":"zoom_out","zoomin":"zoom_in",
                                            "zoomout":"zoom_out","zoom":"zoom_in"}
                            _ie_rb_valid = {"zoom_in","zoom_out","pan_right","pan_left","pan_up","pan_down"}
                            _ie_rb = _ie_rb_alias.get(_ie_rb, _ie_rb)
                            _img_effect_rb = _ie_rb if _ie_rb in _ie_rb_valid else None
                            # ── FIX: Ưu tiên đọc duration từ JSON gốc ──────────────────────────
                            # JSON có thể chứa calculated_tts_duration (ước tính chính xác hơn),
                            # duration (target gốc), hoặc target_duration.
                            # Fallback cuối: tính theo wps.
                            _sc_dur_json = (
                                sc_data.get("calculated_tts_duration")
                                or sc_data.get("target_duration")
                                or sc_data.get("duration")
                            )
                            if _sc_dur_json and isinstance(_sc_dur_json, (int, float)) and 1.5 <= float(_sc_dur_json) <= 60:
                                # Dùng calculated_tts_duration + 0.3s buffer; không nhỏ hơn target_sec_per_scene
                                _sc_dur_calc = round(max(float(target_sec_per_scene), float(_sc_dur_json) + 0.3), 1)
                            else:
                                _sc_dur_calc = round(
                                    max(float(target_sec_per_scene),
                                        len(_scene_text.split()) / max(_words_per_sec, 0.1) + 0.4),
                                    1
                                )
                            scenes.append({
                                "id":          sc_data.get("id", len(scenes) + 1),
                                "text":        _scene_text,
                                "keyword":     sc_data.get("keyword", niche),
                                "veo3_prompt": sc_data.get("veo3_prompt", ""),
                                "imagePrompt": _ip_raw,
                                "imageEffect": _img_effect_rb,
                                "soundEffect": sc_data.get("soundEffect", "none") if sc_data.get("soundEffect") in ("none", "whoosh", "click", "chime", "deep_hit") else "none",
                                "videoUrl":    None,
                                "veo3Path":    None,
                                "imageUrl":    None,
                                "audioDone":   False,
                                "targetDur":   float(target_sec_per_scene),
                                "duration":    _sc_dur_calc,
                            })
                        proj.update({"scenes": scenes, "lang": lang, "step": 1})
                        save_proj(proj)
                        log(f"✅ Đã khởi tạo {len(scenes)} cảnh từ JSON — bắt đầu STEP 2 (Footage)...")

                # STEP 2: Footage
                if run_all:
                    log("🎬 Tải footage (Pexels / Veo3 / Ảnh AI) — xen kẽ video + ảnh tự động...")
                    vid_orientation = "portrait" if "9:16" in aspect else "landscape"
                    used_urls_step2 = set(s.get("videoUrl") for s in scenes if s.get("videoUrl"))
                    used_photo_urls_step2 = set(
                        s.get("imageUrl") for s in scenes
                        if s.get("imageUrl") and isinstance(s["imageUrl"], str) and s["imageUrl"].startswith("http")
                    )
                    _proj_lang = proj.get("lang", lang)

                    _gemini_keys = cfg.get("gemini", [])
                    _current_gkey = _gemini_keys[0] if _gemini_keys else None

                    # ── Cơ chế xen kẽ: cứ _MIX_PHOTO_EVERY cảnh video/AI-image → 1 cảnh stock photo ──
                    # Không áp dụng khi đang dùng AI Image mode (vì 100% unique ảnh AI rồi)
                    _MIX_PHOTO_EVERY = 3   # cảnh 3, 6, 9, ... sẽ là stock photo Ken Burns
                    _visual_counter = 0    # chỉ đếm cảnh thực sự cần fetch (bỏ qua cảnh đã có visual)

                    for i, s in enumerate(scenes):
                        if not s.get("customVid") and not s.get("videoUrl") and not s.get("veo3Path") and not s.get("imageUrl"):
                            log(f"  Cảnh {i+1}/{len(scenes)}: {s['keyword']}")
                            _kw = inject_region_into_keyword(
                                clean_keyword(s["keyword"], lang=_proj_lang),
                                _proj_lang
                            )

                            # ── Hook (cảnh 0) luôn là video/AI — xen kẽ bắt đầu từ cảnh 1 ──
                            _use_mix_photo = (
                                i > 0
                                and not use_ai_images  # AI image mode thì không xen kẽ stock photo
                                and (_visual_counter % _MIX_PHOTO_EVERY == _MIX_PHOTO_EVERY - 1)
                            )

                            if _use_mix_photo:
                                _ph_url, _ = fetch_stock_photo(_kw, orientation=vid_orientation, used_urls=used_photo_urls_step2)
                                if _ph_url:
                                    used_photo_urls_step2.add(_ph_url)
                                    scenes[i]["imageUrl"] = _ph_url
                                    scenes[i]["videoUrl"] = None
                                    scenes[i]["veo3Path"] = None
                                    log(f"  🖼️ Cảnh {i+1}: xen ảnh stock (Ken Burns) — nhịp {_visual_counter+1}/{_MIX_PHOTO_EVERY}")
                                    _visual_counter += 1
                                    continue
                                else:
                                    log(f"  ⚠️ Cảnh {i+1}: không tìm được ảnh stock — fallback sang AI image/video")

                            if use_ai_images and _current_gkey:
                                log(f"  🎨 Tạo ảnh AI tĩnh cho cảnh {i+1}...")
                                img_save = work / f"ai_img_s{i}.jpg"
                                _img_prompt = (s.get("imagePrompt") or "").strip()
                                img_path, err = generate_scene_image_ai(
                                    _kw, _current_gkey, W, H, img_save,
                                    image_prompt=_img_prompt
                                )
                                if img_path:
                                    scenes[i]["imageUrl"] = str(img_path)
                                    if _img_prompt:
                                        log(f"  ✅ Cảnh {i+1}: ảnh AI từ imagePrompt tùy chỉnh")
                                    else:
                                        log(f"  ✅ Cảnh {i+1}: ảnh AI từ keyword '{_kw}'")
                                    _visual_counter += 1
                                    continue
                                else:
                                    log(f"  ⚠️ Lỗi tạo ảnh AI: {err} — Fallback sang Stock Video...")
                                    use_ai_images = False

                            _raw_vid = fetch_video_with_veo3(
                                _kw,
                                orientation=vid_orientation,
                                used_urls=used_urls_step2,
                                scene_text=s.get("text", ""),
                                veo3_prompt=s.get("veo3_prompt", ""),
                                log_cb=log,
                                force_veo3=(st.session_state.get("proj_mode") == "veo3")
                            )
                            if _raw_vid and (_raw_vid.startswith("/") or (len(_raw_vid) > 1 and _raw_vid[1] == ":")):
                                scenes[i]["videoUrl"] = None
                                scenes[i]["veo3Path"] = _raw_vid
                                log(f"  🤖 cảnh {i+1} → Veo3 AI: {_raw_vid}")
                            else:
                                scenes[i]["videoUrl"] = _raw_vid or None
                                scenes[i]["veo3Path"] = None
                                log(f"  {'✅' if _raw_vid else '⬜'} cảnh {i+1} → Stock video: {_kw}")
                            _visual_counter += 1
                        else:
                            log(f"  ♻️ Cảnh {i+1} đã có visual sẵn")
                            _visual_counter += 1  # vẫn đếm để giữ đúng nhịp xen kẽ
                    proj.update({"scenes": scenes, "step": 2})
                    save_proj(proj)

                # STEP 3: TTS + Subtitles
                # Chạy TTS cho cả run_all và run_render (render-only cũng cần audio/SRT mới)
                if run_all or run_render:
                    # ── Reset circuit breaker mỗi lần chạy mới ──────────────────────────────
                    # Giữ đúng lựa chọn force Edge của người dùng thay vì luôn
                    # bật lại CapCut khi bắt đầu render.
                    # Dùng globals() để truy cập đúng module scope (Streamlit chạy as __main__)
                    import sys as _sys
                    _main_mod = _sys.modules.get("__main__") or _sys.modules.get("tool")
                    if _main_mod:
                        _main_mod._CAPCUT_FAIL_COUNT = 0
                        _main_mod._CAPCUT_SKIP = bool(_force_edge)
                    else:
                        globals()["_CAPCUT_FAIL_COUNT"] = 0
                        globals()["_CAPCUT_SKIP"] = bool(_force_edge)
                    _tts_label = (
                        "CapCut TTS"
                        if (_CAPCUT_OK and not _force_edge and voice_cfg_key in _cc.CAPCUT_VOICES)
                        else "Edge TTS"
                    )
                    log(f"🎤 TTS: [{_tts_label}] Ngôn ngữ={lang} | Giọng='{voice_cfg_key}' | Tốc độ={tts_rate}x")
                    log(f"   ℹ️ Hash sẽ thay đổi nếu giọng/tốc độ khác lần trước → auto regenerate")
                    _consecutive_tts_failures = 0
                    _tts_batch_aborted = False
                    _tts_abort_scene = None
                    for i, s in enumerate(scenes):
                        log(f"  TTS cảnh {i+1}/{len(scenes)}")
                        import hashlib
                        # Tốc độ đọc riêng của cảnh (nếu có), ngược lại dùng tốc độ chung
                        _sc_rate = s.get("tts_speed") or tts_rate
                        # v2 invalidates files previously cached under a CapCut
                        # voice name even though their actual audio came from Edge.
                        tts_text = (
                            normalize_vietnamese_tts(s["text"])
                            if lang == "Vietnamese" else s["text"]
                        )
                        hash_str = (
                            f"tts-cache-v3|{tts_text}|{voice_cfg_key}|{_sc_rate}|"
                            f"force-edge={bool(_force_edge)}|fallback={bool(_allow_voice_fallback)}"
                        )
                        h = hashlib.md5(hash_str.encode()).hexdigest()[:12]
                        audio_path = AUDIO_DIR / f"s{h}.mp3"
                        srt_path   = AUDIO_DIR / f"s{h}.srt"
                        actual_dur = None
                        tts_succeeded = False

                        # Never reuse scene metadata from different text/voice/rate.
                        if s.get("audioCacheKey") not in (None, h):
                            scenes[i].pop("audioFile", None)
                            scenes[i].pop("srtFile", None)
                            scenes[i].pop("audioDur", None)
                        scenes[i]["audioCacheKey"] = h

                        # Rate limits commonly begin after 5-6 sequential calls.
                        if i > 0 and i % 5 == 0 and not is_valid_audio(audio_path):
                            log("  ⏸️ Cooldown TTS 10s sau mỗi 5 cảnh...")
                            time.sleep(10)
                        if _consecutive_tts_failures >= 2:
                            log("  ⏸️ Hai cảnh lỗi liên tiếp — cooldown provider 20s...")
                            time.sleep(20)

                        if is_valid_audio(audio_path):
                            log(f"  ♻️ Cache audio cảnh {i+1} — probe duration...")
                            actual_dur = probe_audio_duration(audio_path)
                            tts_succeeded = actual_dur is not None
                            if show_sub and (not srt_path.exists() or srt_path.stat().st_size == 0):
                                actual_dur = srt_from_audio(audio_path, s["text"], srt_path)
                        else:
                            audio_path.unlink(missing_ok=True)
                            srt_path.unlink(missing_ok=True)
                            result = tts(tts_text, voice_cfg_key,
                                         srt_out=str(srt_path) if show_sub else None,
                                         rate=_sc_rate,
                                         allow_edge_fallback=_allow_voice_fallback)
                            if result and is_valid_audio(result):
                                # Sleep đủ lâu để tránh ExceededConcurrentLimit ở cảnh 5+
                                if not _CAPCUT_SKIP:
                                    time.sleep(3)  # tăng từ 1s → 3s để CapCut không timeout
                                shutil.copy(result, audio_path)
                                actual_dur = probe_audio_duration(audio_path)
                                tts_succeeded = actual_dur is not None
                                if show_sub and srt_path.exists() and srt_path.stat().st_size == 0:
                                    actual_dur = srt_from_audio(audio_path, s["text"], srt_path)
                            elif _allow_voice_fallback:
                                # Give Edge's throttle window time to recover.
                                log(f"  ⚠️ TTS cảnh {i+1} thất bại, cooldown 12s rồi retry Edge TTS...")
                                time.sleep(12)
                                edge_key = "vi-female" if lang == "Vietnamese" else ("ko-female" if lang == "Korean" else ("ja-female" if lang == "Japanese" else "en-US"))
                                edge_audio = AUDIO_DIR / f"{uuid.uuid4().hex}_edge.mp3"
                                retry_result, _ = tts_edge_with_timing(
                                    s["text"], edge_key, edge_audio,
                                    str(srt_path) if show_sub else None,
                                    rate=_sc_rate
                                )
                                if retry_result and is_valid_audio(retry_result):
                                    shutil.copy(retry_result, audio_path)
                                    actual_dur = probe_audio_duration(audio_path)
                                    tts_succeeded = actual_dur is not None
                                    _duration_label = f"{actual_dur:.1f}s" if actual_dur is not None else "chưa đo được duration"
                                    log(f"  ✅ Retry Edge TTS cảnh {i+1} thành công ({_duration_label})")
                                else:
                                    log(f"  ❌ CẢNH {i+1}: tất cả provider TTS đều thất bại — render sẽ bị chặn!")
                                    log(f"     → Nguyên nhân có thể: rate limit CapCut, asyncio conflict, hoặc mất mạng")
                                    log(f"     → Chạy Render lại: cảnh đã thành công dùng cache, chỉ cảnh lỗi được tạo lại")
                            else:
                                _real_err = getattr(_cc, "_LAST_ERROR", "") if _CAPCUT_OK else ""
                                log(
                                    f"  ❌ CẢNH {i+1}: giọng '{voice_cfg_key}' không tạo được. "
                                    "Không đổi sang Hoài My vì tùy chọn giọng dự phòng đang tắt."
                                )
                                if _real_err:
                                    log(f"     🔍 Lỗi thực sự: {_real_err}")
                                log("     → Chờ một lúc rồi Render lại; các cảnh đã thành công vẫn dùng cache.")
                        # ── Update audio duration + path + srtFile cho scene ──
                        estimated_dur = max(3.0, len(s["text"].split()) / 3.5)
                        aud_dur = actual_dur if tts_succeeded else estimated_dur
                        if tts_succeeded and is_valid_audio(audio_path):
                            scenes[i]["audioDur"] = actual_dur
                            scenes[i]["audioFile"] = str(audio_path)
                            scenes[i]["ttsStatus"] = "ready"
                            scenes[i].pop("ttsError", None)
                            _consecutive_tts_failures = 0
                        else:
                            audio_path.unlink(missing_ok=True)
                            srt_path.unlink(missing_ok=True)
                            scenes[i].pop("audioFile", None)
                            scenes[i].pop("audioDur", None)
                            scenes[i].pop("srtFile", None)
                            scenes[i]["ttsStatus"] = "error"
                            scenes[i]["ttsError"] = "Không provider TTS nào trả về audio hợp lệ"
                            _consecutive_tts_failures += 1
                            log(f"  ❌ TTS cảnh {i+1} THẤT BẠI hoàn toàn — render sẽ bị chặn, không dùng nhầm audio cũ.")
                        # Preserve srtFile: chỉ cập nhật khi có file mới, giữ lại nếu đã có từ lần trước
                        if srt_path.exists() and srt_path.stat().st_size > 0:
                            scenes[i]["srtFile"] = str(srt_path)
                        # Không xóa srtFile cũ nếu show_sub=False lần này
                        AUDIO_PADDING = 0.3
                        # ── DURATION CLAMPING: Giữ đúng thời gian user chọn ──
                        # Nếu audio ngắn hơn target → pad đến target (video giữ đúng nhịp độ đã cài)
                        # Nếu audio dài hơn target * 1.5 → cảnh tự nhiên dài hơn (không cắt audio)
                        target_dur = float(s.get("targetDur") or target_sec_per_scene)
                        if aud_dur <= target_dur:
                            # Audio ngắn hơn target: pad đến target để đồng bộ nhịp cảnh
                            final_dur = max(1.5, round(max(aud_dur + AUDIO_PADDING, target_dur), 1))
                        else:
                            # Audio dài hơn target: dùng audio duration thực tế (không cắt giọng đọc)
                            final_dur = max(1.5, round(aud_dur + AUDIO_PADDING, 1))
                        scenes[i]["duration"] = final_dur
                        if tts_succeeded:
                            log(f"  ✅ Audio cảnh {i+1}: đọc {aud_dur:.1f}s | target {target_dur:.0f}s → scene {final_dur:.1f}s" + (" + sub" if scenes[i].get('srtFile') else ""))
                        else:
                            log(f"  ⛔ Cảnh {i+1}: chưa có audio; render sẽ bị chặn.")

                        # Lưu tiến độ sau từng cảnh để lần chạy sau tiếp tục đúng
                        # từ cache, kể cả khi CapCut rate-limit giữa một dự án dài.
                        proj.update({"scenes": scenes, "step": 3})
                        save_proj(proj)

                        # Chế độ khóa giọng phải dừng ngay từ cảnh lỗi đầu tiên.
                        if (
                            not _allow_voice_fallback
                            and _consecutive_tts_failures >= 1
                        ):
                            _tts_batch_aborted = True
                            _tts_abort_scene = i + 1
                            log("  🛑 TTS lỗi — dừng ngay để bảo vệ đúng giọng đã chọn và không render cảnh im lặng.")
                            log("     Các cảnh thành công đã được lưu cache; bấm Render lại để thử lại cảnh lỗi.")
                            break
                    proj.update({"scenes": scenes, "step": 3})
                    save_proj(proj)

                    if _tts_batch_aborted:
                        st.error(
                            f"Giọng '{voice_cfg_key}' không tạo được audio cho cảnh {_tts_abort_scene}. "
                            "Đã dừng trước khi render để video không có cảnh im lặng. "
                            "Các cảnh thành công đã lưu; hãy bấm Render lại để thử tiếp."
                        )
                        st.stop()

                    _missing_audio_scenes = [
                        i + 1 for i, scene in enumerate(scenes)
                        if not is_valid_audio(scene.get("audioFile"))
                    ]
                    if _missing_audio_scenes:
                        st.error(
                            "Không render vì các cảnh sau chưa có giọng đọc hợp lệ: "
                            + ", ".join(map(str, _missing_audio_scenes))
                        )
                        st.stop()

                # STEP 4: Render
                log("🎞️ Render video...")
                scene_mp4s = []
                scene_is_img = []  # theo dõi cảnh nào là ảnh để xfade
                used_urls_render = set(s.get("videoUrl") for s in scenes if s.get("videoUrl"))

                for i, s in enumerate(scenes):
                    log(f"  Render cảnh {i+1}/{len(scenes)}")
                    s_dir = work / f"s{i}"
                    s_dir.mkdir(exist_ok=True)

                    # ── PER-SCENE RENDER CACHE ─────────────────────────────────────────────
                    # Hash tất cả tham số ảnh hưởng render. Với file local, đưa cả
                    # size + mtime vào fingerprint để nhận ra file bị ghi đè cùng path.
                    import hashlib as _hc

                    def _render_input_fingerprint(value):
                        if not value:
                            return ""
                        raw_value = str(value)
                        candidate = Path(raw_value)
                        try:
                            if candidate.is_file():
                                stat = candidate.stat()
                                return f"{candidate.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
                        except (OSError, ValueError):
                            pass
                        return raw_value

                    _resolved_sfx_name = s.get("soundEffect")
                    if _resolved_sfx_name is None:
                        # Không tự chèn click/whoosh vào đầu lời thoại. Những âm
                        # ngắn này rất dễ bị nghe thành tiếng "bụp" giữa các cảnh.
                        _resolved_sfx_name = "none"

                    _scene_fp_parts = [
                        "scene-render-v3-audio-declick",
                        s.get("text", ""),
                        _render_input_fingerprint(s.get("audioFile", "")),
                        _render_input_fingerprint(s.get("srtFile", "")),
                        _render_input_fingerprint(s.get("videoUrl", "")),
                        _render_input_fingerprint(s.get("imageUrl", "")),
                        _render_input_fingerprint(s.get("customVid", "")),
                        _render_input_fingerprint(s.get("customImg", "")),
                        _render_input_fingerprint(s.get("veo3Path", "")),
                        str(s.get("duration", "")),
                        str(s.get("videoSpeed", 1.0)),
                        str(s.get("imageEffect", "")),
                        str(s.get("introEffect", "")),
                        str(_resolved_sfx_name),
                        str(s.get("videoTrimMode", "")),
                        str(s.get("videoTrimStart", 0.0)),
                        str(show_sub), str(sub_style), str(enable_transition),
                        str(W), str(H), str(voice_cfg_key), str(tts_rate),
                        str(intro_vol_boost if i == 0 else 1.0),
                        str(s.get("tts_speed", "")),
                        # Hook 2 giây đầu
                        str(s.get("hookQuestion", "")),
                        str(s.get("hookBigText", "")),
                        str(s.get("hookSfx", "")),
                    ]
                    _scene_hash = _hc.sha256("|".join(_scene_fp_parts).encode()).hexdigest()[:20]
                    _scene_hash_file = s_dir / ".scene_hash"
                    _cached_scene_out = s_dir / "scene.mp4"
                    if (
                        _cached_scene_out.exists()
                        and _cached_scene_out.stat().st_size > 10000
                        and _scene_hash_file.exists()
                        and _scene_hash_file.read_text().strip() == _scene_hash
                    ):
                        log(f"  ♻️ Cache hit cảnh {i+1} (hash={_scene_hash[:8]}) — skip render")
                        scene_mp4s.append(_cached_scene_out)
                        # Đọc lại is_img từ vid_path của cache
                        _cached_vid = s_dir / "video.mp4"
                        scene_is_img.append(_cached_vid.exists() and is_image_file(str(_cached_vid)))
                        continue
                    # ──────────────────────────────────────────────────────────────────────

                    # ── Tìm audio file: ưu tiên audioFile trong scene, fallback reconstruct từ hash ──
                    src_audio = None
                    if s.get("audioFile") and Path(s["audioFile"]).exists():
                        src_audio = Path(s["audioFile"])
                        log(f"  📦 Audio cảnh {i+1}: dùng audioFile đã lưu ({src_audio.name})")
                    else:
                        # Reconstruct hash path — dùng khi project cũ chưa lưu audioFile
                        import hashlib as _hl
                        _hash_str = (
                            f"tts-cache-v2|{s.get('text', '')}|{voice_cfg_key}|{tts_rate}|"
                            f"force-edge={bool(_force_edge)}|fallback={bool(_allow_voice_fallback)}"
                        )
                        _h = _hl.md5(_hash_str.encode()).hexdigest()[:12]
                        _reconstructed = AUDIO_DIR / f"s{_h}.mp3"
                        if _reconstructed.exists() and _reconstructed.stat().st_size > 1000:
                            src_audio = _reconstructed
                            log(f"  ♻️ Audio cảnh {i+1}: dùng cache hash ({_reconstructed.name})")
                        else:
                            # Fallback: tìm bất kỳ file audio nào trong AUDIO_DIR có thể khớp
                            # (được tạo khi voice/rate khác) — lấy file mới nhất trùng hash text-only
                            _text_only_hash = _hl.md5(s.get("text", "").encode()).hexdigest()[:8]
                            _candidates = sorted(
                                [f for f in AUDIO_DIR.glob("s*.mp3") if f.stat().st_size > 1000],
                                key=lambda f: f.stat().st_mtime, reverse=True
                            )
                            # Thử tìm file audio ướng nhất bằng cách hash text-only
                            _text_hash_file = AUDIO_DIR / f"s{_hl.md5(s.get('text','').encode()).hexdigest()[:12]}.mp3"
                            if (
                                _allow_voice_fallback
                                and _text_hash_file.exists()
                                and _text_hash_file.stat().st_size > 1000
                            ):
                                src_audio = _text_hash_file
                                log(f"  🔄 Audio cảnh {i+1}: tìm bằng text-hash fallback ({src_audio.name})")
                            else:
                                # Cuối cùng: re-run TTS inline thay vì im lặng
                                log(f"  ⚠️ Cảnh {i+1}: không tìm thấy audio (voice/rate có thể đã đổi) — tạo mới...")
                                _inline_audio = AUDIO_DIR / f"s{_h}.mp3"
                                _inline_srt = AUDIO_DIR / f"s{_h}.srt" if show_sub else None
                                _retry_result = tts(
                                    s.get("text", ""), voice_cfg_key,
                                    srt_out=str(_inline_srt) if _inline_srt else None,
                                    rate=s.get("tts_speed") or tts_rate,
                                    allow_edge_fallback=_allow_voice_fallback,
                                )
                                if _retry_result and Path(_retry_result).exists():
                                    shutil.copy(_retry_result, _inline_audio)
                                    src_audio = _inline_audio
                                    # Cập nhật scenes để lần sau không cần tạo lại
                                    scenes[i]["audioFile"] = str(_inline_audio)
                                    if _inline_srt and _inline_srt.exists() and _inline_srt.stat().st_size > 0:
                                        scenes[i]["srtFile"] = str(_inline_srt)
                                    log(f"  ✅ Re-TTS cảnh {i+1} thành công ({src_audio.name})")
                                else:
                                    log(f"  ❌ Cảnh {i+1}: TTS thất bại hoàn toàn — dừng render, không tạo silence.")
                                    st.error(f"Cảnh {i+1} chưa có giọng đọc hợp lệ. Đã dừng render.")
                                    st.stop()
                    stored_dur = float(s.get("duration") or 5)
                    dur = stored_dur  # fallback

                    if src_audio and src_audio.exists():
                        try:
                            _probe = subprocess.run(
                                [FFMPEG, "-i", str(src_audio), "-f", "null", "-"],
                                capture_output=True, text=True
                            )
                            for _line in _probe.stderr.split("\n"):
                                if "Duration:" in _line:
                                    _ts = _line.split("Duration:")[1].split(",")[0].strip()
                                    _hh, _mm, _ss = _ts.split(":")
                                    _real_dur = int(_hh)*3600 + int(_mm)*60 + float(_ss)
                                    if _real_dur > 0.5:
                                        # Buffer tối thiểu để không cắt tiếng cuối câu
                                        # 0.05s thay vì 0.3s cũ — giảm dôi thời gian khi concat nhiều cảnh
                                        dur = max(1.5, round(_real_dur + 0.05, 2))
                                    break
                        except Exception:
                            pass
                        log(f"  ⏱ Cảnh {i+1}: audio={dur-0.05:.2f}s → scene={dur:.2f}s (stored was {stored_dur:.1f}s)")

                    # ── AUDIO: Trim/pad đúng `dur` giây và ép chuẩn Stereo/44100Hz ──
                    audio_path = s_dir / "audio_trimmed.aac"
                    if src_audio and src_audio.exists():
                        # Cảnh đầu tiên: boost âm lượng để kéo sự chú ý ngay từ giây 0
                        _vol_filter = f",volume={intro_vol_boost:.2f}" if (i == 0 and intro_vol_boost > 1.0) else ""
                        ffmpeg("-i", str(src_audio),
                               # Fade 35ms đủ đưa biên sóng về zero, không làm
                               # mất phụ âm/chữ đầu như fade dài 150ms.
                               "-af", f"afade=t=in:st=0:d=0.035,apad=pad_dur={dur}{_vol_filter}",
                               "-t", str(dur),
                               "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k", "-y", str(audio_path))
                    else:
                        st.error(f"Cảnh {i+1} không có audio nguồn. Đã dừng render.")
                        st.stop()


                    # Visual background: ảnh hoặc video
                    vid_path = s_dir / "video.mp4"   # dùng chung path dù là ảnh hay video
                    has_vid  = False
                    vid_orientation = "portrait" if "9:16" in aspect else "landscape"

                    custom_img = s.get("customImg", "")   # ảnh upload thủ công
                    image_url  = s.get("imageUrl", "")    # ảnh stock đã chọn
                    custom_vid = s.get("customVid", "")   # video upload thủ công
                    video_url  = s.get("videoUrl", "")    # video stock

                    # ── Ưu tiên 1: ảnh upload thủ công ──
                    if custom_img and Path(custom_img).exists():
                        shutil.copy(custom_img, vid_path)
                        has_vid = vid_path.stat().st_size > 5000
                        log(f"  🖼️ Dùng ảnh tải lên: {Path(custom_img).name}")

                    # ── Ưu tiên 2: ảnh stock hoặc ảnh AI tĩnh đã tạo ──
                    elif image_url:
                        try:
                            # Nếu imageUrl là đường dẫn local (sinh từ generate_scene_image_ai)
                            if Path(image_url).exists():
                                shutil.copy(image_url, vid_path)
                                has_vid = vid_path.stat().st_size > 5000
                                log(f"  🖼️ Dùng ảnh AI local: {vid_path.stat().st_size//1024}KB")
                            else:
                                download_url(image_url, str(vid_path))
                                has_vid = vid_path.stat().st_size > 5000
                                log(f"  🖼️ Tải ảnh stock: {vid_path.stat().st_size//1024}KB")
                        except Exception as e:
                            log(f"  ⚠️ Lỗi lấy ảnh: {str(e)[:60]}")

                    # ── Ưu tiên 3: video upload thủ công ──
                    elif custom_vid and Path(custom_vid).exists():
                        shutil.copy(custom_vid, vid_path)
                        has_vid = vid_path.stat().st_size > 10000
                        log(f"  📥 Dùng video tải lên tùy chỉnh: {Path(custom_vid).name}")

                    # ── Ưu tiên 3.5: Veo3 AI video (cached local path) ──
                    elif s.get("veo3Path") and Path(s["veo3Path"]).exists():
                        veo3_local = s["veo3Path"]
                        shutil.copy(veo3_local, vid_path)
                        has_vid = vid_path.stat().st_size > 10000
                        log(f"  🤖 Dùng Veo3 cached: {Path(veo3_local).name} ({vid_path.stat().st_size//1024}KB)")

                    # ── Ưu tiên 4: video stock (hoặc Veo3 generate mới nếu enabled) ──
                    else:
                        if not video_url:
                            log(f"  🔍 Tìm video [{vid_orientation}]: {s.get('keyword','')}")
                            _raw = fetch_video_with_veo3(
                                clean_keyword(s.get("keyword", "")),
                                orientation=vid_orientation,
                                used_urls=used_urls_render,
                                scene_text=s.get("text", ""),
                                veo3_prompt=s.get("veo3_prompt", ""),
                                log_cb=log,
                                force_veo3=(st.session_state.get("proj_mode") == "veo3")
                            )
                            # Veo3 trả local path → copy trực tiếp
                            if _raw and (_raw.startswith("/") or (len(_raw) > 1 and _raw[1] == ":")):
                                if Path(_raw).exists():
                                    shutil.copy(_raw, vid_path)
                                    has_vid = vid_path.stat().st_size > 10000
                                    log(f"  🤖 Veo3 live OK: {vid_path.stat().st_size//1024}KB")
                                video_url = ""  # local path đã copy, không cần download
                            else:
                                video_url = _raw or ""
                                if video_url:
                                    used_urls_render.add(video_url)
                                    log(f"  ✅ Stock Video URL tìm được")
                                else:
                                    log(f"  ⚠️ Không tìm được video (kiểm tra API key hoặc bật Veo3 trong Settings)")

                        if video_url and not has_vid:
                            try:
                                download_url(video_url, str(vid_path))
                                size = vid_path.stat().st_size
                                log(f"  📥 Tải video: {size//1024}KB")
                                has_vid = size > 10000
                                if not has_vid:
                                    log(f"  ⚠️ File video quá nhỏ ({size}B), bỏ qua")
                            except Exception as e:
                                log(f"  ⚠️ Tải thất bại: {str(e)[:80]} — tìm lại...")
                                _render_lang = proj.get("lang", "")
                                _render_kw = inject_region_into_keyword(
                                    clean_keyword(s.get("keyword", ""), lang=_render_lang),
                                    _render_lang
                                )
                                new_url = fetch_stock_video(_render_kw, orientation=vid_orientation, used_urls=used_urls_render) or ""
                                if new_url and new_url != video_url:
                                    used_urls_render.add(new_url)
                                    try:
                                        log(f"  🔍 Thử URL mới...")
                                        download_url(new_url, str(vid_path))
                                        has_vid = vid_path.stat().st_size > 10000
                                        if has_vid:
                                            log(f"  ✅ Tải lại thành công")
                                    except Exception as e2:
                                        log(f"  ⚠️ Vẫn lỗi: {str(e2)[:60]}")


                    # Note: ASS subtitle handles its own styling via sub_style (user selection)
                    # _ffmpeg_sub_style below is kept for legacy SRT fallback only, not used with ASS
                    _ffmpeg_sub_fs = 20 if W == 1080 else 16
                    _ffmpeg_sub_style = (
                        f"FontName=Arial,FontSize={_ffmpeg_sub_fs},PrimaryColour=&H00FFFFFF,"
                        "BackColour=&H90000000,BorderStyle=3,Outline=0,Shadow=0,"
                        f"Alignment=2,MarginV={120 if W==1080 else 80}"
                    )

                    out = s_dir / "scene.mp4"
                    scale_filter = f"fps=30,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"

                    # Speed up logic if audio is longer than scene duration
                    aud_dur = s.get("audioDur", dur)
                    speed = min(2.0, aud_dur / dur) if aud_dur > dur else 1.0

                    # Transitions
                    # Ảnh: fade 0.4s để transition đủ mượt; video: 0.15s để không bị đen lâu
                    _is_img_scene = has_vid and is_image_file(str(vid_path))
                    _fd = 0.4 if _is_img_scene else 0.15
                    v_fade = f",fade=t=in:st=0:d={_fd},fade=t=out:st={max(0.0, dur-_fd):.3f}:d={_fd}" if enable_transition else ""
                    def _sub_filter(ass_path):
                        """Return ass= FFmpeg filter string with properly escaped path."""
                        p = str(ass_path).replace("\\", "\\\\").replace(":", "\\:")
                        return f"ass='{p}'"

                    # Prepare subtitles
                    srt_file = s.get("srtFile")
                    has_srt  = False
                    ass_local = None
                    if show_sub and not HAS_SUB:
                        log("  ⚠️ FFmpeg thiếu libass — bỏ phụ đề. Chạy: brew reinstall ffmpeg")
                    elif show_sub and HAS_SUB and srt_file and Path(srt_file).exists():
                        try:
                            w_list = srt_to_words(srt_file)
                            if w_list:
                                # Apply speed up to timestamps if needed
                                if speed > 1.0:
                                    for w in w_list:
                                        w["start"] /= speed
                                        w["end"] /= speed
                                ass_content = make_ass(w_list, W=W, H=H, style_name=sub_style)
                                ass_local = s_dir / "sub.ass"
                                ass_local.write_text(ass_content, encoding="utf-8")
                                has_srt = True
                        except Exception as srt_e:
                            log(f"  ⚠️ Lỗi tạo ASS: {srt_e} — bỏ phụ đề")

                    # ----- FFMPEG RENDER CORE (thay thế MoviePy — nhanh hơn 10-20x) -----
                    base_out = s_dir / "base.mp4"
                    log(f"  ⚡ Render cảnh {i+1} bằng FFmpeg...")

                    # Probe video duration
                    vid_len = 0.0
                    if has_vid:
                        try:
                            probe_v = subprocess.run(
                                [FFMPEG, "-i", str(vid_path), "-f", "null", "-"],
                                capture_output=True, text=True
                            )
                            for line in probe_v.stderr.split("\n"):
                                if "Duration:" in line:
                                    ts2 = line.split("Duration:")[1].split(",")[0].strip()
                                    hh2, mm2, ss2 = ts2.split(":")
                                    vid_len = int(hh2)*3600 + int(mm2)*60 + float(ss2)
                                    break
                        except Exception:
                            vid_len = dur

                    # Tính start_time để trim video
                    # Default "random" để tự chọn đoạn hay nhất thay vì luôn lấy đầu video
                    trim_mode = s.get("videoTrimMode") or "random"
                    if has_vid and vid_len > dur:
                        if trim_mode == "middle":
                            start_time = max(0.0, (vid_len - dur) / 2.0)
                        elif trim_mode == "end":
                            start_time = max(0.0, vid_len - dur)
                        elif trim_mode == "random":
                            # Random trong 60% đầu video — tránh đoạn cuối thường nhàm
                            max_start = max(0.0, vid_len - dur)
                            start_time = random.uniform(0.0, min(max_start, vid_len * 0.6))
                        elif trim_mode == "custom":
                            cs = float(s.get("videoTrimStart", 0.0))
                            start_time = min(cs, max(0.0, vid_len - dur))
                        else:  # "start"
                            start_time = 0.0
                        log(f"  🎬 Trim ({trim_mode}): {start_time:.1f}s → {start_time+dur:.1f}s")
                    else:
                        start_time = 0.0

                    # Tốc độ video nền (0.25x–2.0x). Không ảnh hưởng audio TTS.
                    _bg_speed = float(s.get("videoSpeed", 1.0))
                    if _bg_speed <= 0 or _bg_speed > 4.0: _bg_speed = 1.0
                    _setpts = f",setpts={round(1.0/_bg_speed, 4)}*PTS" if _bg_speed != 1.0 else ""
                    scale_crop = f"fps=30,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}{_setpts}"

                    # Hiệu ứng intro: Nếu chưa chọn → auto random (trừ khi tắt đi = "none")
                    scene_intro_effect = s.get("introEffect")  # None = random, "none" = tắt hẳn

                    if has_vid:
                        is_img = is_image_file(str(vid_path))
                        if is_img:
                            # Hiệu ứng ảnh: Nếu chưa chọn → auto random trong 6 preset
                            img_effect = s.get("imageEffect")  # None = ngẫu nhiên
                            vid_input_args = ["-i", str(vid_path)]
                            scale_crop = make_image_effect_filter(W, H, dur, effect=img_effect)
                            chosen_eff = img_effect or "ngẫu nhiên"
                            log(f"  🎨 Hiệu ứng ảnh: {chosen_eff}")
                        else:
                            # Trường hợp video ngắn hơn dur → loop
                            if vid_len > 0 and vid_len < dur:
                                vid_input_args = ["-stream_loop", "-1", "-i", str(vid_path)]
                            else:
                                vid_input_args = ["-ss", str(start_time), "-i", str(vid_path)]
                             # KHÔNG áp zoompan/intro_vf lên video stock
                             # → zoompan nặng CPU, tạo PTS không đều → giật hình
                             # → Hiệu ứng động chỉ dành cho ảnh tĩnh (is_img branch bên trên)

                        if audio_path.exists():
                            ffmpeg_cmd = (
                                vid_input_args +
                                ["-i", str(audio_path),
                                 "-vf", scale_crop,
                                 "-t", str(dur),
                                 "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                                 "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                                 "-af", f"apad=whole_dur={dur}",
                                 "-map", "0:v", "-map", "1:a",
                                 "-y", str(base_out)]
                            )
                        else:
                            st.error(f"Cảnh {i+1} mất audio đã chuẩn hóa. Đã dừng render.")
                            st.stop()
                    else:
                        # Nền đen vẫn bắt buộc phải có audio thuyết minh.
                        color_src = f"color=c=1a1d27:s={W}x{H}:r=30"
                        if audio_path.exists():
                            ffmpeg_cmd = [
                                "-f", "lavfi", "-i", color_src,
                                "-i", str(audio_path),
                                "-t", str(dur),
                                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                                "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                                "-af", f"apad=whole_dur={dur}",
                                "-map", "0:v", "-map", "1:a",
                                "-y", str(base_out)
                            ]
                        else:
                            st.error(f"Cảnh {i+1} mất audio đã chuẩn hóa. Đã dừng render.")
                            st.stop()

                    # ── Tính fade filter string — ảnh dùng 0.4s, video 0.15s ──
                    _fd = 0.4 if _is_img_scene else 0.15
                    # Không dùng fade đen (dip to black) cho cảnh ảnh nếu bật transition,
                    # vì cảnh ảnh sẽ dùng xfade crossfade ở bước ghép (ghép đúp sẽ gây chớp đen).
                    if enable_transition and not _is_img_scene:
                        _fade_str = f",fade=t=in:st=0:d={_fd},fade=t=out:st={max(0.0, dur-_fd):.3f}:d={_fd}"
                    else:
                        _fade_str = ""

                    # ── Quyết định chiến lược render ──
                    # has_srt = cần subtitle pass → luôn phải output pass 1 ra base_out
                    # Không có subtitle + video thường → merge fade vào pass 1, output thẳng ra out (1 pass)
                    _is_plain_video = has_vid and not is_image_file(str(vid_path))
                    _need_pass2 = (has_srt and ass_local and ass_local.exists())

                    if _is_plain_video and not _need_pass2 and _fade_str:
                        # Tối ưu: 1 pass duy nhất — merge fade vào scale_crop, output → out
                        try:
                            vf_idx = ffmpeg_cmd.index("-vf")
                            ffmpeg_cmd[vf_idx + 1] = scale_crop + _fade_str
                            ffmpeg_cmd[-1] = str(out)   # output trực tiếp ra out
                        except (ValueError, IndexError):
                            pass
                        ffmpeg(*ffmpeg_cmd)
                    else:
                        # Bình thường: pass 1 → base_out
                        ffmpeg(*ffmpeg_cmd)

                        # ----- SUBTITLE BURN-IN (pass 2) -----
                        if _need_pass2:
                            log(f"  ✍️ Đang gắn phụ đề cảnh {i+1}...")
                            vf_filter = _sub_filter(ass_local) + _fade_str
                            cmd_args = ["-i", str(base_out), "-vf", vf_filter,
                                        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                                        "-c:a", "copy", "-y", str(out)]
                            try:
                                ffmpeg(*cmd_args)
                            except Exception as e:
                                log(f"  ⚠️ Lỗi gắn phụ đề: {e} → dùng bản không phụ đề.")
                                shutil.copy(base_out, out)
                        else:
                            # Không có subtitle, cần copy/fade từ base_out → out
                            if _fade_str:
                                v_fade_only = _fade_str.lstrip(",")  # bỏ dấu phẩy đầu
                                cmd_args = ["-i", str(base_out), "-vf", v_fade_only,
                                            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                                            "-c:a", "copy", "-y", str(out)]
                                ffmpeg(*cmd_args)
                            else:
                                shutil.copy(base_out, out)

                    # ── Sound Effect: auto-random nếu chưa chọn ──
                    sfx_name = _resolved_sfx_name
                    if sfx_name and sfx_name != "none" and out.exists():
                        sfx_out = s_dir / "scene_sfx.mp4"
                        ok = apply_sound_effect_to_scene(out, sfx_name, sfx_out)
                        if ok:
                            shutil.move(str(sfx_out), str(out))
                            log(f"  🔊 Sound effect: {sfx_name}")

                    # ── 🪝 Hook Overlay (chỉ cảnh đầu, i==0) ─────────────────────────────
                    # Hiển thị chữ to nổi bật 2 giây đầu để giật mình khán giả
                    _hook_q  = s.get("hookQuestion", "").strip()
                    _hook_b  = s.get("hookBigText", "").strip()
                    _hook_sfx = s.get("hookSfx", "none")
                    if i == 0 and (_hook_q or _hook_b) and out.exists():
                        try:
                            _hook_out = s_dir / "scene_hook.mp4"
                            # ── Chọn font fallback an toàn ──
                            _font_candidates = [
                                "/Library/Fonts/Arial Bold.ttf",
                                "/Library/Fonts/Arial.ttf",
                                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                                "/System/Library/Fonts/Supplemental/Arial.ttf",
                                "/System/Library/Fonts/Helvetica.ttc",
                                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                            ]
                            _font_path = next((f for f in _font_candidates if Path(f).exists()), None)
                            _font_arg = f":fontfile='{_font_path}'" if _font_path else ""

                            # ── Tính vị trí text ──
                            _cx = W // 2   # center X
                            _q_y = int(H * 0.30)   # Câu hỏi sốc: 30% từ trên
                            _b_y = int(H * 0.55)   # Chữ to phụ: 55% từ trên

                            # ── Drawtext filter: flash trong 2 giây đầu ──
                            # alpha(t): ramp in 0→0.3s, hold 0.3→1.7s, ramp out 1.7→2s
                            _alpha_expr = (
                                "if(lt(t,0.3), t/0.3,"
                                " if(lt(t,1.7), 1.0,"
                                " if(lt(t,2.0), (2.0-t)/0.3, 0)))"
                            )
                            # Scale font size với zoom-pulse: lớn nhất lúc 0.8s
                            _q_size_expr = f"if(lt(t,0.8), {int(W*0.085)}*0.7 + {int(W*0.085)}*0.3*(t/0.8), {int(W*0.085)})"
                            _b_size_base = int(W * 0.065)

                            _vf_parts = []
                            if _hook_q:
                                _safe_q = _hook_q.replace("'", "\\'").replace(":", "\\:")
                                _vf_parts.append(
                                    f"drawtext=text='{_safe_q}'{_font_arg}"
                                    f":fontsize={int(W*0.082)}:fontcolor=white"
                                    f":bordercolor=black:borderw=4"
                                    f":x=(w-text_w)/2:y={_q_y}"
                                    f":alpha='{_alpha_expr}'"
                                    f":enable='lt(t,2.0)'"
                                )
                            if _hook_b:
                                _safe_b = _hook_b.replace("'", "\\'").replace(":", "\\:")
                                _vf_parts.append(
                                    f"drawtext=text='{_safe_b}'{_font_arg}"
                                    f":fontsize={_b_size_base}:fontcolor=yellow"
                                    f":bordercolor=red:borderw=3"
                                    f":x=(w-text_w)/2:y={_b_y}"
                                    f":alpha='{_alpha_expr}'"
                                    f":enable='lt(t,2.0)'"
                                )
                            _vf_hook = ",".join(_vf_parts)

                            # ── FFmpeg: overlay chữ (giữ audio nguyên) ──
                            ffmpeg(
                                "-i", str(out),
                                "-vf", _vf_hook,
                                "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                                "-c:a", "copy",
                                "-y", str(_hook_out)
                            )
                            if _hook_out.exists() and _hook_out.stat().st_size > 10000:
                                shutil.move(str(_hook_out), str(out))
                                log(f"  🪝 Hook overlay: '{_hook_q[:20]}…' + '{_hook_b[:20]}…'")

                            # ── hookSfx: thêm âm giật mình tại t=0 ──
                            _hook_sfx_valid = {"deep_hit", "whoosh", "horror", "slam"}
                            if _hook_sfx and _hook_sfx != "none":
                                # Dùng apply_sound_effect_to_scene với sfx deep_hit hoặc whoosh
                                _sfx_map = {
                                    "horror": "deep_hit",  # fallback sang deep_hit nếu chưa có horror
                                    "slam":   "deep_hit",
                                }
                                _resolved_hook_sfx = _sfx_map.get(_hook_sfx, _hook_sfx)
                                if _resolved_hook_sfx in ("deep_hit", "whoosh", "click", "chime"):
                                    _hook_sfx_out = s_dir / "scene_hook_sfx.mp4"
                                    _sfx_ok = apply_sound_effect_to_scene(out, _resolved_hook_sfx, _hook_sfx_out)
                                    if _sfx_ok and _hook_sfx_out.exists():
                                        shutil.move(str(_hook_sfx_out), str(out))
                                        log(f"  🔊 Hook SFX: {_hook_sfx} → {_resolved_hook_sfx}")
                        except Exception as _hook_err:
                            log(f"  ⚠️ Hook overlay lỗi (bỏ qua): {_hook_err}")

                    # Ghi hash cache sau khi render thành công — lần sau sẽ skip

                    if out.exists() and out.stat().st_size > 10000:
                        try:
                            _scene_hash_file.write_text(_scene_hash)
                        except Exception:
                            pass
                    scene_mp4s.append(out)
                    scene_is_img.append(_is_img_scene)

                # Các scene đã được chuẩn hóa H.264/AAC cùng resolution/fps ở trên.
                # Nếu enable_transition và có cảnh ảnh → dùng xfade crossfade giữa cảnh ảnh liên tiếp.
                # Ngược lại: thử concat stream-copy trước (nhanh, không giảm chất lượng).
                raw_final = work / "final.mp4"

                # ── Helper: ghép N clips với xfade crossfade ──
                def _concat_with_xfade(clips, is_img_flags, out_path, xfade_dur=0.35):
                    """Ghép clips với xfade crossfade ở chỗ giao tiếp ảnh–ảnh hoặc ảnh–video.
                    Trả về True nếu thành công."""
                    n = len(clips)
                    if n == 0:
                        return False
                    if n == 1:
                        shutil.copy(clips[0], out_path)
                        return True

                    # Probe duration của từng clip
                    durations = []
                    for cp in clips:
                        try:
                            pb = subprocess.run(
                                [FFMPEG, "-i", str(cp), "-f", "null", "-"],
                                capture_output=True, text=True
                            )
                            dur_v = 0.0
                            for ln in pb.stderr.split("\n"):
                                if "Duration:" in ln:
                                    ts = ln.split("Duration:")[1].split(",")[0].strip()
                                    hh, mm, ss = ts.split(":")
                                    dur_v = int(hh)*3600 + int(mm)*60 + float(ss)
                                    break
                            durations.append(max(dur_v, 1.0))
                        except Exception:
                            durations.append(5.0)

                    # Xây dựng filter_complex cho xfade
                    # Mỗi transition: nếu cảnh hiện tại HOẶC cảnh tiếp theo là ảnh → dùng xfade
                    # Ngược lại → concat thô (xfade video song song rất nặng CPU)
                    inputs = []
                    for cp in clips:
                        inputs.extend(["-i", str(cp)])

                    filter_parts = []
                    # Label đầu ra của mỗi clip: [v0],[v1],...
                    v_labels = [f"[v{j}]" for j in range(n)]
                    a_labels = [f"[a{j}]" for j in range(n)]
                    # Map mỗi input → v/a label
                    for j in range(n):
                        filter_parts.append(f"[{j}:v]copy[v{j}]")
                        filter_parts.append(f"[{j}:a]acopy[a{j}]")

                    # Tính offset tích lũy và áp xfade từng cặp
                    offset = durations[0] - xfade_dur
                    cur_v = "[v0]"
                    cur_a = "[a0]"
                    _xfade_effects = ["fade", "dissolve", "smoothleft", "wipeleft", "slideleft"]
                    for j in range(1, n):
                        use_xfade = is_img_flags[j-1] or is_img_flags[j]
                        next_v = f"[xv{j}]" if j < n-1 else "[vout]"
                        next_a = f"[xa{j}]" if j < n-1 else "[aout]"
                        if use_xfade:
                            _xfx = _xfade_effects[j % len(_xfade_effects)]
                            filter_parts.append(
                                f"{cur_v}{v_labels[j]}xfade=transition={_xfx}:duration={xfade_dur}:offset={offset:.3f}{next_v}"
                            )
                            filter_parts.append(
                                f"{cur_a}{a_labels[j]}acrossfade=d={xfade_dur}{next_a}"
                            )
                        else:
                            filter_parts.append(
                                f"{cur_v}{v_labels[j]}concat=n=2:v=1:a=0{next_v}"
                            )
                            filter_parts.append(
                                f"{cur_a}{a_labels[j]}concat=n=2:v=0:a=1{next_a}"
                            )
                        cur_v = next_v
                        cur_a = next_a
                        if j < n-1:
                            offset += durations[j] - xfade_dur

                    fc = ";".join(filter_parts)
                    try:
                        ffmpeg(
                            *inputs,
                            "-filter_complex", fc,
                            "-map", "[vout]", "-map", "[aout]",
                            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                            "-movflags", "+faststart",
                            "-y", str(out_path)
                        )
                        return out_path.exists() and out_path.stat().st_size > 10000
                    except Exception as _xfe:
                        log(f"  ⚠️ xfade thất bại ({_xfe}), fallback sang concat thô...")
                        return False

                # ── Quyết định chiến lược ghép ──
                _has_any_img = any(scene_is_img)
                _xfade_ok = False
                if enable_transition and _has_any_img and len(scene_mp4s) > 1:
                    log("✨ Ghép scene với xfade crossfade (cảnh ảnh)...")
                    _xfade_ok = _concat_with_xfade(
                        scene_mp4s, scene_is_img, raw_final, xfade_dur=0.35
                    )
                    if _xfade_ok:
                        log("✅ Ghép xfade thành công.")

                if not _xfade_ok:
                    concat_txt = work / "concat.txt"
                    concat_txt.write_text("\n".join(f"file '{p}'" for p in scene_mp4s))
                    try:
                        ffmpeg(
                            "-f", "concat", "-safe", "0", "-i", str(concat_txt),
                            "-map", "0:v", "-map", "0:a",
                            "-c", "copy", "-movflags", "+faststart",
                            "-y", str(raw_final)
                        )
                        log("⚡ Ghép scene bằng stream-copy (không encode lại).")
                    except Exception as copy_error:
                        log(f"  ↪️ Stream-copy không tương thích ({copy_error}); đang encode chuẩn hóa...")
                        ffmpeg(
                            "-f", "concat", "-safe", "0", "-i", str(concat_txt),
                            "-vf", f"fps=30,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
                            "-vsync", "cfr",
                            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                            "-map", "0:v", "-map", "0:a",
                            "-movflags", "+faststart",
                            "-y", str(raw_final)
                        )

                # Mix background music — hỗ trợ cả upload lẫn local path
                _effective_bgm = bgm_file or (_bgm_local_path and Path(_bgm_local_path).exists())
                if _effective_bgm:
                    log("🎵 Đang mix nhạc nền...")
                    if bgm_file:
                        bgm_path = work / f"bgm_{bgm_file.name}"
                        bgm_path.write_bytes(bgm_file.read())
                    else:
                        bgm_path = Path(_bgm_local_path)
                    final_with_bgm = work / "final_with_bgm.mp4"


                    try:
                        cmd = [
                            "-i", str(raw_final),
                            "-stream_loop", "-1", "-i", str(bgm_path),
                            "-filter_complex", f"[0:a]volume={tts_vol:.2f}[a0];[1:a]volume={bgm_vol}[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[a]",
                            "-map", "0:v", "-map", "[a]",
                            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
                            "-y", str(final_with_bgm)
                        ]
                        ffmpeg(*cmd)
                        raw_final = final_with_bgm
                        log("✅ Đã mix nhạc nền xong.")
                    except Exception as e:
                        log(f"⚠️ Lỗi mix nhạc nền: {e}, giữ nguyên gốc.")

                # Không có BGM nhưng tts_vol > 1.0 → áp dụng volume filter riêng
                elif tts_vol > 1.0:
                    try:
                        _tts_vol_out = work / "final_tts_vol.mp4"
                        ffmpeg(
                            "-i", str(raw_final),
                            "-af", f"volume={tts_vol:.2f}",
                            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
                            "-y", str(_tts_vol_out)
                        )
                        raw_final = _tts_vol_out
                        log(f"🔊 Đã tăng âm lượng giọng đọc ×{tts_vol:.1f}")
                    except Exception as e:
                        log(f"⚠️ Lỗi tăng âm lượng TTS: {e}, giữ nguyên gốc.")

                # Use the requested output name when supplied; otherwise use the AI title.
                title = proj.get("script", {}).get("title", "") or ""
                safe_name = output_file_stem(proj.get("output_name", "") or title)

                save_dir = Path.home() / "Desktop" / "AI_Videos"
                save_dir.mkdir(parents=True, exist_ok=True)
                final = available_output_path(save_dir, safe_name)
                safe_name = final.stem
                shutil.copy(raw_final, final)

                size_mb = final.stat().st_size / 1024 / 1024
                log(f"✅ Render xong! {size_mb:.1f} MB")
                log(f"📂 Lưu tại: {final}")

                # ── Full Combo SEO Export ──────────────────────────────────────
                try:
                    sc_data = proj.get("script", {})
                    seo_title = sc_data.get("title", title)
                    seo_desc  = sc_data.get("description", "")
                    seo_tags  = sc_data.get("tags", [])
                    sc_scenes = proj.get("scenes", [])
                    is_shorts = "9:16" in aspect
                    platform  = "YouTube Shorts / TikTok" if is_shorts else "YouTube"

                    # Tính chapter timestamps từ duration từng cảnh
                    chapters, cursor_t = [], 0.0
                    for idx_c, sc_c in enumerate(sc_scenes):
                        mm = int(cursor_t // 60)
                        ss = int(cursor_t % 60)
                        snippet = sc_c.get("text", "")[:50].strip()
                        chapters.append(f"{mm:02d}:{ss:02d} – Cảnh {idx_c+1}: {snippet}")
                        cursor_t += float(sc_c.get("duration", 5))

                    if is_shorts:
                        # Caption cho Shorts/TikTok
                        top_tags = " ".join([f"#{t.replace(' ','').replace('#','')}" for t in seo_tags[:7]])
                        metadata_txt = (
                            f"=== 📱 {platform} — Full Combo SEO ===\n\n"
                            f"── CAPTION ──\n"
                            f"{seo_title}\n\n"
                            f"{seo_desc}\n\n"
                            f"{top_tags}\n\n"
                            f"── HASHTAGS (copy & paste) ──\n"
                            f"{top_tags}\n"
                        )
                    else:
                        # Metadata đầy đủ cho YouTube
                        desc_with_chapters = (
                            f"{seo_desc}\n\n"
                            f"── CHAPTERS ──\n"
                            + "\n".join(chapters) +
                            f"\n\n"
                            f"#{'  #'.join([t.replace(' ','').replace('#','') for t in seo_tags[:5]])}"
                        )
                        all_tags = ", ".join(seo_tags)
                        metadata_txt = (
                            f"=== 🎬 {platform} — Full Combo SEO ===\n\n"
                            f"── TITLE (copy vào YouTube) ──\n"
                            f"{seo_title}\n\n"
                            f"── DESCRIPTION (copy vào YouTube) ──\n"
                            f"{desc_with_chapters}\n\n"
                            f"── TAGS (30 tags, copy vào mục Tags) ──\n"
                            f"{all_tags}\n"
                        )

                    meta_file = save_dir / f"{safe_name}_SEO.txt"
                    meta_file.write_text(metadata_txt, encoding="utf-8")
                    log(f"📄 SEO metadata: {meta_file.name}")
                    proj["seoMetaPath"] = str(meta_file)
                except Exception as seo_e:
                    log(f"⚠️ Lỗi tạo SEO file: {seo_e}")

                proj.update({"step": 4, "finalPath": str(final), "fileName": f"{safe_name}.mp4"})
                save_proj(proj)

            except Exception as e:
                st.error(f"❌ {e}")

        # ── Show results ───────────────────────────────────────────────────
        if proj.get("script"):
            st.divider()
            s = proj["script"]

            # ── Thumbnail panel ─────────────────────────────────────────────
            thumb_path = proj.get("thumbnailPath")
            if thumb_path and Path(thumb_path).exists():
                tcol, tinfo = st.columns([1, 1.2])
                with tcol:
                    st.image(thumb_path, caption="🖼️ Thumbnail (Gemini Imagen 3)",
                             width="stretch")
                with tinfo:
                    st.markdown(f"**🎬 {s.get('title','')}**")
                    st.caption(f"{len(proj.get('scenes',[]))} cảnh · {len(s.get('tags',[]))} tags")
                    thumb_bytes = Path(thumb_path).read_bytes()
                    st.download_button(
                        "⬇️ Tải thumbnail (.jpg)",
                        data=thumb_bytes,
                        file_name=Path(thumb_path).name,
                        mime="image/jpeg",
                        width="stretch",
                    )
                    if st.button("🔄 Tạo lại Thumbnail", width="stretch",
                                 help="Dùng OpenAI DALL-E 3 (hoặc Gemini Imagen) để tạo ảnh mới"):
                        with st.spinner("Đang tạo thumbnail mới..."):
                            gk  = (cfg.get("gemini") or [None])[0]
                            oai = cfg.get("openai", "") or None
                            new_thumb, new_thumb_err = generate_thumbnail(s, gk, W, H,
                                                           save_dir=Path.home() / "Desktop" / "AI_Videos",
                                                           openai_key=oai)
                            if new_thumb:
                                proj["thumbnailPath"] = str(new_thumb)
                                save_proj(proj)
                                st.success("✅ Thumbnail mới đã được tạo!")
                                st.rerun()
                            else:
                                st.error(f"❌ {new_thumb_err}")
            else:
                st.markdown(f"**🎬 {s.get('title','')}**")
                st.caption(f"{len(proj.get('scenes',[]))} cảnh · {len(s.get('tags',[]))} tags")
                if st.button("🖼️ Tạo Thumbnail (DALL-E 3 / Imagen)", width="stretch"):
                    with st.spinner("Đang tạo thumbnail..."):
                        gk  = (cfg.get("gemini") or [None])[0]
                        oai = cfg.get("openai", "") or None
                        new_thumb, new_thumb_err = generate_thumbnail(s, gk, W, H,
                                                       save_dir=Path.home() / "Desktop" / "AI_Videos",
                                                       openai_key=oai)
                        if new_thumb:
                            proj["thumbnailPath"] = str(new_thumb)
                            save_proj(proj)
                            st.rerun()
                        else:
                            st.error(f"❌ {new_thumb_err}")

            # Show script preview with retention notes and allow editing
            st.markdown("### 📝 Duyệt & Chỉnh Sửa Kịch Bản")
            st.info("Sửa trực tiếp nội dung kịch bản hoặc từ khóa tìm video (keyword) ở dưới. Hệ thống sẽ lưu tự động.")

            scenes = proj.get("scenes", [])
            total_scenes = len(scenes)

        @st.fragment
        def _scene_editor_fragment():
            # ── Fragment-local imports (st.fragment có scope riêng) ───────────
            import json, os, re, uuid, random, math, time, subprocess, shutil, tempfile
            from pathlib import Path
            from typing import Optional
            from app.config import load_cfg, output_file_stem, available_output_path
            from app.project import get_proj_file
            from app.subtitle import srt_to_words
            from app.media_fetch import (
                search_pexels_videos, search_pixabay_videos, search_coverr_videos,
                search_pexels_photos_only, search_pixabay_photos_only,
                _translate_keyword_to_en, clean_keyword, inject_region_into_keyword,
                optimize_query_for_region, fetch_stock_video, fetch_stock_photo,
                search_stock_videos, search_stock_photos, is_image_file,
            )
            from app.ffmpeg_utils import probe_audio_duration, download_url
            from app.effects import (
                make_image_effect_filter, make_video_intro_filter,
                apply_sound_effect_to_scene,
                IMAGE_EFFECTS, VIDEO_INTRO_EFFECTS, SOUND_EFFECTS,
            )
            from app.image_gen import generate_scene_image_ai, generate_thumbnail
            from app.subtitle import make_srt, make_ass, srt_to_words, SUB_STYLES
            # ─────────────────────────────────────────────────────────────────
            proj = st.session_state.proj
            cfg  = load_cfg()

            scenes = proj.get("scenes", [])
            total_scenes = len(scenes)


            edited = False

            if total_scenes > 0:
                # Progress Bar
                completed_count = sum(1 for sc in scenes if sc.get("completed"))
                col_prog1, col_prog2 = st.columns([3, 1], vertical_alignment="center")
                with col_prog1:
                    st.progress(completed_count / total_scenes)
                with col_prog2:
                    st.markdown(f"🏆 **Đã duyệt: {completed_count}/{total_scenes}**")

                _flow_options = ["current", "google_flow_auto"]
                _saved_flow = proj.get("video_generation_flow", "current")
                if _saved_flow not in _flow_options:
                    _saved_flow = "current"
                _production_flow = st.radio(
                    "🎬 Chọn luồng tạo hình ảnh/video cho project này",
                    options=_flow_options,
                    index=_flow_options.index(_saved_flow),
                    format_func=lambda value: {
                        "current": "Luồng hiện tại — stock / ảnh AI / upload thủ công",
                        "google_flow_auto": "Google Flow tự động — prompt → video → đúng cảnh",
                    }[value],
                    horizontal=True,
                    key="project_video_generation_flow",
                )
                if _production_flow != proj.get("video_generation_flow"):
                    proj["video_generation_flow"] = _production_flow
                    save_proj(proj)

                _flow_cfg = dict(cfg)
                if _production_flow == "google_flow_auto":
                    _flow_cfg["veo3_provider"] = "google_flow"
                    _flow_cfg["veo3_enabled"] = True
                _veo_auto_ready = (
                    _production_flow == "google_flow_auto"
                    and _VEO3_OK
                    and bool(_flow_cfg.get("useapi_token"))
                )
                _prompted_scenes = [
                    (scene_index, candidate)
                    for scene_index, candidate in enumerate(scenes)
                    if str(candidate.get("veo3_prompt", "")).strip()
                ]
                _missing_prompt_count = total_scenes - len(_prompted_scenes)
                if _production_flow == "google_flow_auto":
                    st.markdown("#### 🤖 Google Flow tự động")
                    st.caption(
                        f"Sẵn sàng tạo {len(_prompted_scenes)}/{total_scenes} cảnh có prompt. "
                        "Flow credit chỉ được dùng khi bạn bấm nút bên dưới hoặc chạy toàn pipeline."
                    )
                    if _missing_prompt_count:
                        st.warning(f"Còn {_missing_prompt_count} cảnh chưa có veo3_prompt nên sẽ được bỏ qua.")
                else:
                    st.info(
                        "Đang dùng luồng hiện tại. Stock, ảnh AI, upload và các visual đang có "
                        "được giữ nguyên; Google Flow sẽ không tự chạy."
                    )

                if _production_flow == "google_flow_auto" and st.button(
                    "⚡ Google Flow: tạo và gắn vào TẤT CẢ cảnh",
                    key="generate_all_reviewed_google_flow_scenes",
                    type="primary",
                    use_container_width=True,
                    disabled=not _veo_auto_ready or not _prompted_scenes,
                    help="Sẽ dùng Flow credit. Visual hiện tại chỉ bị thay khi MP4 mới tải thành công.",
                ):
                    _orientation = "portrait" if "9:16" in str(proj.get("aspect", "")) else "landscape"
                    _progress = st.progress(0, text="Chuẩn bị tạo Veo 3...")
                    _success_count = 0
                    _failed_scenes = []
                    for _position, (_scene_index, _candidate) in enumerate(_prompted_scenes):
                        _progress.progress(
                            _position / max(1, len(_prompted_scenes)),
                            text=f"Đang tạo cảnh {_scene_index + 1}/{total_scenes}...",
                        )
                        try:
                            _path = generate_scene_video_with_veo3(
                                _candidate, _flow_cfg, orientation=_orientation
                            )
                            if not _path:
                                raise RuntimeError("Veo 3 không trả về video")
                            attach_veo3_video(proj["scenes"][_scene_index], _path)
                            _success_count += 1
                        except Exception as _veo_exc:
                            proj["scenes"][_scene_index]["veo3Error"] = str(_veo_exc)[:300]
                            _failed_scenes.append(_scene_index + 1)
                        save_proj(proj)
                    _progress.progress(1.0, text=f"Hoàn tất: {_success_count}/{len(_prompted_scenes)} cảnh")
                    if _failed_scenes:
                        st.error("Không tạo được cảnh: " + ", ".join(map(str, _failed_scenes)))
                    else:
                        st.success("Đã tạo bằng Google Flow và gắn video vào đúng tất cả cảnh.")
                    st.rerun(scope="fragment")

                if _production_flow == "google_flow_auto" and not _veo_auto_ready:
                    st.warning("Vào Settings → Google Flow và nhập UseAPI token để bật luồng tự động.")
                # Global region preference
                proj_region = proj.get("region", "Châu Á / Việt Nam")
                region_options = ["Không giới hạn", "Châu Á / Việt Nam", "Phương Tây (Western)"]
                if proj_region not in region_options:
                    proj_region = "Châu Á / Việt Nam"
                new_region = st.selectbox(
                    "🌐 Ưu tiên hình ảnh/video thuộc khu vực:",
                    options=region_options,
                    index=region_options.index(proj_region),
                    key="global_region_select",
                    help="Tự động thêm từ khóa tối ưu hóa (ví dụ: 'asian') để tìm kiếm hình ảnh/video phù hợp với khu vực bạn nhắm tới."
                )
                if new_region != proj.get("region"):
                    proj["region"] = new_region
                    save_proj(proj)

                # ── 📦 BULK IMAGE UPLOAD ─────────────────────────────────────
                with st.expander("📦 Upload hàng loạt ảnh vào cảnh", expanded=False):
                    st.caption(
                        "Upload nhiều ảnh cùng lúc. Mỗi ảnh sẽ tự động gán vào cảnh "
                        "tương ứng dựa trên **số trong tên file** "
                        "(vd: `scene_001.jpg` → Cảnh 1, `003.png` → Cảnh 3, `1.jpg` → Cảnh 1). "
                        "Nếu không tìm thấy số, ảnh sẽ được gán theo **thứ tự upload**."
                    )
                    bulk_files = st.file_uploader(
                        "Chọn ảnh (jpg, png, webp, jpeg):",
                        type=["jpg", "jpeg", "png", "webp"],
                        accept_multiple_files=True,
                        key="bulk_img_uploader",
                    )
                    if bulk_files:
                        import re as _re
                        # Parse số từ tên file → 1-based scene index
                        def _parse_scene_idx(filename: str) -> int | None:
                            nums = _re.findall(r"\d+", Path(filename).stem)
                            if nums:
                                return int(nums[0])  # số đầu tiên trong stem
                            return None

                        # Sort files: ưu tiên theo số parse được, rồi theo tên
                        def _sort_key(f):
                            n = _parse_scene_idx(f.name)
                            return (0 if n is not None else 1, n or 0, f.name)

                        sorted_files = sorted(bulk_files, key=_sort_key)

                        st.markdown(f"**Xem trước mapping ({len(sorted_files)} ảnh):**")
                        preview_cols = st.columns(min(4, len(sorted_files)))
                        mapping: list[tuple[int, object]] = []  # (0-based scene idx, file)
                        fallback_order = 0
                        parse_warnings = []
                        for f in sorted_files:
                            parsed = _parse_scene_idx(f.name)
                            if parsed is not None:
                                scene_idx_0 = parsed - 1  # convert 1-based → 0-based
                            else:
                                scene_idx_0 = fallback_order
                                parse_warnings.append(f.name)
                            fallback_order += 1
                            mapping.append((scene_idx_0, f))

                        for i, (sidx, f) in enumerate(mapping):
                            with preview_cols[i % len(preview_cols)]:
                                if 0 <= sidx < total_scenes:
                                    st.image(f, caption=f"Cảnh {sidx+1}", use_container_width=True)
                                else:
                                    st.warning(f"⚠️ `{f.name}` → Cảnh {sidx+1} (ngoài range)")

                        if parse_warnings:
                            st.warning(
                                f"⚠️ Không tìm thấy số trong tên file: "
                                + ", ".join(f"`{n}`" for n in parse_warnings)
                                + " — đã gán theo thứ tự upload."
                            )

                        col_apply, col_clear = st.columns([2, 1])
                        with col_apply:
                            if st.button("✅ Áp dụng tất cả vào cảnh", key="bulk_img_apply", type="primary"):
                                _bulk_applied = 0
                                _bulk_skipped = []
                                AUDIO_DIR.mkdir(parents=True, exist_ok=True)
                                for sidx, f in mapping:
                                    if 0 <= sidx < total_scenes:
                                        img_path = AUDIO_DIR / f"custom_img_{sidx}_{f.name}"
                                        img_path.write_bytes(f.read())
                                        proj["scenes"][sidx]["customImg"] = str(img_path)
                                        proj["scenes"][sidx]["imageUrl"]  = None
                                        proj["scenes"][sidx]["videoUrl"]  = None
                                        proj["scenes"][sidx]["customVid"] = None
                                        _bulk_applied += 1
                                    else:
                                        _bulk_skipped.append(f"Cảnh {sidx+1} ({f.name})")
                                save_proj(proj)
                                msg = f"✅ Đã gán **{_bulk_applied}** ảnh vào các cảnh!"
                                if _bulk_skipped:
                                    msg += f" ⚠️ Bỏ qua: {', '.join(_bulk_skipped)}"
                                st.success(msg)
                                st.rerun()
                        with col_clear:
                            if st.button("🗑️ Xóa tất cả ảnh custom", key="bulk_img_clear"):
                                for s in proj["scenes"]:
                                    s["customImg"] = None
                                save_proj(proj)
                                st.success("Đã xóa toàn bộ ảnh custom khỏi tất cả cảnh.")
                                st.rerun()
                # ── End bulk upload ──────────────────────────────────────────

                # Active page or scene select
                if "selectbox_scene_active" not in st.session_state:
                    st.session_state.selectbox_scene_active = proj.get("active_scene_idx", 0)
                if "selectbox_page_active" not in st.session_state:
                    st.session_state.selectbox_page_active = proj.get("active_page", 0)
                if "view_mode" not in st.session_state:
                    st.session_state.view_mode = proj.get("view_mode", "Tập trung (Mượt nhất)")

                def go_prev_scene(curr):
                    # Xóa widget cache cảnh hiện tại để cảnh mới render lại từ proj data
                    for _k in [f"veo3_{curr}", f"text_{curr}"]:
                        st.session_state.pop(_k, None)
                    st.session_state.selectbox_scene_active = curr - 1
                    proj["active_scene_idx"] = curr - 1
                    save_proj(proj)

                def go_next_scene(curr):
                    # Xóa widget cache cảnh hiện tại để cảnh mới render lại từ proj data
                    for _k in [f"veo3_{curr}", f"text_{curr}"]:
                        st.session_state.pop(_k, None)
                    st.session_state.selectbox_scene_active = curr + 1
                    proj["active_scene_idx"] = curr + 1
                    save_proj(proj)

                view_mode = st.radio(
                    "👁️ Chế độ xem kịch bản:",
                    options=["Tập trung (Mượt nhất)", "Phân trang (10 cảnh/trang)", "Tất cả (Yêu cầu cấu hình mạnh)"],
                    horizontal=True,
                    index=["Tập trung (Mượt nhất)", "Phân trang (10 cảnh/trang)", "Tất cả (Yêu cầu cấu hình mạnh)"].index(st.session_state.view_mode),
                    key="view_mode_select"
                )
                if view_mode != proj.get("view_mode"):
                    proj["view_mode"] = view_mode
                    st.session_state.view_mode = view_mode
                    save_proj(proj)

                scenes_to_render = []
                if view_mode == "Tập trung (Mượt nhất)":
                    scene_options = [
                        f"Cảnh {idx+1} {'(✅ Hoàn tất)' if sc.get('completed') else '(⏳ Đang chờ)'}: {sc.get('text', '')[:50]}..." 
                        for idx, sc in enumerate(scenes)
                    ]
                    # Clamp session state value trước khi render để tránh out-of-range
                    if st.session_state.get("selectbox_scene_active", 0) >= total_scenes:
                        st.session_state["selectbox_scene_active"] = max(0, total_scenes - 1)
                    active_idx = st.selectbox(
                        "🎯 Chọn cảnh đang chỉnh sửa:",
                        options=range(total_scenes),
                        format_func=lambda x: scene_options[x],
                        key="selectbox_scene_active"
                    )
                    if active_idx != proj.get("active_scene_idx"):
                        # Chuyển cảnh qua selectbox: xóa widget cache cảnh cũ để render lại từ proj
                        _old_idx = proj.get("active_scene_idx", 0)
                        for _k in [f"veo3_{_old_idx}", f"text_{_old_idx}"]:
                            st.session_state.pop(_k, None)
                        proj["active_scene_idx"] = active_idx
                        save_proj(proj)
                    scenes_to_render.append((active_idx, scenes[active_idx]))

                    # Jump buttons
                    col_nav1, col_nav2, col_nav3 = st.columns([1, 2, 1])
                    with col_nav1:
                        st.button(
                            "◀ Cảnh Trước", 
                            disabled=(active_idx == 0), 
                            key="btn_prev_scene",
                            on_click=go_prev_scene,
                            args=(active_idx,)
                        )
                    with col_nav3:
                        st.button(
                            "Cảnh Tiếp Theo ▶", 
                            disabled=(active_idx == total_scenes - 1), 
                            key="btn_next_scene",
                            on_click=go_next_scene,
                            args=(active_idx,)
                        )

                elif view_mode == "Phân trang (10 cảnh/trang)":
                    items_per_page = 10
                    total_pages = (total_scenes + items_per_page - 1) // items_per_page
                    active_page = st.selectbox(
                        "📄 Chọn trang:",
                        options=range(total_pages),
                        format_func=lambda x: f"Trang {x+1} (Cảnh {x*items_per_page+1} - {min((x+1)*items_per_page, total_scenes)})",
                        index=min(st.session_state.selectbox_page_active, total_pages - 1),
                        key="selectbox_page_active"
                    )
                    if active_page != proj.get("active_page"):
                        proj["active_page"] = active_page
                        save_proj(proj)
                    start_idx = active_page * items_per_page
                    end_idx = min(start_idx + items_per_page, total_scenes)
                    for idx in range(start_idx, end_idx):
                        scenes_to_render.append((idx, scenes[idx]))
                else:
                    for idx in range(total_scenes):
                        scenes_to_render.append((idx, scenes[idx]))

                for idx, scene in scenes_to_render:
                    scene_data = proj.get("scenes", [])
                    note = ""
                    if idx < len(scene_data) and isinstance(scene_data[idx], dict):
                        note = scene_data[idx].get("retention_note", "")

                    label_emoji = "✅" if scene.get("completed") else ("🪝" if idx == 0 else ("🎯" if idx == total_scenes - 1 else "▶️"))
                    is_expanded = True if view_mode == "Tập trung (Mượt nhất)" else (idx == scenes_to_render[0][0])

                    with st.expander(f"{label_emoji} Cảnh {idx+1}: {scene.get('text', '')[:40]}... ⏱️{scene.get('duration',5)}s", expanded=is_expanded):
                        # ── Badge số cảnh — to rõ, luôn hiện đầu tiên ──
                        st.markdown(
                            f"<div style='background:#1e3a5f;border-left:4px solid #4a9eff;"
                            f"padding:8px 14px;border-radius:6px;margin-bottom:10px;'>"
                            f"<span style='font-size:20px;font-weight:bold;color:#4a9eff'>🎬 CẢNH {idx+1}</span>"
                            f"<span style='color:#888;font-size:14px;margin-left:10px'>/ {total_scenes} cảnh</span>"
                            f"</div>",
                            unsafe_allow_html=True
                        )
                        if note:
                            st.caption(f"💡 *Mục tiêu cảnh: {note}*")

                        col_left, col_right = st.columns([2, 1])
                        with col_left:
                            new_text = st.text_area("Nội dung lời đọc (Voice):", value=scene.get('text', ''), key=f"text_{idx}", height=120)

                            # ── Veo3 Prompt output: nổi bật để dễ copy gen tay ──
                            st.markdown("**🤖 Veo3 / Sora / Kling Prompt — Copy để gen video thủ công:**")
                            veo3_prompt = scene.get('veo3_prompt', '')
                            _veo_col1, _veo_col2, _veo_col3 = st.columns([5, 1, 1])
                            with _veo_col1:
                                new_veo3 = st.text_area(
                                    "veo3_prompt_label",
                                    value=veo3_prompt,
                                    key=f"veo3_{idx}",
                                    height=350,
                                    label_visibility="collapsed",
                                    placeholder="📋 Prompt chưa có — bấm '✨ AI Tạo Prompt' để sinh tự động, hoặc tự nhập tiếng Anh mô tả cảnh này (lighting, camera angle, subject, mood...)"
                                )
                                if new_veo3 != veo3_prompt:
                                    proj["scenes"][idx]["veo3_prompt"] = new_veo3
                                    edited = True
                            with _veo_col2:
                                if st.button("✨ AI Tạo\nPrompt", key=f"gen_veo_{idx}", use_container_width=True, help="AI viết prompt chuẩn Veo3/Sora (Netflix Documentary style)"):
                                    with st.spinner("AI đang viết..."):
                                        try:
                                            _txt = scene.get("text", "")
                                            _lc = proj.get("lang", "Korean")
                                            _nat = "South Korean" if _lc == "Korean" else "Vietnamese" if _lc == "Vietnamese" else "Western"
                                            _ap = (
                                                f"Based on this narration: '{_txt}'\n\n"
                                                f"Write 3 short English sections for a cinematic documentary video prompt:\n"
                                                f"1. CHARACTER: {_nat} character appearance, clothing, emotional state. 2-3 sentences.\n"
                                                f"2. ACTION: Natural movements, expressions, gestures. 2-3 sentences.\n"
                                                f"3. ENVIRONMENT: Authentic {_nat} location, architectural details, atmosphere. 2-3 sentences.\n\n"
                                                'Return ONLY JSON: {"character":"...","action":"...","environment":"..."}\nNo markdown.'
                                            )
                                            _raw = call_ai(_ap).strip()
                                            try:
                                                _p = parse_json_robust(_raw)
                                                _c = _p.get("character","").strip()
                                                _a = _p.get("action","").strip()
                                                _e = _p.get("environment","").strip()
                                            except Exception:
                                                _c = f"A realistic {_nat} person with authentic appearance."
                                                _a = "Moves naturally with subtle expressions and body language."
                                                _e = f"Authentic {_nat} urban setting with everyday atmosphere."
                                            _res = build_veo3_prompt(_c, _a, _e, _nat)
                                            if _res:
                                                proj["scenes"][idx]["veo3_prompt"] = _res
                                                save_proj(proj)
                                                # Xoá widget cache để text_area render lại với giá trị mới
                                                st.session_state.pop(f"veo3_{idx}", None)
                                                st.rerun(scope="fragment")
                                        except Exception as e:
                                            st.error(f"Lỗi: {e}")
                            with _veo_col3:
                                if st.button(
                                    "🎬 Tạo\nFlow",
                                    key=f"generate_veo_scene_{idx}",
                                    use_container_width=True,
                                    disabled=not _veo_auto_ready or not bool(str(new_veo3).strip()),
                                    help="Google Flow tạo video từ prompt đang duyệt và tự gắn vào cảnh này.",
                                ):
                                    _orientation = "portrait" if "9:16" in str(proj.get("aspect", "")) else "landscape"
                                    try:
                                        # Use the widget's latest value even before the normal
                                        # fragment save at the bottom of this render pass.
                                        proj["scenes"][idx]["veo3_prompt"] = str(new_veo3).strip()
                                        with st.spinner(f"Veo 3 đang tạo cảnh {idx + 1}..."):
                                            _path = generate_scene_video_with_veo3(
                                                proj["scenes"][idx], _flow_cfg, orientation=_orientation
                                            )
                                        if not _path:
                                            raise RuntimeError("Veo 3 không trả về video")
                                        attach_veo3_video(proj["scenes"][idx], _path)
                                        save_proj(proj)
                                        st.success(f"Đã gắn video Google Flow vào cảnh {idx + 1}")
                                        st.rerun(scope="fragment")
                                    except Exception as _veo_exc:
                                        proj["scenes"][idx]["veo3Error"] = str(_veo_exc)[:300]
                                        save_proj(proj)
                                        st.error(f"Veo 3 lỗi: {_veo_exc}")

                            # ── 🖼️ Image Prompt (cho AI Image mode — video dài chỉ dùng ảnh) ──
                            st.markdown("**🖼️ Prompt Ảnh AI (Imagen / Flux / Midjourney):**")
                            st.caption("Mô tả ảnh tĩnh cần tạo (tiếng Anh, 20–60 từ). Dùng khi chạy chế độ **AI Image**. Để trống → dùng Keyword.")
                            _img_col1, _img_col2, _img_col3 = st.columns([5, 1, 1])
                            with _img_col1:
                                _curr_img_prompt = scene.get("imagePrompt", "")
                                _new_img_prompt = st.text_area(
                                    "imagePrompt_label",
                                    value=_curr_img_prompt,
                                    key=f"img_prompt_{idx}",
                                    height=100,
                                    label_visibility="collapsed",
                                    placeholder="Ví dụ: A worried Vietnamese man staring at stock charts on monitor, dark dramatic office, red glow, cinematic, hyperrealistic..."
                                )
                                if _new_img_prompt != _curr_img_prompt:
                                    proj["scenes"][idx]["imagePrompt"] = _new_img_prompt
                                    edited = True
                            with _img_col2:
                                if st.button("✨ AI Viết\nPrompt Ảnh", key=f"gen_img_p_{idx}", use_container_width=True,
                                             help="AI tự viết prompt ảnh chuẩn cho Imagen/Flux dựa trên nội dung cảnh"):
                                    with st.spinner("AI đang viết prompt ảnh..."):
                                        _sc_text = scene.get("text", "")
                                        _kw_txt = scene.get("keyword", "")
                                        _gen_img_p_prompt = (
                                            f"Scene narration: \"{_sc_text[:300]}\"\n"
                                            f"Keyword: {_kw_txt}\n\n"
                                            "Write a SHORT English image generation prompt (20-60 words) for AI image tools (Imagen, Flux, Midjourney).\n"
                                            "MUST: concrete visual subject + dramatic mood + lighting style. Photorealistic, cinematic.\n"
                                            "FORBIDDEN: abstract ideas, text overlay, logos, brand names.\n"
                                            "Reply with ONLY the prompt text. No explanation."
                                        )
                                        try:
                                            _ai_img_p = call_ai(_gen_img_p_prompt).strip().strip('"').strip("'")
                                            if _ai_img_p:
                                                proj["scenes"][idx]["imagePrompt"] = _ai_img_p
                                                save_proj(proj)
                                                st.success("✅ Đã tạo prompt ảnh!")
                                                st.rerun(scope="fragment")
                                        except Exception as _e_ip:
                                            st.error(f"Lỗi: {_e_ip}")
                            with _img_col3:
                                _gemini_key_ui = proj.get("gemini_key") or st.session_state.get("gemini_key", "")
                                if st.button("🎨 Gen Ảnh\nNgay", key=f"gen_img_now_{idx}",
                                             use_container_width=True, help="Tạo ảnh AI cho cảnh này ngay lập tức bằng Imagen 3"):
                                    if not _gemini_key_ui:
                                        st.error("Cần Gemini API Key")
                                    else:
                                        with st.spinner(f"Imagen 3 đang tạo ảnh cảnh {idx+1}..."):
                                            try:
                                                _W_ui = proj.get("W", 1080)
                                                _H_ui = proj.get("H", 1920)
                                                _img_save_ui = Path(str(proj.get("work_dir", TMP))) / f"s{idx}" / f"ai_img_manual_{idx}.jpg"
                                                _img_save_ui.parent.mkdir(parents=True, exist_ok=True)
                                                _ip_val = proj["scenes"][idx].get("imagePrompt", "").strip()
                                                _kw_val = clean_keyword(scene.get("keyword", ""), lang=proj.get("lang", "Vietnamese"))
                                                _p, _e = generate_scene_image_ai(
                                                    _kw_val, _gemini_key_ui, _W_ui, _H_ui, _img_save_ui,
                                                    image_prompt=_ip_val
                                                )
                                                if _p:
                                                    proj["scenes"][idx]["imageUrl"] = str(_p)
                                                    proj["scenes"][idx]["videoUrl"] = None
                                                    proj["scenes"][idx]["customVid"] = None
                                                    proj["scenes"][idx]["customImg"] = None
                                                    proj["scenes"][idx]["veo3Path"] = None
                                                    save_proj(proj)
                                                    st.success(f"✅ Đã tạo ảnh AI cho cảnh {idx+1}!")
                                                    st.rerun(scope="fragment")
                                                else:
                                                    st.error(f"❌ Lỗi tạo ảnh: {_e}")
                                            except Exception as _e_gn:
                                                st.error(f"❌ {_e_gn}")

                            # Gemini Web mode: use the user's existing Google AI
                            # subscription with an explicit human confirmation,
                            # then attach the downloaded MP4 to this scene.
                            with st.expander("🌐 Gemini Web — tạo bằng tài khoản Pro/Ultra", expanded=False):
                                st.caption(
                                    "1) Tải/copy prompt → 2) mở Gemini Create video → "
                                    "3) tải MP4 về Downloads → 4) chọn file và nhập vào cảnh."
                                )
                                _web_prompt = proj["scenes"][idx].get("veo3_prompt", "") or new_veo3
                                _web_col1, _web_col2 = st.columns(2)
                                with _web_col1:
                                    st.link_button(
                                        "↗️ Mở Gemini Create video",
                                        "https://gemini.google.com/app",
                                        use_container_width=True,
                                    )
                                with _web_col2:
                                    st.download_button(
                                        "⬇️ Tải prompt .txt",
                                        data=_web_prompt,
                                        file_name=f"scene_{idx + 1}_veo_prompt.txt",
                                        mime="text/plain",
                                        use_container_width=True,
                                        key=f"download_web_prompt_{idx}",
                                    )

                                _downloads_dir = Path.home() / "Downloads"
                                try:
                                    _recent_web_videos = sorted(
                                        (
                                            p for p in _downloads_dir.glob("*.mp4")
                                            if p.is_file() and p.stat().st_size > 10_000
                                        ),
                                        key=lambda p: p.stat().st_mtime,
                                        reverse=True,
                                    )[:12]
                                except OSError:
                                    _recent_web_videos = []

                                if _recent_web_videos:
                                    _selected_web_video = st.selectbox(
                                        "MP4 mới tải trong Downloads",
                                        _recent_web_videos,
                                        format_func=lambda p: f"{p.name} · {p.stat().st_size / 1_000_000:.1f} MB",
                                        key=f"gemini_web_download_{idx}",
                                    )
                                    if st.button(
                                        "✅ Dùng MP4 này cho cảnh",
                                        key=f"import_gemini_web_{idx}",
                                        use_container_width=True,
                                    ):
                                        proj["scenes"][idx]["customVid"] = str(_selected_web_video)
                                        proj["scenes"][idx]["videoUrl"] = None
                                        proj["scenes"][idx]["imageUrl"] = None
                                        proj["scenes"][idx]["customImg"] = None
                                        proj["scenes"][idx]["veo3Path"] = None
                                        save_proj(proj)
                                        st.success(f"Đã gắn {_selected_web_video.name} vào cảnh {idx + 1}")
                                        st.rerun(scope="fragment")
                                else:
                                    st.info("Chưa thấy file MP4 nào trong thư mục Downloads.")

                            # Nút dịch Voice
                            col_tr_btn, col_tr_val = st.columns([1, 3])
                            with col_tr_btn:
                                if st.button("💬 Dịch Voice", key=f"tr_voice_btn_{idx}"):
                                    with st.spinner("Đang dịch..."):
                                        prompt_tr = f"Translate the following text to Vietnamese if it is English/Korean, or to English if it is Vietnamese. Return ONLY the translation, no extra text:\n\n{new_text}"
                                        try:
                                            st.session_state[f"tr_voice_{idx}"] = call_ai(prompt_tr).strip()
                                        except Exception as e:
                                            st.error(f"Lỗi: {e}")
                            with col_tr_val:
                                tr_val = st.session_state.get(f"tr_voice_{idx}", "")
                                if tr_val:
                                    st.info(f"Bản dịch: {tr_val}")

                            kw_col1, kw_col2 = st.columns([3, 1])
                            with kw_col1:
                                user_kw = st.text_input("Từ khóa tìm kiếm (Tiếng Việt / Tiếng Anh):", value=scene.get('keyword', ''), key=f"kw_{idx}",
                                    help="Nhập từ khóa tiếng Việt hoặc tiếng Anh. AI sẽ tự động dịch sang tiếng Anh và tối ưu hóa cho stock API.")
                            with kw_col2:
                                if st.button("🤖 AI gợi ý", key=f"ai_kw_{idx}", help="AI phân tích nội dung cảnh và đề xuất keyword tốt hơn"):
                                    scene_text = scene.get("text", "")
                                    if scene_text:
                                        with st.spinner("AI đang gợi ý..."):
                                            kw_prompt = (
                                                f"Scene narration: \"{scene_text[:300]}\"\n\n"
                                                f"Generate 1 stock video search keyword (2-5 words, English or Vietnamese).\n"
                                                f"The keyword = what a CAMERA physically sees. NOT the abstract concept.\n\n"
                                                f"Reply with ONLY the keyword phrase. Nothing else."
                                            )
                                            try:
                                                ai_kw = call_ai(kw_prompt).strip().strip('"').strip("'").lower()
                                                import re as _re
                                                ai_kw = _re.sub(r'[^a-z0-9A-Za-đÝỹửựăâđêôơưàảãáạằẳẵắặầẩẫấậèẻẽéẹềểễếệìỉĩíịòỏõóọờởỡớợồổỗốộùủũúụừửữứựỳỷỹýỵ ]', '', ai_kw).strip()
                                                if ai_kw:
                                                    proj["scenes"][idx]["keyword"] = ai_kw
                                                    save_proj(proj)
                                                    st.success(f"✅ Đã cập nhật keyword gợi ý!")
                                                    st.rerun(scope="fragment")
                                            except Exception as ex:
                                                st.error(f"Lỗi gợi ý: {ex}")

                            # Tự động dịch và tối ưu hóa keyword
                            opt_lang = "Vietnamese" if "Vietnamese" in proj.get("lang", "Vietnamese") or new_region == "Châu Á / Việt Nam" else "English"
                            new_kw = _translate_keyword_to_en(user_kw, lang=opt_lang) if user_kw else ""
                            if new_kw != user_kw:
                                st.caption(f"🇬🇧 Bản dịch/Tối ưu tiếng Anh: `{new_kw}`")
                            else:
                                new_kw = user_kw

                            # ── Auto-fetch footage tự động khi chưa có nền ────────────────────
                            _has_footage = (scene.get("videoUrl") or scene.get("imageUrl")
                                           or scene.get("customVid") or scene.get("customImg"))
                            _auto_done_key = f"auto_vid_done_{proj.get('id','')}{idx}"
                            _pexels_key_av = (cfg.get("pexels") or [None])[0]

                            if not _has_footage and new_kw and _pexels_key_av \
                                    and not st.session_state.get(_auto_done_key):
                                # Chưa fetch lần nào — tự động fetch ngay
                                _use_ai_auto = st.session_state.get("use_ai_images_confirm",
                                               st.session_state.get("use_ai_images_main", True))
                                _is_photo_scene = (idx > 0) and (idx % 3 == 2) and not _use_ai_auto
                                _opt_auto = optimize_query_for_region(new_kw, new_region)
                                with st.spinner(f"⚡ Đang tự chọn {'ảnh' if _is_photo_scene else 'video'} cho cảnh {idx+1}..."):
                                    try:
                                        if _is_photo_scene:
                                            _res_auto = search_pexels_photos_only(
                                                _opt_auto,
                                                orientation="portrait" if "9:16" in aspect else "landscape"
                                            )
                                        else:
                                            _res_auto = search_pexels_videos(
                                                _opt_auto,
                                                orientation="portrait" if "9:16" in aspect else "landscape"
                                            )
                                        _pick_auto = next((r for r in (_res_auto or []) if not r.get("already_used")), None)
                                        if not _pick_auto and _res_auto:
                                            _pick_auto = _res_auto[0]
                                        if _pick_auto:
                                            if _is_photo_scene:
                                                proj["scenes"][idx]["imageUrl"]  = _pick_auto["url"]
                                                proj["scenes"][idx]["videoUrl"]  = None
                                            else:
                                                proj["scenes"][idx]["videoUrl"]  = _pick_auto["url"]
                                                # Không ghi đè duration — ffmpeg cắt theo scene duration
                                                proj["scenes"][idx]["imageUrl"]  = None
                                            proj["scenes"][idx]["customVid"] = None
                                            proj["scenes"][idx]["customImg"] = None
                                            if "used_videos" not in cfg:
                                                cfg["used_videos"] = []
                                            if _pick_auto["url"] not in cfg["used_videos"]:
                                                cfg["used_videos"].append(_pick_auto["url"])
                                            save_cfg(cfg)
                                            save_proj(proj)
                                        # Đánh dấu đã fetch dù kết quả thế nào
                                        st.session_state[_auto_done_key] = True
                                        st.rerun(scope="fragment")
                                    except Exception as _ae:
                                        st.session_state[_auto_done_key] = True  # tránh loop lỗi

                            # ── Nút override thủ công (luôn hiện khi chưa có custom) ──────────
                            if not _has_footage:
                                _auto_col1, _auto_col2 = st.columns([1, 1])
                                with _auto_col1:
                                    if st.button("⚡ Auto-chọn Video (Pexels)", key=f"auto_vid_{idx}",
                                                  use_container_width=True,
                                                  help="Tìm lại và chọn video Pexels khác"):
                                        if new_kw and _pexels_key_av:
                                            with st.spinner(f"⚡ Đang chọn video cho cảnh {idx+1}..."):
                                                _opt = optimize_query_for_region(new_kw, new_region)
                                                _res = search_pexels_videos(_opt, orientation="portrait" if "9:16" in aspect else "landscape")
                                                _pick = next((r for r in (_res or []) if not r.get("already_used")), None) or (_res[0] if _res else None)
                                                if _pick:
                                                    proj["scenes"][idx]["videoUrl"] = _pick["url"]
                                                    # Không ghi đè duration — giữ duration từ text
                                                    proj["scenes"][idx]["imageUrl"] = proj["scenes"][idx]["customVid"] = proj["scenes"][idx]["customImg"] = None
                                                    if "used_videos" not in cfg: cfg["used_videos"] = []
                                                    if _pick["url"] not in cfg["used_videos"]: cfg["used_videos"].append(_pick["url"])
                                                    save_cfg(cfg); save_proj(proj)
                                                    st.session_state[_auto_done_key] = True
                                                    st.rerun(scope="fragment")
                                with _auto_col2:
                                    if st.button("⚡ Auto-chọn Ảnh (Pexels)", key=f"auto_img_{idx}",
                                                  use_container_width=True,
                                                  help="Tìm lại và chọn ảnh Pexels (Ken Burns)"):
                                        if new_kw and _pexels_key_av:
                                            with st.spinner(f"⚡ Đang chọn ảnh cho cảnh {idx+1}..."):
                                                _opt = optimize_query_for_region(new_kw, new_region)
                                                _res = search_pexels_photos_only(_opt, orientation="portrait" if "9:16" in aspect else "landscape")
                                                _pick = next((r for r in (_res or []) if not r.get("already_used")), None) or (_res[0] if _res else None)
                                                if _pick:
                                                    proj["scenes"][idx]["imageUrl"] = _pick["url"]
                                                    proj["scenes"][idx]["videoUrl"] = proj["scenes"][idx]["customVid"] = proj["scenes"][idx]["customImg"] = None
                                                    if "used_videos" not in cfg: cfg["used_videos"] = []
                                                    if _pick["url"] not in cfg["used_videos"]: cfg["used_videos"].append(_pick["url"])
                                                    save_cfg(cfg); save_proj(proj)
                                                    st.session_state[_auto_done_key] = True
                                                    st.rerun(scope="fragment")

                            # ── Chọn video từ máy — nằm ngoài tabs, luôn visible ──
                            with st.expander("📁 Dùng video từ máy", expanded=False):
                                _local_vid_scan_dirs = [
                                    Path.home() / "Documents" / "99999",
                                    Path.home() / "Desktop",
                                    Path.home() / "Downloads",
                                    Path.home() / "Movies",
                                ]
                                _local_vid_found = {"(Không chọn)": ""}
                                for _lvd in _local_vid_scan_dirs:
                                    if _lvd.exists():
                                        for _ext in ["*.mp4", "*.mov", "*.mkv", "*.avi"]:
                                            for _lvf in sorted(_lvd.glob(_ext)):
                                                _lv_label = f"{_lvf.name}  [{_lvd.name}/]"
                                                _local_vid_found[_lv_label] = str(_lvf)
                                _local_vid_opts = list(_local_vid_found.keys())
                                _lv_col1, _lv_col2 = st.columns([3, 1])
                                with _lv_col1:
                                    _local_vid_sel = st.selectbox(
                                        "📂 Chọn file video có sẵn:",
                                        _local_vid_opts,
                                        key=f"local_vid_sel_{idx}",
                                        help="Quét tự động: Documents/99999, Desktop, Downloads, Movies"
                                    )
                                    _local_vid_manual = st.text_input(
                                        "✏️ Hoặc dán đường dẫn file:",
                                        placeholder="/Users/you/Videos/myvideo.mp4",
                                        key=f"local_vid_path_{idx}"
                                    )
                                with _lv_col2:
                                    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                                    if st.button("✅ Áp dụng", key=f"apply_local_vid_{idx}", type="primary", use_container_width=True):
                                        _chosen_path = st.session_state.get(f"local_vid_path_{idx}", "").strip() or _local_vid_found.get(_local_vid_sel, "")
                                        if _chosen_path and Path(_chosen_path).exists():
                                            proj["scenes"][idx]["customVid"] = _chosen_path
                                            proj["scenes"][idx]["customImg"] = None
                                            proj["scenes"][idx]["imageUrl"]  = None
                                            proj["scenes"][idx]["videoUrl"]  = None
                                            # ── Probe duration nhanh: chỉ đọc metadata header, không decode ──
                                            try:
                                                _ffprobe = FFMPEG.replace("ffmpeg", "ffprobe")
                                                _probe = subprocess.run(
                                                    [_ffprobe, "-v", "error",
                                                     "-show_entries", "format=duration",
                                                     "-of", "default=noprint_wrappers=1:nokey=1",
                                                     _chosen_path],
                                                    capture_output=True, text=True, timeout=5
                                                )
                                                _dur_str = _probe.stdout.strip()
                                                if _dur_str and _dur_str not in ("N/A", ""):
                                                    proj["scenes"][idx]["duration"] = round(float(_dur_str))
                                            except Exception:
                                                pass  # giữ nguyên duration cũ nếu probe lỗi
                                            save_proj(proj)
                                            st.success(f"✅ Đã dùng: {Path(_chosen_path).name}")
                                            st.rerun(scope="fragment")
                                        else:
                                            st.error("❌ Không tìm thấy file — kiểm tra lại đường dẫn.")

                            tab_pexels_vid, tab_pixabay_vid, tab_coverr_vid, tab_pexels_photo, tab_pixabay_photo, tab_upload = st.tabs([
                                "📹 Pexels Video", "📹 Pixabay Video", "📹 Coverr Video",
                                "🖼️ Pexels Photo", "🖼️ Pixabay Photo", "📤 Upload"
                            ])

                            with tab_pexels_vid:
                                pexels_key = (cfg.get("pexels") or [None])[0]
                                if not pexels_key:
                                    st.warning("⚠️ Chưa cấu hình API Key Pexels. Hãy vào tab Settings để nhập key.")
                                else:
                                    st.markdown("**🔍 Tìm video trên Pexels:**")
                                    opt_kw = optimize_query_for_region(new_kw, new_region)
                                    if opt_kw != new_kw:
                                        st.caption(f"💡 Từ khóa tối ưu vùng miền: `{opt_kw}`")
                                    # Auto-search nếu chưa có kết quả và có keyword
                                    if st.session_state.get(f"pexels_vid_{idx}") is None and opt_kw:
                                        with st.spinner("🔍 Đang tìm Pexels Video tự động..."):
                                            st.session_state[f"pexels_vid_{idx}"] = search_pexels_videos(
                                                opt_kw,
                                                orientation="portrait" if "9:16" in aspect else "landscape"
                                            )
                                    if st.button("🔄 Tìm lại Pexels Video", key=f"search_pexels_btn_{idx}"):
                                        with st.spinner("Đang tìm video trên Pexels..."):
                                            st.session_state[f"pexels_vid_{idx}"] = search_pexels_videos(
                                                opt_kw,
                                                orientation="portrait" if "9:16" in aspect else "landscape"
                                            )

                                    pexels_vids = st.session_state.get(f"pexels_vid_{idx}", None)
                                    if pexels_vids is not None:
                                        if not pexels_vids:
                                            st.info("Không tìm thấy video nào trên Pexels với từ khóa này. Vui lòng kiểm tra lại từ khóa hoặc trạng thái API Key.")
                                        else:
                                            fresh_v = sum(1 for r in pexels_vids if not r.get("already_used"))
                                            st.caption(f"🆕 {fresh_v} video mới · ♻️ {len(pexels_vids)-fresh_v} đã dùng")
                                            cols = st.columns(3)
                                            for res_idx, res in enumerate(pexels_vids[:9]):
                                                with cols[res_idx % 3]:
                                                    img_url = res.get("image", "")
                                                    if img_url:
                                                        st.image(img_url, width="stretch")
                                                    used_badge = " ♻️" if res.get("already_used") else " 🆕"
                                                    st.caption(f"⏱️ {res['duration']}s{used_badge}")
                                                    if st.button("Chọn video", key=f"sel_pex_vid_{idx}_{res_idx}"):
                                                        proj["scenes"][idx]["videoUrl"] = res["url"]
                                                        proj["scenes"][idx]["customVid"] = None
                                                        proj["scenes"][idx]["imageUrl"] = None
                                                        proj["scenes"][idx]["customImg"] = None
                                                        # Không ghi đè duration — giữ duration từ text
                                                        if "used_videos" not in cfg:
                                                            cfg["used_videos"] = []
                                                        if res["url"] not in cfg["used_videos"]:
                                                            cfg["used_videos"].append(res["url"])
                                                            if len(cfg["used_videos"]) > 1000:
                                                                cfg["used_videos"].pop(0)
                                                        save_cfg(cfg)
                                                        edited = True
                                                        st.rerun(scope="fragment")

                            with tab_pixabay_vid:
                                pix_key = cfg.get("pixabay", "")
                                if not pix_key:
                                    st.warning("⚠️ Chưa cấu hình API Key Pixabay. Hãy vào tab Settings để nhập key.")
                                else:
                                    st.markdown("**🔍 Tìm video trên Pixabay:**")
                                    opt_kw = optimize_query_for_region(new_kw, new_region)
                                    if opt_kw != new_kw:
                                        st.caption(f"💡 Từ khóa tối ưu vùng miền: `{opt_kw}`")
                                    if st.session_state.get(f"pix_vid_{idx}") is None and opt_kw:
                                        with st.spinner("🔍 Đang tìm Pixabay Video tự động..."):
                                            st.session_state[f"pix_vid_{idx}"] = search_pixabay_videos(
                                                opt_kw,
                                                orientation="portrait" if "9:16" in aspect else "landscape"
                                            )
                                    if st.button("🔄 Tìm lại Pixabay Video", key=f"search_pix_btn_{idx}"):
                                        with st.spinner("Đang tìm video trên Pixabay..."):
                                            st.session_state[f"pix_vid_{idx}"] = search_pixabay_videos(
                                                opt_kw,
                                                orientation="portrait" if "9:16" in aspect else "landscape"
                                            )

                                    pix_vids = st.session_state.get(f"pix_vid_{idx}", None)
                                    if pix_vids is not None:
                                        if not pix_vids:
                                            st.info("Không tìm thấy video nào trên Pixabay với từ khóa này. Vui lòng kiểm tra lại từ khóa hoặc trạng thái API Key.")
                                        else:
                                            fresh_v = sum(1 for r in pix_vids if not r.get("already_used"))
                                            st.caption(f"🆕 {fresh_v} video mới · ♻️ {len(pix_vids)-fresh_v} đã dùng")
                                            cols = st.columns(3)
                                            for res_idx, res in enumerate(pix_vids[:9]):
                                                with cols[res_idx % 3]:
                                                    img_url = res.get("image", "")
                                                    if img_url:
                                                        st.image(img_url, width="stretch")
                                                    used_badge = " ♻️" if res.get("already_used") else " 🆕"
                                                    st.caption(f"⏱️ {res['duration']}s{used_badge}")
                                                    if st.button("Chọn video", key=f"sel_pix_vid_{idx}_{res_idx}"):
                                                        proj["scenes"][idx]["videoUrl"] = res["url"]
                                                        proj["scenes"][idx]["customVid"] = None
                                                        proj["scenes"][idx]["imageUrl"] = None
                                                        proj["scenes"][idx]["customImg"] = None
                                                        # Không ghi đè duration — giữ duration từ text
                                                        if "used_videos" not in cfg:
                                                            cfg["used_videos"] = []
                                                        if res["url"] not in cfg["used_videos"]:
                                                            cfg["used_videos"].append(res["url"])
                                                            if len(cfg["used_videos"]) > 1000:
                                                                cfg["used_videos"].pop(0)
                                                        save_cfg(cfg)
                                                        edited = True
                                                        st.rerun(scope="fragment")

                            with tab_coverr_vid:
                                st.markdown("**🔍 Tìm video trên Coverr (Free, không cần API key):**")
                                opt_kw = optimize_query_for_region(new_kw, new_region)
                                if opt_kw != new_kw:
                                    st.caption(f"💡 Từ khóa tối ưu vùng miền: `{opt_kw}`")
                                if st.session_state.get(f"cov_vid_{idx}") is None and opt_kw:
                                    with st.spinner("🔍 Đang tìm Coverr Video tự động..."):
                                        st.session_state[f"cov_vid_{idx}"] = search_coverr_videos(
                                            opt_kw,
                                            orientation="portrait" if "9:16" in aspect else "landscape"
                                        )
                                if st.button("🔄 Tìm lại Coverr Video", key=f"search_cov_btn_{idx}"):
                                    with st.spinner("Đang tìm video trên Coverr..."):
                                        st.session_state[f"cov_vid_{idx}"] = search_coverr_videos(
                                            opt_kw,
                                            orientation="portrait" if "9:16" in aspect else "landscape"
                                        )

                                cov_vids = st.session_state.get(f"cov_vid_{idx}", None)
                                if cov_vids is not None:
                                    if not cov_vids:
                                        st.info("Không tìm thấy video nào trên Coverr với từ khóa này.")
                                    else:
                                        fresh_v = sum(1 for r in cov_vids if not r.get("already_used"))
                                        st.caption(f"🆕 {fresh_v} video mới · ♻️ {len(cov_vids)-fresh_v} đã dùng")
                                        cols = st.columns(3)
                                        for res_idx, res in enumerate(cov_vids[:9]):
                                            with cols[res_idx % 3]:
                                                img_url = res.get("image", "")
                                                if img_url:
                                                    st.image(img_url, width="stretch")
                                                used_badge = " ♻️" if res.get("already_used") else " 🆕"
                                                st.caption(f"⏱️ {res['duration']}s{used_badge}")
                                                if st.button("Chọn video", key=f"sel_cov_vid_{idx}_{res_idx}"):
                                                    proj["scenes"][idx]["videoUrl"] = res["url"]
                                                    proj["scenes"][idx]["customVid"] = None
                                                    proj["scenes"][idx]["imageUrl"] = None
                                                    proj["scenes"][idx]["customImg"] = None
                                                    # Không ghi đè duration — giữ duration từ text
                                                    if "used_videos" not in cfg:
                                                        cfg["used_videos"] = []
                                                    if res["url"] not in cfg["used_videos"]:
                                                        cfg["used_videos"].append(res["url"])
                                                        if len(cfg["used_videos"]) > 1000:
                                                            cfg["used_videos"].pop(0)
                                                    save_cfg(cfg)
                                                    edited = True
                                                    st.rerun(scope="fragment")

                            with tab_pexels_photo:
                                pexels_key = (cfg.get("pexels") or [None])[0]
                                if not pexels_key:
                                    st.warning("⚠️ Chưa cấu hình API Key Pexels. Hãy vào tab Settings để nhập key.")
                                else:
                                    st.markdown("**🔍 Tìm ảnh trên Pexels (Hiệu ứng Động):**")
                                    opt_kw = optimize_query_for_region(new_kw, new_region)
                                    if opt_kw != new_kw:
                                        st.caption(f"💡 Từ khóa tối ưu vùng miền: `{opt_kw}`")
                                    if st.session_state.get(f"pex_img_{idx}") is None and opt_kw:
                                        with st.spinner("🔍 Đang tìm Pexels Photo tự động..."):
                                            st.session_state[f"pex_img_{idx}"] = search_pexels_photos_only(
                                                opt_kw,
                                                orientation="portrait" if "9:16" in aspect else "landscape"
                                            )
                                    if st.button("🔄 Tìm lại Pexels Photo", key=f"search_pex_img_btn_{idx}"):
                                        with st.spinner("Đang tìm ảnh trên Pexels..."):
                                            st.session_state[f"pex_img_{idx}"] = search_pexels_photos_only(
                                                opt_kw,
                                                orientation="portrait" if "9:16" in aspect else "landscape"
                                            )

                                    pex_imgs = st.session_state.get(f"pex_img_{idx}", None)
                                    if pex_imgs is not None:
                                        if not pex_imgs:
                                            st.info("Không tìm thấy ảnh nào trên Pexels với từ khóa này. Vui lòng kiểm tra lại từ khóa hoặc trạng thái API Key.")
                                        else:
                                            fresh_i = sum(1 for r in pex_imgs if not r.get("already_used"))
                                            st.caption(f"🆕 {fresh_i} ảnh mới · ♻️ {len(pex_imgs)-fresh_i} đã dùng")
                                            cols = st.columns(3)
                                            for res_idx, res in enumerate(pex_imgs[:9]):
                                                with cols[res_idx % 3]:
                                                    img_url = res.get("image", "")
                                                    if img_url:
                                                        st.image(img_url, width="stretch")
                                                    used_badge = " ♻️" if res.get("already_used") else " 🆕"
                                                    st.caption(f"📸 {res.get('photographer','')}{used_badge}")
                                                    if st.button("Chọn ảnh", key=f"sel_pex_img_{idx}_{res_idx}"):
                                                        proj["scenes"][idx]["imageUrl"] = res["url"]
                                                        proj["scenes"][idx]["customImg"] = None
                                                        proj["scenes"][idx]["videoUrl"] = None
                                                        proj["scenes"][idx]["customVid"] = None
                                                        if "used_videos" not in cfg:
                                                            cfg["used_videos"] = []
                                                        if res["url"] not in cfg["used_videos"]:
                                                            cfg["used_videos"].append(res["url"])
                                                            if len(cfg["used_videos"]) > 1000:
                                                                cfg["used_videos"].pop(0)
                                                        save_cfg(cfg)
                                                        edited = True
                                                        st.rerun(scope="fragment")

                            with tab_pixabay_photo:
                                pix_key = cfg.get("pixabay", "")
                                if not pix_key:
                                    st.warning("⚠️ Chưa cấu hình API Key Pixabay. Hãy vào tab Settings để nhập key.")
                                else:
                                    st.markdown("**🔍 Tìm ảnh trên Pixabay (Hiệu ứng Động):**")
                                    opt_kw = optimize_query_for_region(new_kw, new_region)
                                    if opt_kw != new_kw:
                                        st.caption(f"💡 Từ khóa tối ưu vùng miền: `{opt_kw}`")
                                    if st.session_state.get(f"pix_img_{idx}") is None and opt_kw:
                                        with st.spinner("🔍 Đang tìm Pixabay Photo tự động..."):
                                            st.session_state[f"pix_img_{idx}"] = search_pixabay_photos_only(
                                                opt_kw,
                                                orientation="portrait" if "9:16" in aspect else "landscape"
                                            )
                                    if st.button("🔄 Tìm lại Pixabay Photo", key=f"search_pix_img_btn_{idx}"):
                                        with st.spinner("Đang tìm ảnh trên Pixabay..."):
                                            st.session_state[f"pix_img_{idx}"] = search_pixabay_photos_only(
                                                opt_kw,
                                                orientation="portrait" if "9:16" in aspect else "landscape"
                                            )

                                    pix_imgs = st.session_state.get(f"pix_img_{idx}", None)
                                    if pix_imgs is not None:
                                        if not pix_imgs:
                                            st.info("Không tìm thấy ảnh nào trên Pixabay với từ khóa này. Vui lòng kiểm tra lại từ khóa hoặc trạng thái API Key.")
                                        else:
                                            fresh_i = sum(1 for r in pix_imgs if not r.get("already_used"))
                                            st.caption(f"🆕 {fresh_i} ảnh mới · ♻️ {len(pix_imgs)-fresh_i} đã dùng")
                                            cols = st.columns(3)
                                            for res_idx, res in enumerate(pix_imgs[:9]):
                                                with cols[res_idx % 3]:
                                                    img_url = res.get("image", "")
                                                    if img_url:
                                                        st.image(img_url, width="stretch")
                                                    used_badge = " ♻️" if res.get("already_used") else " 🆕"
                                                    st.caption(f"📸 {res.get('photographer','')}{used_badge}")
                                                    if st.button("Chọn ảnh", key=f"sel_pix_img_{idx}_{res_idx}"):
                                                        proj["scenes"][idx]["imageUrl"] = res["url"]
                                                        proj["scenes"][idx]["customImg"] = None
                                                        proj["scenes"][idx]["videoUrl"] = None
                                                        proj["scenes"][idx]["customVid"] = None
                                                        if "used_videos" not in cfg:
                                                            cfg["used_videos"] = []
                                                        if res["url"] not in cfg["used_videos"]:
                                                            cfg["used_videos"].append(res["url"])
                                                            if len(cfg["used_videos"]) > 1000:
                                                                cfg["used_videos"].pop(0)
                                                        save_cfg(cfg)
                                                        edited = True
                                                        st.rerun(scope="fragment")


                            with tab_upload:
                                st.markdown("**📤 Tải lên file của bạn (Ghi đè Stock):**")
                                up_vid = st.file_uploader("Upload Video (mp4, mov):", type=["mp4","mov"], key=f"up_{idx}")
                                up_img = st.file_uploader("Upload Ảnh (jpg, png, webp):", type=["jpg","jpeg","png","webp"], key=f"up_img_{idx}")


                                effect_labels = {
                                    None: "🎲 Ngẫu nhiên (Không lặp)",
                                    "zoom_in": "🔍 Zoom In (Từ xa lại gần)",
                                    "zoom_out": "🔎 Zoom Out (Từ gần ra xa)",
                                    "pan_right": "➡️ Pan Sang Phải",
                                    "pan_left": "⬅️ Pan Sang Trái",
                                    "pan_up": "⬆️ Pan Lên Trên",
                                    "pan_down": "⬇️ Pan Xuống Dưới",
                                }
                                effect_keys = list(effect_labels.keys())
                                curr_effect = scene.get("imageEffect", None)
                                curr_eff_idx = effect_keys.index(curr_effect) if curr_effect in effect_keys else 0
                                new_img_effect = st.selectbox(
                                    "🎨 Hiệu ứng chuyển động ảnh tải lên:",
                                    options=effect_keys,
                                    format_func=lambda x: effect_labels[x],
                                    index=curr_eff_idx,
                                    key=f"img_effect_{idx}"
                                )
                                if new_img_effect != scene.get("imageEffect"):
                                    proj["scenes"][idx]["imageEffect"] = new_img_effect
                                    edited = True
                        with col_right:
                            new_dur = st.number_input("⏱️ Thời lượng (giây):", min_value=1.0, max_value=300.0,
                                                       value=float(scene.get("duration") or 5.0),
                                                       step=0.1, key=f"rv_dur_{idx}")

                            st.markdown("**🎥 Nền hiện tại**")
                            has_any_video = False
                            # Hiển thị trạng thái: ảnh upload
                            if proj["scenes"][idx].get("customImg") and Path(proj["scenes"][idx]["customImg"]).exists():
                                st.success("🖼️ Dùng ảnh tải lên")
                                st.image(proj["scenes"][idx]["customImg"], width="stretch")
                                if st.button("Xóa ảnh tải lên", key=f"del_img_{idx}"):
                                    proj["scenes"][idx]["customImg"] = None
                                    edited = True
                                    st.rerun(scope="fragment")
                                has_any_video = True
                            # Ảnh stock đã chọn
                            elif scene.get("imageUrl"):
                                st.success("🖼️ Ảnh stock (hiệu ứng động)")
                                st.image(scene["imageUrl"], width="stretch")
                                if st.button("Xóa ảnh stock", key=f"del_img_url_{idx}"):
                                    proj["scenes"][idx]["imageUrl"] = None
                                    edited = True
                                    st.rerun(scope="fragment")
                                has_any_video = True
                            # Video upload / chọn từ máy
                            elif proj["scenes"][idx].get("customVid") and Path(proj["scenes"][idx]["customVid"]).exists():
                                st.success("🎥 Dùng video tải lên / từ máy")
                                _cv_path = proj["scenes"][idx]["customVid"]
                                try:
                                    st.video(_cv_path)
                                except Exception:
                                    st.caption(f"📄 `{Path(_cv_path).name}`")
                                if st.button("Xóa video tải lên", key=f"del_{idx}"):
                                    proj["scenes"][idx]["customVid"] = None
                                    edited = True
                                    st.rerun(scope="fragment")
                                has_any_video = True

                            elif scene.get("veo3Path") and Path(scene["veo3Path"]).is_file():
                                st.success("🤖 Video được tạo bằng Veo 3")
                                st.video(scene["veo3Path"])
                                if st.button("Xóa video Veo 3", key=f"del_veo3_{idx}"):
                                    proj["scenes"][idx]["veo3Path"] = None
                                    edited = True
                                    st.rerun(scope="fragment")
                                has_any_video = True
                            elif scene.get("videoUrl"):
                                st.success("🔗 Đã liên kết Video Stock")
                                st.video(scene.get("videoUrl"))
                                if st.button("Xóa liên kết video", key=f"del_url_{idx}"):
                                    proj["scenes"][idx]["videoUrl"] = None
                                    edited = True
                                    st.rerun(scope="fragment")
                                has_any_video = True
                            else:
                                st.warning("⚠️ Chưa chọn nền")
                                if scene.get("veo3Error"):
                                    st.error(f"Lần tạo Veo gần nhất lỗi: {scene['veo3Error']}")
                                # Gợi ý nhẹ về loại footage mặc định
                                _use_ai_right = st.session_state.get("use_ai_images_confirm",
                                               st.session_state.get("use_ai_images_main", True))
                                _is_mix_photo = (idx > 0) and (idx % 3 == 2) and not _use_ai_right
                                if _is_mix_photo:
                                    st.caption("↓ Hoặc để trống → tool tự dùng **ảnh stock** (xen kẽ)")
                                elif _use_ai_right:
                                    st.caption("↓ Hoặc để trống → tool tự tạo **AI Image**")
                                else:
                                    st.caption("↓ Hoặc để trống → tool tự tìm **video Pexels**")

                            # Đọc từ scene hiện tại làm default — tránh ghi đè khi widget không hiển thị
                            new_mode = scene.get("videoTrimMode", "start")
                            new_start = float(scene.get("videoTrimStart", 0.0))
                            if has_any_video:
                                st.markdown("---")
                                trim_options = {
                                    "start": "Đầu video (0s)",
                                    "middle": "Giữa video",
                                    "end": "Cuối video",
                                    "random": "Ngẫu nhiên",
                                    "custom": "Tự chọn giây bắt đầu"
                                }
                                curr_mode = scene.get("videoTrimMode", "start")
                                mode_keys = list(trim_options.keys())
                                default_idx = mode_keys.index(curr_mode) if curr_mode in mode_keys else 0
                                new_mode = st.selectbox(
                                    "✂️ Đoạn hiển thị video:",
                                    options=mode_keys,
                                    format_func=lambda x: trim_options[x],
                                    index=default_idx,
                                    key=f"trim_mode_{idx}"
                                )
                                if new_mode == "custom":
                                    curr_start = float(scene.get("videoTrimStart", 0.0))
                                    new_start = st.number_input(
                                        "⏱️ Giây bắt đầu cắt:",
                                        min_value=0.0,
                                        max_value=300.0,
                                        value=curr_start,
                                        step=0.5,
                                        key=f"trim_start_{idx}"
                                    )

                            # ── 🪝 HOOK 2 giây đầu (chỉ cảnh 1) ──────────────────────────────
                            if idx == 0:
                                st.markdown("---")
                                st.markdown("### 🪝 Hook 2 Giây Đầu — Giữ Chân Người Xem")
                                st.caption("Hiển thị chữ to nổi bật trong 2 giây đầu để giật mình khán giả. Để trống nếu không dùng.")
                                _hook_col1, _hook_col2 = st.columns(2)
                                with _hook_col1:
                                    _curr_hook_q = scene.get("hookQuestion", "")
                                    _new_hook_q = st.text_input(
                                        "❓ Câu hỏi sốc (dòng 1 — chữ to):",
                                        value=_curr_hook_q,
                                        key=f"hook_q_{idx}",
                                        placeholder="Ví dụ: Bạn có biết điều này?",
                                        help="Câu hỏi giật mình xuất hiện to ở đầu cảnh, kèm hiệu ứng zoom-flash"
                                    )
                                with _hook_col2:
                                    _curr_hook_b = scene.get("hookBigText", "")
                                    _new_hook_b = st.text_input(
                                        "🔥 Chữ nổi to (dòng 2 — màu vàng):",
                                        value=_curr_hook_b,
                                        key=f"hook_b_{idx}",
                                        placeholder="Ví dụ: SỰ THẬT KINH HOÀNG!",
                                        help="Chữ phụ màu vàng/đỏ in hoa, rung lắc nhẹ phía dưới câu hỏi"
                                    )
                                _hook_sfx_labels = {
                                    "none":      "🔇 Không có",
                                    "deep_hit":  "💥 Deep Hit (GIẬT MÌNH — khuyên dùng)",
                                    "whoosh":    "💨 Whoosh (chuyển cảnh nhanh)",
                                    "horror":    "😱 Horror Sting (rùng rợn)",
                                    "slam":      "🔔 Slam (mạnh, cứng)",
                                }
                                _curr_hook_sfx = scene.get("hookSfx", "deep_hit")
                                if _curr_hook_sfx not in _hook_sfx_labels: _curr_hook_sfx = "deep_hit"
                                _new_hook_sfx = st.selectbox(
                                    "🔊 Âm thanh giật mình đầu video:",
                                    options=list(_hook_sfx_labels.keys()),
                                    format_func=lambda x: _hook_sfx_labels[x],
                                    index=list(_hook_sfx_labels.keys()).index(_curr_hook_sfx),
                                    key=f"hook_sfx_{idx}",
                                    help="Âm thanh phát ngay đầu cảnh cùng lúc với chữ nổi để tạo cú sốc tâm lý"
                                )
                                if (_new_hook_q != scene.get("hookQuestion", "") or
                                    _new_hook_b != scene.get("hookBigText", "") or
                                    _new_hook_sfx != scene.get("hookSfx", "deep_hit")):
                                    proj["scenes"][idx]["hookQuestion"] = _new_hook_q
                                    proj["scenes"][idx]["hookBigText"] = _new_hook_b
                                    proj["scenes"][idx]["hookSfx"] = _new_hook_sfx
                                    edited = True

                            st.markdown("---")
                            # ── Sound Effect ──
                            sfx_labels = {
                                "none":     "🔇 Không có",
                                "whoosh":   "💨 Whoosh (chuyển cảnh nhanh)",
                                "click":    "🖱️ Click (chuyển slide)",
                                "chime":    "🔔 Chime (nhẹ nhàng)",
                                "deep_hit": "💥 Deep Hit (căng thẳng)",
                            }
                            curr_sfx = scene.get("soundEffect", "none")
                            if curr_sfx not in sfx_labels: curr_sfx = "none"
                            new_sfx = st.selectbox(
                                "🔊 Sound Effect (đầu cảnh):",
                                options=list(sfx_labels.keys()),
                                format_func=lambda x: sfx_labels[x],
                                index=list(sfx_labels.keys()).index(curr_sfx),
                                key=f"sfx_{idx}",
                                help="Thêm âm thanh ngắn vào đầu cảnh để tạo nhịp điệu"
                            )
                            if new_sfx != scene.get("soundEffect", "none"):
                                proj["scenes"][idx]["soundEffect"] = new_sfx
                                edited = True

                            # ── Intro Effect (cho video) ──
                            intro_labels = {
                                None:         "🎲 Tự động (ngẫu nhiên)",
                                "fade_in":    "⬛ Fade In (mờ vào)",
                                "zoom_punch": "🔍 Zoom Punch (phóng to nhanh)",
                                "none":       "⚡ Không có (cắt thẳng)",
                            }
                            curr_intro = scene.get("introEffect")
                            intro_keys = list(intro_labels.keys())
                            curr_intro_idx = intro_keys.index(curr_intro) if curr_intro in intro_keys else 0
                            new_intro = st.selectbox(
                                "✨ Intro Effect (video):",
                                options=intro_keys,
                                format_func=lambda x: intro_labels[x],
                                index=curr_intro_idx,
                                key=f"intro_{idx}",
                                help="Hiệu ứng khi video cảnh này bắt đầu phát"
                            )
                            if new_intro != scene.get("introEffect"):
                                proj["scenes"][idx]["introEffect"] = new_intro
                                edited = True

                            # ── Video Speed Control ──
                            _speed_opts = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
                            _speed_labels = {
                                0.25: "0.25x (rất chậm — cinematic)",
                                0.5:  "0.5x (chậm — lời đọc nhanh)",
                                0.75: "0.75x (hơi chậm)",
                                1.0:  "1.0x (bình thường)",
                                1.25: "1.25x (hơi nhanh)",
                                1.5:  "1.5x (nhanh)",
                                2.0:  "2.0x (rất nhanh — hyper)",
                            }
                            _curr_spd = float(scene.get("videoSpeed", 1.0))
                            if _curr_spd not in _speed_opts: _curr_spd = 1.0
                            _new_spd = st.select_slider(
                                "⚡ Tốc độ video nền:",
                                options=_speed_opts,
                                value=_curr_spd,
                                format_func=lambda x: _speed_labels[x],
                                key=f"vid_speed_{idx}",
                                help="Làm chậm video nền → người xem tập trung vào lời đọc hơn. Không ảnh hưởng TTS/âm thanh."
                            )
                            if _new_spd != scene.get("videoSpeed", 1.0):
                                proj["scenes"][idx]["videoSpeed"] = _new_spd
                                edited = True

                            # ── TTS Speed Control (per-scene reading speed) ──
                            _tts_rate_opts = ["0.8","0.9","1.0","1.1","1.2","1.3","1.4","1.5","1.6","1.7","1.8","2.0"]
                            # Giá trị hiện tại: ưu tiên tts_speed riêng cảnh → tốc độ chung dự án
                            _curr_sc_rate = scene.get("tts_speed") or tts_rate
                            if _curr_sc_rate not in _tts_rate_opts: _curr_sc_rate = tts_rate
                            _new_sc_rate = st.select_slider(
                                "🗣️ Tốc độ đọc cảnh này (TTS):",
                                options=_tts_rate_opts,
                                value=_curr_sc_rate,
                                key=f"sc_tts_speed_{idx}",
                                help=f"Điều chỉnh tốc độ đọc riêng cho cảnh này. Mặc định dùng tốc độ chung ({tts_rate}x). Thay đổi sẽ tạo lại audio khi render."
                            )
                            if _new_sc_rate != scene.get("tts_speed"):
                                # Nếu chọn đúng tốc độ chung → xóa trường tts_speed (để thừa kế)
                                if _new_sc_rate == tts_rate:
                                    proj["scenes"][idx].pop("tts_speed", None)
                                else:
                                    proj["scenes"][idx]["tts_speed"] = _new_sc_rate
                                # Xóa cache audio để render lại với tốc độ mới
                                proj["scenes"][idx].pop("audioFile", None)
                                proj["scenes"][idx].pop("audioDur", None)
                                proj["scenes"][idx].pop("audioCacheKey", None)
                                edited = True

                            # ── Nút Render đơn cảnh ─────────────────────────────────────────
                            st.markdown("---")
                            _rcol1, _rcol2 = st.columns([1, 1])
                            with _rcol1:
                                _btn_render_one = st.button(
                                    "⚡ Render cảnh này",
                                    key=f"btn_render_one_{idx}",
                                    use_container_width=True,
                                    help="Chỉ render lại cảnh này — không ảnh hưởng cảnh khác"
                                )
                            with _rcol2:
                                _btn_preview_one = st.button(
                                    "▶️ Preview cảnh này",
                                    key=f"btn_preview_one_{idx}",
                                    use_container_width=True,
                                    help="Xem video cảnh vừa render"
                                )

                            if _btn_render_one:
                                # Lưu thay đổi trước khi render
                                save_proj(proj)
                                _s = proj["scenes"][idx]
                                _proj_mode_slug_r = st.session_state.get("proj_mode", "main")
                                _work_r = TMP / f"proj_{_proj_mode_slug_r}"
                                _work_r.mkdir(exist_ok=True)
                                _s_dir_r = _work_r / f"s{idx}"
                                _s_dir_r.mkdir(exist_ok=True)

                                # Xóa hash cũ để buộc re-render
                                _hash_file_r = _s_dir_r / ".scene_hash"
                                if _hash_file_r.exists():
                                    _hash_file_r.unlink()

                                # Lấy cấu hình hiện tại
                                _cfg_r = load_cfg()
                                _aspect_r = proj.get("aspect", "9:16 (Shorts/TikTok)")
                                _W_r, _H_r = (1080, 1920) if "9:16" in _aspect_r else (1920, 1080)
                                _sub_style_r = proj.get("sub_style", "🟡 TikTok Yellow (Viral)")
                                _sub_checkbox_r = st.session_state.get(f"{_proj_mode_slug_r}_show_subtitles", True)
                                _srt_file_r_check = _s.get("srtFile", "")
                                _srt_exists_r = bool(_srt_file_r_check and Path(_srt_file_r_check).exists())
                                _show_sub_r = bool(_sub_checkbox_r and _srt_exists_r)
                                _enable_trans_r = proj.get("enable_transition", False)
                                _voice_r = proj.get("voice_cfg_key", "en-US")
                                _rate_r = proj.get("tts_rate", "1.0")

                                with st.spinner(f"⚡ Đang render cảnh {idx+1}..."):
                                    try:
                                        # Audio
                                        _src_audio_r = None
                                        _audio_file_r = _s.get("audioFile", "")
                                        if _audio_file_r and Path(_audio_file_r).exists():
                                            _src_audio_r = Path(_audio_file_r)

                                        if not is_valid_audio(_src_audio_r):
                                            st.error(
                                                f"Cảnh {idx+1} chưa có giọng đọc hợp lệ. "
                                                "Hãy tạo lại TTS trước khi render cảnh này."
                                            )
                                            st.stop()

                                        # Duration
                                        _dur_r = float(_s.get("duration") or 5.0)
                                        if _src_audio_r:
                                            try:
                                                _probe_r = subprocess.run(
                                                    [FFMPEG, "-i", str(_src_audio_r), "-f", "null", "-"],
                                                    capture_output=True, text=True
                                                )
                                                for _ln_r in _probe_r.stderr.split("\n"):
                                                    if "Duration:" in _ln_r:
                                                        _ts_r = _ln_r.split("Duration:")[1].split(",")[0].strip()
                                                        _hh_r, _mm_r, _ss_r = _ts_r.split(":")
                                                        _real_r = int(_hh_r)*3600 + int(_mm_r)*60 + float(_ss_r)
                                                        if _real_r > 0.5:
                                                            _dur_r = max(1.5, round(_real_r + 0.05, 2))
                                                        break
                                            except Exception:
                                                pass

                                        # Trim audio
                                        _audio_trim_r = _s_dir_r / "audio_trimmed.aac"
                                        if _src_audio_r and _src_audio_r.exists():
                                            ffmpeg("-i", str(_src_audio_r),
                                                   "-af", f"afade=t=in:st=0:d=0.035,apad=pad_dur={_dur_r}",
                                                   "-t", str(_dur_r),
                                                   "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k",
                                                   "-y", str(_audio_trim_r))
                                        else:
                                            st.error(f"Cảnh {idx+1} không có audio nguồn. Đã dừng render.")
                                            st.stop()

                                        # Visual source
                                        _vid_r = _s_dir_r / "video.mp4"
                                        _has_vid_r = False
                                        for _src_key in ["customImg", "imageUrl", "customVid", "veo3Path", "videoUrl"]:
                                            _sv = _s.get(_src_key, "")
                                            if not _sv:
                                                continue
                                            _sp = Path(_sv) if _sv.startswith("/") else None
                                            if _sp and _sp.exists():
                                                import shutil as _sh
                                                _sh.copy(_sp, _vid_r)
                                                _has_vid_r = _vid_r.stat().st_size > 5000
                                            elif _sv.startswith("http"):
                                                try:
                                                    download_url(_sv, str(_vid_r))
                                                    _has_vid_r = _vid_r.exists() and _vid_r.stat().st_size > 5000
                                                except Exception:
                                                    pass
                                            if _has_vid_r:
                                                break

                                        # FFmpeg render core
                                        _base_r = _s_dir_r / "base.mp4"
                                        _bg_speed_r = float(_s.get("videoSpeed", 1.0))
                                        if _bg_speed_r <= 0 or _bg_speed_r > 4.0: _bg_speed_r = 1.0
                                        _setpts_r = f",setpts={round(1.0/_bg_speed_r,4)}*PTS" if _bg_speed_r != 1.0 else ""
                                        _scale_r = f"fps=30,scale={_W_r}:{_H_r}:force_original_aspect_ratio=increase,crop={_W_r}:{_H_r}{_setpts_r}"

                                        if _has_vid_r:
                                            _is_img_r = is_image_file(str(_vid_r))
                                            if _is_img_r:
                                                _scale_r = make_image_effect_filter(_W_r, _H_r, _dur_r, effect=_s.get("imageEffect"))
                                                _vin_r = ["-i", str(_vid_r)]
                                            else:
                                                # Probe video duration to calculate start time for trim
                                                _vid_len_r = 0.0
                                                try:
                                                    _probe_v_r = subprocess.run(
                                                        [FFMPEG, "-i", str(_vid_r), "-f", "null", "-"],
                                                        capture_output=True, text=True
                                                    )
                                                    for _line_r in _probe_v_r.stderr.split("\n"):
                                                        if "Duration:" in _line_r:
                                                            _ts2_r = _line_r.split("Duration:")[1].split(",")[0].strip()
                                                            _hh2_r, _mm2_r, _ss2_r = _ts2_r.split(":")
                                                            _vid_len_r = int(_hh2_r)*3600 + int(_mm2_r)*60 + float(_ss2_r)
                                                            break
                                                except Exception:
                                                    _vid_len_r = _dur_r

                                                _trim_mode_r = _s.get("videoTrimMode") or "random"
                                                _start_time_r = 0.0
                                                if _vid_len_r > _dur_r:
                                                    if _trim_mode_r == "middle":
                                                        _start_time_r = max(0.0, (_vid_len_r - _dur_r) / 2.0)
                                                    elif _trim_mode_r == "end":
                                                        _start_time_r = max(0.0, _vid_len_r - _dur_r)
                                                    elif _trim_mode_r == "random":
                                                        _max_start_r = max(0.0, _vid_len_r - _dur_r)
                                                        _start_time_r = random.uniform(0.0, min(_max_start_r, _vid_len_r * 0.6))
                                                    elif _trim_mode_r == "custom":
                                                        _cs_r = float(_s.get("videoTrimStart", 0.0))
                                                        _start_time_r = min(_cs_r, max(0.0, _vid_len_r - _dur_r))
                                                    else: # "start"
                                                        _start_time_r = 0.0

                                                if _vid_len_r > 0 and _vid_len_r < _dur_r:
                                                    _vin_r = ["-stream_loop", "-1", "-i", str(_vid_r)]
                                                else:
                                                    _vin_r = ["-ss", str(_start_time_r), "-i", str(_vid_r)]
                                            _cmd_r = _vin_r + [
                                                "-i", str(_audio_trim_r),
                                                "-vf", _scale_r, "-t", str(_dur_r),
                                                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                                                "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                                                "-af", f"apad=whole_dur={_dur_r}",
                                                "-map", "0:v", "-map", "1:a", "-y", str(_base_r)
                                            ]
                                        else:
                                            _black_r = f"color=c=black:s={_W_r}x{_H_r}:r=30"
                                            _cmd_r = [
                                                "-f","lavfi","-i",_black_r,"-i",str(_audio_trim_r),
                                                "-t",str(_dur_r),"-c:v","libx264","-preset","fast","-crf","22",
                                                "-c:a","aac","-b:a","128k","-ar","44100",
                                                "-af",f"apad=whole_dur={_dur_r}",
                                                "-map","0:v","-map","1:a","-y",str(_base_r)
                                            ]
                                        ffmpeg(*_cmd_r)

                                        # Subtitle
                                        _out_r = _s_dir_r / "scene.mp4"
                                        _srt_r = _s.get("srtFile")
                                        _has_srt_r = False

                                        # Nếu srtFile chưa có nhưng checkbox bật → tự tạo SRT từ audio
                                        if _sub_checkbox_r and HAS_SUB and _src_audio_r and not _srt_exists_r:
                                            _auto_srt_r = _s_dir_r / "auto.srt"
                                            try:
                                                srt_from_audio(str(_src_audio_r), _s.get("text", ""), str(_auto_srt_r), tts_rate=_rate_r)
                                                if _auto_srt_r.exists() and _auto_srt_r.stat().st_size > 10:
                                                    _srt_r = str(_auto_srt_r)
                                                    _show_sub_r = True
                                            except Exception as _srt_gen_e:
                                                st.warning(f"Không tạo được SRT: {_srt_gen_e}")

                                        if _show_sub_r and HAS_SUB and _srt_r and Path(_srt_r).exists():
                                            try:
                                                _wl_r = srt_to_words(_srt_r)
                                                if _wl_r:
                                                    _ass_c = make_ass(_wl_r, W=_W_r, H=_H_r, style_name=_sub_style_r)
                                                    _ass_r = _s_dir_r / "sub.ass"
                                                    _ass_r.write_text(_ass_c, encoding="utf-8")
                                                    _p_r = str(_ass_r).replace("\\", "\\\\").replace(":", "\\:")
                                                    ffmpeg("-i", str(_base_r), "-vf", f"ass='{_p_r}'",
                                                           "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                                                           "-c:a", "copy", "-y", str(_out_r))
                                                    _has_srt_r = True
                                            except Exception as _se_r:
                                                st.warning(f"Sub lỗi: {_se_r}")

                                        if not _has_srt_r:
                                            if _base_r.exists():
                                                import shutil as _sh2
                                                _sh2.copy(_base_r, _out_r)

                                        # ── 🪝 Hook Overlay (đơn cảnh, idx==0) ──────────────────
                                        if idx == 0:
                                            _hk_q_r = _s.get("hookQuestion", "").strip()
                                            _hk_b_r = _s.get("hookBigText", "").strip()
                                            _hk_sfx_r = _s.get("hookSfx", "none")
                                            if (_hk_q_r or _hk_b_r) and _out_r.exists():
                                                try:
                                                    import shutil as _sh_hk
                                                    _fc_r = [
                                                        "/Library/Fonts/Arial Bold.ttf",
                                                        "/Library/Fonts/Arial.ttf",
                                                        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                                                        "/System/Library/Fonts/Supplemental/Arial.ttf",
                                                        "/System/Library/Fonts/Helvetica.ttc",
                                                    ]
                                                    _fp_font = next((f for f in _fc_r if Path(f).exists()), None)
                                                    _fa_r = f":fontfile='{_fp_font}'" if _fp_font else ""
                                                    _q_y_r = int(_H_r * 0.30)
                                                    _b_y_r = int(_H_r * 0.55)
                                                    _alp_r = ("if(lt(t,0.3), t/0.3,"
                                                               " if(lt(t,1.7), 1.0,"
                                                               " if(lt(t,2.0), (2.0-t)/0.3, 0)))")
                                                    _vfp_r = []
                                                    if _hk_q_r:
                                                        _sq_r = _hk_q_r.replace("'","\\'").replace(":","\\:")
                                                        _vfp_r.append(
                                                            f"drawtext=text='{_sq_r}'{_fa_r}"
                                                            f":fontsize={int(_W_r*0.082)}:fontcolor=white"
                                                            f":bordercolor=black:borderw=4"
                                                            f":x=(w-text_w)/2:y={_q_y_r}"
                                                            f":alpha='{_alp_r}':enable='lt(t,2.0)'"
                                                        )
                                                    if _hk_b_r:
                                                        _sb_r = _hk_b_r.replace("'","\\'").replace(":","\\:")
                                                        _vfp_r.append(
                                                            f"drawtext=text='{_sb_r}'{_fa_r}"
                                                            f":fontsize={int(_W_r*0.065)}:fontcolor=yellow"
                                                            f":bordercolor=red:borderw=3"
                                                            f":x=(w-text_w)/2:y={_b_y_r}"
                                                            f":alpha='{_alp_r}':enable='lt(t,2.0)'"
                                                        )
                                                    _hk_tmp_r = _s_dir_r / "scene_hook_r.mp4"
                                                    ffmpeg("-i", str(_out_r),
                                                           "-vf", ",".join(_vfp_r),
                                                           "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                                                           "-c:a", "copy", "-y", str(_hk_tmp_r))
                                                    if _hk_tmp_r.exists() and _hk_tmp_r.stat().st_size > 10000:
                                                        _sh_hk.move(str(_hk_tmp_r), str(_out_r))
                                                    if _hk_sfx_r and _hk_sfx_r != "none":
                                                        _smap_r = {"horror": "deep_hit", "slam": "deep_hit"}
                                                        _res_sfx_r = _smap_r.get(_hk_sfx_r, _hk_sfx_r)
                                                        if _res_sfx_r in ("deep_hit", "whoosh", "click", "chime"):
                                                            _hsfx_tmp = _s_dir_r / "scene_hsfx_r.mp4"
                                                            if apply_sound_effect_to_scene(_out_r, _res_sfx_r, _hsfx_tmp):
                                                                _sh_hk.move(str(_hsfx_tmp), str(_out_r))
                                                except Exception as _hke_r:
                                                    st.warning(f"Hook overlay lỗi: {_hke_r}")

                                        # Ghi hash cache
                                        import hashlib as _hcr
                                        _fp_r = "|".join([
                                            _s.get("text",""), str(_s.get("audioFile","")),
                                            str(_s.get("videoUrl","")), str(_s.get("imageUrl","")),
                                            str(_s.get("customVid","")), str(_s.get("customImg","")),
                                            str(_s.get("veo3Path","")), str(_s.get("duration","")),
                                            str(_s.get("videoSpeed",1.0)), str(_s.get("imageEffect","")),
                                            str(_s.get("introEffect","")), str(_s.get("soundEffect","")),
                                            str(_s.get("videoTrimMode","")), str(_s.get("videoTrimStart",0.0)),
                                            str(_show_sub_r), str(_sub_style_r), str(_enable_trans_r),
                                            str(_W_r), str(_H_r), str(_voice_r), str(_rate_r),
                                            str(_s.get("tts_speed", "")),
                                            str(_s.get("hookQuestion", "")),
                                            str(_s.get("hookBigText", "")),
                                            str(_s.get("hookSfx", "")),
                                        ])
                                        _hash_file_r.write_text(_hcr.md5(_fp_r.encode()).hexdigest()[:16])

                                        if _out_r.exists() and _out_r.stat().st_size > 10000:
                                            st.success(f"✅ Render cảnh {idx+1} xong! ({_out_r.stat().st_size//1024}KB)")
                                            st.session_state[f"preview_scene_{idx}"] = str(_out_r)
                                        else:
                                            st.error("❌ Render thất bại — file không tạo được")
                                    except Exception as _re:
                                        st.error(f"❌ Lỗi render: {_re}")

                            if _btn_preview_one or st.session_state.get(f"preview_scene_{idx}"):
                                _preview_path = st.session_state.get(f"preview_scene_{idx}")
                                if not _preview_path:
                                    _proj_mode_slug_p = st.session_state.get("proj_mode", "main")
                                    _preview_path = str(TMP / f"proj_{_proj_mode_slug_p}" / f"s{idx}" / "scene.mp4")
                                if _preview_path and Path(_preview_path).exists():
                                    st.video(_preview_path)
                                else:
                                    st.info("Chưa có video — nhấn '⚡ Render cảnh này' trước")
                            st.markdown("---")
                            # ────────────────────────────────────────────────────────────────

                            completed = st.checkbox("✅ Đã duyệt xong cảnh này", value=bool(scene.get("completed", False)), key=f"comp_{idx}")

                            # Next and save button
                            if view_mode == "Tập trung (Mượt nhất)":
                                st.button(
                                    "💾 Lưu & Sang cảnh tiếp ▶", 
                                    key=f"next_btn_{idx}", 
                                    width="stretch",
                                    on_click=save_and_next_scene,
                                    args=(
                                        idx,
                                        new_text,
                                        new_kw,
                                        new_dur,
                                        new_mode,
                                        new_start if new_mode == "custom" else 0.0
                                    )
                                )

                            # ── Badge số cảnh cuối khung ──
                            st.markdown(
                                f"<div style='text-align:center;color:#555;font-size:12px;margin-top:8px'>"
                                f"— CẢNH {idx+1} / {total_scenes} —"
                                f"</div>",
                                unsafe_allow_html=True,
                            )

                        if (new_text != scene.get('text') or 
                            new_kw != scene.get('keyword') or 
                            new_dur != scene.get('duration') or 
                            (has_any_video and new_mode != scene.get('videoTrimMode', 'start')) or
                            (has_any_video and new_mode == 'custom' and new_start != scene.get('videoTrimStart', 0.0)) or
                            completed != scene.get('completed', False)):

                            proj["scenes"][idx]["text"] = new_text
                            proj["scenes"][idx]["keyword"] = new_kw
                            proj["scenes"][idx]["duration"] = new_dur
                            # Chỉ cập nhật trim settings khi widget thực sự được hiển thị (has_any_video)
                            # Tránh ghi đè setting 'custom' bằng default 'start' khi không có video
                            if has_any_video:
                                proj["scenes"][idx]["videoTrimMode"] = new_mode
                                proj["scenes"][idx]["videoTrimStart"] = new_start if new_mode == "custom" else 0.0
                            proj["scenes"][idx]["completed"] = completed
                            edited = True

                        if up_vid:
                            custom_path = AUDIO_DIR / f"custom_{idx}_{up_vid.name}"
                            if not custom_path.exists() or custom_path.stat().st_size != up_vid.size:
                                custom_path.write_bytes(up_vid.read())

                            dur_seconds = 10
                            try:
                                probe = subprocess.run(
                                    [FFMPEG, "-i", str(custom_path), "-f", "null", "-"],
                                    capture_output=True, text=True
                                )
                                for line in probe.stderr.split("\n"):
                                    if "Duration:" in line:
                                        ts = line.split("Duration:")[1].split(",")[0].strip()
                                        h, m, s = ts.split(":")
                                        dur_seconds = int(h)*3600 + int(m)*60 + float(s)
                                        break
                            except Exception as pe:
                                print(f"[Probe] Lỗi: {pe}")

                            if proj["scenes"][idx].get("customVid") != str(custom_path):
                                proj["scenes"][idx]["customVid"] = str(custom_path)
                                proj["scenes"][idx]["customImg"] = None
                                proj["scenes"][idx]["imageUrl"] = None
                                proj["scenes"][idx]["duration"] = round(dur_seconds)
                                edited = True
                                st.rerun(scope="fragment")

                        # ── Xử lý upload ảnh thủ công (lấy từ widget key trong tab_img) ──
                        up_img_key = f"up_img_{idx}"
                        up_img_file = st.session_state.get(up_img_key)
                        if up_img_file is not None:
                            img_path = AUDIO_DIR / f"custom_img_{idx}_{up_img_file.name}"
                            if not img_path.exists() or img_path.stat().st_size != up_img_file.size:
                                img_path.write_bytes(up_img_file.read())
                            if proj["scenes"][idx].get("customImg") != str(img_path):
                                proj["scenes"][idx]["customImg"] = str(img_path)
                                proj["scenes"][idx]["imageUrl"] = None
                                proj["scenes"][idx]["videoUrl"] = None
                                proj["scenes"][idx]["customVid"] = None
                                edited = True
                                st.rerun(scope="fragment")


            if edited:
                save_proj(proj)
                st.success("Đã lưu các thay đổi của bạn!")


            _meta = proj.get("script", {}) if isinstance(proj.get("script"), dict) else {}
            if _meta.get("tags"):
                st.write(" ".join(f"`#{t}`" for t in _meta["tags"]))

            c1, c2 = st.columns(2)
            c1.button("📋 Copy title", on_click=lambda: None)
            if c2.button("📄 Tải metadata"):
                txt = f"TITLE:\n{_meta.get('title','')}\n\nDESCRIPTION:\n{_meta.get('description','')}\n\nTAGS:\n{' '.join('#'+t for t in _meta.get('tags',[]))}\n\nSCRIPT:\n"
                txt += "\n\n".join(f"[Cảnh {i+1}]\n{sc.get('text','')}" for i, sc in enumerate(proj.get("scenes", [])))
                st.download_button("⬇️ metadata.txt", txt, "youtube_meta.txt", "text/plain")



        _scene_editor_fragment()

        if proj.get("finalPath") and Path(proj["finalPath"]).exists():
            st.divider()
            file_name = proj.get("fileName", "ai_video.mp4")
            final_path = Path(proj["finalPath"])
            size_mb = final_path.stat().st_size / 1024 / 1024

            st.success(f"🎉 Video hoàn tất! ({size_mb:.1f} MB)")
            st.info(f"📂 File lưu tại: `{final_path}`")

            video_bytes = final_path.read_bytes()
            if _SOCIAL_PUBLISHING_OK:
                render_post_render_publish(
                    st,
                    _SOCIAL_STORE,
                    str(final_path),
                    proj.get("script", {}),
                    key_prefix=f"pipeline_{proj.get('id', 'current')}",
                )
            else:
                st.video(video_bytes)

            # Download button with proper .mp4 filename
            st.download_button(
                label=f"⬇️ Tải xuống {file_name}",
                data=video_bytes,
                file_name=file_name,
                mime="video/mp4",
                width="stretch",
            )
            st.caption(f"Hoặc mở thẳng tại: `{final_path}`")

        elif proj.get("step",0) == 0 and not run_all:
            st.info("👈 Chọn cấu hình bên trái và bấm **Bắt Đầu Tự Động**\n\nSettings → thêm API keys trước")


    # ════════════════════════════════════════════════════════════
    # VIDEO DÀI TAB — standalone, không đụng proj/Pipeline cũ
    # ════════════════════════════════════════════════════════════
