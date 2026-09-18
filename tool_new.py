"""
AI Video Creator — Refactored Entry Point
Chạy: streamlit run tool_new.py

Đây là phiên bản mới của tool.py, được tổ chức lại thành các module trong app/.
"""
import streamlit as st

# ── Page config (PHẢI gọi TRƯỚC mọi import streamlit khác) ───────────────────
st.set_page_config(page_title="AI Video Creator", page_icon="🎬", layout="wide")

# ── Standard imports ─────────────────────────────────────────────────────────
import json, os, re, uuid, base64, subprocess, shutil, time, tempfile, random, math
from typing import Optional
from pathlib import Path
import requests

# ── Third-party helper modules ────────────────────────────────────────────────
from vietnamese_tts import normalize_vietnamese_tts
from korean_tts import normalize_korean_tts
from video_config import normalize_import_video_config
from secret_config import ENV_FILE, SECRET_ENV_MAP, extract_legacy_secrets, load_secrets, save_secrets

# ── App modules ───────────────────────────────────────────────────────────────
from app.config import (
    FFMPEG, TMP, AUDIO_DIR,
    load_cfg, save_cfg,
    output_file_stem, available_output_path,
)
from app.project import load_proj, save_proj, get_proj_file
from app.ai_client import (
    call_ai, call_ai_script, call_gemini, call_groq_llm, call_openai,
    parse_json_robust, reset_groq_cache,
)
from app.tts_engine import (
    tts, srt_from_audio, tts_edge_with_timing, tts_edge,
    EDGE_VOICES, KOREAN_EDGE_VOICES,
)
from app.subtitle import make_srt, make_ass, srt_to_words, SUB_STYLES
from app.media_fetch import (
    fetch_stock_video, fetch_stock_photo,
    fetch_pexels, fetch_coverr, fetch_pixabay,
    search_pexels_videos, search_pixabay_videos, search_coverr_videos,
    search_pexels_photos_only, search_pixabay_photos_only,
    search_stock_photos, search_stock_videos,
    clean_keyword, enrich_keyword_with_context, inject_region_into_keyword,
    optimize_query_for_region, is_image_file,
    _translate_keyword_to_en,
)
from app.veo3_media import (
    build_veo3_prompt, build_visual_prompts_batch,
    fetch_video_with_veo3, generate_scene_video_with_veo3,
    attach_veo3_video, VEO3_PROMPT_TEMPLATE,
)
from app.image_gen import (
    generate_thumbnail, generate_thumbnail_openai, generate_scene_image_ai,
)
from app.effects import (
    make_image_effect_filter, make_video_intro_filter,
    apply_sound_effect_to_scene,
    IMAGE_EFFECTS, VIDEO_INTRO_EFFECTS, SOUND_EFFECTS,
)
from app.ffmpeg_utils import (
    ffmpeg, has_subtitles_filter, probe_audio_duration, download_url,
    is_valid_audio,
)
from app.ui.styles import inject_styles
from app.ui.helpers import save_and_next_scene

# ── Optional modules (social publishing, CapCut, ZeroTTS, Veo3, Creative) ────
_SOCIAL_PUBLISHING_OK = False
_SOCIAL_STORE = None
_SOCIAL_WORKER = None
render_connection_settings = lambda *a, **kw: None
render_post_render_publish = lambda *a, **kw: None
render_social_publish_ui = lambda *a, **kw: None

try:
    from social_publisher import PublishWorker, SocialStore
    from social_publisher_ui import (
        render_connection_settings,
        render_post_render_publish,
        render_publish_tab as render_social_publish_ui,
    )
    _SOCIAL_PUBLISHING_OK = True
except Exception as _e:
    print(f"[social] Module not loaded: {_e}")

_CAPCUT_OK = False
_cc = None
try:
    import capcut_tts as _cc
    _CAPCUT_OK = _cc.is_available()
    if not _CAPCUT_OK:
        print(f"[tool] CapCut TTS loaded nhưng not available: {_cc._CC_IMPORT_ERR}")
except Exception as _cce:
    import traceback as _cce_tb
    print(f"[tool] CapCut TTS not loaded: {_cce}")
    _cce_tb.print_exc()

_ZEROTTS_OK = False
_zt = None
try:
    import zerotts_adapter as _zt
    _ZEROTTS_OK = _zt.is_available()
    if not _ZEROTTS_OK:
        print(f"[tool] ZeroTTS loaded nhưng not available: {_zt._ZEROTTS_IMPORT_ERR}")
except Exception as _zte:
    print(f"[tool] ZeroTTS not loaded: {_zte}")

_VEO3_OK = False
_veo3 = None
try:
    import veo3_video as _veo3
    _VEO3_OK = True
