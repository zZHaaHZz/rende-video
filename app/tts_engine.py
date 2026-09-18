"""
app/tts_engine.py — TTS dispatcher: CapCut → Edge TTS → ZeroTTS → Groq Orpheus.
"""
import asyncio
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

import requests

from app.config import FFMPEG, AUDIO_DIR
from app.subtitle import make_srt, srt_to_words

# ── Edge voice map ────────────────────────────────────────────────────────────
EDGE_VOICES = {
    "en-US":   "en-US-GuyNeural",
    "vi-VN":   "vi-VN-NamMinhNeural",
    "en-female": "en-US-JennyNeural",
    "vi-female": "vi-VN-HoaiMyNeural",
    "ko-KR":   "ko-KR-InJoonNeural",
    "ko-female": "ko-KR-SunHiNeural",
    "🆻🇳 NamMinh (Nam — Long-form)":   "vi-VN-NamMinhNeural",
    "🆻🇳 NamMinh (Nam — Shorts x1.4)":  "vi-VN-NamMinhNeural",
    "🆻🇳 HoaiMy (Nữ)":                  "vi-VN-HoaiMyNeural",
    "🇰🇷 Hyunsu Đa Ngôn Ngữ (Nam)":     "ko-KR-HyunsuMultilingualNeural",
    "🇰🇷 InJoon (Nam)":                  "ko-KR-InJoonNeural",
    "🇰🇷 SunHi (Nữ)":                   "ko-KR-SunHiNeural",
    "🇺🇸 Guy (Nam)":                     "en-US-GuyNeural",
    "🇺🇸 Jenny (Nữ)":                   "en-US-JennyNeural",
    "ja-JP":   "ja-JP-KeitaNeural",
    "ja-female": "ja-JP-NanamiNeural",
}

KOREAN_EDGE_VOICES = [
    "🇰🇷 Hyunsu Đa Ngôn Ngữ (Nam)",
    "🇰🇷 InJoon (Nam)",
    "🇰🇷 SunHi (Nữ)",
]

# ── CapCut circuit breaker ────────────────────────────────────────────────────
_CAPCUT_FAIL_COUNT = 0
_CAPCUT_SKIP = False


# ── Text chunking ─────────────────────────────────────────────────────────────
def _split_text_chunks(text: str, max_chars: int = 350) -> list:
    """Split text into chunks ≤ max_chars, breaking at sentence boundaries."""
    import re as _re
    sentences = _re.split(r'(?<=[.!?])\s+', text.strip())
    chunks, current = [], ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if len(sent) > max_chars:
            parts = _re.split(r'(?<=,)\s+', sent)
            for part in parts:
                if len(current) + len(part) + 1 <= max_chars:
                    current = (current + " " + part).strip() if current else part
                else:
                    if current:
                        chunks.append(current)
                    while len(part) > max_chars:
                        chunks.append(part[:max_chars])
                        part = part[max_chars:]
                    current = part
        else:
            if len(current) + len(sent) + 1 <= max_chars:
                current = (current + " " + sent).strip() if current else sent
            else:
                if current:
                    chunks.append(current)
                current = sent
    if current:
        chunks.append(current)
    return chunks or [text]


def _concat_audio_chunks(chunk_paths: list, out_path: str) -> bool:
    """Dùng FFmpeg nối nhiều file audio thành 1 file duy nhất."""
    if not chunk_paths:
        return False
    if len(chunk_paths) == 1:
        import shutil as _sh
        _sh.copy(chunk_paths[0], out_path)
        return True
    try:
        import tempfile as _tf
        list_file = Path(_tf.gettempdir()) / f"concat_{uuid.uuid4().hex}.txt"
        list_file.write_text(
            "\n".join(f"file '{p}'" for p in chunk_paths), encoding="utf-8"
        )
        from app.ffmpeg_utils import ffmpeg
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(list_file),
               "-c:a", "aac", "-b:a", "128k", "-y", out_path)
        list_file.unlink(missing_ok=True)
        return Path(out_path).exists() and Path(out_path).stat().st_size > 1000
    except Exception as e:
        print(f"[concat_audio] {e}")
        return False


