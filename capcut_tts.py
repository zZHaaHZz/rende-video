"""
capcut_tts.py — CapCut TTS wrapper for AI Video Creator
=========================================================
Wraps capcut-tts-api/capcut_common_task_client.py to provide:
  - tts_capcut(text, voice_type, resource_id, rate, out_path) -> (audio_path, srt_content)
  - CAPCUT_VOICES: dict mapping display names → (voice_type, resource_id)
  - poll_tts_task(task_id, token) -> audio_url

Flow:
  1. POST /lv/v1/common_task/new  (tts-new)
  2. Poll /lv/v1/common_task/query until status == "succeeded"
  3. Download mp3 from result URL
  4. Build synthetic SRT from word count + probed duration (same as Edge TTS fallback)
"""

import sys
import os
import time
import uuid
import hashlib
import requests
from pathlib import Path
from copy import deepcopy
from typing import Optional, Tuple

# ── Add capcut-tts-api to path ────────────────────────────────────────────────
_HERE = Path(__file__).parent
_CC_DIR = _HERE / "capcut-tts-api"
if str(_CC_DIR) not in sys.path:
    sys.path.insert(0, str(_CC_DIR))

_CC_AVAILABLE = False
_CC_IMPORT_ERR = ""

try:
    from capcut_common_task_client import (
        DEFAULT_DEVICE,
        compact_json,
        common_query,
        base_headers,
        make_sign_header,
        tts_new_body,
        query_body,
        checked_json_response,
        BASE,
    )
    _CC_AVAILABLE = True
except ImportError as _e:
    _CC_IMPORT_ERR = str(_e)


# ── Vietnamese, English & Korean voices from Voice.json (curated subset) ───────
CAPCUT_VOICES = {
    # ── Vietnamese ──────────────────────────────────────────────────────
    # Đã probe trực tiếp với sami_text_to_speech ngày 2026-08-10. Hai speaker
    # Neural HoaiMy/NamMinh bị loại vì trả 40402004/TTSInvalidSpeaker.
    "🇻🇳 Nhỏ Ngọt Ngào":                  ("BV421_vivn_streaming",                 "7252594014782755330"),
    "🇻🇳 Giọng Nữ Phổ Thông":             ("vi_female_huong",                      "7264854897953083905"),
    "🇻🇳 Giọng Bé":                       ("BV074_streaming_dsp",                  "7550087831092251920"),
    "🇻🇳 Cô Gái Hoạt Ngôn":               ("BV074_streaming",                      "7102355709945188865"),
    "🇻🇳 Việt Méo":                       ("BV075_streaming_vibrato_dsp",          "7569450639810465040"),
    "🇻🇳 Mai":                            ("BV562_streaming",                      "7483736254694035984"),
    "🇻🇳 Ban Mai":                        ("multi_female_yangguangnv_uranus_bigtts","7637456432522218773"),
    "🇻🇳 Nữ Review Phim":                 ("multi_female_richgirl_uranus_bigtts",  "7637460351541447956"),
    "🇻🇳 Bản Tin 1":                      ("multi_female_quanweinv_uranus_bigtts", "7637458743197732117"),
    "🇻🇳 Review Phim 4":                  ("multi_female_stokie_uranus_bigtts",    "7637456729696996628"),
    "🇻🇳 Bản Tin Nữ":                     ("multi_female_sisi_uranus_bigtts",      "7637455857285860629"),
    "🇻🇳 Review Phim 3":                  ("multi_female_daqi_uranus_bigtts",      "7637451983389019409"),
    "🇻🇳 Review Phim 2":                  ("multi_female_xyf04auto_uranus_bigtts", "7637458743197732117"),
    "🇻🇳 Sunny Idol":                     ("multi_female_kiwi_uranus_bigtts",      "7637457995882089749"),
    "🇻🇳 Kenny Đại Đế":                   ("BV075_streaming_demon_dsp",            "7569442422665661712"),
    "🇻🇳 Robot VN":                       ("BV075_streaming_robot_dsp",            "7538698409633516816"),
    "🇻🇳 Giọng Nam Trầm":                 ("multi_male_felipe_uranus_bigtts",      "7637456729696996628"),
    "🇻🇳 Giọng Gái Mới Lớn":              ("multi_female_peiqi_uranus_bigtts",     "7637458789033151751"),
    "🇻🇳 Nam Bản Tin":                    ("multi_female_xinwenjieshuo_uranus_bigtts","7637455039719640327"),
    "🇻🇳 Nữ Thuyết Minh Ngọt Ngào":        ("multi_female_tianmeijieshuo_uranus_bigtts","7637460417295469832"),
    "🇻🇳 Nam Tự Tin":                     ("BV075_streaming",                      "7102355803792740865"),
    "🇻🇳 Alex Đại Đế":                    ("BV560_streaming",                      "7483736167565758992"),
    # ── English ─────────────────────────────────────────────────────────
    "🇺🇸 EN US Male":                     ("en_us_002",                            "7130515992936976897"),
    "🇺🇸 EN US Male 2":                   ("en_us_006",                            "7114563482518819329"),
    "🇺🇸 Male Professional":              ("en_us_007",                            "7114563482472681986"),
    "🇺🇸 Charming Male":                  ("en_us_010",                            "7114563482359435778"),
    "🇺🇸 Narrator":                       ("ICL_en_male_philosopher_dsp",          "7525722920161725712"),
    "🇺🇸 Female Teacher":                 ("en_female_soothing_mars_bigtts",       "7526754143369760016"),
    "🇺🇸 Jenny":                          ("en-US-JennyMultilingualNeural",        "7569439521352338689"),
    "🇺🇸 Sherry":                         ("en_female_sherry",                     "7278146554844680706"),
    "🇺🇸 Janeamber":                      ("en_female_janeamber_mars_bigtts",      "7538652405005700369"),
    "🇺🇸 Deadpool":                       ("en_male_deadpool",                     "7231025912261644802"),
    "🇺🇸 Grim Rock":                      ("en_male_death_rock",                   "7372472588859085313"),
    "🇺🇸 Trickster":                      ("en_male_trickster_stream",             "7189462618589893121"),
    "🇺🇸 Cute Girl":                      ("ICL_en_female_little_cute_dsp",        "7605129105306111233"),
    "🇺🇸 Energetic Female":               ("BV503_streaming",                      "7081168775646548482"),
    "🇺🇸 English Standard":               ("BV510_streaming",                      "7081169180120060418"),
}