except Exception as _ve:
    print(f"[tool] Veo3 module not loaded: {_ve}")

_CREATIVE_OK = False
_creative = None
try:
    import creative_studio as _creative
    import importlib as _importlib, inspect as _inspect
    if "veo_engine" not in _inspect.signature(_creative.render_creative_studio).parameters:
        _creative = _importlib.reload(_creative)
    _CREATIVE_OK = True
except Exception as _creative_error:
    print(f"[tool] Creative Studio not loaded: {_creative_error}")

# ── Social runtime (durable per Streamlit process) ────────────────────────────
if _SOCIAL_PUBLISHING_OK:
    @st.cache_resource
    def _get_social_runtime():
        store = SocialStore()
        worker = PublishWorker(store).start()
        return store, worker
    try:
        _SOCIAL_STORE, _SOCIAL_WORKER = _get_social_runtime()
    except Exception as _social_err:
        _SOCIAL_PUBLISHING_OK = False
        print(f"[social] Runtime not started: {_social_err}")

# ── Session state init ────────────────────────────────────────────────────────
if "cfg" not in st.session_state:
    st.session_state.cfg = load_cfg()
if "proj_mode" not in st.session_state:
    st.session_state.proj_mode = st.session_state.cfg.get("last_proj_mode", "main")
if "proj" not in st.session_state:
    st.session_state.proj = load_proj()

cfg = st.session_state.cfg
proj = st.session_state.proj

# ── FFmpeg status ─────────────────────────────────────────────────────────────
HAS_SUB = has_subtitles_filter()

# ── TTS wrapper (injects context from session_state) ─────────────────────────
def _tts_wrapper(text, voice_cfg="en-US", srt_out=None, rate="1.0", allow_edge_fallback=True):
    """TTS dispatcher với context từ session_state."""
    return tts(
        text=text, voice_cfg=voice_cfg, srt_out=srt_out, rate=rate,
        allow_edge_fallback=allow_edge_fallback,
        cfg=cfg,
        capcut_ok=_CAPCUT_OK, capcut_module=_cc,
        zerotts_ok=_ZEROTTS_OK, zerotts_module=_zt,
    )

# ── Backward-compat wrappers injecting cfg ────────────────────────────────────
def _call_ai(prompt):
    return call_ai(prompt, cfg)

def _call_ai_script(prompt):
    return call_ai_script(prompt, cfg)

def _fetch_stock_video(keyword, orientation="landscape", used_urls=None):
    return fetch_stock_video(keyword, orientation=orientation, used_urls=used_urls, cfg=cfg)

def _fetch_stock_photo(keyword, orientation="landscape", used_urls=None):
    return fetch_stock_photo(keyword, orientation=orientation, used_urls=used_urls, cfg=cfg)

def _search_stock_videos(keyword, orientation="landscape"):
    return search_stock_videos(keyword, orientation=orientation, cfg=cfg)

def _search_stock_photos(keyword, orientation="landscape"):
    return search_stock_photos(keyword, orientation=orientation, cfg=cfg)

def _fetch_video_with_veo3(keyword, orientation="landscape", used_urls=None, scene_text="",
                            log_cb=None, force_veo3=False, veo3_prompt=""):
    return fetch_video_with_veo3(
        keyword=keyword, orientation=orientation, used_urls=used_urls,
        scene_text=scene_text, log_cb=log_cb, force_veo3=force_veo3,
        veo3_prompt=veo3_prompt, cfg=cfg, veo3_ok=_VEO3_OK, veo3_module=_veo3,
    )

def _generate_thumbnail(script, gemini_key, W, H, save_dir=None):
    oai_key = cfg.get("openai", "") or None
    return generate_thumbnail(script, gemini_key, W, H, save_dir=save_dir, openai_key=oai_key)

def _build_visual_prompts_batch(scenes, lang, log_cb=None):
    return build_visual_prompts_batch(scenes, lang, cfg=cfg, log_cb=log_cb)

def _clean_keyword(kw, lang=""):
    return clean_keyword(kw, lang=lang, cfg=cfg)

def _translate_kw(kw, lang=""):
    return _translate_keyword_to_en(kw, lang=lang, cfg=cfg)

def _generate_scene_image_ai(keyword, gemini_key, W, H, save_path, image_prompt=""):
    return generate_scene_image_ai(keyword, gemini_key, W, H, save_path, image_prompt)

def _generate_scene_video_with_veo3(scene, video_cfg, orientation="landscape", log_cb=None):
    return generate_scene_video_with_veo3(
        scene=scene, video_cfg=video_cfg, orientation=orientation, log_cb=log_cb,
        veo3_ok=_VEO3_OK, veo3_module=_veo3,
    )