# ── Edge TTS ──────────────────────────────────────────────────────────────────
def tts_edge_with_timing(text: str, voice_key: str = "en-US",
                          audio_out=None, srt_out=None, rate: str = "1.0"):
    """Edge TTS with word-level timing. Auto-retry khi bị rate-limit."""
    import edge_tts
    voice = EDGE_VOICES.get(voice_key, voice_key)
    audio_out = audio_out or (AUDIO_DIR / f"{uuid.uuid4().hex}.mp3")

    async def _run():
        try:
            _rate_pct = round((float(rate) - 1.0) * 100)
            _rate_str = f"+{_rate_pct}%" if _rate_pct >= 0 else f"{_rate_pct}%"
        except Exception:
            _rate_str = "+0%"
        comm = edge_tts.Communicate(text, voice, rate=_rate_str)
        words, audio_bytes = [], bytearray()
        async for ev in comm.stream():
            if ev["type"] == "audio":
                audio_bytes.extend(ev["data"])
            elif ev["type"] == "WordBoundary":
                start = ev["offset"] / 10_000_000
                dur   = ev["duration"] / 10_000_000
                words.append({"word": ev["text"], "start": start, "end": start + dur})
        Path(audio_out).write_bytes(bytes(audio_bytes))
        if not audio_bytes:
            raise RuntimeError("No audio received — rate-limited by Edge TTS")
        return words

    def _run_in_thread():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        try:
            return _loop.run_until_complete(_run())
        finally:
            _loop.close()

    for attempt in range(3):
        try:
            _sleep = 1.5 if attempt == 0 else (2.5 * attempt)
            time.sleep(_sleep)

            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=1) as _exe:
                words = _exe.submit(_run_in_thread).result(timeout=60)

            if Path(audio_out).exists() and Path(audio_out).stat().st_size > 1000:
                _audio_dur = 5.0
                try:
                    _probe_dur = subprocess.run(
                        [FFMPEG, "-i", str(audio_out), "-f", "null", "-"],
                        capture_output=True, text=True
                    )
                    for _line in _probe_dur.stderr.split("\n"):
                        if "Duration:" in _line:
                            _ts = _line.split("Duration:")[1].split(",")[0].strip()
                            _hh, _mm, _ss = _ts.split(":")
                            _audio_dur = int(_hh)*3600 + int(_mm)*60 + float(_ss)
                            break
                except Exception as _pe:
                    print(f"[TTS] Duration probe failed: {_pe}")

                def _cjk_w(ch):
                    cp = ord(ch)
                    if (0xAC00 <= cp <= 0xD7A3 or 0x1100 <= cp <= 0x11FF
                            or 0x4E00 <= cp <= 0x9FFF or 0x3040 <= cp <= 0x30FF):
                        return 1.8
                    return 1.0

                text_words = text.split()
                if not words:
                    if text_words and _audio_dur > 0:
                        _char_lens = [max(1.0, sum(_cjk_w(c) for c in w)) for w in text_words]
                        _total_chars = sum(_char_lens)
                        _t = 0.0
                        for _w, _cl in zip(text_words, _char_lens):
                            _wd = _audio_dur * _cl / _total_chars
                            words.append({"word": _w, "start": _t, "end": _t + _wd})
                            _t += _wd
                else:
                    _n_boundary = len(words)
                    _n_text     = len(text_words)
                    if _n_boundary < _n_text:
                        _last_end = words[-1]["end"] if words else 0.0
                        _remaining_dur = max(0.05, _audio_dur - _last_end)
                        _missing_words = text_words[_n_boundary:]
                        _ml = [max(1.0, sum(_cjk_w(c) for c in w)) for w in _missing_words]
                        _mt = sum(_ml) or 1.0
                        _t = _last_end
                        for _mw, _mc in zip(_missing_words, _ml):
                            _md = _remaining_dur * _mc / _mt
                            words.append({"word": _mw, "start": _t, "end": _t + _md})
                            _t += _md
                        print(f"[TTS] Filled {len(_missing_words)} missing tail word(s): {_missing_words}")

                _is_cjk = any(
                    0xAC00 <= ord(c) <= 0xD7A3 or 0x4E00 <= ord(c) <= 0x9FFF or 0x3040 <= ord(c) <= 0x30FF
                    for c in text if c.strip()
                )
                srt = make_srt(words, group=3 if _is_cjk else 4)
                if srt_out and srt:
                    Path(srt_out).write_text(srt, encoding="utf-8")
                return str(audio_out), srt
        except Exception as e:
            print(f"[EdgeTTS] attempt {attempt+1}/3 fail: {e}")
    return None, None


def tts_edge(text: str, voice_key: str = "en-US", out_path=None):
    """Simple Edge TTS without timing (fallback)."""
    audio, _ = tts_edge_with_timing(text, voice_key, out_path)
    return audio