# Default voices for quick language selection
CAPCUT_VOICE_DEFAULTS = {
    "vi": "🇻🇳 Cô Gái Hoạt Ngôn",
    "en": "🇺🇸 EN US Male",
}

POLL_INTERVAL = 2.0
# CapCut thường giữ task trong queue lâu hơn 30 giây khi dự án có nhiều cảnh.
# 120 giây vẫn có giới hạn rõ ràng nhưng tránh tạo task trùng chỉ vì queue chậm.
POLL_TIMEOUT = 120.0


def is_available() -> bool:
    return _CC_AVAILABLE


def _fresh_device() -> dict:
    """Return a deepcopy of DEFAULT_DEVICE with freshly randomised device/iid IDs
    so each TTS request looks like a brand-new CapCut installation (bypasses
    'shark block only' rate-limiting that targets a fixed device_id)."""
    import random
    d = deepcopy(DEFAULT_DEVICE)
    new_did = str(random.randint(7_000_000_000_000_000_000, 7_999_999_999_999_999_999))
    new_iid = str(random.randint(7_000_000_000_000_000_000, 7_999_999_999_999_999_999))
    d["device_id"] = new_did
    d["iid"]       = new_iid
    d["tdid"]      = new_did
    return d


def _build_tts_request(
    text: str,
    voice_type: str,
    resource_id: str,
    rate: str = "1.0",
    lang: str = "en-US",
):
    """Build the URL, headers and body for a TTS task creation request."""
    device = _fresh_device()
    babi, body = tts_new_body([text], voice_type, resource_id, rate, device, lang=lang)
    path  = "/lv/v1/common_task/new"
    query = common_query(device, babi, include_region=True)
    from urllib.parse import urlencode
    url = BASE + path + "?" + urlencode(query)
    body_text = compact_json(body)
    headers = base_headers(device, body_text, appid=True)
    lower_h = {k.lower(): v for k, v in headers.items()}
    if "sign" not in lower_h:
        headers["sign"] = make_sign_header(url, device["appvr"], lower_h["device-time"], device["tdid"])
    return url, headers, body_text



