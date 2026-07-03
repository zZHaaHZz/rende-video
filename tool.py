"""
AI Video Creator — Python Streamlit App
Chạy: streamlit run tool.py
"""
import streamlit as st
import asyncio, json, os, re, uuid, base64, subprocess, shutil, time, tempfile, random, math
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
    default_cfg = {"gemini": [], "groq": [], "pexels": [], "pixabay": "", "openai": "", "used_videos": []}
    if CFG_FILE.exists():
        try:
            data = json.loads(CFG_FILE.read_text())
            for k, v in default_cfg.items():
                if k not in data:
                    data[k] = v
            return data
        except: pass
    return default_cfg

def save_cfg(cfg):
    CFG_FILE.write_text(json.dumps(cfg, indent=2))

if "cfg" not in st.session_state:
    st.session_state.cfg = load_cfg()

# Project state (persisted in JSON)
def get_proj_file():
    mode = st.session_state.get("proj_mode", "main")
    return Path.home() / (".avc_project_shorts.json" if mode == "shorts" else ".avc_project.json")

def load_proj():
    pf = get_proj_file()
    if pf.exists():
        try: return json.loads(pf.read_text())
        except: pass
    return {"script": None, "scenes": [], "step": 0}

def save_proj(p):
    pf = get_proj_file()
    pf.write_text(json.dumps(p, ensure_ascii=False, indent=2))

if "proj_mode" not in st.session_state:
    st.session_state.proj_mode = st.session_state.cfg.get("last_proj_mode", "main")
if "proj" not in st.session_state:
    st.session_state.proj = load_proj()

cfg = st.session_state.cfg
proj = st.session_state.proj

# ── AI helpers ────────────────────────────────────────────────────────────────
def call_gemini(key, prompt):
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}",
        json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.85, "maxOutputTokens": 8192, "responseMimeType": "application/json"}},
        timeout=60,
    )
    d = r.json()
    if not r.ok: raise Exception(d.get("error", {}).get("message", f"Gemini {r.status_code}"))
    return d["candidates"][0]["content"]["parts"][0]["text"].replace("```json", "").replace("```", "").strip()

def call_groq_llm(key, prompt):
    # Models đang hoạt động tốt trên Groq (cập nhật 2025-07)
    # llama-3.1-70b-versatile ❌ deprecated
    # deepseek-r1-distill-llama-70b ❌ 400 on most orgs
    LARGE_MODELS = [
        "llama-3.3-70b-versatile",       # 70B — tốt nhất, ưu tiên
        "meta-llama/llama-4-scout-17b-16e-instruct",  # Llama 4 Scout mới
        "llama3-70b-8192",               # Llama 3 70B legacy (vẫn hoạt động)
    ]
    SMALL_MODELS = [
        "llama-3.1-8b-instant",          # Nhanh, chỉ dùng khi prompt < 6000 chars
        "gemma2-9b-it",                  # Google Gemma
        "llama3-8b-8192",               # Llama 3 8B legacy
    ]

    # Với prompt lớn, chỉ dùng large models (tránh 413)
    prompt_chars = len(prompt)
    models = LARGE_MODELS if prompt_chars > 5000 else (LARGE_MODELS + SMALL_MODELS)

    for model in models:
        max_retries = 2
        backoff = 10
        for attempt in range(max_retries):
            try:
                r = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.85,
                        "max_tokens": 8192,
                    },
                    timeout=90,
                )
            except requests.exceptions.Timeout:
                print(f"[Groq/{model}] Timeout attempt {attempt+1}")
                continue
            except Exception as req_e:
                print(f"[Groq/{model}] Request error: {req_e}")
                break

            if r.status_code == 413:
                # Prompt quá lớn cho model này → thử model tiếp theo (bỏ qua small models)
                print(f"[Groq/{model}] 413 Prompt too large ({prompt_chars} chars) — thử model khác")
                break
            if r.status_code in (400, 404):
                print(f"[Groq/{model}] {r.status_code} — model không khả dụng, thử tiếp")
                break
            if r.status_code == 429:
                retry_after = int(r.headers.get("retry-after", backoff))
                if retry_after > 60:
                    print(f"[Groq/{model}] Quota hết dài hạn ({retry_after}s) — chuyển model/key khác")
                    break
                wait = max(retry_after, backoff)
                print(f"[Groq/{model}] Rate limit 429 — waiting {wait}s (attempt {attempt+1}/{max_retries})...")
                time.sleep(wait)
                backoff = min(backoff * 2, 45)
                continue
            if not r.ok:
                d = r.json() if r.content else {}
                print(f"[Groq/{model}] {r.status_code}: {d.get('error',{}).get('message','?')[:100]}")
                break
            d = r.json()
            content = d["choices"][0]["message"]["content"]
            return content.replace("```json", "").replace("```", "").strip()
    raise Exception("All Groq models unavailable after retries")


def call_openai(key, prompt, model="gpt-4o-mini"):
    """Gọi OpenAI API với model cụ thể."""
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.85,
                "max_tokens": 8192,
            },
            timeout=120,
        )
    except requests.exceptions.Timeout:
        raise Exception(f"OpenAI/{model} Timeout")
    except Exception as e:
        raise Exception(f"OpenAI/{model} Request error: {e}")

    if r.status_code == 429:
        d = r.json() if r.content else {}
        msg = d.get("error", {}).get("message", "")
        raise Exception(f"OpenAI 429: {msg[:100]}")
    if not r.ok:
        d = r.json() if r.content else {}
        msg = d.get("error", {}).get("message", f"HTTP {r.status_code}")
        raise Exception(f"OpenAI {r.status_code}: {msg[:100]}")

    d = r.json()
    content = d["choices"][0]["message"]["content"]
    return content.replace("```json", "").replace("```", "").strip()


def call_ai_script(prompt):
    """Được tối ưu cho sinh kịch bản: ưu tiên OpenAI gpt-4o (chất lượng cao nhất).
    Fallback: gpt-4o-mini → Gemini → Groq.
    """
    last_err = None
    oai_key = cfg.get("openai", "") or ""
    if oai_key.startswith("sk-"):
        # Ưu tiên GPT-4o cho script (sáng tạo hơn gpt-4o-mini)
        for model in ["gpt-4o", "gpt-4o-mini"]:
            try:
                result = call_openai(oai_key, prompt, model=model)
                print(f"[Script] Dùng OpenAI {model}")
                return result
            except Exception as e:
                last_err = str(e)
                print(f"[Script/OpenAI/{model}] skip: {str(e)[:100]}")
                continue
    # Fallback: Gemini
    for key in cfg.get("gemini", []):
        try:
            return call_gemini(key, prompt)
        except Exception as e:
            last_err = str(e)
            print(f"[Script/Gemini] skip: {str(e)[:80]}")
            continue
    # Fallback: Groq
    for key in cfg.get("groq", []):
        try:
            return call_groq_llm(key, prompt)
        except Exception as e:
            last_err = str(e)
            print(f"[Script/Groq] skip: {str(e)[:100]}")
            continue
    if last_err:
        raise Exception(f"Tất cả key lỗi (script). Lỗi cuối: {last_err[:150]}")
    raise Exception("Chưa có API key! Vào Settings thêm OpenAI, Gemini hoặc Groq.")




def call_ai(prompt):
    last_err = None
    # Ưu tiên 1: OpenAI (GPT-4o-mini) — nhanh, ổn định
    oai_key = cfg.get("openai", "") or ""
    if oai_key.startswith("sk-"):
        try:
            return call_openai(oai_key, prompt)
        except Exception as e:
            last_err = str(e)
            print(f"[OpenAI] skip: {str(e)[:100]}")
    # Ưu tiên 2: Gemini
    for key in cfg.get("gemini", []):
        try:
            return call_gemini(key, prompt)
        except Exception as e:
            last_err = str(e)
            print(f"[Gemini] skip: {str(e)[:80]}")
            continue
    # Ưu tiên 3: Groq LLM — try ALL keys before giving up
    for key in cfg.get("groq", []):
        try:
            return call_groq_llm(key, prompt)
        except Exception as e:
            last_err = str(e)
            print(f"[Groq] skip key: {str(e)[:100]}")
            continue
    if last_err:
        raise Exception(f"Tất cả key lỗi. Lỗi cuối: {last_err[:150]}")
    raise Exception("Chưa có API key! Vào Settings thêm OpenAI, Gemini hoặc Groq key.")


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