# ── Groq Orpheus TTS ──────────────────────────────────────────────────────────
def tts_groq_api(text: str, voice: str = "troy", out_path=None, cfg: dict = None):
    """Groq Orpheus English TTS fallback."""
    cfg = cfg or {}
    key = (cfg.get("groq") or [None])[0]
    if not key:
        return None
    try:
        chunks = _split_text_chunks(text, max_chars=190)
        chunk_paths = []
        for chunk in chunks:
            r = requests.post(
                "https://api.groq.com/openai/v1/audio/speech",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": "canopylabs/orpheus-v1-english",
                    "input": chunk,
                    "voice": voice,
                    "response_format": "wav",
                },
                timeout=60,
            )
            if not r.ok:
                print(f"[GroqTTS/Orpheus] HTTP {r.status_code}: {r.text[:200]}")
                return None
            chunk_path = AUDIO_DIR / f"{uuid.uuid4().hex}_orpheus.wav"
            chunk_path.write_bytes(r.content)
            chunk_paths.append(str(chunk_path))
        out_path = Path(out_path or (AUDIO_DIR / f"{uuid.uuid4().hex}_orpheus.m4a"))
        if _concat_audio_chunks(chunk_paths, str(out_path)):
            return str(out_path)
    except Exception as e:
        print(f"[GroqTTS/Orpheus] {e}")
    return None


