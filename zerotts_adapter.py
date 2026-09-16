"""
zerotts_adapter.py — ZeroTTS wrapper for AI Video Creator
==========================================================
Wraps the ZeroTTS library (https://github.com/zeroweight-ai/ZeroTTS) to provide:
  - tts_zerotts(text, voice, out_path) -> audio_path | None
  - ZEROTTS_VOICES: dict mapping display names → voice IDs
  - _ZEROTTS_OK: bool flag để tool.py biết engine có sẵn không
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional

# ── Availability flag ────────────────────────────────────────────────────────
_ZEROTTS_OK = False
_ZEROTTS_IMPORT_ERR = ""
_tts_instance = None  # Singleton — lazy init

try:
    from zerotts import ZeroTTS
    from zerotts.chunking import chunk_text, clean_segment_punctuation, normalize_punctuation
    _ZEROTTS_OK = True
except Exception as _e:
    _ZEROTTS_IMPORT_ERR = str(_e)


# ── Voice mapping (display name → ZeroTTS voice ID) ─────────────────────────
ZEROTTS_VOICES: dict[str, str] = {
    # ── Giọng Nữ ────────────────────────────────────────────────────────────
    "🇻🇳 Mai Chi — Nữ · Trẻ · Kể chuyện · Nhẹ nhàng · Thân thiện":      "maichi",
    "🇻🇳 Bảo Trang — Nữ · Trưởng thành · Tin tức · Rõ ràng · Trung tính": "baotrang",
    "🇻🇳 Hà My — Nữ · Trẻ · Hoạt hình · Cao · Biểu cảm":                "hamy",
    "🇻🇳 Kim Oanh — Nữ · Trung niên · Kể chuyện · Ấm áp · Truyền cảm":  "kimoanh",
    # ── Giọng Nam ────────────────────────────────────────────────────────────
    "🇻🇳 Gia Huy — Nam · Trẻ · Kể chuyện · Trầm ấm · Tâm tình":         "giahuy",
    "🇻🇳 Quang Minh — Nam · Trẻ · Tin tức · Rõ ràng · Dứt khoát":        "quangminh",
    "🇻🇳 Tiến Đạt — Nam · Trẻ · Bình luận · Sôi nổi · Năng lượng cao":   "tiendat",
    "🇻🇳 Hữu Đức — Nam · Lớn tuổi · Kể chuyện · Trầm · Điềm đạm":       "huuduc",
}

ZEROTTS_DEFAULT_VOICE = "maichi"


def _get_tts():
    global _tts_instance
    if _tts_instance is not None:
        return _tts_instance
    if not _ZEROTTS_OK:
        return None
    try:
        print("[ZeroTTS] Loading model...")
        _tts_instance = ZeroTTS.from_pretrained("zeroweight-ai/ZeroTTS")
        print("[ZeroTTS] ✅ Model loaded!")
        return _tts_instance
    except Exception as e:
        print(f"[ZeroTTS] ❌ Load model failed: {e}")
        return None


def _wav_to_mp3(wav_path: str, mp3_path: str, ffmpeg_bin: str = "ffmpeg") -> bool:
    try:
        result = subprocess.run(
            [ffmpeg_bin, "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-q:a", "2", mp3_path],
            capture_output=True, timeout=30
        )
        return result.returncode == 0 and Path(mp3_path).exists()
    except Exception:
        return False


def _chunk_vi_text(text: str, max_chunk_sec: float = 12.0) -> list:
    try:
        segments = [
            clean_segment_punctuation(s)
            for s in chunk_text(normalize_punctuation(text), max_chunk_sec=max_chunk_sec)
        ]
        return [s for s in segments if s.strip()]
    except Exception:
        import re
        parts = re.split(r'(?<=[.!?…])\s+', text)
        chunks, current = [], ""
        for p in parts:
            if len(current) + len(p) < 400:
                current = (current + " " + p).strip()
            else:
                if current:
                    chunks.append(current)
                current = p
        if current:
            chunks.append(current)
        return chunks or [text]


def tts_zerotts(
    text: str,
    voice: str = "maichi",
    out_path: Optional[str] = None,
    ffmpeg_bin: str = "ffmpeg",
    output_format: str = "mp3",
) -> Optional[str]:
    """
    Generate speech với ZeroTTS. Return audio path hoặc None nếu lỗi.
    voice: ZeroTTS voice ID ('maichi') hoặc display key từ ZEROTTS_VOICES.
    """
    if not _ZEROTTS_OK:
        print(f"[ZeroTTS] Not available: {_ZEROTTS_IMPORT_ERR}")
        return None

    # Resolve display name → voice ID
    voice_id = ZEROTTS_VOICES.get(voice, voice) if voice else ZEROTTS_DEFAULT_VOICE

    tts = _get_tts()
    if tts is None:
        return None

    if out_path is None:
        suffix = ".mp3" if output_format == "mp3" else ".wav"
        out_path = str(Path(tempfile.gettempdir()) / f"zerotts_{uuid.uuid4().hex}{suffix}")
    out_path = str(out_path)

    try:
        chunks = _chunk_vi_text(text)
        print(f"[ZeroTTS] Synthesizing {len(chunks)} chunk(s), voice='{voice_id}'...")

        import numpy as np
        all_audio = []
        for i, chunk in enumerate(chunks):
            if len(chunks) > 1:
                print(f"[ZeroTTS]   chunk {i+1}/{len(chunks)}: {chunk[:60]}...")
            all_audio.append(tts.synthesize(chunk, voice=voice_id))

        # Concat với silence 0.2s giữa các đoạn
        if len(all_audio) > 1:
            silence = np.zeros((1, int(tts.sample_rate * 0.2)), dtype="float32")
            parts = []
            for j, a in enumerate(all_audio):
                parts.append(a)
                if j < len(all_audio) - 1:
                    parts.append(silence)
            combined = np.concatenate(parts, axis=1)
        else:
            combined = all_audio[0]

        # Save
        if output_format == "mp3":
            wav_tmp = out_path.replace(".mp3", "_tmp.wav")
            tts.save_audio(combined, wav_tmp)
            if _wav_to_mp3(wav_tmp, out_path, ffmpeg_bin):
                Path(wav_tmp).unlink(missing_ok=True)
            else:
                # ffmpeg không có — giữ WAV, đổi extension
                out_path = out_path.replace(".mp3", ".wav")
                shutil.move(wav_tmp, out_path)
        else:
            tts.save_audio(combined, out_path)

        if Path(out_path).exists() and Path(out_path).stat().st_size > 1000:
            print(f"[ZeroTTS] ✅ {out_path} ({Path(out_path).stat().st_size // 1024}KB)")
            return out_path

        print(f"[ZeroTTS] ❌ Output file missing or too small")
        return None

    except Exception as e:
        print(f"[ZeroTTS] ❌ Synthesis error: {e}")
        import traceback; traceback.print_exc()
        return None


def is_available() -> bool:
    return _ZEROTTS_OK


def list_display_voices() -> list:
    return list(ZEROTTS_VOICES.keys())