def _build_query_request(task_id: str, token: str):
    """Build URL/headers/body for polling a TTS task."""
    device = deepcopy(DEFAULT_DEVICE)
    body = query_body(task_id, token, "sami_text_to_speech")
    path = "/lv/v1/common_task/query"
    from urllib.parse import urlencode
    query = common_query(device, None, include_region=False)
    url = BASE + path + "?" + urlencode(query)
    body_text = compact_json(body)
    headers = base_headers(device, body_text, appid=True)
    lower_h = {k.lower(): v for k, v in headers.items()}
    if "sign" not in lower_h:
        headers["sign"] = make_sign_header(url, device["appvr"], lower_h["device-time"], device["tdid"])
    return url, headers, body_text


def submit_tts_task(
    text: str,
    voice_type: str,
    resource_id: str,
    rate: str = "1.0",
    lang: str = "en-US",
):
    """
    Submit a TTS task to CapCut API.
    Returns (task_id, token) on success, raises on error.
    """
    if not _CC_AVAILABLE:
        raise RuntimeError(f"capcut-tts-api not available: {_CC_IMPORT_ERR}")
    url, headers, body_text = _build_tts_request(
        text, voice_type, resource_id, rate, lang=lang
    )
    resp = requests.post(url, headers=headers, data=body_text.encode("utf-8"), timeout=30)
    data = checked_json_response(resp, "tts-new")
    tasks = data.get("data", {}).get("tasks", [])
    if not tasks:
        raise RuntimeError(f"TTS submit: no tasks in response: {data}")
    task = tasks[0]
    return task["id"], task["token"]


def poll_tts_task(task_id: str, token: str, timeout: float = 120.0):
    """
    Poll until TTS task completes.
    Returns the audio URL string on success, raises on timeout/error.
    """
    if not _CC_AVAILABLE:
        raise RuntimeError(f"capcut-tts-api not available: {_CC_IMPORT_ERR}")
    started_at = time.time()
    deadline = started_at + timeout
    last_status = None
    last_progress_log = started_at
    while time.time() < deadline:
        url, headers, body_text = _build_query_request(task_id, token)
        resp = requests.post(url, headers=headers, data=body_text.encode("utf-8"), timeout=30)
        data = checked_json_response(resp, "tts-query")
        tasks = data.get("data", {}).get("tasks", [])
        if not tasks:
            raise RuntimeError(f"TTS query: no tasks in response: {data}")
        task = tasks[0]
        status = task.get("status", "")
        now = time.time()
        if status != last_status or now - last_progress_log >= 20:
            elapsed = int(now - started_at)
            print(f"[CapCut TTS] Task {task_id}: status={status or 'unknown'} ({elapsed}s/{int(timeout)}s)")
            last_status = status
            last_progress_log = now
        if status in ("succeeded", "succeed"):
            # payload is a JSON string with audio_url
            import json
            payload_raw = task.get("payload", "{}")
            try:
                payload = json.loads(payload_raw)
            except Exception:
                payload = {}
            audio_url = payload.get("audio_url") or payload.get("mp3_url") or payload.get("url", "")
            if not audio_url:
                # Try nested structure
                items = payload.get("audio_list") or []
                if items:
                    audio_url = items[0].get("audio_url", "")
            if not audio_url:
                subtitles = payload.get("audio_subtitles") or []
                if subtitles:
                    audio_url = subtitles[0].get("speech_url") or subtitles[0].get("audio_url", "")
            if not audio_url:
                raise RuntimeError(f"TTS succeeded but no audio_url in payload: {payload}")
            return audio_url
        elif status in ("failed", "error", "fail"):
            raise RuntimeError(f"TTS task failed: {task}")
        # queueing / processing — wait and retry
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"TTS task {task_id} did not complete within {timeout}s")