# ── Main TTS dispatcher ───────────────────────────────────────────────────────
def tts(text: str, voice_cfg: str = "en-US", srt_out=None, rate: str = "1.0",
        allow_edge_fallback: bool = True,
        cfg: dict = None,
        capcut_ok: bool = False, capcut_module=None,
        zerotts_ok: bool = False, zerotts_module=None):
    """Try CapCut TTS (chunked) → ZeroTTS → Edge TTS → Groq.
    voice_cfg: CapCut display key hoặc legacy Edge key (e.g. 'en-US', 'vi-VN').
    """
    global _CAPCUT_FAIL_COUNT, _CAPCUT_SKIP
    cfg = cfg or {}

    # Normalize text
    from vietnamese_tts import normalize_vietnamese_tts
    from korean_tts import normalize_korean_tts
    if "🇻🇳" in voice_cfg or voice_cfg in ("vi-VN", "vi-female"):
        text = normalize_vietnamese_tts(text, voice_key=voice_cfg)
    if "🇰🇷" in voice_cfg or voice_cfg in ("ko-KR", "ko-female"):
        text = normalize_korean_tts(text)

    # ── ZeroTTS (local offline) ───────────────────────────────────────────────
    if zerotts_ok and zerotts_module and voice_cfg in zerotts_module.ZEROTTS_VOICES:
        _zt_audio_raw = AUDIO_DIR / f"{uuid.uuid4().hex}_zt_raw.mp3"
        result = zerotts_module.tts_zerotts(
            text,
            voice=voice_cfg,
            out_path=str(_zt_audio_raw),
            ffmpeg_bin=FFMPEG or "ffmpeg",
        )
        if result and Path(result).exists():
            if srt_out:
                try:
                    _ffmpeg_bin = FFMPEG or "ffmpeg"
                    _zt_dur1x = 0.0
                    _zt_pb = subprocess.run(
                        [_ffmpeg_bin, "-i", str(result), "-f", "null", "-"],
                        capture_output=True, text=True
                    )
                    for _ln in _zt_pb.stderr.split("\n"):
                        if "Duration:" in _ln:
                            _ts = _ln.split("Duration:")[1].split(",")[0].strip()
                            _h, _m, _s = _ts.split(":")
                            _zt_dur1x = int(_h)*3600 + int(_m)*60 + float(_s)
                            break
                    _zt_toks = text.split()
                    _zt_tok_dur = _zt_dur1x / max(len(_zt_toks), 1)
                    _zt_words_1x = []
                    for _i, _w in enumerate(_zt_toks):
                        _ws = _i * _zt_tok_dur
                        _zt_words_1x.append({"word": _w, "start": _ws, "end": _ws + _zt_tok_dur})
                    try:
                        _zt_rate_f = float(rate) if rate else 1.0
                    except Exception:
                        _zt_rate_f = 1.0
                    _zt_scale = 1.0 / _zt_rate_f if _zt_rate_f > 0 else 1.0
                    _zt_words_fast = [
                        {"word": w["word"], "start": w["start"]*_zt_scale, "end": w["end"]*_zt_scale}
                        for w in _zt_words_1x
                    ]
                    _zt_srt = make_srt(_zt_words_fast, group=4)
                    if _zt_srt:
                        Path(srt_out).write_text(_zt_srt, encoding="utf-8")
                except Exception as _zt_srt_err:
                    print(f"[ZeroTTS] SRT gen failed: {_zt_srt_err}")

            try:
                _zt_rate = float(rate) if rate else 1.0
            except (TypeError, ValueError):
                _zt_rate = 1.0
            if abs(_zt_rate - 1.0) < 0.05:
                return result
            _zt_audio_fast = AUDIO_DIR / f"{uuid.uuid4().hex}_zt_speed.mp3"
            try:
                if 0.5 <= _zt_rate <= 2.0:
                    _atempo_chain = f"atempo={_zt_rate:.3f}"
                elif _zt_rate > 2.0:
                    _atempo_chain = f"atempo=2.0,atempo={_zt_rate/2.0:.3f}"
                else:
                    _atempo_chain = f"atempo=0.5,atempo={_zt_rate/0.5:.3f}"
                _sp_ret = subprocess.run(
                    [FFMPEG or "ffmpeg", "-i", str(result),
                     "-af", _atempo_chain,
                     "-codec:a", "libmp3lame", "-q:a", "2",
                     "-y", str(_zt_audio_fast)],
                    capture_output=True, timeout=60
                )
                if _sp_ret.returncode == 0 and _zt_audio_fast.exists() and _zt_audio_fast.stat().st_size > 1000:
                    Path(result).unlink(missing_ok=True)
                    return str(_zt_audio_fast)
            except Exception as _zt_spd_err:
                print(f"[ZeroTTS] atempo speed adjust failed: {_zt_spd_err}")
            return result
        print("[TTS] ZeroTTS failed → fallback Edge TTS")

    # ── CapCut TTS ────────────────────────────────────────────────────────────
    _cc = capcut_module
    if capcut_ok and not _CAPCUT_SKIP and _cc and voice_cfg in _cc.CAPCUT_VOICES:
        CAPCUT_MAX_CHARS = 350
        chunks = _split_text_chunks(text, max_chars=CAPCUT_MAX_CHARS) if len(text) > CAPCUT_MAX_CHARS else [text]
        if len(chunks) > 1:
            print(f"[TTS] Chunked: {len(text)} chars → {len(chunks)} chunks")

        chunk_audio_paths = []
        all_srt_words = []
        time_offset = 0.0
        chunk_failed = False

        for ci, chunk_text in enumerate(chunks):
            chunk_audio = AUDIO_DIR / f"{uuid.uuid4().hex}_c{ci}.mp3"
            chunk_srt   = AUDIO_DIR / f"{uuid.uuid4().hex}_c{ci}.srt" if srt_out else None
            audio, _ = _cc.tts_capcut(
                chunk_text,
                voice_key=voice_cfg,
                rate=rate,
                out_path=chunk_audio,
                srt_out=str(chunk_srt) if chunk_srt else None,
                ffmpeg_bin=FFMPEG or "ffmpeg",
            )
            if not audio:
                print(f"[TTS] CapCut chunk {ci+1} lần 1 fail → cooldown 5s rồi retry...")
                time.sleep(5)
                chunk_audio2 = AUDIO_DIR / f"{uuid.uuid4().hex}_c{ci}_r.mp3"
                audio, _ = _cc.tts_capcut(
                    chunk_text,
                    voice_key=voice_cfg,
                    rate=rate,
                    out_path=chunk_audio2,
                    srt_out=str(chunk_srt) if chunk_srt else None,
                    ffmpeg_bin=FFMPEG or "ffmpeg",
                )
                if audio:
                    chunk_audio = chunk_audio2
                    print(f"[TTS] CapCut chunk {ci+1} retry thành công ✅")
            if not audio:
                print(f"[TTS] CapCut chunk {ci+1}/{len(chunks)} failed sau retry")
                chunk_failed = True
                break

            chunk_audio_paths.append(str(chunk_audio))
            if srt_out and chunk_srt and chunk_srt.exists():
                words = srt_to_words(str(chunk_srt))
                for w in words:
                    w["start"] += time_offset
                    w["end"]   += time_offset
                all_srt_words.extend(words)

            try:
                probe = subprocess.run(
                    [FFMPEG, "-i", str(chunk_audio), "-f", "null", "-"],
                    capture_output=True, text=True
                )
                for line in probe.stderr.split("\n"):
                    if "Duration:" in line:
                        ts = line.split("Duration:")[1].split(",")[0].strip()
                        hh, mm, ss = ts.split(":")
                        time_offset += int(hh)*3600 + int(mm)*60 + float(ss)
                        break
            except Exception:
                time_offset += len(chunk_text.split()) / 3.5

            if ci < len(chunks) - 1:
                time.sleep(2)

        if not chunk_failed and chunk_audio_paths:
            final_audio = AUDIO_DIR / f"{uuid.uuid4().hex}.mp3"
            if _concat_audio_chunks(chunk_audio_paths, str(final_audio)):
                if srt_out and all_srt_words:
                    srt_content = make_srt(all_srt_words, group=4)
                    Path(srt_out).write_text(srt_content, encoding="utf-8")
                _CAPCUT_FAIL_COUNT = 0
                return str(final_audio)

        _CAPCUT_FAIL_COUNT += 1
        if allow_edge_fallback and _CAPCUT_FAIL_COUNT >= 4:
            _CAPCUT_SKIP = True
            print(f"[TTS] CapCut failed {_CAPCUT_FAIL_COUNT}x → CIRCUIT BREAKER ON")
        if not allow_edge_fallback:
            return None

    # ── Edge TTS fallback ─────────────────────────────────────────────────────
    _vn_female_hints = ["cô gái", "nữ", "mai", "gái", "hoài my", "hoaimy", "ngọt", "review", "bản tin nữ", "female", "jenny", "sherry"]
    _key_lower = voice_cfg.lower()

    if voice_cfg in EDGE_VOICES:
        edge_key = voice_cfg
    elif "🇻🇳" in voice_cfg:
        is_female_vn = any(h in _key_lower for h in _vn_female_hints)
        edge_key = "vi-female" if is_female_vn else "vi-VN"
    elif "🇰🇷" in voice_cfg:
        is_female_kr = any(h in _key_lower for h in ["여성", "female", "sunhi", "sun", "cute"])
        edge_key = "ko-female" if is_female_kr else "ko-KR"
    elif "🇺🇸" in voice_cfg:
        is_female_en = any(h in _key_lower for h in ["female", "jenny", "sherry", "janeamber"])
        edge_key = "en-female" if is_female_en else "en-US"
    else:
        edge_key = "en-US"

    audio_path = AUDIO_DIR / f"{uuid.uuid4().hex}.mp3"
    audio, srt = tts_edge_with_timing(text, edge_key, audio_path, srt_out, rate=rate)
    if audio:
        return audio

    # ── Groq Orpheus last resort ──────────────────────────────────────────────
    _looks_english = (
        voice_cfg in ("en-US", "en-female")
        or "🇺🇸" in voice_cfg
        or "english" in voice_cfg.lower()
    )
    return tts_groq_api(text, "troy", cfg=cfg) if _looks_english else None