def _srt_from_audio(audio_path, text, srt_path, tts_rate="1.0"):
    return srt_from_audio(audio_path, text, srt_path, tts_rate)

def _save_and_next_scene(idx_val, n_text, n_kw, n_dur, n_mode, n_start=0.0):
    return save_and_next_scene(idx_val, n_text, n_kw, n_dur, n_mode, n_start)

# ── UI ────────────────────────────────────────────────────────────────────────
inject_styles()

tab_main, tab_slide_v2, tab_creative, tab_longvideo, tab_shortvideo, tab_publish, tab_settings = st.tabs(
    ["🎬 Pipeline", "🎞️ Slide v2", "🎨 Creative Studio", "📹 Video Dài", "⚡ Video Ngắn", "📣 Xuất bản", "⚙️ Settings"]
)

# ════════════════════════════════════════════════════════════
# SETTINGS TAB
# ════════════════════════════════════════════════════════════
from app.ui.tab_settings import render_settings_tab
with tab_settings:
    render_settings_tab(
        cfg=cfg, save_cfg=save_cfg,
        _VEO3_OK=_VEO3_OK, _veo3=_veo3,
        _SOCIAL_PUBLISHING_OK=_SOCIAL_PUBLISHING_OK,
        _SOCIAL_STORE=_SOCIAL_STORE,
        render_connection_settings=render_connection_settings,
        reset_groq_cache=reset_groq_cache,
        ENV_FILE=ENV_FILE,
        FFMPEG=FFMPEG,
    )

# ════════════════════════════════════════════════════════════
# SLIDE V2 TAB
# ════════════════════════════════════════════════════════════
from app.ui.tab_slide_v2 import render_slide_v2_tab
with tab_slide_v2:
    render_slide_v2_tab(
        cfg=cfg, save_cfg=save_cfg,
        FFMPEG=FFMPEG, ffmpeg=ffmpeg, tts=_tts_wrapper,
        TMP=TMP, AUDIO_DIR=AUDIO_DIR,
        load_proj=load_proj, save_proj=save_proj,
        EDGE_VOICES=EDGE_VOICES, KOREAN_EDGE_VOICES=KOREAN_EDGE_VOICES,
        SUB_STYLES=SUB_STYLES, HAS_SUB=HAS_SUB,
        _ZEROTTS_OK=_ZEROTTS_OK, _zt=_zt,
        _CAPCUT_OK=_CAPCUT_OK, _cc=_cc,
        generate_scene_image_ai=_generate_scene_image_ai,
    )

# ════════════════════════════════════════════════════════════
# PIPELINE TAB (lớn nhất — 5000+ dòng)
# ════════════════════════════════════════════════════════════
from app.ui.tab_pipeline import render_pipeline_tab
with tab_main:
    render_pipeline_tab(
        cfg=cfg, save_cfg=save_cfg,
        load_proj=load_proj, save_proj=save_proj,
        tts=_tts_wrapper, ffmpeg=ffmpeg, FFMPEG=FFMPEG,
        call_ai=_call_ai, call_ai_script=_call_ai_script,
        parse_json_robust=parse_json_robust,
        fetch_stock_video=_fetch_stock_video,
        fetch_video_with_veo3=_fetch_video_with_veo3,
        search_stock_videos=_search_stock_videos,
        search_stock_photos=_search_stock_photos,
        fetch_stock_photo=_fetch_stock_photo,
        build_visual_prompts_batch=_build_visual_prompts_batch,
        make_ass=make_ass, make_srt=make_srt, srt_from_audio=_srt_from_audio,
        generate_thumbnail=_generate_thumbnail,
        generate_scene_image_ai=_generate_scene_image_ai,
        generate_scene_video_with_veo3=_generate_scene_video_with_veo3,
        attach_veo3_video=attach_veo3_video,
        make_image_effect_filter=make_image_effect_filter,
        make_video_intro_filter=make_video_intro_filter,
        apply_sound_effect_to_scene=apply_sound_effect_to_scene,
        probe_audio_duration=probe_audio_duration,
        is_valid_audio=is_valid_audio,
        download_url=download_url, is_image_file=is_image_file,
        inject_region_into_keyword=inject_region_into_keyword,
        enrich_keyword_with_context=enrich_keyword_with_context,
        clean_keyword=_clean_keyword,
        optimize_query_for_region=optimize_query_for_region,
        save_and_next_scene=_save_and_next_scene,
        IMAGE_EFFECTS=IMAGE_EFFECTS, VIDEO_INTRO_EFFECTS=VIDEO_INTRO_EFFECTS,
        SOUND_EFFECTS=SOUND_EFFECTS, SUB_STYLES=SUB_STYLES,
        EDGE_VOICES=EDGE_VOICES, KOREAN_EDGE_VOICES=KOREAN_EDGE_VOICES,
        HAS_SUB=HAS_SUB, _VEO3_OK=_VEO3_OK, _veo3=_veo3,
        TMP=TMP, AUDIO_DIR=AUDIO_DIR,
        # Extra: capcut, zerotts for render_post_render_publish etc.
        _CAPCUT_OK=_CAPCUT_OK, _cc=_cc,
        _ZEROTTS_OK=_ZEROTTS_OK, _zt=_zt,
        _SOCIAL_PUBLISHING_OK=_SOCIAL_PUBLISHING_OK,
        render_post_render_publish=render_post_render_publish,
        normalize_import_video_config=normalize_import_video_config,
        build_veo3_prompt=build_veo3_prompt,
        search_pexels_videos=search_pexels_videos,
        search_pixabay_videos=search_pixabay_videos,
        search_coverr_videos=search_coverr_videos,
        search_pexels_photos_only=search_pexels_photos_only,
        search_pixabay_photos_only=search_pixabay_photos_only,
    )

