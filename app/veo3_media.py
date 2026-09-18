"""
app/veo3_media.py — Veo3 video generation wrappers.
"""
import json
from pathlib import Path
from typing import Optional

from app.ai_client import call_ai, parse_json_robust
from app.media_fetch import fetch_stock_video

# ── Veo3 prompt template ──────────────────────────────────────────────────────
VEO3_PROMPT_TEMPLATE = """\
SUBJECT: {character}
ACTION: {action}
ENVIRONMENT: {environment}
CAMERA: Eye-level cinematic documentary shot, slow smooth push-in, stable natural motion, shallow depth of field.
LIGHTING: Natural realistic light, soft shadows, balanced colors.
AUDIO: Ambient location sound only; no narration or spoken dialogue.
STYLE: Photorealistic, authentic {nationality} setting, believable human behavior, subtle film grain.
AVOID: Text, subtitles, logos, watermark, distorted anatomy, duplicated people, CGI or cartoon look.\
"""


def build_veo3_prompt(character: str, action: str, environment: str, nationality: str) -> str:
    """Single canonical Veo prompt used by API, editor and web export."""
    fallback_character = f"A realistic {nationality} person with natural appearance"
    return VEO3_PROMPT_TEMPLATE.format(
        character=(character or fallback_character).strip(),
        action=(action or "Natural movement matching the narration, with subtle expressions").strip(),
        environment=(environment or f"An authentic everyday {nationality} location").strip(),
        nationality=(nationality or "local").strip(),
    ).strip()


def build_visual_prompts_batch(scenes: list, lang: str, cfg: dict, log_cb=None) -> list:
    """Generate visual-only fields after narration is final, in economical batches."""
    nationality = {
        "Korean": "South Korean",
        "Vietnamese": "Vietnamese",
        "Japanese": "Japanese",
        "English": "Western",
    }.get(lang, "local")

    for start in range(0, len(scenes), 10):
        chunk = scenes[start:start + 10]
        compact_input = [
            {
                "id": scene.get("id", start + offset + 1),
                "narration": scene.get("text", "")[:500],
                "keyword": scene.get("keyword", ""),
            }
            for offset, scene in enumerate(chunk)
        ]
        prompt = (
            "You are a visual director. Convert each narration into one filmable, "
            "photorealistic documentary shot. Do not rewrite the narration. "
            "Return ONLY JSON with this schema: "
            '{"scenes":[{"id":1,"character":"English description",'
            '"action":"English description","environment":"English description"}]}. '
            f"People and locations should be authentically {nationality}. "
            "One subject, one clear action, one location per scene. No text, logos, "
            "spoken dialogue, brand-name cameras or resolution claims.\n\n"
            f"INPUT:\n{json.dumps(compact_input, ensure_ascii=False)}"
        )
        try:
            parsed = parse_json_robust(call_ai(prompt, cfg))
            by_id = {str(item.get("id")): item for item in parsed.get("scenes", [])}
        except Exception as exc:
            by_id = {}
            if callable(log_cb):
                log_cb(f"  ⚠️ Visual prompt batch lỗi: {exc} — dùng prompt local")

        for scene in chunk:
            visual = by_id.get(str(scene.get("id")), {})
            scene["veo3_prompt"] = build_veo3_prompt(
                visual.get("character", f"A realistic {nationality} person"),
                visual.get("action", "Natural movement matching the scene"),
                visual.get("environment", scene.get("keyword", f"An authentic {nationality} location")),
                nationality,
            )
    return scenes