def tts_capcut(
    text: str,
    voice_key: str = "🇻🇳 Cô Gái Hoạt Ngôn",
    rate: str = "1.0",
    out_path: Optional[str] = None,
    srt_out: Optional[str] = None,
    ffmpeg_bin: str = "ffmpeg",
) -> Tuple[Optional[str], Optional[str]]:
    """
    Full CapCut TTS pipeline: submit → poll → download → build SRT.

    Args:
        text:       Text to synthesize.
        voice_key:  Key from CAPCUT_VOICES dict (display name).
        rate:       Speed rate string, e.g. "1.0", "1.2".
        out_path:   Where to save the downloaded mp3 (auto-generated if None).
        srt_out:    Where to save the SRT file (None = skip).
        ffmpeg_bin: Path to ffmpeg for duration probing.

    Returns:
        (audio_path_str, srt_content_str) — both None on failure.
    """
    if not _CC_AVAILABLE:
        print(f"[CapCut TTS] Not available: {_CC_IMPORT_ERR}")
        return None, None

    try:
        # Không âm thầm đổi một key cũ/không hợp lệ sang BV074. Việc đó che giấu
        # cấu hình project lỗi và có thể làm đổi giọng giữa các cảnh.
        if voice_key not in CAPCUT_VOICES:
            raise ValueError(f"Giọng CapCut không được hỗ trợ: {voice_key!r}")
        voice_type, resource_id = CAPCUT_VOICES[voice_key]
        voice_lang = (
            "ko-KR" if "🇰🇷" in voice_key
            else "vi-VN" if "🇻🇳" in voice_key
            else "ja-JP" if "🇯🇵" in voice_key
            else "en-US"
        )
        # _build_tts_request đã dùng _fresh_device() → deepcopy + randomize device IDs
        # KHÔNG mutate DEFAULT_DEVICE trực tiếp vì sẽ gây lỗi concurrent requests

        # 1. Submit
        task_id, token = submit_tts_task(
            text, voice_type, resource_id, rate, lang=voice_lang
        )
        print(f"[CapCut TTS] Task submitted: {task_id}")

        # 2. Poll
        audio_url = poll_tts_task(task_id, token, timeout=POLL_TIMEOUT)
        print(f"[CapCut TTS] Audio ready: {audio_url[:80]}...")

        # 3. Download
        if out_path is None:
            from pathlib import Path as _P
            import tempfile
            tmp = _P(tempfile.gettempdir()) / "avc"
            tmp.mkdir(exist_ok=True)
            out_path = tmp / f"cc_{uuid.uuid4().hex}.mp3"
        out_path = Path(out_path)
        _download_audio(audio_url, out_path)
        print(f"[CapCut TTS] Saved: {out_path} ({out_path.stat().st_size} bytes)")

        # 4. Build SRT (synthetic timing from word count + FFmpeg probe)
        srt_content = None
        if srt_out:
            srt_content = _build_srt_from_audio(str(out_path), text, str(srt_out), ffmpeg_bin)

        return str(out_path), srt_content

    except Exception as e:
        print(f"[CapCut TTS] Error: {e}")
        return None, None


def _download_audio(url: str, dest: Path, timeout: int = 60):
    resp = requests.get(url, timeout=timeout, stream=True, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(65536):
            if chunk:
                f.write(chunk)


def _probe_duration(audio_path: str, ffmpeg_bin: str = "ffmpeg") -> float:
    """Probe audio duration using FFmpeg. Returns seconds."""
    import subprocess
    try:
        result = subprocess.run(
            [ffmpeg_bin, "-i", audio_path, "-f", "null", "-"],
            capture_output=True, text=True,
        )
        for line in result.stderr.split("\n"):
            if "Duration:" in line:
                ts = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = ts.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception as e:
        print(f"[CapCut TTS] Duration probe failed: {e}")
    return 5.0


def _build_srt_from_audio(audio_path: str, text: str, srt_path: str, ffmpeg_bin: str = "ffmpeg") -> str:
    """
    Build a synthetic SRT using proportional word timing (same algorithm as tool.py).
    Groups 4 words per subtitle block.
    """
    dur = _probe_duration(audio_path, ffmpeg_bin)
    words_list = text.split()
    if not words_list or dur <= 0:
        return ""

    char_lens = [max(1, len(w)) for w in words_list]
    total_chars = sum(char_lens)
    t = 0.0
    word_entries = []
    for w, cl in zip(words_list, char_lens):
        wd = dur * cl / total_chars
        word_entries.append({"word": w, "start": t, "end": t + wd})
        t += wd

    def _fmt(s: float) -> str:
        h, m = int(s // 3600), int((s % 3600) // 60)
        sec, ms = int(s % 60), int((s - int(s)) * 1000)
        return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

    GROUP = 4
    lines, idx = [], 1
    for i in range(0, len(word_entries), GROUP):
        chunk = word_entries[i:i + GROUP]
        text_block = " ".join(e["word"] for e in chunk).upper()
        lines.append(f"{idx}\n{_fmt(chunk[0]['start'])} --> {_fmt(chunk[-1]['end'])}\n{text_block}\n")
        idx += 1

    srt_content = "\n".join(lines)
    Path(srt_path).write_text(srt_content, encoding="utf-8")
    return srt_content
