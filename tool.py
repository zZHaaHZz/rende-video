"""
AI Video Creator — Python Streamlit App
Chạy: streamlit run tool.py
"""
import streamlit as st
import asyncio, json, os, re, uuid, base64, subprocess, shutil, time, tempfile, random
from typing import Optional
from pathlib import Path
import requests

# ── CapCut TTS ────────────────────────────────────────────────────────────────
try:
    import capcut_tts as _cc
    _CAPCUT_OK = _cc.is_available()
except Exception as _cce:
    _CAPCUT_OK = False
    print(f"[tool] CapCut TTS not loaded: {_cce}")

st.set_page_config(page_title="AI Video Creator", page_icon="🎬", layout="wide")

# Prefer ffmpeg-full (has libass/subtitles filter) over standard ffmpeg
FFMPEG = (
    shutil.which("/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg")
    or shutil.which("ffmpeg")
    or shutil.which("/opt/homebrew/bin/ffmpeg")
)
TMP = Path(tempfile.gettempdir()) / "avc"
TMP.mkdir(exist_ok=True)
AUDIO_DIR = Path.home() / ".avc_audio"  # Permanent audio cache
AUDIO_DIR.mkdir(exist_ok=True)

# ── Persistent settings via session_state + JSON file ────────────────────────
CFG_FILE = Path.home() / ".avc_config.json"

def load_cfg():
    if CFG_FILE.exists():
        try: return json.loads(CFG_FILE.read_text())
        except: pass
    return {"gemini": [], "groq": [], "pexels": [], "pixabay": "", "openai": ""}

def save_cfg(cfg):
    CFG_FILE.write_text(json.dumps(cfg, indent=2))

if "cfg" not in st.session_state:
    st.session_state.cfg = load_cfg()

# Project state (persisted in JSON)
PROJ_FILE = Path.home() / ".avc_project.json"

def load_proj():
    if PROJ_FILE.exists():
        try: return json.loads(PROJ_FILE.read_text())
        except: pass
    return {"script": None, "scenes": [], "step": 0}

def save_proj(p):
    PROJ_FILE.write_text(json.dumps(p, ensure_ascii=False, indent=2))

if "proj" not in st.session_state:
    st.session_state.proj = load_proj()

cfg = st.session_state.cfg
proj = st.session_state.proj

# ── AI helpers ────────────────────────────────────────────────────────────────
def call_gemini(key, prompt):
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}",
        json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.85, "maxOutputTokens": 8192}},
        timeout=60,
    )
    d = r.json()
    if not r.ok: raise Exception(d.get("error", {}).get("message", f"Gemini {r.status_code}"))
    return d["candidates"][0]["content"]["parts"][0]["text"].replace("```json", "").replace("```", "").strip()

def call_groq_llm(key, prompt):
    for model in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.85, "max_tokens": 8192},
            timeout=60,
        )
        d = r.json()
        if r.status_code in (400, 404): continue
        if not r.ok: raise Exception(d.get("error", {}).get("message", f"Groq {r.status_code}"))
        return d["choices"][0]["message"]["content"].replace("```json", "").replace("```", "").strip()
    raise Exception("All Groq models unavailable")

def call_ai(prompt):
    last_err = None
    # Try Gemini — skip on ANY error (quota, billing, rate limit)
    for key in cfg.get("gemini", []):
        try:
            return call_gemini(key, prompt)
        except Exception as e:
            last_err = str(e)
            print(f"[Gemini] skip: {str(e)[:80]}")
            continue  # try next key or fallback to Groq
    # Fallback: Groq LLM (free, no billing needed)
    for key in cfg.get("groq", []):
        try:
            return call_groq_llm(key, prompt)
        except Exception as e:
            if "429" not in str(e) and "rate" not in str(e).lower():
                raise
            last_err = str(e)
    if last_err:
        raise Exception(f"Tất cả key lỗi. Lỗi cuối: {last_err[:150]}")
    raise Exception("Chưa có API key! Vào Settings thêm Gemini hoặc Groq key.")

def parse_json_robust(raw: str) -> dict:
    """Parse AI-generated JSON that may contain common formatting issues:
    - Markdown code fences (```json ... ```)
    - Trailing commas before } or ]
    - Smart/curly quotes replaced with straight quotes
    - Embedded literal newlines inside string values
    - Truncated responses (no closing brace) — raises a clear error
    Raises json.JSONDecodeError if all attempts fail.
    """
    import re as _re
    # 1. Strip markdown code fences
    text = raw.strip()
    text = _re.sub(r'^```(?:json)?\s*', '', text, flags=_re.MULTILINE)
    text = _re.sub(r'```\s*$', '', text, flags=_re.MULTILINE)
    text = text.strip()

    # 2. Detect truncation: JSON started but no matching closing brace
    brace_start = text.find('{')
    brace_end   = text.rfind('}')
    if brace_start != -1 and brace_end == -1:
        raise json.JSONDecodeError(
            "AI response was TRUNCATED (no closing brace found). "
            "Increase maxOutputTokens or shorten the prompt. "
            f"Response ends with: ...{raw[-120:]!r}",
            raw, len(raw)
        )
    if brace_start == -1:
        raise json.JSONDecodeError(
            f"AI response contains no JSON object. Raw: {raw[:300]!r}",
            raw, 0
        )

    # 3. Extract the outermost {...} block (handles preamble text)
    text = text[brace_start:brace_end + 1]

    # 4. Replace smart quotes with straight quotes
    for src, dst in [('\u201c', '"'), ('\u201d', '"'), ('\u2018', "'"), ('\u2019', "'")]:
        text = text.replace(src, dst)

    # 5. Remove trailing commas before } or ] (invalid in JSON)
    text = _re.sub(r',\s*([\]}])', r'\1', text)

    # 6. First attempt: plain parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 7. Second attempt: collapse unescaped literal newlines inside string values
    text2 = _re.sub(r'(?<!\\)\n', ' ', text)
    try:
        return json.loads(text2)
    except json.JSONDecodeError:
        pass

    # 8. Last attempt: ast.literal_eval (handles single-quoted Python dicts)
    import ast as _ast
    try:
        obj = _ast.literal_eval(text)
        return json.loads(json.dumps(obj, ensure_ascii=False))
    except Exception:
        pass

    # All attempts failed — raise with helpful snippet
    raise json.JSONDecodeError(
        f"parse_json_robust: all parse attempts failed. First 300 chars: {raw[:300]!r}",
        raw, 0
    )

# ── OpenAI DALL-E 3 Thumbnail ─────────────────────────────────────────────────
def generate_thumbnail_openai(script: dict, openai_key: str, W: int, H: int,
                              save_dir: Optional[Path] = None):
    """
    Gọi OpenAI DALL-E 3 để tạo thumbnail.
    Trả về tuple (Path | None, error_msg | None).
    Size: 1792x1024 (16:9) hoặc 1024x1792 (9:16).
    """
    title = script.get("title", "video")
    desc  = script.get("description", "")
    tags  = ", ".join(script.get("tags", [])[:5])
    size  = "1792x1024" if W > H else "1024x1792"

    prompt = (
        f"A hyper-realistic, cinematic YouTube thumbnail for a video titled: \"{title}\". "
        f"Topic: {desc[:200]}. Themes: {tags}. "
        "Style: dramatic lighting, vibrant colors, bold composition, photorealistic. "
        "NO text, no watermarks, no borders."
    )

    try:
        r = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {openai_key}"},
            json={"model": "dall-e-3", "prompt": prompt, "n": 1,
                  "size": size, "response_format": "b64_json"},
            timeout=90,
        )
        if not r.ok:
            api_err = r.json().get("error", {})
            code    = r.status_code
            raw_msg = api_err.get("message", r.text[:300])
            if code in (401, 403):
                msg = f"OpenAI key không hợp lệ hoặc hết hạn (HTTP {code})."
            elif code == 429:
                msg = f"Vượt quota OpenAI (HTTP {code}) — thử lại sau."
            elif "billing" in raw_msg.lower() or "insufficient" in raw_msg.lower():
                msg = f"Tài khoản OpenAI chưa có credit (HTTP {code}) — nạp thêm tại platform.openai.com/billing."
            else:
                msg = f"OpenAI DALL-E lỗi (HTTP {code}): {raw_msg[:200]}"
            print(f"[Thumbnail/OpenAI] {msg}")
            return None, msg

        import base64 as _b64
        b64 = r.json()["data"][0]["b64_json"]
        img_bytes = _b64.b64decode(b64)
        save_dir = save_dir or (Path.home() / "Desktop" / "AI_Videos")
        save_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:40] or "thumb"
        out  = save_dir / f"{safe}_thumbnail.jpg"
        out.write_bytes(img_bytes)
        return out, None

    except Exception as e:
        msg = f"Lỗi không xác định (OpenAI): {e}"
        print(f"[Thumbnail/OpenAI] {msg}")
        return None, msg