# ════════════════════════════════════════════════════════════
# LONG VIDEO TAB
# ════════════════════════════════════════════════════════════
from app.ui.tab_longvideo import render_longvideo_tab
with tab_longvideo:
    render_longvideo_tab(
        cfg=cfg, save_cfg=save_cfg,
        load_proj=load_proj, save_proj=save_proj,
        tts=_tts_wrapper, ffmpeg=ffmpeg, FFMPEG=FFMPEG,
        call_ai=_call_ai, call_ai_script=_call_ai_script,
        parse_json_robust=parse_json_robust,
        fetch_stock_video=_fetch_stock_video,
        make_srt=make_srt, make_ass=make_ass,
        srt_from_audio=_srt_from_audio,
        generate_thumbnail=_generate_thumbnail,
        make_image_effect_filter=make_image_effect_filter,
        IMAGE_EFFECTS=IMAGE_EFFECTS, HAS_SUB=HAS_SUB,
        SUB_STYLES=SUB_STYLES, EDGE_VOICES=EDGE_VOICES,
        TMP=TMP, AUDIO_DIR=AUDIO_DIR,
        inject_region_into_keyword=inject_region_into_keyword,
        clean_keyword=_clean_keyword,
        probe_audio_duration=probe_audio_duration,
        download_url=download_url,
    )

# ════════════════════════════════════════════════════════════
# SHORT VIDEO TAB
# ════════════════════════════════════════════════════════════
from app.ui.tab_shortvideo import render_shortvideo_tab
with tab_shortvideo:
    render_shortvideo_tab(
        cfg=cfg, save_cfg=save_cfg,
        load_proj=load_proj, save_proj=save_proj,
        tts=_tts_wrapper, ffmpeg=ffmpeg, FFMPEG=FFMPEG,
        call_ai=_call_ai, call_ai_script=_call_ai_script,
        parse_json_robust=parse_json_robust,
        fetch_stock_video=_fetch_stock_video,
        make_srt=make_srt, make_ass=make_ass,
        srt_from_audio=_srt_from_audio,
        generate_thumbnail=_generate_thumbnail,
        make_image_effect_filter=make_image_effect_filter,
        IMAGE_EFFECTS=IMAGE_EFFECTS, HAS_SUB=HAS_SUB,
        SUB_STYLES=SUB_STYLES, EDGE_VOICES=EDGE_VOICES,
        TMP=TMP, AUDIO_DIR=AUDIO_DIR,
        normalize_import_video_config=normalize_import_video_config,
    )

# ════════════════════════════════════════════════════════════
# PUBLISH TAB
# ════════════════════════════════════════════════════════════
from app.ui.tab_publish import render_publish_tab
with tab_publish:
    render_publish_tab(
        _SOCIAL_PUBLISHING_OK=_SOCIAL_PUBLISHING_OK,
        _SOCIAL_STORE=_SOCIAL_STORE,
        render_social_publish_ui=render_social_publish_ui,
    )

# ════════════════════════════════════════════════════════════
# CREATIVE STUDIO TAB
# ════════════════════════════════════════════════════════════
from app.ui.tab_creative import render_creative_tab
with tab_creative:
    render_creative_tab(
        _CREATIVE_OK=_CREATIVE_OK,
        _creative=_creative,
        call_ai=_call_ai,
        parse_json_robust=parse_json_robust,
        FFMPEG=FFMPEG,
        _veo3=_veo3,
        _VEO3_OK=_VEO3_OK,
        cfg=cfg,
    )