def fetch_video_with_veo3(keyword: str, orientation: str = "landscape",
                           used_urls=None, scene_text: str = "",
                           log_cb=None, force_veo3: bool = False,
                           veo3_prompt: str = "",
                           cfg: dict = None,
                           veo3_ok: bool = False,
                           veo3_module=None) -> str:
    """Smart video fetch: Veo3 AI hoặc stock footage tùy theo cấu hình."""
    cfg = cfg or {}
    import streamlit as st
    _active_project = st.session_state.get("proj", {})
    _project_flow = (
        _active_project.get("video_generation_flow", "current")
        if isinstance(_active_project, dict) else "current"
    )
    veo3_provider = (
        "google_flow" if _project_flow == "google_flow_auto"
        else cfg.get("veo3_provider", "stock")
    )
    veo3_requested = (
        veo3_provider in ("gemini_web", "google_flow")
        or cfg.get("veo3_enabled", False)
        or force_veo3
    )
    veo3_on = (
        veo3_requested
        and (
            (veo3_provider == "api" and veo3_ok)
            or (veo3_provider == "google_flow" and bool(cfg.get("useapi_token")))
        )
    )
    veo3_mode = (
        "all" if force_veo3 or _project_flow == "google_flow_auto"
        else cfg.get("veo3_mode", "fallback")
    )
    gem_keys  = cfg.get("gemini", [])

    if veo3_requested and veo3_provider == "gemini_web":
        if callable(log_cb):
            log_cb("🌐 Gemini Web: bỏ qua API; hãy tạo và nhập MP4 trong editor cảnh")
        if veo3_mode == "all":
            return ""
        return fetch_stock_video(keyword, orientation=orientation, used_urls=used_urls, cfg=cfg) or ""

    def _veo3_generate():
        if not veo3_module:
            return None
        if veo3_provider == "google_flow":
            token = cfg.get("useapi_token", "")
            email = cfg.get("useapi_email", "")
            model = cfg.get("useapi_model", "veo-3.1-fast")
            if not token:
                if callable(log_cb): log_cb("❌ Google Flow: Chưa cấu hình UseAPI Token trong Settings")
                return None
            if callable(log_cb): log_cb("🚀 Gọi Google Flow qua UseAPI...")
            return veo3_module.generate_video_google_flow(
                keyword=keyword, token=token, email=email if email else None,
                model=model, orientation=orientation, scene_text=scene_text,
                timeout_seconds=240, log_cb=log_cb, veo3_prompt=veo3_prompt,
            )
        else:
            if not gem_keys:
                if callable(log_cb): log_cb("❌ Veo3: chưa có Gemini key trong Settings")
                return None
            for ki, api_key in enumerate(gem_keys):
                if callable(log_cb): log_cb(f"  🔑 Veo3 key {ki+1}/{len(gem_keys)} ({api_key[:8]}...)")
                result = veo3_module.generate_video_veo3_best(
                    keyword=keyword, gemini_api_key=api_key, orientation=orientation,
                    scene_text=scene_text, timeout_seconds=200,
                    resolution=cfg.get("veo3_resolution", "720p"),
                    log_cb=log_cb, veo3_prompt=veo3_prompt,
                )
                if result:
                    if callable(log_cb): log_cb(f"  ✅ Veo3 OK với key {ki+1}")
                    return result
                if callable(log_cb): log_cb(f"  ⚠️ Key {ki+1} thất bại → thử key tiếp")
            if callable(log_cb): log_cb("❌ Veo3: tất cả key đều thất bại → dùng stock footage")
            return None

    if veo3_on and veo3_mode == "all":
        if callable(log_cb): log_cb(f"🤖 Veo3 [ALL] generating: {keyword[:50]}...")
        veo_path = _veo3_generate()
        if veo_path:
            return veo_path
        if callable(log_cb): log_cb("⚠️ Veo3 tất cả key fail → fallback stock footage")

    stock_url = fetch_stock_video(keyword, orientation=orientation, used_urls=used_urls, cfg=cfg)

    if not stock_url and veo3_on and veo3_mode == "fallback":
        if callable(log_cb): log_cb(f"🤖 Stock không có → Veo3 fallback: {keyword[:50]}...")
        veo_path = _veo3_generate()
        if veo_path:
            return veo_path

    return stock_url or ""


def generate_scene_video_with_veo3(scene: dict, video_cfg: dict,
                                    orientation: str = "landscape",
                                    log_cb=None,
                                    veo3_ok: bool = False,
                                    veo3_module=None) -> str:
    """Generate one scene from its reviewed Veo prompt and return a local MP4."""
    if not veo3_ok or not veo3_module:
        raise RuntimeError("Module veo3_video chưa load được")

    prompt = str(scene.get("veo3_prompt", "")).strip()
    if not prompt:
        raise ValueError("Cảnh chưa có veo3_prompt")

    provider = video_cfg.get("veo3_provider", "stock")
    keyword = str(scene.get("keyword", "") or scene.get("text", ""))
    scene_text = str(scene.get("text", ""))

    if provider == "google_flow":
        token = str(video_cfg.get("useapi_token", "")).strip()
        if not token:
            raise ValueError("Chưa cấu hình UseAPI Token cho Google Flow")
        result = veo3_module.generate_video_google_flow(
            keyword=keyword, token=token,
            email=video_cfg.get("useapi_email") or None,
            model=video_cfg.get("useapi_model", "veo-3.1-fast"),
            orientation=orientation, scene_text=scene_text,
            veo3_prompt=prompt, timeout_seconds=240, log_cb=log_cb,
        )
        return result if result and Path(result).is_file() else ""

    if provider != "api" or not video_cfg.get("veo3_enabled", False):
        raise ValueError("Hãy chọn Veo API hoặc Google Flow trong Settings")

    api_keys = video_cfg.get("gemini", [])
    if not api_keys:
        raise ValueError("Chưa cấu hình Gemini API key")

    for key_index, api_key in enumerate(api_keys):
        if callable(log_cb):
            log_cb(f"🔑 Thử Veo API key {key_index + 1}/{len(api_keys)}")
        result = veo3_module.generate_video_veo3_best(
            keyword=keyword, gemini_api_key=api_key, orientation=orientation,
            scene_text=scene_text, veo3_prompt=prompt, timeout_seconds=240,
            resolution=video_cfg.get("veo3_resolution", "720p"), log_cb=log_cb,
        )
        if result and Path(result).is_file():
            return result
    return ""


def attach_veo3_video(scene: dict, video_path: str) -> None:
    """Attach a generated MP4 as the scene's sole visual source."""
    if not video_path or not Path(video_path).is_file():
        raise ValueError("Video Veo 3 tải về không hợp lệ")
    scene["veo3Path"] = str(video_path)
    scene["videoUrl"] = None
    scene["imageUrl"] = None
    scene["customVid"] = None
    scene["customImg"] = None
    scene.pop("veo3Error", None)