def generate_thumbnail(script: dict, gemini_key: Optional[str], W: int, H: int,
                       save_dir: Optional[Path] = None, openai_key: Optional[str] = None):
    """
    Tạo thumbnail: thử OpenAI DALL-E 3 trước, fallback sang Gemini Imagen 3.
    Trả về tuple (Path | None, error_msg | None).
    """
    # 1️⃣ Ưu tiên OpenAI DALL-E 3
    if openai_key:
        print("[Thumbnail] Thử OpenAI DALL-E 3...")
        path, err = generate_thumbnail_openai(script, openai_key, W, H, save_dir)
        if path:
            return path, None
        print(f"[Thumbnail] OpenAI thất bại: {err}")

    # 2️⃣ Fallback: Gemini Imagen 3
    if not gemini_key:
        if openai_key:
            # OpenAI đã thử nhưng fail
            msg = f"OpenAI DALL-E thất bại và không có Gemini key để fallback."
        else:
            msg = "Chưa có OpenAI key lẫn Gemini key — vào Settings để thêm ít nhất 1 key."
        print(f"[Thumbnail] {msg}")
        return None, msg

    print("[Thumbnail] Thử Gemini Imagen 3...")
    title   = script.get("title", "video")
    desc    = script.get("description", "")
    tags    = ", ".join(script.get("tags", [])[:5])
    ar      = "16:9" if W > H else "9:16"

    prompt = (
        f"Create a hyper-realistic, eye-catching YouTube / TikTok thumbnail for a video titled: \"{title}\". "
        f"Topic summary: {desc[:200]}. Related themes: {tags}. "
        "Style: cinematic, vibrant colors, dramatic lighting, bold composition. "
        "NO text overlay, no watermarks, no borders. "
        f"Aspect ratio {ar}, high resolution, photorealistic."
    )

    try:
        import base64 as _b64
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-008:predict?key={gemini_key}",
            json={"instances": [{"prompt": prompt}],
                  "parameters": {"sampleCount": 1, "aspectRatio": ar, "personGeneration": "allow_adult"}},
            timeout=60,
        )
        if not r.ok:
            api_err = r.json().get("error", {})
            code    = api_err.get("code", r.status_code)
            raw_msg = api_err.get("message", r.text[:300])
            if code in (403, 401) or "API_KEY" in raw_msg.upper() or "PERMISSION" in raw_msg.upper():
                msg = f"Gemini Imagen: key không có quyền (HTTP {code}) — cần bật Imagen API và billing."
            elif code == 429 or "QUOTA" in raw_msg.upper():
                msg = f"Gemini Imagen: vượt quota (HTTP {code})."
            elif "BILLING" in raw_msg.upper() or "PAYMENT" in raw_msg.upper():
                msg = f"Gemini Imagen: chưa bật billing (HTTP {code}) — yêu cầu tài khoản có thanh toán."
            else:
                msg = f"Gemini Imagen lỗi (HTTP {code}): {raw_msg[:200]}"
            print(f"[Thumbnail/Gemini] {msg}")
            return None, msg

        data = r.json()
        b64  = data["predictions"][0]["bytesBase64Encoded"]
        img_bytes = _b64.b64decode(b64)
        save_dir = save_dir or (Path.home() / "Desktop" / "AI_Videos")
        save_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:40] or "thumb"
        out  = save_dir / f"{safe}_thumbnail.jpg"
        out.write_bytes(img_bytes)
        return out, None

    except Exception as e:
        msg = f"Lỗi không xác định (Gemini): {e}"
        print(f"[Thumbnail/Gemini] {msg}")
        return None, msg

EDGE_VOICES = {
    "en-US": "en-US-GuyNeural",      # Male EN — clear narrator voice
    "vi-VN": "vi-VN-NamMinhNeural",  # Male VI
    "en-female": "en-US-JennyNeural",
    "vi-female": "vi-VN-HoaiMyNeural",
    "ko-KR": "ko-KR-InJoonNeural",   # Male KO
    "ko-female": "ko-KR-SunHiNeural",# Female KO
}

def tts_edge_with_timing(text, voice_key="en-US", audio_out=None, srt_out=None):
    """Edge TTS with word-level timing for subtitle generation."""
    import edge_tts
    voice = EDGE_VOICES.get(voice_key, voice_key)
    audio_out = audio_out or (AUDIO_DIR / f"{uuid.uuid4().hex}.mp3")

    async def _run():
        comm = edge_tts.Communicate(text, voice)
        words, audio_bytes = [], bytearray()
        async for ev in comm.stream():
            if ev["type"] == "audio":
                audio_bytes.extend(ev["data"])
            elif ev["type"] == "WordBoundary":
                start = ev["offset"] / 10_000_000
                dur   = ev["duration"] / 10_000_000
                words.append({"word": ev["text"], "start": start, "end": start + dur})
        Path(audio_out).write_bytes(bytes(audio_bytes))
        return words

    try:
        loop = asyncio.new_event_loop()
        words = loop.run_until_complete(_run())
        loop.close()
        if Path(audio_out).exists() and Path(audio_out).stat().st_size > 1000:
            # If no WordBoundary events (e.g. Vietnamese), generate synthetic timings
            if not words:
                # Estimate audio duration using FFmpeg probe
                dur = 5.0
                try:
                    probe = subprocess.run(
                        [FFMPEG, "-i", str(audio_out), "-f", "null", "-"],
                        capture_output=True, text=True
                    )
                    for line in probe.stderr.split("\n"):  # \n not \\n
                        if "Duration:" in line:
                            ts = line.split("Duration:")[1].split(",")[0].strip()
                            h, m, s = ts.split(":")
                            dur = int(h)*3600 + int(m)*60 + float(s)
                            print(f"[TTS] Detected audio duration: {dur:.2f}s")
                            break
                except Exception as pe:
                    print(f"[TTS] Duration probe failed: {pe}")

                text_words = text.split()
                if text_words and dur > 0:
                    # Distribute time proportional to word length (longer word = more time)
                    char_lens = [max(1, len(w)) for w in text_words]
                    total_chars = sum(char_lens)
                    t = 0.0
                    for w, cl in zip(text_words, char_lens):
                        word_dur = dur * cl / total_chars
                        words.append({"word": w, "start": t, "end": t + word_dur})
                        t += word_dur

            # Build SRT: group 4 words per block
            srt = make_srt(words, group=4)
            if srt_out and srt:
                Path(srt_out).write_text(srt, encoding="utf-8")
            return str(audio_out), srt
    except Exception as e:
        print(f"[EdgeTTS] {e}")
    return None, None

