"""
veo3_video.py — Google Veo 3 Video Generation Engine
=====================================================
Updated to use latest Google Gen AI SDK API format (2026-07):
  - Model: veo-3.1-fast-generate-preview (faster) / veo-3.0-generate-preview (quality)
  - source=types.VideoGenerationSource(prompt=...) — new prompt format
  - operation.result instead of operation.response
  - resolution config: "720p" | "1080p" | "4k"

Yêu cầu:
  pip install google-genai

API key: Gemini API key (cùng key dùng cho gemini flash trong tool.py)

Flow:
  1. Gọi client.models.generate_videos(model, source, config)
  2. Poll operation.done mỗi 10s
  3. Download bytes → lưu vào cache dir
  4. Trả về đường dẫn file .mp4

Fallback: nếu Veo3 fail → trả None → tool.py dùng stock footage như bình thường.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Optional, Callable

# ── Cache dir ─────────────────────────────────────────────────────────────────
VEO_CACHE_DIR = Path.home() / ".avc_veo_cache"
VEO_CACHE_DIR.mkdir(exist_ok=True)

# ── Models theo thứ tự ưu tiên (cập nhật 2026-07) ────────────────────────────
# List bằng: client.models.list() -> chỉ có 3 model veo-3.1-* trên v1beta
VEO_MODELS = [
    "veo-3.1-fast-generate-preview",  # Veo 3.1 Fast — ưu tiên (nhanh nhất)
    "veo-3.1-generate-preview",       # Veo 3.1 Standard — chất lượng cao hơn
    "veo-3.1-lite-generate-preview",  # Veo 3.1 Lite — nhẹ nhất, fallback cuối
]

# ── Aspect ratio mapping ───────────────────────────────────────────────────────
ORIENTATION_MAP = {
    "landscape": "16:9",
    "portrait":  "9:16",
    "":          "16:9",
}


def _build_cinematic_prompt(keyword: str, scene_text: str = "") -> str:
    """
    Chuyển keyword + narration text → prompt Veo3 style điện ảnh.
    Veo3 phản ứng tốt với prompt mô tả cảnh quay cụ thể, không phải từ khóa search.
    """
    base = keyword.strip()

    context = ""
    if scene_text:
        context = f" The scene conveys: {scene_text[:100].strip()}."

    prompt = (
        f"Cinematic short video clip: {base}.{context} "
        f"Style: documentary, natural lighting, smooth camera movement, "
        f"shallow depth of field. No text overlay. 8 seconds. "
        f"High quality, photorealistic."
    )
    return prompt


def generate_video_veo3(
    keyword: str,
    gemini_api_key: str,
    orientation: str = "landscape",
    scene_text: str = "",
    timeout_seconds: int = 240,
    resolution: str = "720p",
    log_cb: Optional[Callable] = None,
) -> Optional[str]:
    """
    Generate 1 video clip bằng Veo3 API (SDK).

    Args:
        keyword:         Keyword mô tả cảnh quay
        gemini_api_key:  Gemini API key
        orientation:     "landscape" | "portrait"
        scene_text:      Narration text để enrich prompt
        timeout_seconds: Timeout tối đa (mặc định 4 phút)
        resolution:      "720p" | "1080p" | "4k"
        log_cb:          Callback để log progress lên UI

    Returns:
        Đường dẫn .mp4 nếu thành công, None nếu thất bại.
    """
    def log(msg: str):
        print(f"[Veo3] {msg}", flush=True)
        if callable(log_cb):
            log_cb(msg)

    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError:
        log("❌ google-genai chưa cài — chạy: pip install google-genai")
        return None

    aspect  = ORIENTATION_MAP.get(orientation, "16:9")
    prompt  = _build_cinematic_prompt(keyword, scene_text)
    log(f"🎬 Prompt: {prompt[:80]}...")

    client = genai.Client(
        http_options={"api_version": "v1beta"},
        api_key=gemini_api_key,
    )

    last_error = None
    for model_id in VEO_MODELS:
        try:
            log(f"🚀 Gọi {model_id} | {aspect} | {resolution}...")

            video_config = genai_types.GenerateVideosConfig(
                aspect_ratio      = aspect,
                number_of_videos  = 1,
                duration_seconds  = 8,
                resolution        = resolution,
                # person_generation: không được hỗ trợ trên v1beta — bỏ để tránh 400
            )

            operation = client.models.generate_videos(
                model  = model_id,
                source = genai_types.GenerateVideosSource(
                    prompt = prompt,
                ),
                config = video_config,
            )

            # ── Polling ─────────────────────────────────────────────────────
            start_t = time.time()
            while not operation.done:
                elapsed = time.time() - start_t
                if elapsed > timeout_seconds:
                    log(f"⏰ Timeout sau {timeout_seconds}s — thử model khác")
                    break
                log(f"  ⏳ Đang generate... ({elapsed:.0f}s / {timeout_seconds}s)")
                time.sleep(10)
                operation = client.operations.get(operation)

            if not operation.done:
                last_error = "timeout"
                continue

            # ── Lấy video từ operation.result (API mới) ───────────────────
            result = operation.result
            if not result:
                log(f"❌ {model_id}: operation.result là None")
                last_error = "no_result"
                continue

            generated_videos = result.generated_videos
            if not generated_videos:
                log(f"❌ {model_id}: không có video trong result")
                last_error = "no_videos"
                continue

            generated_video = generated_videos[0]
            video_file = generated_video.video
            if not video_file:
                log(f"❌ {model_id}: generated_video.video là None")
                last_error = "no_video_object"
                continue

            log(f"  📥 Download: {str(video_file.uri)[:60]}...")

            # Download về local cache
            out_path = VEO_CACHE_DIR / f"veo_{uuid.uuid4().hex}.mp4"
            client.files.download(file=video_file)
            video_file.save(str(out_path))

            if out_path.exists() and out_path.stat().st_size > 10_000:
                size_kb = out_path.stat().st_size // 1024
                log(f"✅ Veo3 OK! {out_path.name} ({size_kb}KB) [{model_id}]")
                return str(out_path)
            else:
                log(f"❌ File quá nhỏ hoặc không tồn tại")
                last_error = "download_failed"
                continue

        except Exception as e:
            err_str = str(e)
            log(f"❌ {model_id} lỗi: {err_str[:150]}")
            last_error = err_str

            # 429 quota — không thử model khác, đều dùng chung quota account
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                log("❌ Veo3: Hết quota (429) — cần nạp thêm hoặc chờ reset. Fallback stock.")
                return None  # không cần thử các model khác
            # model không có quyền / quota → thử model tiếp theo
            if any(k in err_str.lower() for k in [
                "permission", "not found", "403", "allowlist",
                "not_found", "unavailable", "not supported"
            ]):
                log(f"  → Thử model tiếp theo...")
                continue
            # Lỗi kỹ thuật khác — dừng
            break

    log(f"❌ Tất cả Veo3 models thất bại. Lỗi cuối: {last_error}")
    return None


def generate_video_veo3_rest(
    keyword: str,
    gemini_api_key: str,
    orientation: str = "landscape",
    scene_text: str = "",
    timeout_seconds: int = 240,
    resolution: str = "720p",
    log_cb: Optional[Callable] = None,
) -> Optional[str]:
    """
    Fallback dùng REST API trực tiếp (không cần google-genai SDK).
    Gọi generativelanguage.googleapis.com REST endpoint.
    """
    import requests as _req

    def log(msg: str):
        print(f"[Veo3/REST] {msg}", flush=True)
        if callable(log_cb):
            log_cb(msg)

    aspect = ORIENTATION_MAP.get(orientation, "16:9")
    prompt = _build_cinematic_prompt(keyword, scene_text)
    BASE   = "https://generativelanguage.googleapis.com/v1beta"

    for model_id in VEO_MODELS:
        try:
            log(f"🚀 REST: {model_id} | aspect={aspect} | res={resolution}")
            r = _req.post(
                f"{BASE}/models/{model_id}:predictLongRunning",
                params={"key": gemini_api_key},
                json={
                    "instances": [
                        {
                            "prompt": prompt
                        }
                    ],
                    "parameters": {
                        "sampleCount": 1,
                        "resolution": resolution,
                        "aspectRatio": aspect,
                        "durationSeconds": 8
                    }
                },
                timeout=30,
            )
            if not r.ok:
                try:
                    err = r.json().get("error", {})
                    msg = err.get("message", "")
                except Exception:
                    msg = r.text
                log(f"❌ HTTP {r.status_code}: {msg[:150]}")
                if r.status_code in (403, 404):
                    continue
                break

            op      = r.json()
            op_name = op.get("name", "")
            if not op_name:
                log("❌ Không có operation name")
                continue

            log(f"  🔄 Operation: {op_name}")

            # Polling
            start_t = time.time()
            while True:
                elapsed = time.time() - start_t
                if elapsed > timeout_seconds:
                    log(f"⏰ Timeout {timeout_seconds}s")
                    break
                time.sleep(10)
                poll_r = _req.get(
                    f"{BASE}/{op_name}",
                    params={"key": gemini_api_key},
                    timeout=15,
                )
                if not poll_r.ok:
                    log(f"  Poll lỗi: {poll_r.status_code}")
                    continue

                poll_data = poll_r.json()
                log(f"  ⏳ {elapsed:.0f}s — done={poll_data.get('done', False)}")

                if poll_data.get("done"):
                    resp   = poll_data.get("response", {})
                    videos = (
                        resp.get("generatedVideos")
                        or resp.get("generatedSamples")
                        or []
                    )
                    if not videos:
                        log("❌ Response không có video")
                        break

                    video_uri = (
                        videos[0].get("video", {}).get("uri")
                        or videos[0].get("videoUri")
                        or ""
                    )
                    if not video_uri:
                        log("❌ Không tìm thấy video URI")
                        break

                    log(f"  📥 Download: {video_uri[:60]}...")
                    dl = _req.get(video_uri, params={"key": gemini_api_key}, timeout=60)
                    if dl.ok and len(dl.content) > 10_000:
                        out_path = VEO_CACHE_DIR / f"veo_{uuid.uuid4().hex}.mp4"
                        out_path.write_bytes(dl.content)
                        size_kb = len(dl.content) // 1024
                        log(f"✅ Veo3/REST OK! {out_path.name} ({size_kb}KB)")
                        return str(out_path)
                    else:
                        log(f"❌ Download thất bại: status={dl.status_code} size={len(dl.content)}")
                    break

        except Exception as e:
            log(f"❌ REST exception: {e}")
            continue

    return None


def generate_video_veo3_best(
    keyword: str,
    gemini_api_key: str,
    orientation: str = "landscape",
    scene_text: str = "",
    timeout_seconds: int = 240,
    resolution: str = "720p",
    log_cb: Optional[Callable] = None,
) -> Optional[str]:
    """
    Entry point chính: thử SDK trước, fallback REST nếu SDK fail.
    """
    result = generate_video_veo3(
        keyword, gemini_api_key, orientation, scene_text,
        timeout_seconds, resolution, log_cb
    )
    if result:
        return result

    if callable(log_cb):
        log_cb("🔄 SDK thất bại → thử REST API...")
    return generate_video_veo3_rest(
        keyword, gemini_api_key, orientation, scene_text,
        timeout_seconds, resolution, log_cb
    )


def clear_veo_cache(max_files: int = 200):
    """Xóa cache cũ nếu vượt quá max_files (tránh đầy ổ cứng)."""
    files = sorted(VEO_CACHE_DIR.glob("*.mp4"), key=lambda f: f.stat().st_mtime)
    while len(files) > max_files:
        files.pop(0).unlink(missing_ok=True)


def check_veo3_support(api_key: str) -> dict:
    """
    Kiểm tra xem API key có quyền gọi Veo3 hay không và trả về trạng thái chi tiết.
    """
    try:
        from google import genai
        client = genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key)
        # Lấy danh sách models
        models = [m.name for m in client.models.list()]
        veo_supported = any("veo" in m.lower() for m in models)
        return {
            "ok": True,
            "veo_supported": veo_supported,
            "models": [m for m in models if "veo" in m.lower() or "gemini" in m.lower()]
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e)
        }