# ── Subtitle style presets ────────────────────────────────────────────────
SUB_STYLES = {
    "🟡 TikTok Yellow (Viral)":   {"highlight": "&H0000FFFF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&HA0000000", "bold": -1, "shadow": 2},
    "🔥 Fire Orange":              {"highlight": "&H000055FF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&HA0000000", "bold": -1, "shadow": 2},
    "💚 Neon Green":               {"highlight": "&H0000FF66", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&HA0000000", "bold": -1, "shadow": 2},
    "💙 Electric Blue":            {"highlight": "&H00FF8800", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&HA0000000", "bold": -1, "shadow": 2},
    "🩷 Hot Pink":                 {"highlight": "&H006633FF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&HA0000000", "bold": -1, "shadow": 2},
    "⚪ Classic White (Không màu)": {"highlight": "&H00FFFFFF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H80000000", "bold": -1, "shadow": 1},
}

def make_ass(words, W=1920, H=1080, window=4, offset_s=0.0, style_name="🟡 TikTok Yellow (Viral)"):
    """ASS karaoke subtitle — hiển thị 4 từ/lần, highlight TỪNG TỪ khi đang nói.
    Kiểu TikTok/Shorts viral: từ đang nói sáng + to, từ còn lại mờ.

    Input: mỗi entry trong `words` có thể là 1 cụm nhiều từ (từ SRT group=4).
    Hàm sẽ tách ra thành danh sách từ đơn lẻ, phân bổ timestamp đều.
    offset_s: shift ALL subtitle timestamps (negative = earlier).
    """
    if not words:
        return ""

    # Font sizes tuned for portrait (9:16) vs landscape (16:9)
    fs    = 58 if W == 1080 else 34
    margv = 180 if W == 1080 else 120

    # Style preset
    st_cfg = SUB_STYLES.get(style_name, SUB_STYLES["🟡 TikTok Yellow (Viral)"])
    highlight_color = st_cfg["highlight"]
    base_color      = st_cfg["base"]
    outline_color   = st_cfg["outline"]
    back_color      = st_cfg["back"]
    bold            = st_cfg["bold"]
    shadow          = st_cfg["shadow"]

    # ── BƯỚC 1: Tách từng phrase SRT thành danh sách từ đơn lẻ với timestamp ──
    flat_words = []  # list of {"word": str, "start": float, "end": float}
    for entry in words:
        phrase = entry["word"].strip()
        t_start = entry["start"]
        t_end   = entry["end"]
        tokens = phrase.split()
        if not tokens:
            continue
        dur = (t_end - t_start) / len(tokens)  # chia đều thời gian cho mỗi từ
        for k, tok in enumerate(tokens):
            flat_words.append({
                "word":  tok,
                "start": t_start + k * dur,
                "end":   t_start + (k + 1) * dur,
            })

    if not flat_words:
        return ""

    # Auto-detect Korean characters
    has_ko = any(any(0xAC00 <= ord(c) <= 0xD7A3 or 0x1100 <= ord(c) <= 0x11FF for c in w["word"]) for w in flat_words)
    font_name = "Apple SD Gothic Neo" if has_ko else "Arial"

    header = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{fs},{base_color},&H000000FF,{outline_color},{back_color},"
        f"{bold},0,0,0,100,100,5,0,3,3,{shadow},2,30,30,{margv},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    def _t(s):
        s = max(0.0, s + offset_s)
        h = int(s // 3600); m = int((s % 3600) // 60); sec = s % 60
        return f"{h}:{m:02d}:{sec:05.2f}"

    # ── BƯỚC 2: Nhóm thành blocks WINDOW từ, mỗi block hiển thị cùng lúc ──
    WINDOW = 4
    dlg = []

    # ── Detect số/% quan trọng để highlight đặc biệt (đỏ/cam)
    import re as _re
    # Pattern: số nguyên/thập phân kèm đơn vị %, K, M, triệu, 억, 万, etc.
    _STAT_PATTERN = _re.compile(
        r'^[\d,\.]+(%|K|M|B|억|만|triệu|tỷ|ngàn|nghin|lần|x|배|倍|\.)?$',
        _re.IGNORECASE
    )
    # Màu nổi bật cho số thống kê: đỏ cam
    STAT_COLOR   = "&H002222FF"  # Đỏ cam trong BGR (ASS)
    STAT_FS_BUMP = 14            # Phóng to thêm khi là số

    def _is_stat_word(tok: str) -> bool:
        """Trả về True nếu từ này là con số/thống kê cần highlight đặc biệt."""
        t = tok.strip().upper()
        return bool(_STAT_PATTERN.match(t)) and any(c.isdigit() for c in t)

    i = 0
    while i < len(flat_words):
        block = flat_words[i:i + WINDOW]
        for wi, active_w in enumerate(block):
            seg_start = active_w["start"]
            seg_end   = active_w["end"]
            parts = []
            for wj, w in enumerate(block):
                tok = w["word"].upper()
                is_stat = _is_stat_word(tok)
                if wj == wi:
                    # Từ ĐANG NÓI: highlight màu
                    if is_stat:
                        # Số/% → highlight đỏ cam + phóng to nhiều hơn
                        c = STAT_COLOR
                        extra_fs = fs + STAT_FS_BUMP
                        parts.append(
                            f"{{\\c{c}\\fs{extra_fs}\\b1\\shad4\\3c&H00000066&}}{tok}"
                            f"{{\\c{base_color}\\fs{fs}\\b{abs(bold)}\\shad{shadow}}}"
                        )
                    else:
                        parts.append(
                            f"{{\\c{highlight_color}\\fs{fs + 8}\\b1\\shad3}}{tok}"
                            f"{{\\c{base_color}\\fs{fs}\\b{abs(bold)}\\shad{shadow}}}"
                        )
                else:
                    if is_stat:
                        # Số trong block nhưng chưa nói: màu cam mờ
                        parts.append(
                            f"{{\\c{STAT_COLOR}\\alpha&H60&\\fs{fs + 4}\\b1}}{tok}{{\\c{base_color}\\fs{fs}\\alpha&H80&\\b{abs(bold)}}}"
                        )
                    else:
                        parts.append(
                            f"{{\\c{base_color}\\alpha&H80&}}{tok}{{\\alpha&H00&}}"
                        )
            line_text = "\\h".join(parts)
            dlg.append(
                f"Dialogue: 0,{_t(seg_start)},{_t(seg_end)},Default,,0,0,0,,{line_text}"
            )
        i += WINDOW

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

def _split_text_chunks(text: str, max_chars: int = 350) -> list:
    """Split text into chunks ≤ max_chars, breaking at sentence boundaries.
    Giải quyết lỗi CapCut TTS bị cắt cụt với text > ~400 ký tự.
    """
    import re as _re
    # Tách theo câu: dấu chấm/hỏi/chấm than + khoảng trắng
    sentences = _re.split(r'(?<=[.!?])\s+', text.strip())
    chunks, current = [], ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        # Câu đơn dài hơn max_chars → tách theo dấu phẩy
        if len(sent) > max_chars:
            parts = _re.split(r'(?<=,)\s+', sent)
            for part in parts:
                if len(current) + len(part) + 1 <= max_chars:
                    current = (current + " " + part).strip() if current else part
                else:
                    if current:
                        chunks.append(current)
                    # Nếu part vẫn dài thì cắt cứng
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
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(list_file),
               "-c:a", "aac", "-b:a", "128k", "-y", out_path)
        list_file.unlink(missing_ok=True)
        return Path(out_path).exists() and Path(out_path).stat().st_size > 1000
    except Exception as e:
        print(f"[concat_audio] {e}")
        return False


# ── CapCut circuit breaker: auto-skip nếu timeout liên tiếp ────────────────
_CAPCUT_FAIL_COUNT = 0
_CAPCUT_SKIP = False   # True = bỏ qua CapCut, dùng Edge TTS thẳng

def tts(text, voice_cfg="en-US", srt_out=None, rate="1.0"):
    """Try CapCut TTS (chunked) → Edge TTS → Groq, return audio path.
    voice_cfg: either a CapCut display key (e.g. '🇻🇳 Cô Gái Hoạt Ngôn (BV074)')
               or a legacy Edge key (e.g. 'en-US', 'vi-VN').
    rate: speed string for CapCut TTS ('0.8'...'1.3').
    CapCut giới hạn ~400 ký tự/request → tự động chunk + nối audio lại.
    """
    global _CAPCUT_FAIL_COUNT, _CAPCUT_SKIP
    # ── CapCut TTS (preferred, chunked để tránh bị cắt tiếng) ────────────────
    if _CAPCUT_OK and not _CAPCUT_SKIP and voice_cfg in _cc.CAPCUT_VOICES:
        CAPCUT_MAX_CHARS = 350
        if len(text) > CAPCUT_MAX_CHARS:
            chunks = _split_text_chunks(text, max_chars=CAPCUT_MAX_CHARS)
            print(f"[TTS] Chunked: {len(text)} chars → {len(chunks)} chunks")
        else:
            chunks = [text]

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
                print(f"[TTS] CapCut chunk {ci+1}/{len(chunks)} failed → fallback")
                chunk_failed = True
                break

            chunk_audio_paths.append(str(chunk_audio))

            # Merge SRT timestamps với offset
            if srt_out and chunk_srt and chunk_srt.exists():
                words = srt_to_words(str(chunk_srt))
                for w in words:
                    w["start"] += time_offset
                    w["end"]   += time_offset
                all_srt_words.extend(words)

            # Tính offset cho chunk tiếp theo từ duration chunk hiện tại
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
                time_offset += len(chunk_text.split()) / 3.5  # ước lượng

            if ci < len(chunks) - 1:
                import time as _t
                _t.sleep(2)  # Tránh ExceededConcurrentLimit giữa các chunk

        if not chunk_failed and chunk_audio_paths:
            final_audio = AUDIO_DIR / f"{uuid.uuid4().hex}.mp3"
            if _concat_audio_chunks(chunk_audio_paths, str(final_audio)):
                # Ghi SRT tổng hợp
                if srt_out and all_srt_words:
                    srt_content = make_srt(all_srt_words, group=4)
                    Path(srt_out).write_text(srt_content, encoding="utf-8")
                return str(final_audio)

        _CAPCUT_FAIL_COUNT += 1
        if _CAPCUT_FAIL_COUNT >= 2:
            _CAPCUT_SKIP = True
            print(f"[TTS] CapCut failed {_CAPCUT_FAIL_COUNT}x → CIRCUIT BREAKER ON: dùng Edge TTS cho tất cả cảnh còn lại")
        else:
            print("[TTS] CapCut failed → fallback Edge TTS")


    # ── Edge TTS fallback ─────────────────────────────────────────────────────
    # Detect ngôn ngữ + giới tính từ CapCut voice key display name
    _vn_female_hints = ["cô gái", "nữ", "mai", "gái", "hoài my", "hoaimy", "ngọt", "review", "bản tin nữ", "female", "jenny", "sherry"]
    _vn_male_hints   = ["nam minh", "namminh", "thanh niên", "nam trầm", "nam bản", "robot", "male", "guy"]
    _key_lower = voice_cfg.lower()

    if voice_cfg in EDGE_VOICES:
        edge_key = voice_cfg
    elif "🇻🇳" in voice_cfg:
        # Detect giọng nữ VN
        is_female_vn = any(h in _key_lower for h in _vn_female_hints)
        edge_key = "vi-female" if is_female_vn else "vi-VN"
    elif "🇰🇷" in voice_cfg:
        is_female_kr = any(h in _key_lower for h in ["여성", "female", "sunhi", "sun", "cute"])
        edge_key = "ko-female" if is_female_kr else "ko-KR"
    elif "🇺🇸" in voice_cfg:
        is_female_en = any(h in _key_lower for h in ["female", "jenny", "sherry", "janeamber", "cute girl", "energetic female"])
        edge_key = "en-female" if is_female_en else "en-US"
    else:
        edge_key = "en-US"

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
    m = re.search(r'pexels\.com/(?:[^/]+/)*([^/?\&\s]+)', kw)
    if m:
        kw = m.group(1).replace('-', ' ').replace('_', ' ')
    # Strip any remaining URL parts
    kw = re.sub(r'https?://\S+', '', kw)
    kw = kw.replace('/', ' ').replace('\\', ' ')
    # Keep only alphanumeric, spaces, hyphens
    kw = re.sub(r'[^\w\s-]', '', kw).strip()
    # Max 5 words (allow richer context for better search results)
    return ' '.join(kw.split()[:5]) or "nature"


def _keyword_relevance_score(title: str, keyword: str) -> float:
    """Score 0.0-1.0 how relevant a video title is to the search keyword.
    Higher = more relevant. Used to filter out off-topic results like
    'young Korean couple' when keyword is 'studio apartment'.
    """
    if not title or not keyword:
        return 0.0
    kw_words = set(keyword.lower().split())
    title_lower = title.lower()
    # Count how many keyword words appear in the title
    matches = sum(1 for w in kw_words if w in title_lower)
    return matches / len(kw_words) if kw_words else 0.0


MIN_RELEVANCE = 0.25  # Phải có ít nhất 25% từ keyword xuất hiện trong title video
                      # Đặt thấp để không quá loại trừ — chỉ lọc hoàn toàn lạc đề

def is_image_file(path):
    try:
        with open(path, "rb") as f:
            h = f.read(4)
            return h.startswith(b'\xff\xd8\xff') or h.startswith(b'\x89PNG') or h.startswith(b'RIFF')
    except:
        return False

def fetch_pexels(keyword, orientation="landscape", used_urls=None):
    key = (cfg.get("pexels") or [None])[0]
    if not key: return None
    if used_urls is None: used_urls = set()
    
    global_used = set(cfg.get("used_videos", []))
    
    def _search(kw, o, check_global=True):
        url = f"https://api.pexels.com/videos/search?query={requests.utils.quote(kw)}&per_page=30"
        if o: url += f"&orientation={o}"
        r = requests.get(url, headers={"Authorization": key}, timeout=15)
        if not r.ok: return None
        
        videos = r.json().get("videos", [])
        # Shuffle results to avoid choosing the same first video every time
        random.shuffle(videos)
        
        for v in videos:
            files = v.get("video_files", [])
            if not files: continue
            valid_files = [f for f in files if (f.get("width", 0) >= 1080 or f.get("height", 0) >= 1080)]
            if not valid_files: valid_files = files
            valid_files = sorted(valid_files, key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
            f = valid_files[0]
            if not f: continue
            
            link = f["link"]
            if link in used_urls:
                continue
            if check_global and link in global_used:
                continue
                
            # Save to global config
            if "used_videos" not in cfg:
                cfg["used_videos"] = []
            if link not in cfg["used_videos"]:
                cfg["used_videos"].append(link)
                if len(cfg["used_videos"]) > 1000:
                    cfg["used_videos"].pop(0)
                save_cfg(cfg)
            return link
        return None
        
    # Phase 1: Try to search using global deduplication
    res = _search(keyword, orientation, check_global=True)
    if not res and orientation != "":
        res = _search(keyword, "", check_global=True)
    if not res:
        fallback_kw = random.choice(["nature", "landscape", "cityscape", "abstract", "technology", "scenery"])
        res = _search(fallback_kw, orientation, check_global=True)
        if not res and orientation != "":
            res = _search(fallback_kw, "", check_global=True)
            
    # Phase 2: If no new video was found (all were already used), relax global constraint to avoid gray screen
    if not res:
        res = _search(keyword, orientation, check_global=False)
        if not res and orientation != "":
            res = _search(keyword, "", check_global=False)
        if not res:
            fallback_kw = random.choice(["nature", "landscape", "cityscape", "abstract", "technology", "scenery"])
            res = _search(fallback_kw, orientation, check_global=False)
            if not res and orientation != "":
                res = _search(fallback_kw, "", check_global=False)

    def _search_photo(kw, o, check_global=True):
        url = f"https://api.pexels.com/v1/search?query={requests.utils.quote(kw)}&per_page=30"
        if o: url += f"&orientation={o}"
        r = requests.get(url, headers={"Authorization": key}, timeout=15)
        if not r.ok: return None
        photos = r.json().get("photos", [])
        random.shuffle(photos)
        for p in photos:
            link = p.get("src", {}).get("large2x") or p.get("src", {}).get("original")
            if not link: continue
            if link in used_urls: continue
            if check_global and link in global_used: continue
            if "used_videos" not in cfg: cfg["used_videos"] = []
            if link not in cfg["used_videos"]:
                cfg["used_videos"].append(link)
                if len(cfg["used_videos"]) > 1000:
                    cfg["used_videos"].pop(0)
                save_cfg(cfg)
            return link
        return None

    # Phase 3: Fallback to photos if video search exhausted
    if not res:
        res = _search_photo(keyword, orientation, check_global=True)
        if not res and orientation != "":
            res = _search_photo(keyword, "", check_global=True)
        if not res:
            res = _search_photo(keyword, orientation, check_global=False)
            if not res and orientation != "":
                res = _search_photo(keyword, "", check_global=False)

    return res


def _coverr_video_url(v):
    """Build Coverr CDN MP4 URL from video object.
    Ưu tiên: playback_id (Mux CDN) → base_filename (Coverr CDN)
    """
    base = v.get("base_filename", "")
    if base:
        return f"https://cdn.coverr.co/videos/{base}/1080p.mp4"
    return None

def fetch_coverr(keyword, orientation="landscape", used_urls=None):
    """Coverr.co — free stock videos, no API key required.
    API: https://api.coverr.co/videos?query=...
    Response fields: base_filename, is_vertical, thumbnail, duration
    """
    if used_urls is None: used_urls = set()
    global_used = set(cfg.get("used_videos", []))

    def _search(kw, check_global=True):
        try:
            url = f"https://api.coverr.co/videos?query={requests.utils.quote(kw)}&per_page=30"
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if not r.ok:
                print(f"[Coverr] HTTP {r.status_code}")
                return None
            hits = r.json().get("hits", [])
            random.shuffle(hits)
            for v in hits:
                # Bỏ qua video premium
                if v.get("is_premium"): continue

                # Filter orientation dùng is_vertical
                is_vert = v.get("is_vertical", False)
                if orientation == "landscape" and is_vert: continue
                if orientation == "portrait" and not is_vert: continue

                link = _coverr_video_url(v)
                if not link: continue
                if link in used_urls: continue
                if check_global and link in global_used: continue

                if "used_videos" not in cfg: cfg["used_videos"] = []
                if link not in cfg["used_videos"]:
                    cfg["used_videos"].append(link)
                    if len(cfg["used_videos"]) > 1000:
                        cfg["used_videos"].pop(0)
                    save_cfg(cfg)
                print(f"[Coverr] ✅ {v.get('title','?')[:40]}")
                return link
        except Exception as e:
            print(f"[Coverr] {e}")
        return None

    res = _search(keyword, check_global=True)
    if not res:
        fallback_kw = random.choice(["nature", "city", "abstract", "technology", "sky", "ocean"])
        res = _search(fallback_kw, check_global=True)
    if not res:
        res = _search(keyword, check_global=False)
    if not res:
        fallback_kw = random.choice(["nature", "city", "abstract", "technology", "sky", "ocean"])
        res = _search(fallback_kw, check_global=False)
    return res


def search_coverr_videos(keyword, orientation="landscape"):
    """Coverr search for UI preview panel."""
    try:
        url = f"https://api.coverr.co/videos?query={requests.utils.quote(keyword)}&per_page=30"
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if not r.ok:
            return []
        results = []
        hits = r.json().get("hits", [])
        random.shuffle(hits)
        for v in hits:
            if v.get("is_premium"): continue
            is_vert = v.get("is_vertical", False)
            if orientation == "landscape" and is_vert: continue
            if orientation == "portrait" and not is_vert: continue
            link = _coverr_video_url(v)
            if not link: continue
            thumb = v.get("thumbnail") or v.get("poster") or ""
            results.append({
                "id": str(v.get("id", "")),
                "url": link,
                "image": thumb,
                "duration": float(v.get("duration", 0) or 0)
            })
        return results
    except Exception as e:
        print(f"[Coverr Search] {e}")
        return []


def search_pexels_videos(keyword, orientation="landscape"):
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

def fetch_pixabay(keyword, orientation="landscape", used_urls=None):
    key = cfg.get("pixabay", "")
    if not key: return None
    if used_urls is None: used_urls = set()
    global_used = set(cfg.get("used_videos", []))

    def _search(kw, o, check_global=True):
        url = f"https://pixabay.com/api/videos/?key={key}&q={requests.utils.quote(kw)}&per_page=30"
        try:
            r = requests.get(url, timeout=15)
            if not r.ok: return None
            
            videos = r.json().get("hits", [])
            random.shuffle(videos)
            
            for v in videos:
                if not isinstance(v.get("videos"), dict): continue
                res_list = list(v["videos"].values())
                res_list = [r for r in res_list if r.get("url") and r.get("width") and r.get("height")]
                if not res_list: continue
                
                w = res_list[0]["width"]
                h = res_list[0]["height"]
                is_landscape = w >= h
                
                if o == "landscape" and not is_landscape: continue
                if o == "portrait" and is_landscape: continue
                
                res_list = sorted(res_list, key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
                link = res_list[0]["url"]
                
                if link in used_urls: continue
                if check_global and link in global_used: continue
                    
                if "used_videos" not in cfg: cfg["used_videos"] = []
                if link not in cfg["used_videos"]:
                    cfg["used_videos"].append(link)
                    if len(cfg["used_videos"]) > 1000:
                        cfg["used_videos"].pop(0)
                    save_cfg(cfg)
                return link
            return None
        except Exception as e:
            print(f"[Pixabay] {e}")
            return None
            
    res = _search(keyword, orientation, check_global=True)
    if not res and orientation != "": res = _search(keyword, "", check_global=True)
    if not res:
        fallback_kw = random.choice(["nature", "landscape", "cityscape", "abstract", "technology", "scenery"])
        res = _search(fallback_kw, orientation, check_global=True)
        if not res and orientation != "": res = _search(fallback_kw, "", check_global=True)
            
    if not res:
        res = _search(keyword, orientation, check_global=False)
        if not res and orientation != "": res = _search(keyword, "", check_global=False)
        if not res:
            fallback_kw = random.choice(["nature", "landscape", "cityscape", "abstract", "technology", "scenery"])
            res = _search(fallback_kw, orientation, check_global=False)
            if not res and orientation != "": res = _search(fallback_kw, "", check_global=False)
                
    return res

def search_pixabay_videos(keyword, orientation="landscape"):
    key = cfg.get("pixabay", "")
    if not key: return []
    url = f"https://pixabay.com/api/videos/?key={key}&q={requests.utils.quote(keyword)}&per_page=30"
    try:
        r = requests.get(url, timeout=15)
        if not r.ok: return []
        results = []
        videos = r.json().get("hits", [])
        random.shuffle(videos)
        for v in videos:
            if not isinstance(v.get("videos"), dict): continue
            res_list = list(v["videos"].values())
            res_list = [r for r in res_list if r.get("url") and r.get("width") and r.get("height")]
            if not res_list: continue
            
            w = res_list[0]["width"]
            h = res_list[0]["height"]
            is_landscape = w >= h
            if orientation == "landscape" and not is_landscape: continue
            if orientation == "portrait" and is_landscape: continue
                
            res_list = sorted(res_list, key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
            best_res = res_list[0]
            
            results.append({
                "id": str(v["id"]),
                "url": best_res["url"],
                "image": f"https://i.vimeocdn.com/video/{v.get('picture_id')}_640x360.jpg",
                "duration": v.get("duration", 0)
            })
        return results
    except Exception as e:
        print(f"[Pixabay Search] Error: {e}")
        return []

def fetch_stock_video(keyword, orientation="landscape", used_urls=None):
    """Lấy video từ TẤT CẢ providers, lọc theo relevance keyword, tránh dùng lại."""
    if used_urls is None: used_urls = set()
    global_used = set(cfg.get("used_videos", []))

    keyword_candidates  = []  # (url, source, title, relevance_score)
    fallback_candidates = []  # Chỉ dùng khi keyword không có kết quả
    SAFE_FALLBACKS = ["nature scenery", "city street", "ocean waves", "mountain landscape", "forest path"]

    # Pexels
    pexels_key = (cfg.get("pexels") or [None])[0]
    if pexels_key:
        try:
            url_q = f"https://api.pexels.com/videos/search?query={requests.utils.quote(keyword)}&per_page=30"
            if orientation: url_q += f"&orientation={orientation}"
            r = requests.get(url_q, headers={"Authorization": pexels_key}, timeout=10)
            if r.ok:
                for v in r.json().get("videos", []):
                    files = v.get("video_files", [])
                    valid = [f for f in files if (f.get("width",0) >= 1080 or f.get("height",0) >= 1080)]
                    if not valid: valid = files
                    if valid:
                        valid = sorted(valid, key=lambda x: x.get("width",0)*x.get("height",0), reverse=True)
                        vid_title = (v.get("user", {}).get("name", "") + " " + " ".join(str(t) for t in v.get("tags", []))).lower()
                        score = _keyword_relevance_score(v.get("url", "") + " " + vid_title, keyword)
                        keyword_candidates.append((valid[0]["link"], "pexels", vid_title, score))

            # Fallback generic
            fb_kw = random.choice(SAFE_FALLBACKS)
            url_q2 = f"https://api.pexels.com/videos/search?query={requests.utils.quote(fb_kw)}&per_page=15"
            if orientation: url_q2 += f"&orientation={orientation}"
            r2 = requests.get(url_q2, headers={"Authorization": pexels_key}, timeout=10)
            if r2.ok:
                for v in r2.json().get("videos", []):
                    files = v.get("video_files", [])
                    valid = [f for f in files if (f.get("width",0) >= 1080 or f.get("height",0) >= 1080)]
                    if not valid: valid = files
                    if valid:
                        valid = sorted(valid, key=lambda x: x.get("width",0)*x.get("height",0), reverse=True)
                        fallback_candidates.append((valid[0]["link"], "pexels_fb", "", 0.0))
        except Exception as e:
            print(f"[Pexels pool] {e}")

    # Pixabay
    pix_key = cfg.get("pixabay", "")
    if pix_key:
        try:
            url_q = f"https://pixabay.com/api/videos/?key={pix_key}&q={requests.utils.quote(keyword)}&per_page=30"
            r = requests.get(url_q, timeout=10)
            if r.ok:
                for v in r.json().get("hits", []):
                    if not isinstance(v.get("videos"), dict): continue
                    res_list = list(v["videos"].values())
                    res_list = [x for x in res_list if x.get("url") and x.get("width") and x.get("height")]
                    if not res_list: continue
                    w, h = res_list[0]["width"], res_list[0]["height"]
                    is_ls = w >= h
                    if orientation == "landscape" and not is_ls: continue
                    if orientation == "portrait" and is_ls: continue
                    res_list = sorted(res_list, key=lambda x: x.get("width",0)*x.get("height",0), reverse=True)
                    vid_title = v.get("tags", "").lower()
                    score = _keyword_relevance_score(vid_title, keyword)
                    keyword_candidates.append((res_list[0]["url"], "pixabay", vid_title, score))
        except Exception as e:
            print(f"[Pixabay pool] {e}")

    # Coverr (free, no key)
    try:
        url_q = f"https://api.coverr.co/videos?query={requests.utils.quote(keyword)}&per_page=30"
        r = requests.get(url_q, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.ok:
            for v in r.json().get("hits", []):
                files = v.get("urls", {})
                link = files.get("mp4_url") or files.get("mobile_url") or v.get("mp4_url") or v.get("url")
                if not link: continue
                w, h = v.get("width", 0), v.get("height", 0)
                is_ls = (w >= h) if (w and h) else True
                if orientation == "landscape" and not is_ls: continue
                if orientation == "portrait" and is_ls: continue
                vid_title = v.get("title", "").lower()
                score = _keyword_relevance_score(vid_title, keyword)
                keyword_candidates.append((link, "coverr", vid_title, score))

        fb_kw = random.choice(SAFE_FALLBACKS)
        url_q2 = f"https://api.coverr.co/videos?query={requests.utils.quote(fb_kw)}&per_page=15"
        r2 = requests.get(url_q2, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if r2.ok:
            for v in r2.json().get("hits", []):
                files = v.get("urls", {})
                link = files.get("mp4_url") or files.get("mobile_url") or v.get("mp4_url") or v.get("url")
                if link:
                    fallback_candidates.append((link, "coverr_fb", "", 0.0))
    except Exception as e:
        print(f"[Coverr pool] {e}")

    # ── Lọc theo relevance score ──
    # Chia thành: relevant (score >= MIN) và weak (score < MIN, dùng nếu không có gì tốt hơn)
    relevant   = [(u, s, t, sc) for u, s, t, sc in keyword_candidates if sc >= MIN_RELEVANCE]
    weak       = [(u, s, t, sc) for u, s, t, sc in keyword_candidates if sc < MIN_RELEVANCE]
    # Sắp xếp relevant theo score giảm dần
    relevant.sort(key=lambda x: x[3], reverse=True)

    # Log để debug
    print(f"[Stock] keyword='{keyword}' → {len(relevant)} relevant, {len(weak)} weak, {len(fallback_candidates)} fallbacks")
    for u, s, t, sc in relevant[:3]:
        print(f"  [{s}] score={sc:.2f} title='{t[:50]}'")

    # Chọn pool: relevant > weak > fallback
    if relevant:
        all_candidates = [(u, s) for u, s, t, sc in relevant]
    elif weak:
        print(f"[Stock] Không có kết quả relevant — dùng weak pool ({len(weak)} videos)")
        all_candidates = [(u, s) for u, s, t, sc in weak]
    else:
        print(f"[Stock] Không có kết quả keyword — fallback to generic")
        all_candidates = [(u, s) for u, s, t, sc in fallback_candidates]

    if not all_candidates:
        return None

    # Ưu tiên: (1) chưa dùng bao giờ → (2) chưa dùng session → (3) bất kỳ
    random.shuffle(all_candidates)
    fresh   = [(u, s) for u, s in all_candidates if u not in global_used and u not in used_urls]
    session = [(u, s) for u, s in all_candidates if u not in used_urls]
    pool    = fresh or session or all_candidates

    chosen_url, chosen_src = random.choice(pool)
    print(f"[Stock] ✅ {chosen_src}: {chosen_url[:70]}...")

    # Lưu vào lịch sử
    if "used_videos" not in cfg: cfg["used_videos"] = []
    if chosen_url not in cfg["used_videos"]:
        cfg["used_videos"].append(chosen_url)
        if len(cfg["used_videos"]) > 1000:
            cfg["used_videos"].pop(0)
        save_cfg(cfg)

    return chosen_url


def fetch_stock_photo(keyword, orientation="landscape", used_urls=None):
    """Lấy ẢNH stock từ Pexels + Pixabay để làm nền cảnh (thay thế video)."""
    if used_urls is None: used_urls = set()
    global_used = set(cfg.get("used_videos", []))
    candidates = []  # list of (url, preview_url, source)

    # Pexels Photos
    pexels_key = (cfg.get("pexels") or [None])[0]
    if pexels_key:
        try:
            for kw in [keyword, random.choice(["nature", "city", "abstract", "technology", "sky"])]:
                orient_map = {"portrait": "portrait", "landscape": "landscape"}
                o_param = orient_map.get(orientation, "landscape")
                url_q = f"https://api.pexels.com/v1/search?query={requests.utils.quote(kw)}&per_page=30&orientation={o_param}"
                r = requests.get(url_q, headers={"Authorization": pexels_key}, timeout=10)
                if r.ok:
                    for p in r.json().get("photos", []):
                        src = p.get("src", {})
                        link = src.get("original") or src.get("large2x") or src.get("large")
                        preview = src.get("medium") or src.get("small")
                        if link:
                            candidates.append((link, preview or link, "pexels_photo"))
        except Exception as e:
            print(f"[Pexels Photo pool] {e}")

    # Pixabay Photos
    pix_key = cfg.get("pixabay", "")
    if pix_key:
        try:
            o_param = "vertical" if orientation == "portrait" else "horizontal"
            url_q = f"https://pixabay.com/api/?key={pix_key}&q={requests.utils.quote(keyword)}&image_type=photo&per_page=30&orientation={o_param}"
            r = requests.get(url_q, timeout=10)
            if r.ok:
                for p in r.json().get("hits", []):
                    link = p.get("largeImageURL") or p.get("webformatURL")
                    preview = p.get("webformatURL") or p.get("previewURL")
                    if link:
                        candidates.append((link, preview or link, "pixabay_photo"))
        except Exception as e:
            print(f"[Pixabay Photo pool] {e}")

    if not candidates:
        return None, None

    random.shuffle(candidates)
    fresh   = [(u, pv, s) for u, pv, s in candidates if u not in global_used and u not in used_urls]
    session = [(u, pv, s) for u, pv, s in candidates if u not in used_urls]
    pool    = fresh or session or candidates

    chosen_url, chosen_preview, chosen_src = random.choice(pool)
    print(f"[Stock Photo] {chosen_src}: {chosen_url[:60]}...")

    if "used_videos" not in cfg: cfg["used_videos"] = []
    if chosen_url not in cfg["used_videos"]:
        cfg["used_videos"].append(chosen_url)
        if len(cfg["used_videos"]) > 1000:
            cfg["used_videos"].pop(0)
        save_cfg(cfg)

    return chosen_url, chosen_preview


def search_stock_photos(keyword, orientation="landscape"):
    """Tìm kiếm ảnh stock để hiển thị lựa chọn trong UI editor."""
    results = []
    global_used = set(cfg.get("used_videos", []))

    # Pexels Photos
    pexels_key = (cfg.get("pexels") or [None])[0]
    if pexels_key:
        try:
            o_param = "portrait" if orientation == "portrait" else "landscape"
            url_q = f"https://api.pexels.com/v1/search?query={requests.utils.quote(keyword)}&per_page=15&orientation={o_param}"
            r = requests.get(url_q, headers={"Authorization": pexels_key}, timeout=10)
            if r.ok:
                for p in r.json().get("photos", []):
                    src = p.get("src", {})
                    link = src.get("original") or src.get("large2x")
                    preview = src.get("medium") or src.get("small")
                    if link:
                        results.append({
                            "id": str(p["id"]),
                            "url": link,
                            "image": preview or link,
                            "source": "pexels_photo",
                            "already_used": link in global_used,
                            "photographer": p.get("photographer", ""),
                        })
        except Exception as e:
            print(f"[Pexels Photo Search] {e}")

    # Pixabay Photos
    pix_key = cfg.get("pixabay", "")
    if pix_key:
        try:
            o_param = "vertical" if orientation == "portrait" else "horizontal"
            url_q = f"https://pixabay.com/api/?key={pix_key}&q={requests.utils.quote(keyword)}&image_type=photo&per_page=15&orientation={o_param}"
            r = requests.get(url_q, timeout=10)
            if r.ok:
                for p in r.json().get("hits", []):
                    link = p.get("largeImageURL") or p.get("webformatURL")
                    preview = p.get("webformatURL") or p.get("previewURL")
                    if link:
                        results.append({
                            "id": str(p["id"]),
                            "url": link,
                            "image": preview or link,
                            "source": "pixabay_photo",
                            "already_used": link in global_used,
                            "photographer": p.get("user", ""),
                        })
        except Exception as e:
            print(f"[Pixabay Photo Search] {e}")

    # Sắp xếp: chưa dùng lên đầu
    results.sort(key=lambda x: x["already_used"])
    return results


# ── Hiệu ứng ảnh tĩnh (Ken Burns variations) ──────────────────────────────
IMAGE_EFFECTS = [
    "zoom_in",       # Zoom in từ 1.0 → 1.2 (giữa)
    "zoom_out",      # Zoom out từ 1.2 → 1.0 (giữa)
    "pan_right",     # Zoom 1.1, pan từ trái → phải
    "pan_left",      # Zoom 1.1, pan từ phải → trái
    "pan_up",        # Zoom 1.1, pan từ dưới → trên
    "pan_down",      # Zoom 1.1, pan từ trên → xuống
]

# ── Hiệu ứng intro video (áp dụng khi video bắt đầu mỗi cảnh) ─────────────
VIDEO_INTRO_EFFECTS = [
    "fade_in",          # Fade từ đen → hình (0.3s)
    "slide_right",      # Trượt vào từ trái sang phải
    "slide_up",         # Trượt vào từ dưới lên
    "zoom_punch",       # Zoom nhanh từ 1.1 → 1.0 (punch in)
    "none",             # Không hiệu ứng (cut trực tiếp)
]

def make_video_intro_filter(W, H, dur, effect=None):
    """Tạo FFmpeg vf filter cho video intro effect.
    Trả về filter string hoặc None nếu không cần.
    """
    if effect is None:
        effect = random.choice(["fade_in", "slide_right", "slide_up", "zoom_punch", "none", "none"])
    if effect == "none" or not effect:
        return None
    intro_dur = min(0.4, dur * 0.15)  # tối đa 0.4s, không quá 15% cảnh
    if effect == "fade_in":
        return f"fade=t=in:st=0:d={intro_dur:.2f}"
    elif effect == "slide_right":
        # Trượt từ trái vào: x từ -W → 0 trong intro_dur giây
        frames = max(1, int(intro_dur * 30))
        return f"scale={W}:{H},crop={W}:{H},overlay=x='if(lt(n,{frames}),(-{W}+(n*{W}/{frames})),0)':y=0" \
               if False else f"fade=t=in:st=0:d={intro_dur:.2f}"  # fallback fade
    elif effect == "slide_up":
        return f"fade=t=in:st=0:d={intro_dur:.2f}"  # simplified
    elif effect == "zoom_punch":
        # Zoom từ 1.05 → 1.0 nhanh
        frames = max(1, int(intro_dur * 30))
        return (
            f"zoompan=z='if(lt(on,{frames}),1.05-0.05*(on/{frames}),1.0)'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={frames+1}:s={W}x{H},fps=30"
        )
    return None


# ── Sound Effects nhúng sẵn (Base64 hoặc URL) ────────────────────────────
# Dùng FFmpeg lavfi để tạo sound effect đơn giản (không cần file ngoài)
SOUND_EFFECTS = {
    "whoosh":    "sine=frequency=400:duration=0.3,afade=t=in:ss=0:d=0.05,afade=t=out:st=0.25:d=0.05,volume=0.6",
    "click":     "sine=frequency=800:duration=0.08,afade=t=out:st=0.02:d=0.06,volume=0.7",
    "chime":     "sine=frequency=880:duration=0.5,afade=t=in:ss=0:d=0.05,afade=t=out:st=0.4:d=0.1,volume=0.5",
    "deep_hit":  "sine=frequency=60:duration=0.4,afade=t=in:ss=0:d=0.05,afade=t=out:st=0.3:d=0.1,volume=0.8",
    "none":      None,
}


def apply_sound_effect_to_scene(scene_mp4: Path, effect_name: str, out_path: Path) -> bool:
    """Mix một sound effect ngắn vào đầu video cảnh.
    Trả về True nếu thành công.
    """
    if effect_name == "none" or effect_name not in SOUND_EFFECTS:
        return False
    lavfi_filter = SOUND_EFFECTS[effect_name]
    if not lavfi_filter:
        return False
    try:
        tmp = out_path.parent / f"sfx_tmp_{out_path.name}"
        ffmpeg(
            "-i", str(scene_mp4),
            "-f", "lavfi", "-i", f"aevalsrc={lavfi_filter}",
            "-filter_complex",
            "[0:a]volume=1.0[a0];[1:a]volume=0.6[sfx];[sfx][a0]amix=inputs=2:duration=first:dropout_transition=0.1[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
            "-y", str(tmp)
        )
        if tmp.exists() and tmp.stat().st_size > 10000:
            shutil.move(str(tmp), str(out_path))
            return True
    except Exception as e:
        print(f"[SFX] {effect_name} lỗi: {e}")
    return False

def make_image_effect_filter(W, H, dur, effect=None):
    """
    Tạo FFmpeg filter chain cho ảnh tĩnh với hiệu ứng chuyển động.
    Trả về filter string để dùng trong -vf.
    """
    if effect is None:
        effect = random.choice(IMAGE_EFFECTS)

    d_frames = math.ceil(dur * 30) + 15  # số frame cần cho zoompan
    fps_filter = "fps=30"

    base_scale = f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2}"

    if effect == "zoom_in":
        # Zoom in từ 1.0 → 1.2, anchor giữa
        zp = (
            f"zoompan=z='min(1+0.007*(on/{d_frames}),1.2)'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={d_frames}:s={W}x{H}"
        )
    elif effect == "zoom_out":
        # Zoom out từ 1.2 → 1.0, anchor giữa
        zp = (
            f"zoompan=z='max(1.2-0.007*(on/{d_frames}),1.0)'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={d_frames}:s={W}x{H}"
        )
    elif effect == "pan_right":
        # Pan từ trái → phải với zoom nhẹ
        zp = (
            f"zoompan=z='1.1'"
            f":x='(iw-iw/zoom)*(on/{d_frames})'"
            f":y='ih/2-(ih/zoom/2)'"
            f":d={d_frames}:s={W}x{H}"
        )
    elif effect == "pan_left":
        # Pan từ phải → trái với zoom nhẹ
        zp = (
            f"zoompan=z='1.1'"
            f":x='(iw-iw/zoom)*(1-on/{d_frames})'"
            f":y='ih/2-(ih/zoom/2)'"
            f":d={d_frames}:s={W}x{H}"
        )
    elif effect == "pan_up":
        # Pan từ dưới → trên với zoom nhẹ
        zp = (
            f"zoompan=z='1.1'"
            f":x='iw/2-(iw/zoom/2)'"
            f":y='(ih-ih/zoom)*(1-on/{d_frames})'"
            f":d={d_frames}:s={W}x{H}"
        )
    else:  # pan_down
        # Pan từ trên → xuống với zoom nhẹ
        zp = (
            f"zoompan=z='1.1'"
            f":x='iw/2-(iw/zoom/2)'"
            f":y='(ih-ih/zoom)*(on/{d_frames})'"
            f":d={d_frames}:s={W}x{H}"
        )

    return f"{base_scale},{zp},{fps_filter}"


def search_stock_videos(keyword, orientation="landscape"):
    """Tìm video và ảnh stock cho UI editor. Tự động thêm ảnh nếu video ít."""
    providers = []
    if (cfg.get("pexels") or [None])[0]: providers.append("pexels")
    if cfg.get("pixabay", ""): providers.append("pixabay")
    providers.append("coverr")

    results = []
    if "pexels" in providers: results.extend(search_pexels_videos(keyword, orientation))
    if "pixabay" in providers: results.extend(search_pixabay_videos(keyword, orientation))
    if "coverr" in providers: results.extend(search_coverr_videos(keyword, orientation))

    # Đánh dấu video đã từng dùng, sắp xếp: chưa dùng lên đầu
    global_used = set(cfg.get("used_videos", []))
    for item in results:
        item["already_used"] = item.get("url", "") in global_used

    random.shuffle(results)
    results.sort(key=lambda x: 1 if x.get("already_used") else 0)

    # Nếu video ít hơn 5, tự động bổ sung ảnh stock (có hiệu ứng động khi render)
    if len(results) < 5:
        photo_results = search_stock_photos(keyword, orientation)
        for ph in photo_results[:12]:
            results.append({
                "id": ph["id"],
                "url": ph["url"],
                "image": ph["image"],
                "source": ph["source"],
                "duration": 0,  # ảnh không có duration cố định
                "already_used": ph["already_used"],
                "is_photo": True,  # flag để hiển thị nhãn khác trong UI
                "photographer": ph.get("photographer", ""),
            })

    return results[:30]

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

def save_and_next_scene(idx_val, n_text, n_kw, n_dur, n_mode, n_start=0.0):
    proj = load_proj()
    if idx_val < len(proj.get("scenes", [])):
        proj["scenes"][idx_val]["text"] = n_text
        proj["scenes"][idx_val]["keyword"] = n_kw
        proj["scenes"][idx_val]["duration"] = n_dur
        proj["scenes"][idx_val]["videoTrimMode"] = n_mode
        if n_mode == "custom":
            proj["scenes"][idx_val]["videoTrimStart"] = n_start
        proj["scenes"][idx_val]["completed"] = True
        
        if idx_val < len(proj["scenes"]) - 1:
            st.session_state.selectbox_scene_active = idx_val + 1
            proj["active_scene_idx"] = idx_val + 1
        save_proj(proj)

# ── UI ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
[data-testid="stSidebar"] { background: #13151c; }
.stButton button { width: 100%; }

/* Tạo thanh cuộn riêng biệt cho cột Kết Quả (cột số 2) */
div[data-testid="stTabContent"] > div > div[data-testid="stHorizontalBlock"] > div:nth-child(2) {
    height: calc(100vh - 120px) !important;
    overflow-y: auto !important;
    padding-right: 15px !important;
}
/* Làm đẹp thanh cuộn */
div[data-testid="stTabContent"] > div > div[data-testid="stHorizontalBlock"] > div:nth-child(2)::-webkit-scrollbar {
    width: 6px;
}
div[data-testid="stTabContent"] > div > div[data-testid="stHorizontalBlock"] > div:nth-child(2)::-webkit-scrollbar-track {
    background: transparent;
}
div[data-testid="stTabContent"] > div > div[data-testid="stHorizontalBlock"] > div:nth-child(2)::-webkit-scrollbar-thumb {
    background-color: #555;
    border-radius: 10px;
}

/* Giảm khoảng trắng thừa cho giao diện kịch bản gọn gàng */
div[data-testid="stExpanderDetails"] {
    padding: 0.6rem 0.8rem 0.8rem 0.8rem !important;
}
div[data-testid="stVerticalBlock"] > div {
    gap: 0.4rem !important;
}
div.element-container {
    margin-bottom: 0.15rem !important;
}
hr {
    margin: 0.6rem 0 !important;
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

    st.subheader("🎬 Coverr (Free — Không cần API key)")
    st.success("✅ Coverr.co đã được tích hợp sẵn — không cần cấu hình gì!")
    st.caption("Hàng nghìn video stock 16:9 & 9:16 miễn phí, tự động dùng khi Pexels/Pixabay hết kết quả.")

    st.divider()
    used_count = len(cfg.get("used_videos", []))
    st.markdown(f"**🗂️ Lịch sử video đã dùng:** `{used_count}` URL (tránh lặp lại)")
    st.caption("Hệ thống tự động tránh dùng lại video cũ. Xóa lịch sử nếu muốn cho phép dùng lại.")
    if st.button(f"🗑️ Xóa lịch sử video đã dùng ({used_count})", type="secondary"):
        cfg["used_videos"] = []
        save_cfg(cfg)
        st.success("✅ Đã xóa lịch sử! Hệ thống sẽ có thể dùng lại video cũ.")
        st.rerun()

    st.subheader("🎨 OpenAI Key (DALL-E 3 Thumbnail)")
    st.caption("Dùng để tạo kịch bản AI + thumbnail DALL-E 3. Lấy key tại platform.openai.com/api-keys")
    oai = st.text_input("OpenAI key (dùng cho cả script + thumbnail)", value=cfg.get("openai",""), placeholder="sk-...", type="password", key="oai_in")
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
    st.markdown("### 🗂️ Quản lý Dự án")
    default_mode_idx = 1 if st.session_state.proj_mode == "shorts" else 0
    mode_selection = st.radio(
        "Loại Video đang làm:", 
        ["Video Chính (Dài)", "Video Shorts (Độc lập)"], 
        index=default_mode_idx,
        horizontal=True, 
        help="Shorts = video độc lập, nội dung riêng, không liên quan đến video chính."
    )
    new_mode = "shorts" if "Shorts" in mode_selection else "main"
    if st.session_state.get("proj_mode") != new_mode:
        st.session_state.proj_mode = new_mode
        cfg["last_proj_mode"] = new_mode
        save_cfg(cfg)
        st.session_state.proj = load_proj()
        st.rerun()

    proj = st.session_state.proj

    col_left, col_right = st.columns([1, 1.6])

    with col_left:
        st.subheader("⚙️ Cấu hình")

        niche = st.selectbox("🎯 Chủ đề", [
            "technology","finance","health","science","motivation",
            "business","history","psychology","travel","food"
        ])
        if new_mode == "shorts":
            custom = st.text_area(
                "🎥 Nội dung Short (mô tả càng cụ thể càng tốt)",
                placeholder=(
                    "Ví dụ:\n"
                    "Chủ đề: Tại sao người trẻ Việt không tiết kiệm được tiền\n"
                    "Phông cách: Câu chuyện thực tế, gần gũi, không hàn lâm\n"
                    "Thông điệp chính: 1 lý do cụ thể và 1 giải pháp thực tế"
                ),
                height=130,
                key="shorts_custom_input"
            )
        else:
            custom = st.text_area("Hoặc nhập mô tả chi tiết (tùy chỉnh)", placeholder="Ví dụ:\nChủ đề: 한국 집값\nNội dung chính:\n- ...\nTôn màu: ...", height=150)
        default_dur = 60 if new_mode == "shorts" else 600
        duration = st.number_input("⏱️ Tổng thời lượng (giây)", min_value=15, max_value=18000, value=default_dur, step=30, help="Nhập thời lượng video tính bằng giây (VD: 600 = 10 phút, 1800 = 30 phút)")
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

        # Khôi phục aspect đã chọn trước đó; fallback theo mode nếu chưa có
        _saved_aspect = proj.get("aspect", "")
        if _saved_aspect in ["16:9 (YouTube)", "9:16 (Shorts/TikTok)"]:
            default_aspect = ["16:9 (YouTube)", "9:16 (Shorts/TikTok)"].index(_saved_aspect)
        else:
            default_aspect = 1 if new_mode == "shorts" else 0
        aspect = st.radio("📐 Tỉ lệ", ["16:9 (YouTube)","9:16 (Shorts/TikTok)"], index=default_aspect, horizontal=True)
        if aspect != proj.get("aspect"):
            proj["aspect"] = aspect
            save_proj(proj)
        show_sub = st.checkbox("💬 Thêm phụ đề (sub từng chữ)", value=False)
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
            # Với Shorts: ưu tiên nội dung riêng, fallback về niche nếu trống
            if new_mode == "shorts" and not topic:
                topic = niche + " (short-form, independent)"
            is_shorts_mode = (new_mode == "shorts")

            voice_id = "Fritz-PlayAI" if "Fritz" in voice else "Celeste-PlayAI"
            work = TMP / uuid.uuid4().hex
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

                    rate_val         = float(tts_rate)
                    # Words per second by language (actual TTS playback speed):
                    # Vietnamese Edge TTS reads very fast (~3.8 wps)
                    # Korean/English ~2.2 wps
                    _wps_map = {"Vietnamese": 3.8, "Korean": 2.2, "English": 2.2}
                    words_per_sec    = _wps_map.get(lang, 2.2) * rate_val
                    # Minimum words per scene varies by language (Vietnamese needs more to fill time)
                    _min_words_map   = {"Vietnamese": 35, "Korean": 18, "English": 18}
                    min_words_scene  = _min_words_map.get(lang, 18)
                    total_words      = max(40, round((duration + 2) * words_per_sec))
                    words_per_scene  = max(min_words_scene, round(target_sec_per_scene * words_per_sec))
                    log(f"  📊 Mục tiêu: {sc} cảnh × {words_per_scene} từ/cảnh (~{target_sec_per_scene}s/cảnh) = tổng ~{round(sc*target_sec_per_scene/60,1)}phút")

                    hook_map = {
                        "🤯 Shock & Awe — Con số / sự thật gây sốc":
                            "Start with a SHOCKING statistic or fact. Example: '99% of people do X wrong...' Make viewer think WTF.",
                        "❓ Curiosity Gap — Câu hỏi bỏ lửng tạo tò mò":
                            "Open with a question only answered by finishing the video. Leave an irresistible knowledge gap.",
                        "🔥 Controversial — Phát biểu gây tranh cãi":
                            "Start with a bold polarizing statement. Example: '[Common belief] is completely wrong and here's proof.'",
                        "⚠️ Warning / Fear — Cảnh báo, nguy cơ":
                            "Open with an urgent warning. Example: 'Stop doing this immediately — it's silently damaging your...'",
                        "🤫 Secret / Insider — Bí mật ít người biết":
                            "Position as revealing exclusive insider info. Use 'nobody talks about this' or 'what they don't want you to know'.",
                        "🎭 Story / Relatable — Câu chuyện cá nhân":
                            "Start in the middle of an interesting personal story. Use 'in medias res'.",
                        "📣 Bold Claim — Tuyên bố mạnh mẽ":
                            "Make an audacious specific big promise in the first sentence.",
                        "🎲 Random — AI tự chọn tốt nhất":
                            "Choose the most effective hook type for this topic and audience.",
                    }
                    hook_instruction = hook_map.get(hook_style, hook_map["🎲 Random — AI tự chọn tốt nhất"])

                    retention_rules = ""
                    if pattern_interrupt:
                        retention_rules += "\n- PATTERN INTERRUPT: Every 2-3 scenes insert a surprising twist or tonal shift."
                    if add_loop_teaser:
                        retention_rules += "\n- LOOP ENDING: The LAST scene must call back to the opening hook."
                    if cta_style != "Không có":
                        retention_rules += f'\n- CTA: Add a natural call-to-action: "{cta_style}".'
                    retention_rules += '\n- NEVER end with "Thank you for watching", "감사합니다", or "Cảm ơn".'
                    retention_rules += '\n- ANTI-REPETITION: NEVER repeat the same idea, sentence, or phrase across scenes. Each scene MUST introduce NEW information. If a point was made in scene N, it MUST NOT appear again in any subsequent scene.'

                    if lang == 'Korean':
                        lang_style_instruction = (
                            "For scenes involving people/streets/lifestyle, prefer keywords with 'Korean', 'Korea', or 'Seoul'. "
                            "For universal topics (nature, science, data), use generic English visuals."
                        )
                        kw_example = '"elderly Korean man walking park"'
                        kw_bad = '"aging population", "Korean society", "Korea trend"'
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
                    }

                    keyword_instruction = (
                        f"- keyword: A CONCRETE, VISUAL English search phrase (2-5 words) for stock VIDEO search.\n"
                        f"  The keyword = what a CAMERA physically sees. NOT what the narration talks about conceptually.\n"
                        f"\n"
                        f"  === CRITICAL ANTI-MISMATCH RULES ===\n"
                        f"  ❌ WRONG MAPPING (these cause context errors):\n"
                        f"    - Narration: 'research policy' → keyword: 'scientist lab' (WRONG — that's chemistry lab)\n"
                        f"    - Narration: 'cost management' → keyword: 'VR headset technology' (WRONG — no connection)\n"
                        f"    - Narration: 'government support' → keyword: 'Gyeongbokgung palace tourism' (WRONG — tourist site)\n"
                        f"    - Narration: 'regional difference' → keyword: 'rural mountain village' (WRONG — not urban zones)\n"
                        f"  ✅ CORRECT MAPPING (camera shows the HUMAN CONTEXT of the idea):\n"
                        f"    - Narration: 'research policy' → keyword: 'person reading article laptop' ✓\n"
                        f"    - Narration: 'cost management' → keyword: 'person counting money stress' ✓\n"
                        f"    - Narration: 'government support' → keyword: 'city hall government building' ✓\n"
                        f"    - Narration: 'regional difference' → keyword: 'apartment tower skyline comparison' ✓\n"
                        f"\n"
                        f"  === VISUAL CATEGORY GUIDE (pick the CLOSEST match) ===\n"
                        f"  • Housing/Rent scene → apartment interior, moving boxes, rent sign, real estate\n"
                        f"  • Finance/Money scene → person with calculator, budget spreadsheet, piggy bank, cash\n"
                        f"  • Government/Policy scene → government building, official signing document, city hall\n"
                        f"  • Research/Learning scene → person reading laptop, financial charts screen, notebook desk\n"
                        f"  • Stress/Emotion scene → young adult worried, tired person alone, stressed millennial\n"
                        f"  • City/Urban scene → apartment tower skyline, city street pedestrians, subway commute\n"
                        f"  • When unsure → use 'minimalist abstract background' or 'blurred city lights bokeh'\n"
                        f"\n"
                        f"  {lang_style_instruction}\n"
                        f"  Example for this video: {kw_example}\n"
                        f"  ❌ NEVER use: {kw_bad}\n"
                        f"  ❌ NEVER single words. ❌ NEVER URLs. ❌ NEVER lab/science unless LITERALLY about science."
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
                            else "Write in clear, engaging English."
                        )

                        # ── Ngôn ngữ tự nhiên theo từng thứ tiếng ──
                        if lang == "Vietnamese":
                            speech_rules = (
                                "VIETNAMESE SPEECH STYLE:\n"
                                "- Speak like a REAL Vietnamese content creator on TikTok, not a news anchor.\n"
                                "- Use natural conversational words: 'bạn biết không', 'thật ra', 'thú vị là', 'nghe có vẻ', 'nhưng mà', 'và đây là điều', 'điều điên rồ nhất là'\n"
                                "- Short punchy sentences. Max 2 clauses per sentence.\n"
                                "- NEVER use: formal report language, passive voice excess, academic tone.\n"
                                "- OK to use: rhetorical questions, direct address ('bạn', 'mình'), mild emphasis ('thực sự', 'cực kỳ', 'không ngờ')"
                            )
                        elif lang == "Korean":
                            speech_rules = (
                                "KOREAN SPEECH STYLE:\n"
                                "- Write in natural 해요체, conversational like a Korean YouTuber.\n"
                                "- Use engaging phrases: '알고 계셨나요?', '사실은', '충격적인 건', '여기서 반전이', '근데 진짜로'\n"
                                "- Short sentences. Each scene = 1 clear point.\n"
                                "- AVOID textbook Korean, overly polite 습니다체, robotic phrasing."
                            )
                        else:
                            speech_rules = (
                                "ENGLISH SPEECH STYLE:\n"
                                "- Write like a top TikTok narrator: conversational, punchy, direct.\n"
                                "- Use: 'Here's the thing', 'But wait', 'The crazy part is', 'Nobody talks about this', 'And that's when'\n"
                                "- Short sentences. Fragments OK for emphasis. 'Like this.'\n"
                                "- NEVER start with 'In this video' or 'Today I'm going to'."
                            )

                        # ── Retention framework: Shorts có triết lý riêng với Long video ──
                        if is_shorts:
                            retention_framework = (
                                "=== SHORTS / TIKTOK SCRIPT FRAMEWORK ===\n"
                                f"Format: {total_scenes_needed} scenes × {target_sec_per_scene}s = ~{duration}s vertical video (9:16).\n"
                                "\n"
                                "!!! CRITICAL: This is a 100% STANDALONE, INDEPENDENT Short video. !!!\n"
                                "It has NO connection to any other video, main video, or series.\n"
                                "DO NOT write: 'Watch the full video', 'As mentioned in part 1', 'Link in bio', 'In my previous video'.\n"
                                "Treat this like it\'s the ONLY video the viewer will ever see from this creator.\n\n"
                                "=== THE ONE-IDEA RULE ===\n"
                                "The ENTIRE video = 1 central message. Every scene serves ONLY that 1 idea.\n"
                                f"  • Scene 1 (HOOK — 0\u20133s): {hook_instruction}\n"
                                "    → Must make viewer STOP scrolling instantly. No warm-up. Start mid-story.\n\n"
                                f"  • Scenes 2\u2013{max(2, total_scenes_needed-2)} (CORE): Build the ONE idea layer by layer.\n"
                                "    → Each scene = 1 new layer of the same idea (not a new topic).\n"
                                "    → Use: contrast, surprising fact, relatable example, emotional moment.\n"
                                "    → Viewer should feel: 'I never thought about it that way'.\n\n"
                                f"  • Last scene (PAYOFF — ~{target_sec_per_scene}s): Deliver the insight or emotional peak.\n"
                                "    → This is the reason the viewer watched. Make it EARNED and MEMORABLE.\n"
                                "    → End with a line viewers want to save or share (no CTA needed).\n\n"
                                "=== WHAT MAKES A GREAT STANDALONE SHORT ===\n"
                                "✔️ COMPLETE story arc: setup → build → payoff. Fully satisfying alone.\n"
                                "✔️ 1 clear takeaway the viewer remembers after scrolling away.\n"
                                "✔️ Every scene moves the idea FORWARD, never sideways.\n"
                                "✔️ Sentences: max 10 words. Natural speech rhythm.\n\n"
                                "=== STRICTLY FORBIDDEN ===\n"
                                "❌ Any reference to another video, part, or series\n"
                                "❌ 'In this video I will...' / 'Watch till the end' / 'Like and subscribe'\n"
                                "❌ Ending without resolving the opening hook\n"
                                "❌ Multiple unrelated facts / topics crammed into 60s\n"
                                "❌ Filler: 'As we can see', 'It is worth noting', 'To summarize'\n"
                                "❌ Repeating any information from a previous scene"
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
                                "✅ Start sentences with VERBS or NUMBERS when possible: 'Researchers found...', '90% of people...'\n"
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
                                f'"keyword":{kw_example},"retention_note":"why viewer stays"}}]}}'
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
                                f'"keyword":{kw_example},"retention_note":"why viewer stays"}}]}}'
                            )

                        batch_prompt = (
                            f"[seed:{seed}-b{batch_num}] You are an ELITE {'vertical Shorts/TikTok' if is_shorts else 'viral short-form'} video scriptwriter.\n"
                            f"{'Your Shorts feel meaningful and complete — viewers save and share them.' if is_shorts else 'Your videos consistently get 70%+ completion rates on TikTok and YouTube Shorts.'}\n"
                            f"CRITICAL: ALL \"text\" fields MUST be written in {lang} ({lang_upper}). {lang_rule}\n\n"
                            f"{context_block}\n\n"
                            f"=== THIS BATCH ===\n"
                            f"Write EXACTLY {batch_count} scenes (IDs {batch_start} to {batch_end}).\n"
                            f"Each scene narration: EXACTLY {words_per_scene} words (±3). MINIMUM {min_words_scene} words — NEVER write less.\n"
                            f"SCENE FOCUS RULE (CRITICAL): Each scene = EXACTLY 1 clear point. ONE idea only.\n"
                            f"  ❌ WRONG: Scene combining 2+ facts/ideas/statistics\n"
                            f"  ✅ RIGHT: Scene with 1 specific fact + 1 emotional reaction or 1 action word\n"
                            f"  If you have more to say → save it for the NEXT scene. Never pack 2 ideas into 1 scene.\n"
                            f"{keyword_instruction}\n\n"
                            f"Return ONLY valid JSON (no markdown, no explanation):\n{format_str}"
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
                        use_photo = (sc_idx > 0) and (sc_idx % AUTO_MIX_PHOTO_EVERY == 0)
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
                            vid_url = fetch_stock_video(kw_clean, orientation=vid_orientation, used_urls=used_pexels_urls)
                            if vid_url:
                                used_pexels_urls.add(vid_url)
                        scenes.append({
                            "id":        sc_data["id"],
                            "text":      sc_data["text"],
                            "keyword":   sc_data["keyword"],
                            "videoUrl":  vid_url,
                            "imageUrl":  img_url,
                            "audioDone": False,
                            "targetDur": float(target_sec_per_scene),
                            "duration":  round(max(float(target_sec_per_scene), len(sc_data["text"].split()) / words_per_sec + 0.4), 1),
                        })
                    proj.update({"script": script, "scenes": scenes, "step": 1})
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
                    scenes = proj["scenes"]

                # STEP 2: Footage
                if run_all:
                    log("🎬 Tải footage Pexels...")
                    vid_orientation = "portrait" if "9:16" in aspect else "landscape"
                    used_urls_step2 = set(s.get("videoUrl") for s in scenes if s.get("videoUrl"))
                    for i, s in enumerate(scenes):
                        if not s.get("customVid") and not s.get("videoUrl"):
                            log(f"  Cảnh {i+1}/{len(scenes)}: {s['keyword']}")
                            url = fetch_stock_video(clean_keyword(s["keyword"]), orientation=vid_orientation, used_urls=used_urls_step2)
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
                            log(f"  ♻️ Cache audio cảnh {i+1} — probe duration...")
                            # Vẫn phải probe để cập nhật duration theo audio-driven logic mới
                            try:
                                probe_c = subprocess.run(
                                    [FFMPEG, "-i", str(audio_path), "-f", "null", "-"],
                                    capture_output=True, text=True
                                )
                                for line in probe_c.stderr.split("\n"):
                                    if "Duration:" in line:
                                        ts = line.split("Duration:")[1].split(",")[0].strip()
                                        hc, mc, secc = ts.split(":")
                                        actual_dur = int(hc)*3600 + int(mc)*60 + float(secc)
                                        break
                            except Exception:
                                pass
                            if show_sub and (not srt_path.exists() or srt_path.stat().st_size == 0):
                                actual_dur = srt_from_audio(audio_path, s["text"], srt_path)
                        else:
                            result = tts(s["text"], voice_cfg_key,
                                         srt_out=str(srt_path) if show_sub else None,
                                         rate=tts_rate)
                            if result:
                                # Sleep đủ lâu để tránh ExceededConcurrentLimit ở cảnh 5+
                                if not _CAPCUT_SKIP:
                                    time.sleep(3)  # tăng từ 1s → 3s để CapCut không timeout
                                shutil.copy(result, audio_path)
                                if show_sub and srt_path.exists() and srt_path.stat().st_size == 0:
                                    actual_dur = srt_from_audio(audio_path, s["text"], srt_path)
                            else:
                                # TTS thất bại → retry 1 lần với Edge TTS fallback trực tiếp
                                log(f"  ⚠️ TTS cảnh {i+1} thất bại, retry Edge TTS...")
                                time.sleep(2)
                                edge_key = "vi-female" if lang == "Vietnamese" else ("ko-female" if lang == "Korean" else "en-US")
                                edge_audio = AUDIO_DIR / f"{uuid.uuid4().hex}_edge.mp3"
                                retry_result, _ = tts_edge_with_timing(
                                    s["text"], edge_key, edge_audio,
                                    str(srt_path) if show_sub else None
                                )
                                if retry_result:
                                    shutil.copy(retry_result, audio_path)
                                    log(f"  ✅ Retry Edge TTS cảnh {i+1} thành công")



                        if audio_path.exists():
                            scenes[i]["audioFile"] = str(audio_path)
                            scenes[i]["srtFile"]   = str(srt_path) if (srt_path.exists() and srt_path.stat().st_size > 0) else None
                            
                            if not actual_dur:
                                try:
                                    probe = subprocess.run(
                                        [FFMPEG, "-i", str(audio_path), "-f", "null", "-"],
                                        capture_output=True, text=True
                                    )
                                    for line in probe.stderr.split("\n"):
                                        if "Duration:" in line:
                                            ts = line.split("Duration:")[1].split(",")[0].strip()
                                            h, m, sec = ts.split(":")
                                            actual_dur = int(h)*3600 + int(m)*60 + float(sec)
                                            break
                                except Exception as e:
                                    pass
                                    
                            aud_dur = actual_dur if (actual_dur and actual_dur > 0) else max(3.0, len(s["text"].split()) / 3.5)
                            scenes[i]["audioDur"] = aud_dur

                            # ── Duration = Audio-driven (cảnh chuyển ngay khi giọng kết thúc) ──
                            # Thêm 0.3s padding nhỏ để chuyển cảnh mượt, không im lặng dài
                            AUDIO_PADDING = 0.3
                            final_dur = max(1.5, round(aud_dur + AUDIO_PADDING, 1))
                            scenes[i]["duration"] = final_dur

                            log(f"  ✅ Audio cảnh {i+1}: đọc {aud_dur:.1f}s → scene {final_dur:.1f}s" + (" + sub" if scenes[i].get('srtFile') else ""))
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

                    # ── Lấy duration từ audio thực tế (không tin giá trị cũ trong project) ──
                    src_audio = Path(s.get("audioFile", "")) if s.get("audioFile") else None
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
                                        dur = max(1.5, round(_real_dur + 0.3, 1))
                                    break
                        except Exception:
                            pass
                        log(f"  ⏱ Cảnh {i+1}: audio={dur-0.3:.1f}s → scene={dur:.1f}s (stored was {stored_dur:.1f}s)")

                    # ── AUDIO: Trim/pad đúng `dur` giây ──
                    audio_path = s_dir / "audio_trimmed.aac"
                    if src_audio and src_audio.exists():
                        ffmpeg("-i", str(src_audio),
                               "-af", f"apad=pad_dur={dur}",
                               "-t", str(dur),
                               "-c:a", "aac", "-b:a", "128k", "-y", str(audio_path))
                    else:
                        ffmpeg("-f","lavfi","-i","anullsrc=r=44100:cl=mono",
                               "-t",str(dur),"-c:a","aac","-b:a","128k","-y",str(audio_path))


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

                    # ── Ưu tiên 2: ảnh stock đã chọn ──
                    elif image_url:
                        try:
                            download_url(image_url, str(vid_path))
                            has_vid = vid_path.stat().st_size > 5000
                            log(f"  🖼️ Tải ảnh stock: {vid_path.stat().st_size//1024}KB")
                        except Exception as e:
                            log(f"  ⚠️ Tải ảnh thất bại: {str(e)[:60]}")

                    # ── Ưu tiên 3: video upload thủ công ──
                    elif custom_vid and Path(custom_vid).exists():
                        shutil.copy(custom_vid, vid_path)
                        has_vid = vid_path.stat().st_size > 10000
                        log(f"  📥 Dùng video tải lên tùy chỉnh: {Path(custom_vid).name}")

                    # ── Ưu tiên 4: video stock ──
                    else:
                        if not video_url:
                            log(f"  🔍 Không có URL, tìm Stock Video [{vid_orientation}]: {s.get('keyword','')}")
                            video_url = fetch_stock_video(clean_keyword(s.get("keyword", "")), orientation=vid_orientation, used_urls=used_urls_render) or ""
                            if video_url:
                                used_urls_render.add(video_url)
                                log(f"  ✅ Stock Video trả về URL")
                            else:
                                log(f"  ⚠️ Stock Video không tìm thấy video (kiểm tra API key trong Settings)")

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
                                new_url = fetch_stock_video(clean_keyword(s.get("keyword", "")), orientation=vid_orientation, used_urls=used_urls_render) or ""
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

                    scale_crop = f"fps=30,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"

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
                            # Thêm intro effect vào scale_crop (auto random nếu chưa chọn)
                            intro_vf = make_video_intro_filter(W, H, dur, effect=scene_intro_effect)
                            if intro_vf:
                                scale_crop = f"fps=30,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},{intro_vf}"
                                log(f"  ✨ Intro effect: {scene_intro_effect or 'auto random'}")

                        if audio_path.exists():
                            ffmpeg_cmd = (
                                vid_input_args +
                                ["-i", str(audio_path),
                                 "-vf", scale_crop,
                                 "-t", str(dur),
                                 "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                                 "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                                 "-map", "0:v", "-map", "1:a",
                                 "-shortest", "-y", str(base_out)]
                            )
                        else:
                            ffmpeg_cmd = (
                                vid_input_args +
                                ["-vf", scale_crop,
                                 "-t", str(dur),
                                 "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                                 "-an", "-y", str(base_out)]
                            )
                    else:
                        # Nền đen + audio
                        color_src = f"color=c=1a1d27:s={W}x{H}:r=30"
                        if audio_path.exists():
                            ffmpeg_cmd = [
                                "-f", "lavfi", "-i", color_src,
                                "-i", str(audio_path),
                                "-t", str(dur),
                                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                                "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                                "-map", "0:v", "-map", "1:a",
                                "-shortest", "-y", str(base_out)
                            ]
                        else:
                            ffmpeg_cmd = [
                                "-f", "lavfi", "-i", color_src,
                                "-t", str(dur),
                                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                                "-an", "-y", str(base_out)
                            ]

                    ffmpeg(*ffmpeg_cmd)

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
                            log(f"  ⚠️ Lỗi gắn phụ đề: {e} → dùng bản không phụ đề.")
                            shutil.copy(base_out, out)
                    else:
                        if enable_transition:
                            v_fade = f"fade=t=in:st=0:d=0.15,fade=t=out:st={dur-0.15}:d=0.15"
                            cmd_args = ["-i", str(base_out), "-vf", v_fade, "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-c:a", "copy", "-y", str(out)]
                            ffmpeg(*cmd_args)
                        else:
                            shutil.copy(base_out, out)

                    # ── Sound Effect: auto-random nếu chưa chọn ──
                    sfx_name = s.get("soundEffect")
                    if sfx_name is None:
                        # Tự động chọn: 60% không có (viêm mắt), 40% có hiệu ứng nhẹ
                        sfx_name = random.choice(["none", "none", "none", "whoosh", "chime", "click", "none", "whoosh"])
                    if sfx_name and sfx_name != "none" and out.exists():
                        sfx_out = s_dir / "scene_sfx.mp4"
                        ok = apply_sound_effect_to_scene(out, sfx_name, sfx_out)
                        if ok:
                            shutil.move(str(sfx_out), str(out))
                            log(f"  🔊 Sound effect: {sfx_name}")

                    scene_mp4s.append(out)

                # Concat với re-encode để normalize PTS — tránh freeze/gap giữa các cảnh
                # (stream copy "-c copy" gây PTS discontinuity khi video sources có timebase khác nhau)
                concat_txt = work / "concat.txt"
                concat_txt.write_text("\n".join(f"file '{p}'" for p in scene_mp4s))
                raw_final = work / "final.mp4"
                ffmpeg(
                    "-f", "concat", "-safe", "0", "-i", str(concat_txt),
                    "-vf", f"fps=30,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
                    "-vsync", "cfr",          # Constant Frame Rate — loại PTS gap
                    "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                    "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                    "-movflags", "+faststart",
                    "-y", str(raw_final)
                )

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
                            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
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
                
                # Active page or scene select
                if "selectbox_scene_active" not in st.session_state:
                    st.session_state.selectbox_scene_active = proj.get("active_scene_idx", 0)
                if "selectbox_page_active" not in st.session_state:
                    st.session_state.selectbox_page_active = proj.get("active_page", 0)
                if "view_mode" not in st.session_state:
                    st.session_state.view_mode = proj.get("view_mode", "Tập trung (Mượt nhất)")

                def go_prev_scene(curr):
                    st.session_state.selectbox_scene_active = curr - 1
                    proj["active_scene_idx"] = curr - 1
                    save_proj(proj)

                def go_next_scene(curr):
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
                    active_idx = st.selectbox(
                        "🎯 Chọn cảnh đang chỉnh sửa:",
                        options=range(total_scenes),
                        format_func=lambda x: scene_options[x],
                        index=min(st.session_state.selectbox_scene_active, total_scenes - 1),
                        key="selectbox_scene_active"
                    )
                    if active_idx != proj.get("active_scene_idx"):
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
                    scene_data = s.get("scenes", [])
                    note = ""
                    if idx < len(scene_data) and isinstance(scene_data[idx], dict):
                        note = scene_data[idx].get("retention_note", "")
                    
                    label_emoji = "✅" if scene.get("completed") else ("🪝" if idx == 0 else ("🎯" if idx == total_scenes - 1 else "▶️"))
                    is_expanded = True if view_mode == "Tập trung (Mượt nhất)" else (idx == scenes_to_render[0][0])
                    
                    with st.expander(f"{label_emoji} Cảnh {idx+1}: {scene.get('text', '')[:40]}... ⏱️{scene.get('duration',5)}s", expanded=is_expanded):
                        if note:
                            st.caption(f"💡 *Mục tiêu cảnh: {note}*")
                            
                        col_left, col_right = st.columns([2, 1])
                        with col_left:
                            new_text = st.text_area("Nội dung lời đọc (Voice):", value=scene.get('text', ''), key=f"text_{idx}", height=120)

                            kw_col1, kw_col2 = st.columns([3, 1])
                            with kw_col1:
                                new_kw = st.text_input("Từ khóa AI tìm video (Stock):", value=scene.get('keyword', ''), key=f"kw_{idx}",
                                    help="Keyword tiếng Anh mô tả hình ảnh cụ thể. VD: 'elderly man park bench', 'city traffic night'")
                            with kw_col2:
                                 if st.button("🤖 AI gợi ý", key=f"ai_kw_{idx}", help="AI phân tích nội dung cảnh và đề xuất keyword tốt hơn"):
                                    scene_text = scene.get("text", "")
                                    if scene_text:
                                        with st.spinner("AI đang gợi ý keyword..."):
                                            kw_prompt = (
                                                f"Scene narration: \"{scene_text[:300]}\"\n\n"
                                                f"Generate 1 stock video search keyword (2-5 words, English only).\n"
                                                f"The keyword = what a CAMERA physically sees. NOT the abstract concept.\n\n"
                                                f"=== ANTI-MISMATCH RULES ===\n"
                                                f"❌ WRONG (do NOT do this):\n"
                                                f"  - 'research policy' → 'scientist lab' (shows chemistry, not policy)\n"
                                                f"  - 'cost management' → 'VR headset technology' (no connection)\n"
                                                f"  - 'government support' → 'palace tourism' (landmark, not civic)\n"
                                                f"  - 'regional difference' → 'rural mountain village' (not urban zone)\n"
                                                f"✅ CORRECT (show the human/everyday version):\n"
                                                f"  - 'research policy' → 'person reading article laptop'\n"
                                                f"  - 'cost management' → 'person counting money stress'\n"
                                                f"  - 'government support' → 'city hall government building'\n"
                                                f"  - 'regional housing' → 'apartment tower skyline'\n\n"
                                                f"=== CATEGORY GUIDE ===\n"
                                                f"• Housing/Rent → apartment interior, moving boxes, rent sign\n"
                                                f"• Finance/Budget → calculator desk, piggy bank, cash bills, counting money\n"
                                                f"• Policy/Gov → government building, official document signing, city hall\n"
                                                f"• Research/Learn → person reading laptop, financial charts screen\n"
                                                f"• Stress/Emotion → young adult worried, tired person alone\n"
                                                f"• City/Urban → apartment skyline, subway commute, street pedestrians\n"
                                                f"• Unsure → 'blurred city lights bokeh' or 'minimalist abstract background'\n\n"
                                                f"Reply with ONLY the keyword phrase. Nothing else."
                                            )
                                            try:
                                                ai_kw = call_ai(kw_prompt).strip().strip('"').strip("'").lower()
                                                import re as _re
                                                ai_kw = _re.sub(r'[^a-z0-9 ]', '', ai_kw).strip()
                                                if ai_kw:
                                                    proj["scenes"][idx]["keyword"] = ai_kw
                                                    save_proj(proj)
                                                    st.success(f"✅ Keyword mới: **{ai_kw}**")
                                                    st.rerun()
                                            except Exception as kw_e:
                                                st.error(f"❌ {kw_e}")
                                    else:
                                        st.warning("Cần có nội dung lời đọc trước.")

                            # ── Tab chọn loại nền: tự động đặt tab đúng lên trước ──
                            # Nếu cảnh đang dùng ảnh → 🖼️ lên trước; dùng video → 🎬 lên trước
                            _scene_has_img = bool(
                                proj["scenes"][idx].get("customImg") or
                                proj["scenes"][idx].get("imageUrl")
                            )
                            if _scene_has_img:
                                _tab_labels = ["🖼️ Ảnh (Hiệu ứng Động)", "🎬 Video Stock"]
                                tab_img, tab_vid = st.tabs(_tab_labels)
                            else:
                                _tab_labels = ["🎬 Video Stock", "🖼️ Ảnh (Hiệu ứng Động)"]
                                tab_vid, tab_img = st.tabs(_tab_labels)

                            with tab_vid:
                                up_vid = st.file_uploader("Upload Video (mp4) — ghi đè Stock:", type=["mp4","mov"], key=f"up_{idx}")
                                st.markdown("**🔍 Tìm & Đổi video khác:**")
                                if st.button("🔎 Tải danh sách video", key=f"search_btn_{idx}"):
                                    st.session_state[f"search_results_{idx}"] = search_stock_videos(
                                        new_kw,
                                        orientation="portrait" if "9:16" in aspect else "landscape"
                                    )

                                vid_results = st.session_state.get(f"search_results_{idx}", [])
                                if vid_results:
                                    vid_count  = sum(1 for r in vid_results if not r.get("is_photo"))
                                    photo_count = sum(1 for r in vid_results if r.get("is_photo"))
                                    fresh_count = sum(1 for r in vid_results if not r.get("already_used"))
                                    label_parts = []
                                    if vid_count:  label_parts.append(f"🎬 {vid_count} video")
                                    if photo_count: label_parts.append(f"📸 {photo_count} ảnh")
                                    st.caption(f"🆕 {fresh_count} mới · " + " · ".join(label_parts))
                                    cols = st.columns(3)
                                    for res_idx, res in enumerate(vid_results[:9]):
                                        with cols[res_idx % 3]:
                                            img_url = res.get("image", "")
                                            if img_url:
                                                st.image(img_url, use_container_width=True)
                                            used_badge = " ♻️" if res.get("already_used") else " 🆕"
                                            is_photo = res.get("is_photo", False)
                                            if is_photo:
                                                st.caption(f"📸 Ảnh (hiệu ứng động){used_badge}")
                                            else:
                                                st.caption(f"⏱️ {res['duration']}s{used_badge}")
                                            btn_label = "Chọn ảnh" if is_photo else "Chọn video"
                                            if st.button(btn_label, key=f"sel_res_{idx}_{res_idx}"):
                                                if is_photo:
                                                    # Ảnh → lưu vào imageUrl (render với hiệu ứng động)
                                                    proj["scenes"][idx]["imageUrl"] = res["url"]
                                                    proj["scenes"][idx]["customImg"] = None
                                                    proj["scenes"][idx]["videoUrl"] = None
                                                    proj["scenes"][idx]["customVid"] = None
                                                else:
                                                    # Video → lưu vào videoUrl
                                                    proj["scenes"][idx]["videoUrl"] = res["url"]
                                                    proj["scenes"][idx]["customVid"] = None
                                                    proj["scenes"][idx]["imageUrl"] = None
                                                    proj["scenes"][idx]["customImg"] = None
                                                    proj["scenes"][idx]["duration"] = res["duration"]
                                                if "used_videos" not in cfg:
                                                    cfg["used_videos"] = []
                                                if res["url"] not in cfg["used_videos"]:
                                                    cfg["used_videos"].append(res["url"])
                                                    if len(cfg["used_videos"]) > 1000:
                                                        cfg["used_videos"].pop(0)
                                                    save_cfg(cfg)
                                                edited = True
                                                st.rerun()

                            with tab_img:
                                up_img = st.file_uploader(
                                    "🖼️ Upload Ảnh của bạn (jpg/png) — ghi đè Stock:",
                                    type=["jpg","jpeg","png","webp"],
                                    key=f"up_img_{idx}"
                                )

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
                                    "🎨 Hiệu ứng chuyển động:",
                                    options=effect_keys,
                                    format_func=lambda x: effect_labels[x],
                                    index=curr_eff_idx,
                                    key=f"img_effect_{idx}"
                                )
                                if new_img_effect != scene.get("imageEffect"):
                                    proj["scenes"][idx]["imageEffect"] = new_img_effect
                                    edited = True

                                st.markdown("**🔍 Tìm Ảnh Stock (Pexels / Pixabay):**")
                                if st.button("🔎 Tải danh sách ảnh", key=f"search_img_btn_{idx}"):
                                    st.session_state[f"photo_results_{idx}"] = search_stock_photos(
                                        new_kw,
                                        orientation="portrait" if "9:16" in aspect else "landscape"
                                    )

                                photo_results = st.session_state.get(f"photo_results_{idx}", [])
                                if photo_results:
                                    fresh_p = sum(1 for r in photo_results if not r.get("already_used"))
                                    st.caption(f"🆕 {fresh_p} ảnh mới · ♻️ {len(photo_results)-fresh_p} đã dùng")
                                    pcols = st.columns(3)
                                    for pi, ph in enumerate(photo_results[:9]):
                                        with pcols[pi % 3]:
                                            if ph.get("image"):
                                                st.image(ph["image"], use_container_width=True)
                                            used_badge = " ♻️" if ph.get("already_used") else " 🆕"
                                            st.caption(f"📸 {ph.get('photographer','')}{used_badge}")
                                            if st.button("Chọn ảnh", key=f"sel_photo_{idx}_{pi}"):
                                                proj["scenes"][idx]["imageUrl"] = ph["url"]
                                                proj["scenes"][idx]["customImg"] = None
                                                proj["scenes"][idx]["videoUrl"] = None
                                                proj["scenes"][idx]["customVid"] = None
                                                if "used_videos" not in cfg:
                                                    cfg["used_videos"] = []
                                                if ph["url"] not in cfg["used_videos"]:
                                                    cfg["used_videos"].append(ph["url"])
                                                    if len(cfg["used_videos"]) > 1000:
                                                        cfg["used_videos"].pop(0)
                                                    save_cfg(cfg)
                                                edited = True
                                                st.rerun()
                            
                            # (up_img_file sẽ được gán ngay trong tab_img bên trên)
                            up_vid = up_vid  # giữ tham chiếu với file_uploader từ tab_vid
                                            
                        with col_right:
                            new_dur = st.number_input("⏱️ Thời lượng (giây):", min_value=1.0, max_value=300.0,
                                                       value=float(scene.get("duration") or 5.0),
                                                       step=0.1, key=f"rv_dur_{idx}")

                            st.markdown("**🎥 Nền hiện tại**")
                            has_any_video = False
                            # Hiển thị trạng thái: ảnh upload
                            if proj["scenes"][idx].get("customImg") and Path(proj["scenes"][idx]["customImg"]).exists():
                                st.success("🖼️ Dùng ảnh tải lên")
                                st.image(proj["scenes"][idx]["customImg"], use_container_width=True)
                                if st.button("Xóa ảnh tải lên", key=f"del_img_{idx}"):
                                    proj["scenes"][idx]["customImg"] = None
                                    edited = True
                                    st.rerun()
                                has_any_video = True
                            # Ảnh stock đã chọn
                            elif scene.get("imageUrl"):
                                st.success("🖼️ Ảnh stock (hiệu ứng động)")
                                st.image(scene["imageUrl"], use_container_width=True)
                                if st.button("Xóa ảnh stock", key=f"del_img_url_{idx}"):
                                    proj["scenes"][idx]["imageUrl"] = None
                                    edited = True
                                    st.rerun()
                                has_any_video = True
                            # Video upload
                            elif proj["scenes"][idx].get("customVid") and Path(proj["scenes"][idx]["customVid"]).exists():
                                st.success("🎥 Dùng video tải lên")
                                if st.button("Xóa video tải lên", key=f"del_{idx}"):
                                    proj["scenes"][idx]["customVid"] = None
                                    edited = True
                                    st.rerun()
                                has_any_video = True
                            elif scene.get("videoUrl"):
                                st.success("🔗 Đã liên kết Video Stock")
                                st.video(scene.get("videoUrl"))
                                if st.button("Xóa liên kết video", key=f"del_url_{idx}"):
                                    proj["scenes"][idx]["videoUrl"] = None
                                    edited = True
                                    st.rerun()
                                has_any_video = True
                            else:
                                st.warning("⚠️ Chưa có nền")
                                
                            new_mode = "start"
                            new_start = 0.0
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

                            completed = st.checkbox("✅ Đã duyệt xong cảnh này", value=bool(scene.get("completed", False)), key=f"comp_{idx}")
                            
                            # Next and save button
                            if view_mode == "Tập trung (Mượt nhất)":
                                st.button(
                                    "💾 Lưu & Sang cảnh tiếp ▶", 
                                    key=f"next_btn_{idx}", 
                                    use_container_width=True,
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
                                    
                        if (new_text != scene.get('text') or 
                            new_kw != scene.get('keyword') or 
                            new_dur != scene.get('duration') or 
                            new_mode != scene.get('videoTrimMode', 'start') or
                            (new_mode == 'custom' and new_start != scene.get('videoTrimStart', 0.0)) or
                            completed != scene.get('completed', False)):
                            
                            proj["scenes"][idx]["text"] = new_text
                            proj["scenes"][idx]["keyword"] = new_kw
                            proj["scenes"][idx]["duration"] = new_dur
                            proj["scenes"][idx]["videoTrimMode"] = new_mode
                            if new_mode == "custom":
                                proj["scenes"][idx]["videoTrimStart"] = new_start
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
                                st.rerun()

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