def srt_from_audio(audio_path: str, text: str, srt_path: str, tts_rate: str = "1.0") -> float:
    """Generate SRT from audio using proportional character timing."""
    dur = 5.0
    try:
        probe = subprocess.run(
            [FFMPEG, "-i", str(audio_path), "-f", "null", "-"],
            capture_output=True, text=True
        )
        for line in probe.stderr.split("\n"):
            if "Duration:" in line:
                ts = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = ts.split(":")
                dur = int(h)*3600 + int(m)*60 + float(s)
                break
    except Exception as e:
        print(f"[srt_from_audio] probe failed: {e}")

    text_words = text.split()
    if not text_words or dur <= 0:
        return dur

    def _char_weight(ch):
        cp = ord(ch)
        if (0xAC00 <= cp <= 0xD7A3 or 0x1100 <= cp <= 0x11FF
                or 0x4E00 <= cp <= 0x9FFF or 0x3040 <= cp <= 0x30FF):
            return 1.8
        return 1.0

    char_lens = [max(1.0, sum(_char_weight(c) for c in w)) for w in text_words]
    total_chars = sum(char_lens)
    t, words = 0.0, []
    for w, cl in zip(text_words, char_lens):
        wd = dur * cl / total_chars
        words.append({"word": w, "start": t, "end": t + wd})
        t += wd
    print(f"[srt_from_audio] char-proportion: {len(words)} words, {dur:.2f}s total")

    _is_cjk_lang = any(
        0xAC00 <= ord(c) <= 0xD7A3 or 0x4E00 <= ord(c) <= 0x9FFF or 0x3040 <= ord(c) <= 0x30FF
        for c in text if c.strip()
    )
    _group = 3 if _is_cjk_lang else 4

    srt = make_srt(words, group=_group)
    if srt:
        Path(srt_path).write_text(srt, encoding="utf-8")
    return dur