def make_srt(words, group=4):
    """Group words into SRT subtitle blocks (default 4 words per block)."""
    if not words: return ""
    lines, idx = [], 1
    for i in range(0, len(words), group):
        chunk = words[i:i+group]
        start = chunk[0]["start"]
        end   = chunk[-1]["end"]
        # TikTok style: UPPERCASE words
        text  = " ".join(w["word"] for w in chunk).upper()
        def fmt(s):
            h,m = int(s//3600), int((s%3600)//60)
            sec, ms = int(s%60), int((s-int(s))*1000)
            return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
        lines.append(f"{idx}\n{fmt(start)} --> {fmt(end)}\n{text}\n")
        idx += 1
    return "\n".join(lines)

def srt_to_words(srt_path):
    """Parse an SRT file → list of {word, start, end} dicts.
    Each block's full text is treated as one 'word' entry (supports multi-word groups).
    """
    words = []
    try:
        text = Path(srt_path).read_text(encoding="utf-8")
        for block in text.strip().split("\n\n"):
            lines = block.strip().split("\n")
            if len(lines) >= 3:
                ts = lines[1].replace(",", ".")
                start_s, end_s = ts.split(" --> ")
                def _p(t):
                    h, m, s = t.strip().split(":")
                    return int(h)*3600 + int(m)*60 + float(s)
                # Join all text lines (in case subtitle wraps)
                phrase = " ".join(lines[2:]).strip()
                words.append({"word": phrase, "start": _p(start_s), "end": _p(end_s)})
    except Exception as e:
        print(f"[srt_to_words] {e}")
    return words

def make_ass(words, W=1920, H=1080, window=4, offset_s=0.0):
    """ASS grouped subtitle — shows a block of words all at once for their duration,
    then switches cleanly to the next block. No karaoke highlighting.

    Each 'word' entry from srt_to_words may already be a multi-word phrase (from group=4 SRT).
    offset_s: shift ALL subtitle timestamps (negative = earlier).
    """
    if not words:
        return ""

    # Font sizes tuned for portrait (9:16) vs landscape (16:9)
    fs    = 52 if W == 1080 else 32
    margv = 120 if W == 1080 else 70

    header = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # White bold text, black outline, semi-transparent box background
        f"Style: Default,Arial,{fs},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,2,0,3,2,1,2,30,30,{margv},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    def _t(s):
        s = max(0.0, s + offset_s)
        h = int(s // 3600); m = int((s % 3600) // 60); sec = s % 60
        return f"{h}:{m:02d}:{sec:05.2f}"

    dlg = []
    # Each entry in `words` is already a grouped phrase (from make_srt group=4).
    # Just emit one Dialogue line per group — the entire phrase shows for its full duration.
    for entry in words:
        phrase = entry["word"].upper()
        dlg.append(
            f"Dialogue: 0,{_t(entry['start'])},{_t(entry['end'])},Default,,0,0,0,,{phrase}"
        )

    return header + "\n".join(dlg)


def tts_edge(text, voice_key="en-US", out_path=None):
    """Simple Edge TTS without timing (fallback)."""
    audio, _ = tts_edge_with_timing(text, voice_key, out_path)
    return audio

def tts_groq_api(text, voice="Fritz-PlayAI", out_path=None):
    """Groq TTS — fallback, needs Groq key."""
    key = (cfg.get("groq") or [None])[0]
    if not key: return None
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/audio/speech",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "playai-tts", "input": text, "voice": voice, "response_format": "wav"},
            timeout=60,
        )
        if r.ok:
            out_path = out_path or (AUDIO_DIR / f"{uuid.uuid4().hex}.wav")
            Path(out_path).write_bytes(r.content)
            return str(out_path)
    except Exception as e:
        print(f"[GroqTTS] {e}")
    return None

def tts(text, voice_cfg="en-US", srt_out=None, rate="1.0"):
    """Try CapCut TTS → Edge TTS → Groq, return audio path.
    voice_cfg: either a CapCut display key (e.g. '🇻🇳 Cô Gái Hoạt Ngôn (BV074)')
               or a legacy Edge key (e.g. 'en-US', 'vi-VN').
    rate: speed string for CapCut TTS ('0.8'...'1.3').
    """
    # ── CapCut TTS (preferred, mỗi request dùng device fingerprint mới) ────────
    if _CAPCUT_OK and voice_cfg in _cc.CAPCUT_VOICES:
        audio_path = AUDIO_DIR / f"{uuid.uuid4().hex}.mp3"
        audio, _ = _cc.tts_capcut(
            text,
            voice_key=voice_cfg,
            rate=rate,
            out_path=audio_path,
            srt_out=srt_out,
            ffmpeg_bin=FFMPEG or "ffmpeg",
        )
        if audio:
            return audio
        print("[TTS] CapCut failed → fallback Edge TTS")

    # ── Edge TTS fallback ─────────────────────────────────────────────────────
    # Nếu voice_cfg là tên CapCut (có emoji, không nằm trong EDGE_VOICES),
    # tự động map sang Edge voice key theo ngôn ngữ.
    edge_key = voice_cfg if voice_cfg in EDGE_VOICES else (
        "vi-VN" if "🇻🇳" in voice_cfg else
        "ko-KR" if "🇰🇷" in voice_cfg else
        "en-US"
    )
    audio_path = AUDIO_DIR / f"{uuid.uuid4().hex}.mp3"
    audio, srt = tts_edge_with_timing(text, edge_key, audio_path, srt_out)
    if audio: return audio

    # ── Groq TTS last resort ──────────────────────────────────────────────────
    groq_voice = "Fritz-PlayAI" if "en" in voice_cfg.lower() else "Celeste-PlayAI"
    return tts_groq_api(text, groq_voice)

def srt_from_audio(audio_path, text, srt_path):
    """Generate synthetic SRT from an existing audio file (no API call).
    Probes actual duration with FFmpeg, distributes timing proportional to word length."""
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
    char_lens = [max(1, len(w)) for w in text_words]
    total_chars = sum(char_lens)
    t, words = 0.0, []
    for w, cl in zip(text_words, char_lens):
        wd = dur * cl / total_chars
        words.append({"word": w, "start": t, "end": t + wd})
        t += wd
    srt = make_srt(words, group=1)
    if srt:
        Path(srt_path).write_text(srt, encoding="utf-8")
    return dur

def clean_keyword(kw):
    """Sanitize AI-generated keyword: extract from URLs if needed, return plain search terms."""
    import re
    kw = kw or ""
    # If it looks like a Pexels URL, extract the path segment as keyword
    m = re.search(r'pexels\.com/(?:[^/]+/)*([^/?&\s]+)', kw)
    if m:
        kw = m.group(1).replace('-', ' ').replace('_', ' ')
    # Strip any remaining URL parts
    kw = re.sub(r'https?://\S+', '', kw)
    kw = kw.replace('/', ' ').replace('\\', ' ')
    # Keep only alphanumeric, spaces, hyphens
    kw = re.sub(r'[^\w\s-]', '', kw).strip()
    # Max 4 words
    return ' '.join(kw.split()[:4]) or "nature"

def fetch_pexels(keyword, orientation="landscape", used_urls=None):
    key = (cfg.get("pexels") or [None])[0]
    if not key: return None
    if used_urls is None: used_urls = set()
    
    def _search(o):
        url = f"https://api.pexels.com/videos/search?query={requests.utils.quote(keyword)}&per_page=15"
        if o: url += f"&orientation={o}"
        r = requests.get(url, headers={"Authorization": key}, timeout=15)
        if not r.ok: return None
        for v in r.json().get("videos", []):
            files = v.get("video_files", [])
            if not files: continue
            valid_files = [f for f in files if (f.get("width", 0) >= 1080 or f.get("height", 0) >= 1080)]
            if not valid_files: valid_files = files
            valid_files = sorted(valid_files, key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
            f = valid_files[0]
            if f and f["link"] not in used_urls:
                return f["link"]
        return None
        
    res = _search(orientation)
    if not res and orientation != "":
        # Fallback to any orientation if preferred one yields no results
        res = _search("")
    return res

def search_pexels_videos(keyword, orientation="landscape"):
    import random
    key = (cfg.get("pexels") or [None])[0]
    if not key: return []
    
    url = f"https://api.pexels.com/videos/search?query={requests.utils.quote(keyword)}&per_page=30"
    if orientation: url += f"&orientation={orientation}"
    try:
        r = requests.get(url, headers={"Authorization": key}, timeout=15)
        if not r.ok: return []
        results = []
        videos = r.json().get("videos", [])
        random.shuffle(videos)
        for v in videos:
            files = v.get("video_files", [])
            if not files: continue
            valid_files = [f for f in files if (f.get("width", 0) >= 1080 or f.get("height", 0) >= 1080)]
            if not valid_files: valid_files = files
            valid_files = sorted(valid_files, key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
            f = valid_files[0]
            
            if f:
                results.append({
                    "id": v["id"],
                    "url": f["link"],
                    "image": v["image"],
                    "duration": v["duration"]
                })
        return results
    except Exception as e:
        print(f"[Pexels Search] Error: {e}")
        return []

def download_url(url, dest):
    r = requests.get(url, timeout=60, stream=True, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(65536):
            if chunk: f.write(chunk)

def ffmpeg(*args):
    cmd = [FFMPEG, "-y", "-loglevel", "error"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"FFmpeg: {result.stderr[:300]}")

# Check if FFmpeg has subtitles filter (requires libass)
@st.cache_data
def has_subtitles_filter():
    r = subprocess.run([FFMPEG, "-filters"], capture_output=True, text=True)
    return "subtitles" in r.stdout

HAS_SUB = has_subtitles_filter()

# ── UI ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stSidebar"] { background: #13151c; }
.stButton button { width: 100%; }

/* Tạo thanh cuộn riêng biệt cho cột Kết Quả (cột số 2) */
div[data-testid="stHorizontalBlock"] > div:nth-child(2) {
    height: calc(100vh - 120px) !important;
    overflow-y: auto !important;
    padding-right: 15px !important;
}
/* Làm đẹp thanh cuộn */
div[data-testid="stHorizontalBlock"] > div:nth-child(2)::-webkit-scrollbar {
    width: 6px;
}
div[data-testid="stHorizontalBlock"] > div:nth-child(2)::-webkit-scrollbar-track {
    background: transparent;
}
div[data-testid="stHorizontalBlock"] > div:nth-child(2)::-webkit-scrollbar-thumb {
    background-color: #555;
    border-radius: 10px;
}
</style>
""", unsafe_allow_html=True)

tab_main, tab_settings = st.tabs(["🎬 Pipeline", "⚙️ Settings"])

# ════════════════════════════════════════════════════════════
# SETTINGS TAB
# ════════════════════════════════════════════════════════════
with tab_settings:
    st.header("⚙️ API Keys")
    changed = False

    st.subheader("✨ Gemini Keys")
    new_g = st.text_input("Thêm Gemini key", placeholder="AIza...", type="password", key="g_in")
    if st.button("➕ Thêm Gemini") and new_g.strip():
        cfg.setdefault("gemini", []).append(new_g.strip()); changed = True
    for i, k in enumerate(cfg.get("gemini", [])):
        c1, c2 = st.columns([5,1])
        c1.code(k[:8] + "..." + k[-4:])
        if c2.button("✕", key=f"dg{i}"): cfg["gemini"].pop(i); changed = True

    st.subheader("⚡ Groq Keys (LLM + TTS)")
    new_q = st.text_input("Thêm Groq key", placeholder="gsk_...", type="password", key="q_in")
    if st.button("➕ Thêm Groq") and new_q.strip():
        cfg.setdefault("groq", []).append(new_q.strip()); changed = True
    for i, k in enumerate(cfg.get("groq", [])):
        c1, c2 = st.columns([5,1])
        c1.code(k[:8] + "..." + k[-4:])
        if c2.button("✕", key=f"dq{i}"): cfg["groq"].pop(i); changed = True

    st.subheader("🎥 Pexels Keys (footage CC0)")
    new_p = st.text_input("Thêm Pexels key", placeholder="Pexels API key...", type="password", key="p_in")
    if st.button("➕ Thêm Pexels") and new_p.strip():
        cfg.setdefault("pexels", []).append(new_p.strip()); changed = True
    for i, k in enumerate(cfg.get("pexels", [])):
        c1, c2 = st.columns([5,1])
        c1.code(k[:8] + "..." + k[-4:])
        if c2.button("✕", key=f"dp{i}"): cfg["pexels"].pop(i); changed = True

    st.subheader("🎵 Pixabay Key (nhạc nền - tùy chọn)")
    pix = st.text_input("Pixabay key", value=cfg.get("pixabay",""), type="password", key="pix_in")
    if pix != cfg.get("pixabay",""): cfg["pixabay"] = pix; changed = True

    st.subheader("🎨 OpenAI Key (DALL-E 3 Thumbnail)")
    st.caption("Dùng để tạo thumbnail bằng DALL-E 3. Lấy key tại platform.openai.com/api-keys")
    oai = st.text_input("OpenAI key", value=cfg.get("openai",""), placeholder="sk-...", type="password", key="oai_in")
    if oai != cfg.get("openai",""): cfg["openai"] = oai; changed = True

    if changed:
        save_cfg(cfg)
        st.success("✅ Đã lưu!")

    st.divider()
    if not FFMPEG:
        st.error("❌ Không tìm thấy FFmpeg! Cài: `brew install ffmpeg`")
    else:
        st.success(f"✅ FFmpeg: `{FFMPEG}`")

# ════════════════════════════════════════════════════════════
# MAIN PIPELINE TAB
# ════════════════════════════════════════════════════════════
with tab_main:
    col_left, col_right = st.columns([1, 1.6])

    with col_left:
        st.subheader("⚙️ Cấu hình")

        niche = st.selectbox("🎯 Chủ đề", [
            "technology","finance","health","science","motivation",
            "business","history","psychology","travel","food"
        ])
        custom = st.text_area("Hoặc nhập mô tả chi tiết (tùy chỉnh)", placeholder="Ví dụ:\nChủ đề: 한국 집값\nNội dung chính:\n- ...\nTôn màu: ...", height=150)
        duration = st.select_slider("⏱️ Tổng thời lượng (giây)", [30, 45, 60, 90, 120, 180, 300, 600], value=60)
        target_sec_per_scene = st.number_input("⏳ Nhịp độ 1 cảnh (giây)", min_value=3, max_value=30, value=7, help="Tăng số này nếu muốn AI viết câu thoại dài hơn, đỡ bị vụn vặt.")
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
                ["Không có", "Follow để biết thêm", "Comment ý kiến của bạn", "Share cho bạn bè"],
                index=1
            )
            enable_transition = st.checkbox(
                "🎬 Hiệu ứng chuyển cảnh (Fade in/out)",
                value=False,
                help="Hiệu ứng mờ dần (Fade) có thể làm video bị đen khoảng 0.5s ở giữa các cảnh. Khuyên dùng: Tắt (cắt cảnh nhanh sẽ cuốn hút hơn)."
            )

        lang = st.selectbox("🌍 Ngôn ngữ", ["English", "Vietnamese", "Korean"])

        # ── Voice selector: CapCut voices if available, else Edge fallback ───
        if _CAPCUT_OK:
            _lang_flag = {"Vietnamese": "🇻🇳", "English": "🇺🇸", "Korean": "🇰🇷"}.get(lang, "🇺🇸")
            _lang_code  = {"Vietnamese": "vi", "English": "en", "Korean": "ko"}.get(lang, "en")
            _voice_opts = [k for k in _cc.CAPCUT_VOICES if _lang_flag in k]
            _default_voice = _cc.CAPCUT_VOICE_DEFAULTS.get(_lang_code, _voice_opts[0])
            _default_idx   = _voice_opts.index(_default_voice) if _default_voice in _voice_opts else 0
            voice = st.selectbox(
                "🔊 Giọng đọc (CapCut)",
                _voice_opts,
                index=_default_idx,
                help="Giọng CapCut AI chất lượng cao — không cần Edge TTS hay Groq"
            )
            # Rate slider
            tts_rate = st.select_slider(
                "⚡ Tốc độ đọc",
                options=["0.8", "0.9", "1.0", "1.1", "1.2", "1.3"],
                value="1.0"
            )
            voice_cfg_key = voice  # CapCut key is passed directly
        else:
            st.warning("⚠️ CapCut TTS chưa sẵn sàng — dùng Edge TTS fallback")
            voice = st.selectbox("🔊 Giọng đọc", [
                "en-US (Guy - Male)", "en-US (Jenny - Female)",
                "vi-VN (NamMinh)", "vi-VN (HoaiMy - Female)",
                "ko-KR (InJoon - Male)", "ko-KR (SunHi - Female)",
            ])
            tts_rate = "1.0"
            _legacy_map = {
                "en-US (Guy - Male)": "en-US",
                "en-US (Jenny - Female)": "en-female",
                "vi-VN (NamMinh)": "vi-VN",
                "vi-VN (HoaiMy - Female)": "vi-female",
                "ko-KR (InJoon - Male)": "ko-KR",
                "ko-KR (SunHi - Female)": "ko-female",
            }
            voice_cfg_key = _legacy_map.get(voice, "en-US")

        aspect = st.radio("📐 Tỉ lệ", ["16:9 (YouTube)","9:16 (Shorts/TikTok)"], horizontal=True)
        show_sub = st.checkbox("💬 Thêm phụ đề (sub từng chữ)", value=False)

        st.markdown("**🎵 Nhạc nền (Tùy chọn)**")
        bgm_file = st.file_uploader("Tải lên file nhạc (.mp3, .wav, .m4a)", type=["mp3", "wav", "m4a", "aac"])
        bgm_vol = st.slider("🔊 Âm lượng nhạc nền", min_value=0.01, max_value=0.5, value=0.1, step=0.01) if bgm_file else 0.1

        # Dimensions
        if "9:16" in aspect:
            W, H = 1080, 1920
        else:
            W, H = 1920, 1080

        st.divider()

        # Pipeline steps status
        steps_done = proj.get("step", 0)
        for n, label in [(1,"📝 Kịch bản"),(2,"🎬 Footage"),(3,"🎙️ TTS"),(4,"🎞️ Render")]:
            icon = "✅" if steps_done >= n else "⬜"
            st.write(f"{icon} {label}")

        st.divider()

        gen_script = st.button("📝 1. Tạo Kịch Bản", type="primary") if not proj.get("script") else None
        run_all    = st.button("🚀 2. Tạo Video (Footage + TTS + Render)", type="primary") if proj.get("script") else None
        run_render = st.button("🎞️ 3. Chỉ Render Video") if proj.get("scenes") else None
        reset_btn  = st.button("🗑️ Xóa & làm lại") if proj.get("script") else None

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
        if gen_script or run_all or run_render:
            topic = custom.strip() or niche
            voice_id = "Fritz-PlayAI" if "Fritz" in voice else "Celeste-PlayAI"
            work = TMP / uuid.uuid4().hex
            work.mkdir(exist_ok=True)

            try:
                # STEP 1: Script
                if gen_script:
                    log("📝 Tạo kịch bản AI (retention-optimized)...")
                    sc = max(2, round(duration / target_sec_per_scene))
                    # Seed chống trùng nội dung: timestamp + UUID fragment + topic hash
                    # → ~18 chữ số entropy, cực kỳ khó trùng dù publish cùng topic mỗi ngày
                    import hashlib as _hs
                    _ts   = str(int(time.time() * 1000))          # ms epoch
                    _uid  = uuid.uuid4().hex[:8]                  # 8 hex random
                    _thash = _hs.md5(f"{topic}{lang}{style}".encode()).hexdigest()[:6]  # topic fingerprint
                    seed  = f"{_ts}-{_uid}-{_thash}"             # unique per generation
                    # Tốc độ đọc khoảng 3.5 - 4 từ / giây (Voice AI thường đọc khá nhanh) -> cảnh 5s cần ~18-20 từ
                    words_per_scene = max(18, round(target_sec_per_scene * 3.8))

                    # Map hook style to AI instructions
                    hook_map = {
                        "🤯 Shock & Awe — Con số / sự thật gây sốc":
                            "Start with a SHOCKING statistic or fact that feels unbelievable. Example: '99% of people do X wrong...' or 'Scientists just discovered...' Make viewer think WTF.",
                        "❓ Curiosity Gap — Câu hỏi bỏ lửng tạo tò mò":
                            "Open with a question that can ONLY be answered by watching the whole video. Tease the answer but DON'T give it yet. Example: 'What if I told you the thing you do every day is actually...' Leave an irresistible knowledge gap.",
                        "🔥 Controversial — Phát biểu gây tranh cãi":
                            "Start with a bold, polarizing statement that makes people either strongly agree or disagree. This triggers emotional response and comment impulse. Example: '[Common belief] is actually completely wrong and here's proof.'",
                        "⚠️ Warning / Fear — Cảnh báo, nguy cơ":
                            "Open with an urgent warning or threat the viewer didn't know about. Trigger loss aversion. Example: 'Stop doing this immediately — it's silently damaging your...'",
                        "🤫 Secret / Insider — Bí mật ít người biết":
                            "Position the video as revealing exclusive insider info. Use 'nobody talks about this', 'this is what they don't want you to know', 'I discovered a secret that...'",
                        "🎭 Story / Relatable — Câu chuyện cá nhân":
                            "Start in the middle of an interesting personal story or a relatable situation. Use 'in medias res' — drop the viewer into the most exciting moment first.",
                        "📣 Bold Claim — Tuyên bố mạnh mẽ":
                            "Make an audacious, specific, big promise in the first sentence. Example: 'I increased my income 10x in 3 months using this one technique.'",
                        "🎲 Random — AI tự chọn tốt nhất":
                            "Choose the most effective hook type for this specific topic and audience. Optimize for maximum curiosity and retention.",
                    }
                    hook_instruction = hook_map.get(hook_style, hook_map["🎲 Random — AI tự chọn tốt nhất"])

                    retention_rules = ""
                    if pattern_interrupt:
                        retention_rules += """
- PATTERN INTERRUPT: Every 2-3 scenes, insert a surprising twist, counter-intuitive fact, or tonal shift to re-engage attention."""
                    if add_loop_teaser:
                        retention_refs = """
- LOOP ENDING: The LAST scene must subtly call back to the opening hook, creating a satisfying loop that makes viewers want to rewatch."""
                        retention_rules += retention_refs
                    if cta_style != "Không có":
                        retention_rules += f"""
- CTA: Include a natural, non-pushy call-to-action in the last 3 seconds: "{cta_style}"."""

                    # Nâng mục tiêu số chữ lên cao hơn để chắc chắn video KHÔNG BAO GIỜ bị ngắn hơn thời gian yêu cầu
                    target_duration_padded = duration + 5 
                    total_words = max(80, round(target_duration_padded * 3.8))

                    if lang == 'Korean':
                        keyword_instruction = "- keyword: 1-3 plain English words for Pexels video search. CRITICAL: For ANY scene involving people, streets, lifestyle, or culture, you MUST include 'Asian', 'Korea', 'Korean', or 'Seoul' in the keyword (e.g., 'Asian office worker', 'Seoul street', 'Korean food'). NO URLs."
                    elif lang == 'Vietnamese':
                        keyword_instruction = "- keyword: 1-3 plain English words for Pexels video search. CRITICAL: For ANY scene involving people, streets, lifestyle, or culture, you MUST include 'Asian', 'Vietnam', or 'Vietnamese' in the keyword (e.g., 'Asian office worker', 'Vietnam street', 'Asian student'). NO URLs."
                    else:
                        keyword_instruction = "- keyword: 1-3 plain English words for Pexels video search. NO URLs."

                    raw = call_ai(f"""[seed:{seed}] You are a viral short-form video expert. Create a RETENTION-OPTIMIZED {style} video script about "{topic}" in {lang}.

=== LANGUAGE INSTRUCTIONS ===
{(
    'Write ALL narration text in natural, conversational Korean (한국어). Use informal but respectful speech level (해요체). Optimize for Korean audiences on platforms like YouTube, TikTok KR, and Instagram Reels.'
    if lang == 'Korean' else
    'Write ALL narration text in natural Vietnamese (tiếng Việt). Use colloquial, engaging language suitable for Vietnamese social media audiences.'
    if lang == 'Vietnamese' else
    'Write ALL narration text in clear, engaging English.'
)}

=== HOOK STRATEGY (FIRST 3 SECONDS — MOST CRITICAL) ===
{hook_instruction}
The first sentence of scene 1 MUST be so compelling that viewers CANNOT scroll away.
Never start with "In this video..." or "Today we're going to..."

=== RETENTION STRUCTURE ===
Total video duration MUST BE AT LEAST {duration} seconds.
Total script word count MUST BE AROUND {total_words} words (no less than {total_words - 15}, no more than {total_words + 20}).
You must write exactly {sc} scenes.
- Scene 1 (HOOK): Explosive opening — apply the hook strategy above.
- Scene 2 (AMPLIFY): Deepen the curiosity / tension from the hook. Don't resolve it yet.
- Scenes 3 to {sc-1} (CONTENT): Deliver value in fast, punchy bursts. Each scene = one key insight.
- Scene {sc} (PAYOFF + CTA): Satisfying conclusion + call to action.
{retention_rules}

=== WRITING RULES ===
- CRITICAL — Word count: Each scene narration MUST contain around {words_per_scene + 2} words. DO NOT write ultra-short scenes (e.g. 3-4 words) unless it's a specific stylistic choice.
- Keep sentences punchy, conversational, and active. Write complete, full sentences.
- Use conversational language, active voice, power words. Write complete, full sentences.
- Create OPEN LOOPS — tease what's coming next to prevent drop-off.
{keyword_instruction}

Return ONLY valid JSON:
{{"title":"...","description":"...","tags":["t1","t2"],"scenes":[{{"id":1,"text":"narration text","keyword":"plain english words","retention_note":"why this keeps viewers watching"}}]}}""")                    
                    try:
                        script = parse_json_robust(raw)
                    except (json.JSONDecodeError, ValueError) as _je:
                        log(f"❌ AI trả về JSON lỗi: {_je}")
                        log(f"   Raw (300 ký tự đầu): {raw[:300]}")
                        raise
                    vid_orientation = "portrait" if "9:16" in aspect else "landscape"
                    scenes = []
                    used_pexels_urls = set()
                    for sc_data in script["scenes"]:
                        url = fetch_pexels(clean_keyword(sc_data["keyword"]), orientation=vid_orientation, used_urls=used_pexels_urls)
                        if url:
                            used_pexels_urls.add(url)
                        scenes.append({
                            "id": sc_data["id"],
                            "text": sc_data["text"],
                            "keyword": sc_data["keyword"],
                            "videoUrl": url,
                            "audioDone": False,
                            "duration": round(max(3.0, len(sc_data["text"].split()) / 2.5), 1), # Ước tính ban đầu, sẽ update chính xác ở Step 3
                        })
                    proj.update({"script": script, "scenes": scenes, "step": 1})
                    save_proj(proj)
                    log(f'✅ Kịch bản: "{script["title"]}" — {len(scenes)} cảnh')

                    # ── Tạo Thumbnail (OpenAI DALL-E 3 → Gemini Imagen fallback) ──
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

                    st.rerun()
                else:
                    script = proj["script"]
                    scenes = proj["scenes"]

                # STEP 2: Footage
                if run_all:
                    log("🎬 Tải footage Pexels...")
                    vid_orientation = "portrait" if "9:16" in aspect else "landscape"
                    used_urls_step2 = set(s.get("videoUrl") for s in scenes if s.get("videoUrl"))
                    for i, s in enumerate(scenes):
                        if not s.get("customVid") and not s.get("videoUrl"):
                            log(f"  Cảnh {i+1}/{len(scenes)}: {s['keyword']}")
                            url = fetch_pexels(clean_keyword(s["keyword"]), orientation=vid_orientation, used_urls=used_urls_step2)
                            if url:
                                used_urls_step2.add(url)
                            scenes[i]["videoUrl"] = url
                            log(f"  {'✅' if url else '⬜'} cảnh {i+1}")
                        else:
                            log(f"  ♻️ Cảnh {i+1} đã có video sẵn")
                    proj.update({"scenes": scenes, "step": 2})
                    save_proj(proj)

                # STEP 3: TTS + Subtitles
                if run_all:
                    _tts_label = "CapCut TTS" if (_CAPCUT_OK and voice_cfg_key in _cc.CAPCUT_VOICES) else "Edge TTS"
                    log(f"🎤 Tạo giọng đọc ({_tts_label} — {voice_cfg_key[:30]})...")
                    for i, s in enumerate(scenes):
                        log(f"  TTS cảnh {i+1}/{len(scenes)}")
                        import hashlib
                        hash_str = s['text'] + voice_cfg_key + str(tts_rate)
                        h = hashlib.md5(hash_str.encode()).hexdigest()[:12]
                        audio_path = AUDIO_DIR / f"s{h}.mp3"
                        srt_path   = AUDIO_DIR / f"s{h}.srt"
                        actual_dur = None

                        if audio_path.exists() and audio_path.stat().st_size > 1000:
                            log(f"  ♻️ Cache audio cảnh {i+1}")
                            if show_sub and (not srt_path.exists() or srt_path.stat().st_size == 0):
                                actual_dur = srt_from_audio(audio_path, s["text"], srt_path)
                        else:
                            result = tts(s["text"], voice_cfg_key,
                                         srt_out=str(srt_path) if show_sub else None,
                                         rate=tts_rate)
                            time.sleep(3) # Tránh lỗi ExceededConcurrentLimit của CapCut
                            
                            if result:
                                shutil.copy(result, audio_path)
                                if show_sub and srt_path.exists() and srt_path.stat().st_size == 0:
                                    actual_dur = srt_from_audio(audio_path, s["text"], srt_path)

                        if audio_path.exists():
                            scenes[i]["audioFile"] = str(audio_path)
                            scenes[i]["srtFile"]   = str(srt_path) if (srt_path.exists() and srt_path.stat().st_size > 0) else None
                            
                            if not actual_dur:
                                try:
                                    from moviepy.editor import AudioFileClip
                                    with AudioFileClip(str(audio_path)) as ac:
                                        actual_dur = ac.duration
                                except Exception as e:
                                    pass
                                    
                            aud_dur = actual_dur if (actual_dur and actual_dur > 0) else max(3.0, len(s["text"].split()) / 2.5)
                            scenes[i]["audioDur"] = aud_dur
                            
                            # LUÔN LUÔN set thời lượng cảnh bằng chính xác thời lượng giọng nói!
                            scenes[i]["duration"] = round(aud_dur, 1)
                            
                            log(f"  ✅ Audio cảnh {i+1} ({aud_dur:.1f}s → set video {scenes[i]['duration']}s)" + (" + sub" if scenes[i].get('srtFile') else ""))
                        else:
                            log(f"  ⚠️ TTS thất bại cảnh {i+1}")
                    proj.update({"scenes": scenes, "step": 3})
                    save_proj(proj)

                # STEP 4: Render
                log("🎞️ Render video...")
                scene_mp4s = []
                used_urls_render = set(s.get("videoUrl") for s in scenes if s.get("videoUrl"))

                for i, s in enumerate(scenes):
                    log(f"  Render cảnh {i+1}/{len(scenes)}")
                    s_dir = work / f"s{i}"
                    s_dir.mkdir(exist_ok=True)

                    # Thời lượng cảnh (user có thể chỉnh trong UI review)
                    dur = float(s.get("duration") or 5)

                    # ── AUDIO: Trim/pad cứng đúng `dur` giây bằng FFmpeg ──────────
                    src_audio = Path(s.get("audioFile", "")) if s.get("audioFile") else None
                    audio_path = s_dir / "audio_trimmed.aac"
                    if src_audio and src_audio.exists():
                        # apad: pad silence nếu audio ngắn; -t: cắt nếu dài hơn dur
                        ffmpeg("-i", str(src_audio),
                               "-af", f"apad=pad_dur={dur}",
                               "-t", str(dur),
                               "-c:a", "aac", "-b:a", "128k", "-y", str(audio_path))
                    else:
                        ffmpeg("-f","lavfi","-i","anullsrc=r=44100:cl=mono",
                               "-t",str(dur),"-c:a","aac","-b:a","128k","-y",str(audio_path))

                    # Subtitle: parse SRT → generate karaoke ASS
                    srt_file = s.get("srtFile")
                    has_srt  = False
                    ass_local = None
                    if show_sub and not HAS_SUB:
                        log("  ⚠️ FFmpeg thiếu libass — bỏ phụ đề. Chạy: brew reinstall ffmpeg")
                    elif show_sub and HAS_SUB and srt_file and Path(srt_file).exists():
                        try:
                            w_list = srt_to_words(srt_file)
                            if w_list:
                                ass_content = make_ass(w_list, W=W, H=H)
                                ass_local = s_dir / "sub.ass"
                                ass_local.write_text(ass_content, encoding="utf-8")
                                has_srt = True
                        except Exception as srt_e:
                            log(f"  ⚠️ Lỗi tạo ASS: {srt_e} — bỏ phụ đề")

                    # Video background
                    vid_path = s_dir / "video.mp4"
                    has_vid  = False
                    vid_orientation = "portrait" if "9:16" in aspect else "landscape"

                    # Always try to get video: use cached URL first, re-fetch if needed
                    custom_vid = s.get("customVid", "")
                    video_url = s.get("videoUrl", "")
                    
                    if custom_vid and Path(custom_vid).exists():
                        shutil.copy(custom_vid, vid_path)
                        has_vid = vid_path.stat().st_size > 10000
                        log(f"  📥 Dùng video tải lên tùy chỉnh: {Path(custom_vid).name}")
                    else:
                        if not video_url:
                            log(f"  🔍 Không có URL, tìm Pexels [{vid_orientation}]: {s.get('keyword','')}")
                            video_url = fetch_pexels(clean_keyword(s.get("keyword", "")), orientation=vid_orientation, used_urls=used_urls_render) or ""
                            if video_url:
                                used_urls_render.add(video_url)
                                log(f"  ✅ Pexels trả về URL")
                            else:
                                log(f"  ⚠️ Pexels không tìm thấy video (kiểm tra API key trong Settings)")

                        if video_url:
                            try:
                                download_url(video_url, str(vid_path))
                                size = vid_path.stat().st_size
                                log(f"  📥 Tải video: {size//1024}KB")
                                has_vid = size > 10000
                                if not has_vid:
                                    log(f"  ⚠️ File video quá nhỏ ({size}B), bỏ qua")
                            except Exception as e:
                                log(f"  ⚠️ Tải thất bại: {str(e)[:80]} — tìm lại...")
                                new_url = fetch_pexels(clean_keyword(s.get("keyword", "")), orientation=vid_orientation, used_urls=used_urls_render) or ""
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


                    # Sub style: Bottom-center, small font, semi-transparent box
                    fs = 20 if W == 1080 else 16
                    sub_style = (
                        f"FontName=Arial,FontSize={fs},PrimaryColour=&H00FFFFFF,"  # White text
                        "BackColour=&H90000000,BorderStyle=3,Outline=0,Shadow=0,"  # Dark semi-transparent box
                        f"Alignment=2,MarginV={80 if W==1080 else 50}"             # Bottom-center
                    )
 
                    out = s_dir / "scene.mp4"
                    scale_filter = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
 
                    # Speed up logic if audio is longer than scene duration
                    aud_dur = s.get("audioDur", dur)
                    speed = min(2.0, aud_dur / dur) if aud_dur > dur else 1.0

                    # Transitions & Audio Filters
                    # Giảm fade xuống 0.15s để chỉ chớp mờ chuyển cảnh, không bị đen lâu
                    v_fade = f",fade=t=in:st=0:d=0.15,fade=t=out:st={dur-0.15}:d=0.15" if enable_transition else ""
                    af_list = []
                    if speed > 1.0:
                        af_list.append(f"atempo={speed}")
                    
                    # BỎ fade-out audio vì nó sẽ làm mất/nhỏ tiếng chữ cuối cùng của lời đọc
                    if enable_transition:
                        af_list.append(f"afade=t=in:ss=0:d=0.15")
                        
                    a_fade = ",".join(af_list)

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
                                ass_content = make_ass(w_list, W=W, H=H)
                                ass_local = s_dir / "sub.ass"
                                ass_local.write_text(ass_content, encoding="utf-8")
                                has_srt = True
                        except Exception as srt_e:
                            log(f"  ⚠️ Lỗi tạo ASS: {srt_e} — bỏ phụ đề")

                    # ----- MOVIEPY RENDER CORE -----
                    base_out = s_dir / "base.mp4"
                    try:
                        import PIL.Image
                        if not hasattr(PIL.Image, 'ANTIALIAS'):
                            PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
                            
                        from moviepy.editor import VideoFileClip, AudioFileClip, ColorClip
                        import moviepy.video.fx.all as vfx
                        
                        audio_clip = AudioFileClip(str(audio_path))
                        # Lấy chính xác duration của audio clip
                        exact_dur = audio_clip.duration
                        
                        if has_vid:
                            video_clip = VideoFileClip(str(vid_path))
                            # Loop video nếu ngắn hơn audio
                            if video_clip.duration < exact_dur:
                                video_clip = video_clip.fx(vfx.loop, duration=exact_dur)
                            video_clip = video_clip.subclip(0, exact_dur)
                            
                            # Cắt/Scale để vừa WxH (1080x1920) không bị méo
                            vid_ratio = video_clip.w / video_clip.h
                            target_ratio = W / H
                            if vid_ratio > target_ratio:
                                video_clip = video_clip.resize(height=H)
                                xc = video_clip.w / 2
                                video_clip = video_clip.crop(x1=xc-W/2, y1=0, x2=xc+W/2, y2=H)
                            else:
                                video_clip = video_clip.resize(width=W)
                                yc = video_clip.h / 2
                                video_clip = video_clip.crop(x1=0, y1=yc-H/2, x2=W, y2=yc+H/2)
                        else:
                            # Nền tĩnh nếu không có video
                            video_clip = ColorClip(size=(W, H), color=(26, 29, 39), duration=exact_dur)
                        
                        video_clip = video_clip.set_audio(audio_clip)
                        log(f"  🎬 Đang xử lý khung hình (MoviePy) cho cảnh {i+1}...")
                        video_clip.write_videofile(str(base_out), fps=30, codec="libx264", audio_codec="aac", logger=None)
                        video_clip.close()
                        audio_clip.close()
                    except ImportError:
                        log("⚠️ Thiếu moviepy. Cài đặt: pip install moviepy")
                        raise
                        
                    # ----- SUBTITLE BURN-IN -----
                    if has_srt and ass_local and ass_local.exists():
                        log(f"  ✍️ Đang gắn phụ đề cảnh {i+1}...")
                        vf_filter = _sub_filter(ass_local)
                        if enable_transition:
                            vf_filter += f",fade=t=in:st=0:d=0.15,fade=t=out:st={dur-0.15}:d=0.15"
                            
                        cmd_args = ["-i", str(base_out), "-vf", vf_filter, "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-c:a", "copy", "-y", str(out)]
                        try:
                            ffmpeg(*cmd_args)
                        except Exception as e:
                            log(f"  ⚠️ Lỗi gắn phụ đề: {e} -> Dùng bản không phụ đề.")
                            shutil.copy(base_out, out)
                    else:
                        if enable_transition:
                            v_fade = f"fade=t=in:st=0:d=0.15,fade=t=out:st={dur-0.15}:d=0.15"
                            cmd_args = ["-i", str(base_out), "-vf", v_fade, "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-c:a", "copy", "-y", str(out)]
                            ffmpeg(*cmd_args)
                        else:
                            shutil.copy(base_out, out)
                            
                    scene_mp4s.append(out)

                # Concat
                concat_txt = work / "concat.txt"
                concat_txt.write_text("\n".join(f"file '{p}'" for p in scene_mp4s))
                raw_final = work / "final.mp4"
                ffmpeg("-f","concat","-safe","0","-i",str(concat_txt),"-c","copy",str(raw_final))

                # Mix background music
                if bgm_file:
                    log("🎵 Đang mix nhạc nền...")
                    bgm_path = work / f"bgm_{bgm_file.name}"
                    bgm_path.write_bytes(bgm_file.read())
                    final_with_bgm = work / "final_with_bgm.mp4"
                    
                    try:
                        cmd = [
                            "-i", str(raw_final),
                            "-stream_loop", "-1", "-i", str(bgm_path),
                            "-filter_complex", f"[0:a]volume=1.0[a0];[1:a]volume={bgm_vol}[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[a]",
                            "-map", "0:v", "-map", "[a]",
                            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                            "-y", str(final_with_bgm)
                        ]
                        ffmpeg(*cmd)
                        raw_final = final_with_bgm
                        log("✅ Đã mix nhạc nền xong.")
                    except Exception as e:
                        log(f"⚠️ Lỗi mix nhạc nền: {e}, giữ nguyên gốc.")

                # Save to permanent location with proper name
                title = proj.get("script", {}).get("title", "ai_video") or "ai_video"
                safe_name = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:50] or "ai_video"
                save_dir = Path.home() / "Desktop" / "AI_Videos"
                save_dir.mkdir(parents=True, exist_ok=True)
                final = save_dir / f"{safe_name}.mp4"
                shutil.copy(raw_final, final)

                size_mb = final.stat().st_size / 1024 / 1024
                log(f"✅ Render xong! {size_mb:.1f} MB")
                log(f"📂 Lưu tại: {final}")
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
                             use_container_width=True)
                with tinfo:
                    st.markdown(f"**🎬 {s.get('title','')}**")
                    st.caption(f"{len(proj.get('scenes',[]))} cảnh · {len(s.get('tags',[]))} tags")
                    thumb_bytes = Path(thumb_path).read_bytes()
                    st.download_button(
                        "⬇️ Tải thumbnail (.jpg)",
                        data=thumb_bytes,
                        file_name=Path(thumb_path).name,
                        mime="image/jpeg",
                        use_container_width=True,
                    )
                    if st.button("🔄 Tạo lại Thumbnail", use_container_width=True,
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
                if st.button("🖼️ Tạo Thumbnail (DALL-E 3 / Imagen)", use_container_width=True):
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
            
            edited = False
            for i, scene in enumerate(proj.get("scenes", [])):
                scene_data = s.get("scenes", [])
                note = ""
                if i < len(scene_data) and isinstance(scene_data[i], dict):
                    note = scene_data[i].get("retention_note", "")
                
                label_emoji = "🪝" if i == 0 else ("🎯" if i == len(proj.get('scenes', [])) - 1 else "▶️")
                
                with st.expander(f"{label_emoji} Cảnh {i+1}: {scene.get('text', '')[:30]}... ⏱️{scene.get('duration',5)}s", expanded=(i==0)):
                    if note:
                        st.caption(f"💡 *Mục tiêu cảnh: {note}*")

                    col_left, col_right = st.columns([2, 1])
                    
                    with col_left:
                        new_text = st.text_area("Nội dung lời đọc (Voice):", value=scene.get('text', ''), key=f"text_{i}", height=120)
                        new_kw = st.text_input("Từ khóa AI tìm video (Pexels):", value=scene.get('keyword', ''), key=f"kw_{i}")
                        
                        up_vid = st.file_uploader("Upload Video của bạn (mp4) — ghi đè Pexels:", type=["mp4","mov"], key=f"up_{i}")
                        
                        st.markdown("**🔍 Tìm & Đổi video Pexels khác:**")
                        if st.button("🔎 Tải danh sách video Pexels", key=f"search_btn_{i}"):
                            st.session_state[f"search_results_{i}"] = search_pexels_videos(
                                new_kw, 
                                orientation="portrait" if "9:16" in aspect else "landscape"
                            )
                        
                        results = st.session_state.get(f"search_results_{i}", [])
                        if results:
                            cols = st.columns(3)
                            for idx, res in enumerate(results[:6]): # Limit to 6 results for better UI
                                with cols[idx % 3]:
                                    st.image(res["image"], use_container_width=True)
                                    st.caption(f"⏱️ {res['duration']}s")
                                    if st.button("Chọn", key=f"sel_res_{i}_{idx}"):
                                        proj["scenes"][i]["videoUrl"] = res["url"]
                                        proj["scenes"][i]["customVid"] = None
                                        proj["scenes"][i]["duration"] = res["duration"]
                                        edited = True
                                        st.rerun()

                    with col_right:
                        new_dur = st.number_input("⏱️ Thời lượng (giây):", min_value=1.0, max_value=300.0,
                                                   value=float(scene.get("duration") or 5.0),
                                                   step=0.1, key=f"rv_dur_{i}")
                                                   
                        st.markdown("**🎬 Video hiện tại**")
                        if proj["scenes"][i].get("customVid") and Path(proj["scenes"][i]["customVid"]).exists():
                            st.success(f"🎥 Dùng video tải lên")
                            if st.button("Xóa video tải lên", key=f"del_{i}"):
                                proj["scenes"][i]["customVid"] = None
                                edited = True
                                st.rerun()
                        elif scene.get("videoUrl"):
                            st.success(f"🔗 Đã liên kết Pexels")
                            st.video(scene.get("videoUrl"))
                            if st.button("Xóa liên kết video", key=f"del_url_{i}"):
                                proj["scenes"][i]["videoUrl"] = None
                                edited = True
                                st.rerun()
                        else:
                            st.warning("⚠️ Chưa có video")

                    if new_text != scene.get('text') or new_kw != scene.get('keyword') or new_dur != scene.get('duration'):
                        proj["scenes"][i]["text"] = new_text
                        proj["scenes"][i]["keyword"] = new_kw
                        proj["scenes"][i]["duration"] = new_dur
                        edited = True
                        
                    if up_vid:
                        custom_path = AUDIO_DIR / f"custom_{i}_{up_vid.name}"
                        # Chỉ ghi file nếu chưa tồn tại hoặc khác dung lượng
                        if not custom_path.exists() or custom_path.stat().st_size != up_vid.size:
                            custom_path.write_bytes(up_vid.read())
                        
                        # Probe thời lượng video tải lên
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

                        if proj["scenes"][i].get("customVid") != str(custom_path):
                            proj["scenes"][i]["customVid"] = str(custom_path)
                            # Tự động gán thời lượng bằng video tải lên
                            proj["scenes"][i]["duration"] = round(dur_seconds)
                            edited = True
                            st.rerun()

            if edited:
                save_proj(proj)
                st.success("Đã lưu các thay đổi của bạn!")

            if s.get("tags"):
                st.write(" ".join(f"`#{t}`" for t in s["tags"]))

            c1, c2 = st.columns(2)
            c1.button("📋 Copy title", on_click=lambda: None)
            if c2.button("📄 Tải metadata"):
                txt = f"TITLE:\n{s.get('title','')}\n\nDESCRIPTION:\n{s.get('description','')}\n\nTAGS:\n{' '.join('#'+t for t in s.get('tags',[]))}\n\nSCRIPT:\n"
                txt += "\n\n".join(f"[Cảnh {i+1}]\n{sc.get('text','')}" for i, sc in enumerate(proj.get("scenes", [])))
                st.download_button("⬇️ metadata.txt", txt, "youtube_meta.txt", "text/plain")

        if proj.get("finalPath") and Path(proj["finalPath"]).exists():
            st.divider()
            file_name = proj.get("fileName", "ai_video.mp4")
            final_path = Path(proj["finalPath"])
            size_mb = final_path.stat().st_size / 1024 / 1024

            st.success(f"🎉 Video hoàn tất! ({size_mb:.1f} MB)")
            st.info(f"📂 File lưu tại: `{final_path}`")

            video_bytes = final_path.read_bytes()
            st.video(video_bytes)

            # Download button with proper .mp4 filename
            st.download_button(
                label=f"⬇️ Tải xuống {file_name}",
                data=video_bytes,
                file_name=file_name,
                mime="video/mp4",
                use_container_width=True,
            )
            st.caption(f"Hoặc mở thẳng tại: `{final_path}`")

        elif proj.get("step",0) == 0 and not run_all:
            st.info("👈 Chọn cấu hình bên trái và bấm **Bắt Đầu Tự Động**\n\nSettings → thêm API keys trước")
