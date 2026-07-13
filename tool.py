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

# ── Veo3 Video Generation ─────────────────────────────────────────────────────
try:
    import veo3_video as _veo3
    _VEO3_OK = True
except Exception as _ve:
    _VEO3_OK = False
    print(f"[tool] Veo3 module not loaded: {_ve}")


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
    default_cfg = {
        "gemini": [], "groq": [], "pexels": [], "pixabay": "", "openai": "",
        "used_videos": [],
        # Veo3 settings
        "veo3_enabled": False,      # Bật/tắt Veo3 generation
        "veo3_mode":    "fallback",  # "all" = mọi scene | "fallback" = chỉ khi stock không có
    }
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
    if mode == "veo3":
        return Path.home() / ".avc_project_veo3.json"
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
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}",
            json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.85, "maxOutputTokens": 8192, "responseMimeType": "application/json"}},
            timeout=60,
        )
        d = r.json()
        if r.ok:
            return d["candidates"][0]["content"]["parts"][0]["text"].replace("```json", "").replace("```", "").strip()
        else:
            print(f"[Gemini 2.0-flash fail, trying 1.5-flash] {d.get('error', {}).get('message')}")
    except Exception as e:
        print(f"[Gemini 2.0-flash exception, trying 1.5-flash] {e}")

    # Fallback
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}",
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

def generate_scene_image_ai(keyword: str, gemini_key: str, W: int, H: int, save_path: Path):
    """
    Sinh ảnh AI tĩnh (cho 1 cảnh) bằng Gemini Imagen 3 dựa trên từ khóa.
    Tạo ra ảnh chất lượng cao, cinematic để kết hợp với Ken Burns effect.
    """
    if not gemini_key:
        return None, "Không có Gemini API Key"
    
    ar = "16:9" if W > H else "9:16"
    prompt = (
        f"A cinematic, hyper-realistic photo of {keyword}. "
        "Dramatic lighting, visually stunning, high emotional impact. "
        "NO text, no borders, no logos, photorealistic."
    )
    
    try:
        import base64 as _b64
        import requests
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-008:predict?key={gemini_key}",
            json={"instances": [{"prompt": prompt}],
                  "parameters": {"sampleCount": 1, "aspectRatio": ar, "personGeneration": "allow_adult"}},
            timeout=60,
        )
        if not r.ok:
            return None, f"Lỗi API: {r.status_code}"
            
        data = r.json()
        b64 = data["predictions"][0]["bytesBase64Encoded"]
        img_bytes = _b64.b64decode(b64)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(img_bytes)
        return save_path, None
    except Exception as e:
        return None, str(e)


EDGE_VOICES = {
    "en-US": "en-US-GuyNeural",      # Male EN — clear narrator voice
    "vi-VN": "vi-VN-NamMinhNeural",  # Male VI
    "en-female": "en-US-JennyNeural",
    "vi-female": "vi-VN-HoaiMyNeural",
    "ko-KR": "ko-KR-InJoonNeural",   # Male KO
    "ko-female": "ko-KR-SunHiNeural",# Female KO
}

def tts_edge_with_timing(text, voice_key="en-US", audio_out=None, srt_out=None, rate="1.0"):
    """Edge TTS with word-level timing. Auto-retry khi bị rate-limit."""
    import edge_tts
    voice = EDGE_VOICES.get(voice_key, voice_key)
    audio_out = audio_out or (AUDIO_DIR / f"{uuid.uuid4().hex}.mp3")

    async def _run():
        # Edge TTS rate: convert float multiplier to signed percentage string
        # e.g. "1.5" -> "+50%", "0.8" -> "-20%", "2.0" -> "+100%"
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

    # Retry tối đa 3 lần với delay tăng dần để tránh rate limit Edge TTS
    for attempt in range(3):
        try:
            _sleep = 1.5 if attempt == 0 else (2.5 * attempt)
            time.sleep(_sleep)

            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=1) as _exe:
                words = _exe.submit(_run_in_thread).result(timeout=60)

            if Path(audio_out).exists() and Path(audio_out).stat().st_size > 1000:
                if not words:
                    dur = 5.0
                    try:
                        probe = subprocess.run(
                            [FFMPEG, "-i", str(audio_out), "-f", "null", "-"],
                            capture_output=True, text=True
                        )
                        for line in probe.stderr.split("\n"):
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
                        char_lens = [max(1, len(w)) for w in text_words]
                        total_chars = sum(char_lens)
                        t = 0.0
                        for w, cl in zip(text_words, char_lens):
                            word_dur = dur * cl / total_chars
                            words.append({"word": w, "start": t, "end": t + word_dur})
                            t += word_dur

                srt = make_srt(words, group=4)
                if srt_out and srt:
                    Path(srt_out).write_text(srt, encoding="utf-8")
                return str(audio_out), srt
        except Exception as e:
            print(f"[EdgeTTS] attempt {attempt+1}/3 fail: {e}")
    return None, None


def make_srt(words, group=4):
    """Group words into SRT subtitle blocks.
    Uses semantic chunking: prefer to break at punctuation before breaking mid-phrase.
    Respects Vietnamese compound words (e.g. 'công việc', 'thời gian') by grouping
    together words without sentence-boundary between them.
    """
    if not words: return ""
    import re as _re

    # ── Bước 1: Đánh dấu vị trí ngầt tự nhiên (sau dấu câu) ──
    PUNCT_PATTERN = _re.compile(r'[,\.!\?;:\-—–]$')

    def _has_punct(word_entry):
        """True if this word ends with punctuation — natural break point."""
        return bool(PUNCT_PATTERN.search(word_entry["word"].strip()))

    # ── Bước 2: Tạo chunks theo ngữ nghĩa ──
    chunks, cur_chunk = [], []
    for w in words:
        cur_chunk.append(w)
        # Nếu đạt đến giới hạn group và đây là điểm ngầt tự nhiên — cắt
        if len(cur_chunk) >= group and _has_punct(w):
            chunks.append(cur_chunk)
            cur_chunk = []
        # Nếu đạt 2x group mà chưa có dấu câu — buộc cắt tại đây
        elif len(cur_chunk) >= group * 2:
            chunks.append(cur_chunk)
            cur_chunk = []
    if cur_chunk:
        chunks.append(cur_chunk)

    # ── Bước 3: Xuất SRT ──
    lines, idx = [], 1
    for chunk in chunks:
        start = chunk[0]["start"]
        end   = chunk[-1]["end"]
        text  = " ".join(w["word"] for w in chunk).upper()
        def fmt(s):
            h, m = int(s//3600), int((s%3600)//60)
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
    # back = &H00000000 → fully transparent (no box background)
    # BorderStyle=1 in header → outline-only (no opaque box)
    "🟡 TikTok Yellow (Viral)":   {"highlight": "&H0000FFFF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 2},
    "🔥 Fire Orange":              {"highlight": "&H000055FF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 2},
    "💚 Neon Green":               {"highlight": "&H0000FF66", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 2},
    "💙 Electric Blue":            {"highlight": "&H00FF8800", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 2},
    "🩷 Hot Pink":                 {"highlight": "&H006633FF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 2},
    "⚪ Classic White (Không màu)": {"highlight": "&H00FFFFFF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 1},
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
    # Shorts (9:16, W=1080): push subtitles HIGH enough to clear YouTube UI buttons
    # (Like/Share/Comment bar + channel name occupies bottom ~250px of safe area)
    # Landscape: keep at 120 — no UI overlay risk
    margv = 320 if W == 1080 else 120

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
        # BorderStyle=1 → outline-only (KHÔNG có hộp nền đen)
        # BorderStyle=3 → opaque box (nền đen — đã bỏ)
        f"{bold},0,0,0,100,100,0,0,1,2,{shadow},2,30,30,{margv},1\n\n"
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
            # \h = single hard-space — đủ cách từ nhưng không quá rộng
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
        if _CAPCUT_FAIL_COUNT >= 4:
            _CAPCUT_SKIP = True
            print(f"[TTS] CapCut failed {_CAPCUT_FAIL_COUNT}x → CIRCUIT BREAKER ON: dùng Edge TTS cho tất cả cảnh còn lại")
        else:
            print(f"[TTS] CapCut failed ({_CAPCUT_FAIL_COUNT}/4) → fallback Edge TTS lần này, thử lại CapCut cảnh sau")


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

def srt_from_audio(audio_path, text, srt_path, tts_rate="1.0"):
    """Generate SRT from audio. Tries Edge TTS word-boundary timing (scaled to real duration),
    falls back to proportional character timing if no boundaries available (e.g. Vietnamese).
    """
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

    # ── Phân bổ timing theo số ký tự (proportional, KHÔNG gọi asyncio/Edge TTS) ──
    # QUAN TRỌNG: srt_from_audio chạy đồng bộ — KHÔNG được tạo event loop mới
    # vì sẽ conflict với Streamlit asyncio loop và làm câm toàn bộ scene sau.
    char_lens = [max(1, len(w)) for w in text_words]
    total_chars = sum(char_lens)
    t, words = 0.0, []
    for w, cl in zip(text_words, char_lens):
        wd = dur * cl / total_chars
        words.append({"word": w, "start": t, "end": t + wd})
        t += wd
    print(f"[srt_from_audio] char-proportion: {len(words)} words, {dur:.2f}s total")


    srt = make_srt(words, group=1)
    if srt:
        Path(srt_path).write_text(srt, encoding="utf-8")
    return dur

def clean_keyword(kw, lang=""):
    """Sanitize AI-generated keyword: extract from URLs, auto-translate VN/KR → EN for stock search.
    lang: 'Vietnamese', 'Korean', 'English' — dùng để giữ region context khi dịch.
    """
    import re
    kw = kw or ""
    # If it looks like a Pexels URL, extract the path segment as keyword
    m = re.search(r'pexels\.com/(?:[^/]+/)*([^/?&\s]+)', kw)
    if m:
        kw = m.group(1).replace('-', ' ').replace('_', ' ')
    # Strip any remaining URL parts
    kw = re.sub(r'https?://\S+', '', kw)
    kw = kw.replace('/', ' ').replace('\\', ' ')
    # Keep only alphanumeric, spaces, hyphens (giữ unicode để detect ngôn ngữ)
    kw = re.sub(r'[^\w\s-]', '', kw).strip()
    kw = ' '.join(kw.split()[:5]) or "nature"

    # ── Auto-translate nếu là tiếng Việt hoặc tiếng Hàn ──────────────────────────
    # Pexels/Coverr chỉ hoạt động tốt với keyword tiếng Anh
    has_vi = any(c in kw for c in "àáảãạăắặẳẵặâấầẩẫậèéẹẻẽêềếểễệìíịỉĩòóọỏõôồốổỗộơờớởỡợùúụủũưừứửữựỳýỵỷỹđ")
    has_ko = any(0xAC00 <= ord(c) <= 0xD7A3 or 0x1100 <= ord(c) <= 0x11FF for c in kw)
    if has_vi or has_ko:
        kw = _translate_keyword_to_en(kw, lang=lang)
    return kw


# Cache dịch keyword để không gọi API lặp lại
_KW_TRANSLATE_CACHE: dict = {}

def _translate_keyword_to_en(kw: str, lang: str = "") -> str:
    """Dịch keyword VN/KR → EN ngắn gọn (2-4 từ) cho stock search.
    Ưu tiên Groq (nhanh), fallback Gemini. Cache kết quả để tránh gọi API trùng.
    Nếu truyền lang (Vietnamese/Korean), giữ context vùng địa lý trong kết quả dịch.
    """
    global _KW_TRANSLATE_CACHE
    cache_key = f"{kw}|{lang}"
    if cache_key in _KW_TRANSLATE_CACHE:
        return _KW_TRANSLATE_CACHE[cache_key]

    # Thêm region hint để AI dịch giữ ngữ cảnh địa phương
    region_hint = ""
    if lang == "Vietnamese":
        region_hint = " (keep 'Vietnamese'/'Vietnam' in result if describing people, streets, or lifestyle)"
    elif lang == "Korean":
        region_hint = " (keep 'Korean'/'Korea'/'Seoul' in result if describing people, streets, or lifestyle)"

    prompt = (
        f"Translate this stock video search keyword to concise English (2-4 words max){region_hint}. "
        f"Return ONLY the English keyword, nothing else. No explanation, no quotes.\n"
        f"Keyword: {kw}"
    )
    translated = None
    import re as _re2
    # Ưu tiên Groq (nhanh, miễn phí)
    for key in cfg.get("groq", []):
        try:
            result = call_groq_llm(key, prompt)
            if result and len(result) < 80:
                translated = _re2.sub(r'[^\w\s-]', '', result).strip()[:50]
                break
        except Exception:
            continue
    # Fallback Gemini
    if not translated:
        for key in cfg.get("gemini", []):
            try:
                result = call_gemini(key, prompt)
                if result and len(result) < 80:
                    translated = _re2.sub(r'[^\w\s-]', '', result).strip()[:50]
                    break
            except Exception:
                continue

    out = translated or kw  # fallback: giữ keyword gốc nếu dịch fail
    _KW_TRANSLATE_CACHE[cache_key] = out
    if translated:
        print(f"[KW] '{kw}' → '{out}' (lang={lang or 'auto'})")
    return out

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

# ── Topic context modifiers: inject vào keyword để tránh kết quả lạc đề ──
# Ví dụ: chủ đề career → keyword tự động thêm " office professional" để Pexels
# không trả về cảnh công nhân bốc vác hay cụ già đập gạch
TOPIC_CONTEXT_MODIFIERS = {
    # Career/Office
    "technology":  "modern office tech",
    "business":    "professional business office",
    "finance":     "financial investment modern",
    "health":      "wellness healthy lifestyle",
    "psychology":  "person thinking thoughtful",
    "motivation":  "success achievement person",
    "science":     "research laboratory",
    "history":     "documentary cinematic",
    "travel":      "travel destination scenic",
    "food":        "food cooking kitchen",
}
# Keyword cần được enriched để tránh kết quả không phù hợp
_ENRICH_BLACKLIST = {"worker", "labor", "construction", "factory", "industrial",
                     "manual", "bricklayer", "builder", "welder", "crane"}

def enrich_keyword_with_context(keyword: str, niche: str) -> str:
    """Thêm context modifier vào keyword dựa trên niche video.
    Loại bỏ các từ "lao động chân tay" khỏi keyword để tránh kết quả lạc đề.
    """
    kw_lower = keyword.lower()
    # Loại bỏ blacklisted words
    kw_words = [w for w in keyword.split() if w.lower() not in _ENRICH_BLACKLIST]
    clean_kw = " ".join(kw_words) or keyword
    # Thêm context modifier
    modifier = TOPIC_CONTEXT_MODIFIERS.get(niche.lower(), "")
    if modifier and modifier.split()[0] not in clean_kw.lower():
        return f"{clean_kw} {modifier}"
    return clean_kw


# ── Region-specific terms that signal human/street/lifestyle content ──────────
# Khi keyword có các từ này mà KHÔNG có region → inject region vào
_HUMAN_LIFESTYLE_TERMS = {
    "person", "people", "man", "woman", "couple", "family", "student",
    "worker", "adult", "young", "elderly", "crowd", "street", "market",
    "city", "urban", "district", "neighborhood", "food", "cafe", "restaurant",
    "commute", "subway", "bus", "traffic", "pedestrian", "lifestyle", "daily",
    "home", "apartment", "house", "office", "school",
}
# Từ đã có region → không inject thêm
_REGION_TERMS = {
    "vietnamese", "vietnam", "hanoi", "saigon", "ho chi minh", "hoi an",
    "korean", "korea", "seoul", "busan", "incheon",
    "japanese", "japan", "tokyo", "osaka",
    "chinese", "china", "beijing", "shanghai",
    "thai", "thailand", "bangkok",
    "american", "european", "western", "british", "french",
}
# Keyword đặc thù văn hóa không nên thêm region
_UNIVERSAL_CONTENT = {
    "nature", "ocean", "mountain", "forest", "sky", "sunset", "space",
    "abstract", "bokeh", "background", "chart", "data", "graph",
    "technology", "science", "lab", "research",
}


def inject_region_into_keyword(keyword: str, lang: str) -> str:
    """Tự động inject region vào keyword khi làm video Việt/Hàn mà keyword
    mô tả người/đường phố/lifestyle nhưng chưa có region.

    Ví dụ:
      lang=Vietnamese + 'young couple apartment' → 'Vietnamese young couple apartment'
      lang=Korean    + 'street food vendor'      → 'Korean street food vendor'
      lang=Vietnamese + 'ocean sunset'           → 'ocean sunset'  (universal, không thêm)
    """
    if lang not in ("Vietnamese", "Korean"):
        return keyword

    kw_lower = keyword.lower()

    # Nếu đã có region term → không thêm nữa
    if any(rt in kw_lower for rt in _REGION_TERMS):
        return keyword

    # Nếu là nội dung universal → không thêm region
    if any(ut in kw_lower for ut in _UNIVERSAL_CONTENT):
        return keyword

    # Nếu keyword có từ mô tả người/lifestyle → inject region
    kw_words = set(kw_lower.split())
    if kw_words & _HUMAN_LIFESTYLE_TERMS:
        region_prefix = "Vietnamese" if lang == "Vietnamese" else "Korean"
        result = f"{region_prefix} {keyword}"
        print(f"[KW-Region] '{keyword}' → '{result}' (lang={lang})")
        return result

    return keyword


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
        # Context-aware fallback: derive a safer keyword from the original rather than
        # falling back to 'nature/landscape' which can return flags, dry leaves, yoga books, etc.
        if not res:
            # Strip the last word to broaden — e.g. 'Korean real estate policy 2023' → 'Korean real estate'
            kw_parts = keyword.strip().split()
            _topic_fallbacks = []
            if len(kw_parts) > 2:
                _topic_fallbacks.append(" ".join(kw_parts[:3]))   # first 3 words
            if len(kw_parts) > 1:
                _topic_fallbacks.append(" ".join(kw_parts[:2]))   # first 2 words
            # Generic safe fallbacks that won't surface foreign flags or unrelated content
            _topic_fallbacks += ["apartment building city", "urban cityscape skyline", "office desk work",
                                  "person walking city street", "blurred city lights bokeh"]
            for _fb_kw in _topic_fallbacks:
                res = _search(_fb_kw, orientation, check_global=False)
                if res: break
                if orientation != "":
                    res = _search(_fb_kw, "", check_global=False)
                    if res: break

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


def optimize_query_for_region(keyword, region):
    if not keyword:
        return keyword
    if region == "Châu Á / Việt Nam":
        kw_lower = keyword.lower()
        # Nếu đã có các từ chỉ vùng miền Châu Á thì bỏ qua
        if any(w in kw_lower for w in ["asian", "vietnam", "korean", "japan", "china", "chinese", "vietnamese"]):
            return keyword
        # Các danh từ chỉ người/địa điểm/sinh hoạt cần địa phương hóa
        human_words = ["person", "man", "woman", "people", "couple", "family", "child", "worker", "student", "business", "office", "street", "city", "house", "home", "apartment", "classroom", "school", "restaurant", "food", "dining", "cooking"]
        if any(w in kw_lower for w in human_words):
            return f"asian {keyword}"
        return keyword
    elif region == "Phương Tây (Western)":
        kw_lower = keyword.lower()
        if any(w in kw_lower for w in ["western", "caucasian", "american", "european"]):
            return keyword
        human_words = ["person", "man", "woman", "people", "couple", "family", "child", "worker", "student", "business"]
        if any(w in kw_lower for w in human_words):
            return f"western {keyword}"
    return keyword

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

def fetch_video_with_veo3(keyword: str, orientation: str = "landscape",
                           used_urls=None, scene_text: str = "",
                           log_cb=None, force_veo3=False) -> str:
    """
    Smart video fetch: Veo3 AI hoặc stock footage tùy theo cấu hình.

    Returns:
        - str bắt đầu bằng "/" hoặc đường dẫn local → file Veo3 cache
        - str bắt đầu bằng "http" → URL stock footage
        - "" nếu thất bại hoàn toàn
    """
    veo3_on   = (cfg.get("veo3_enabled", False) or force_veo3) and _VEO3_OK
    veo3_mode = "all" if force_veo3 else cfg.get("veo3_mode", "fallback")
    gem_keys  = cfg.get("gemini", [])

    def _veo3_generate():
        """Rotate qua tất cả Gemini keys — key nào thành công thì dùng."""
        if not gem_keys:
            if callable(log_cb): log_cb("❌ Veo3: chưa có Gemini key trong Settings")
            return None
        for ki, api_key in enumerate(gem_keys):
            if callable(log_cb): log_cb(f"  🔑 Veo3 key {ki+1}/{len(gem_keys)} ({api_key[:8]}...)")
            result = _veo3.generate_video_veo3_best(
                keyword         = keyword,
                gemini_api_key  = api_key,
                orientation     = orientation,
                scene_text      = scene_text,
                timeout_seconds = 200,
                resolution      = cfg.get("veo3_resolution", "720p"),
                log_cb          = log_cb,
            )
            if result:
                if callable(log_cb): log_cb(f"  ✅ Veo3 OK với key {ki+1}")
                return result
            if callable(log_cb): log_cb(f"  ⚠️ Key {ki+1} thất bại → thử key tiếp")
        if callable(log_cb): log_cb("❌ Veo3: tất cả key đều thất bại (quota/permission?) → dùng stock footage")
        return None

    # ── Mode: ALL → Veo3 trước, fallback stock nếu Veo3 fail ──
    if veo3_on and veo3_mode == "all":
        if callable(log_cb): log_cb(f"🤖 Veo3 [ALL] generating: {keyword[:50]}...")
        veo_path = _veo3_generate()
        if veo_path:
            return veo_path
        if callable(log_cb): log_cb("⚠️ Veo3 tất cả key fail → fallback stock footage")

    # ── Stock footage (luôn chạy nếu mode=fallback hoặc Veo3 fail) ──
    stock_url = fetch_stock_video(keyword, orientation=orientation, used_urls=used_urls)

    # ── Mode: FALLBACK → Veo3 chỉ khi stock trống ──
    if not stock_url and veo3_on and veo3_mode == "fallback":
        if callable(log_cb): log_cb(f"🤖 Stock không có → Veo3 fallback: {keyword[:50]}...")
        veo_path = _veo3_generate()
        if veo_path:
            return veo_path

    return stock_url or ""


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


def search_pexels_photos_only(keyword, orientation="landscape"):
    results = []
    global_used = set(cfg.get("used_videos", []))
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
                            "is_photo": True,
                        })
        except Exception as e:
            print(f"[Pexels Photo Search Only] {e}")
    results.sort(key=lambda x: x["already_used"])
    return results


def search_pixabay_photos_only(keyword, orientation="landscape"):
    results = []
    global_used = set(cfg.get("used_videos", []))
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
                            "is_photo": True,
                        })
        except Exception as e:
            print(f"[Pixabay Photo Search Only] {e}")
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
    # Syntax đúng: aevalsrc=sin(2*PI*f*t) — không phải sine=frequency=...
    "whoosh":    "sin(2*PI*400*t)*exp(-t/0.1):s=44100:d=0.3,afade=t=in:ss=0:d=0.05,afade=t=out:st=0.25:d=0.05",
    "click":     "sin(2*PI*800*t)*exp(-t/0.01):s=44100:d=0.08,afade=t=out:st=0.02:d=0.06",
    "chime":     "sin(2*PI*880*t)*exp(-t/0.15):s=44100:d=0.5,afade=t=in:ss=0:d=0.05,afade=t=out:st=0.4:d=0.1",
    "deep_hit":  "sin(2*PI*60*t)*exp(-t/0.1):s=44100:d=0.4,afade=t=in:ss=0:d=0.05,afade=t=out:st=0.3:d=0.1",
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
            "[0:a]volume=1.0[a0];[1:a]volume=0.6[sfx];[a0][sfx]amix=inputs=2:duration=first:dropout_transition=0.1[aout]",
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

def make_image_effect_filter(W, H, dur, effect=None, cinematic=True):
    """
    Tạo FFmpeg filter chain cho ảnh tĩnh với hiệu ứng chuyển động.
    Trả về filter string để dùng trong -vf.
    cinematic=True sẽ thêm nhiễu hạt (film grain) và tăng contrast để lách bot YouTube.
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

tab_main, tab_veo, tab_settings = st.tabs(["🎬 Pipeline", "🤖 Veo3 Studio", "⚙️ Settings"])

# ════════════════════════════════════════════════════════════
# SETTINGS TAB
# ════════════════════════════════════════════════════════════
with tab_settings:
    st.header("⚙️ API Keys")
    changed = False

    st.subheader("✨ Gemini Keys")
    new_g = st.text_input("Thêm Gemini key", placeholder="AIza... hoặc AQ...", type="password", key="g_in")
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

    # ── VEO3 AI VIDEO GENERATION ─────────────────────────────────────────────
    st.divider()
    st.subheader("🤖 Veo3 AI Video Generation (Google)")
    st.caption(
        "Generate video AI cho từng scene bằng Google Veo3 thay vì stock footage.  \n"
        "Dùng chung Gemini API key ở trên — không cần key riêng.  \n"
        "⚠️ Mỗi video mất ~60–120s và tiêu tốn quota. Dùng chế độ **Fallback** nếu chưa chắc."
    )

    _veo3_enabled = st.toggle(
        "🔴 Bật Veo3 Video Generation",
        value=cfg.get("veo3_enabled", False),
        key="veo3_toggle",
        help="Khi bật: mỗi scene trong kịch bản sẽ được generate video bằng Veo3 AI"
    )
    if _veo3_enabled != cfg.get("veo3_enabled", False):
        cfg["veo3_enabled"] = _veo3_enabled
        changed = True

    if _veo3_enabled:
        _veo3_mode = st.radio(
            "🎯 Chế độ Veo3",
            options=["fallback", "all"],
            format_func=lambda x: {
                "fallback": "🔄 Fallback — Chỉ dùng Veo3 khi Pexels/Pixabay không có kết quả phù hợp",
                "all":      "✨ All Scenes — Mọi scene đều dùng Veo3 (chất lượng cao nhất, tốn quota)",
            }.get(x, x),
            index=0 if cfg.get("veo3_mode", "fallback") == "fallback" else 1,
            key="veo3_mode_radio",
            horizontal=True,
        )
        if _veo3_mode != cfg.get("veo3_mode", "fallback"):
            cfg["veo3_mode"] = _veo3_mode
            changed = True

        # Resolution
        _veo3_res = st.radio(
            "🖥️ Resolution",
            options=["720p", "1080p", "4k"],
            index=["720p", "1080p", "4k"].index(cfg.get("veo3_resolution", "720p")),
            key="veo3_res_radio",
            horizontal=True,
            help="720p = nhanh hơn, tốn ít quota | 1080p/4k = chất lượng cao hơn, chậm hơn",
        )
        if _veo3_res != cfg.get("veo3_resolution", "720p"):
            cfg["veo3_resolution"] = _veo3_res
            changed = True

        _gem_keys = cfg.get("gemini", [])
        if _gem_keys:
            st.success(f"✅ Sẵn sàng: {len(_gem_keys)} Gemini key(s) sẽ được thử lần lượt cho Veo3")
        else:
            st.error("❌ Chưa có Gemini key! Thêm Gemini key bên trên để dùng Veo3.")

        if _VEO3_OK:
            _cache_files = list(_veo3.VEO_CACHE_DIR.glob("*.mp4"))
            _cache_mb = sum(f.stat().st_size for f in _cache_files) / 1_000_000
            col_a, col_b = st.columns([3, 1])
            col_a.info(
                f"📁 Veo3 cache: `{len(_cache_files)}` video — `{_cache_mb:.1f}` MB  \n"
                f"   📂 `{_veo3.VEO_CACHE_DIR}`"
            )
            if col_b.button("🗑️ Xóa cache", type="secondary", key="veo3_clear"):
                for _cf in _cache_files:
                    _cf.unlink(missing_ok=True)
                st.success("✅ Đã xóa cache Veo3!")
                st.rerun()
        else:
            st.warning("⚠️ Module veo3_video chưa load — kiểm tra file veo3_video.py")

        st.markdown("**📋 Models theo thứ tự ưu tiên:**")
        st.code(
            "1. veo-3.1-fast-generate-preview  → Veo 3.1 Fast (Tốc độ cao)\n"
            "2. veo-3.1-generate-preview       → Veo 3.1 Standard (Chất lượng cao)\n"
            "3. veo-3.1-lite-generate-preview   → Veo 3.1 Lite (Nhẹ, ổn định)",
            language="text"
        )
        st.caption("💡 Tip: Veo3 mất 60–120s/video. Phải sử dụng API key trả phí (Paid Tier) có bật Billing mới chạy được Veo3.")

        if st.button("🔍 Kiểm tra Quyền & Quota Veo3 của các API key", key="check_veo3_keys"):
            st.session_state.veo3_check_results = []
            with st.spinner("Đang kiểm tra kết nối tới Google AI Studio..."):
                for ki, api_key in enumerate(_gem_keys):
                    res = _veo3.check_veo3_support(api_key)
                    st.session_state.veo3_check_results.append((ki+1, api_key[:8] + "...", res))
            st.rerun()

        # Hiển thị kết quả kiểm tra từ session state (nếu có)
        if "veo3_check_results" in st.session_state:
            st.markdown("### 📋 Kết quả kiểm tra:")
            for index_num, key_prefix, res in st.session_state.veo3_check_results:
                if res["ok"]:
                    if res["veo_supported"]:
                        st.success(f"🔑 Key {index_num} ({key_prefix}): Hoạt động tốt & có hỗ trợ Veo3!")
                    else:
                        st.warning(f"🔑 Key {index_num} ({key_prefix}): Kết nối được nhưng KHÔNG hỗ trợ Veo3 (Có thể là Key Free Tier hoặc tài khoản của bạn chưa kích hoạt billing/whitelist).")
                    with st.expander(f"Xem danh sách models được hỗ trợ của Key {index_num}"):
                        st.write(res["models"])
                else:
                    st.error(f"🔑 Key {index_num} ({key_prefix}) lỗi kết nối: {res['error']}")


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
            custom = st.text_area("Hoặc nhập mô tả chi tiết (tùy chỉnh)", placeholder="Ví dụ:\nChủ đề: 한국 집값\nNội dung chính:\n- ...\nTôn màu: ...", height=150)
        default_dur = 60 if new_mode in ("shorts", "veo3") else 600
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
                key="voice_capcut_sel",
                help="Giọng CapCut AI chất lượng cao — không cần Edge TTS hay Groq"
            )
            # Rate slider — Shorts nên dùng 1.3-1.6x để dồn nhiều nội dung
            # Lấy giá trị từ session_state nếu đã có, không thì dùng default theo mode
            _rate_key = "tts_rate_slider"
            # Ưu tiên: session_state → cfg (persist qua restart) → default theo mode
            _valid_rates = ["0.8", "0.9", "1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "2.0"]
            _default_rate = st.session_state.get(_rate_key) or cfg.get("tts_rate", "1.3" if new_mode == "shorts" else "1.0")
            if _default_rate not in _valid_rates:
                _default_rate = "1.3" if new_mode == "shorts" else "1.0"
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
            # Checkbox force Edge TTS — dùng khi CapCut bị stuck/timeout
            _force_edge = st.checkbox(
                "⚡ Bỏ CapCut → dùng Edge TTS thẳng (nhanh hơn, không bị stuck)",
                value=False,
                key="force_edge_tts",
                help="Bật khi CapCut TTS bị treo hoặc chậm. Edge TTS miễn phí, không cần poll."
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
            default_aspect = 1 if new_mode in ("shorts", "veo3") else 0
        aspect = st.radio("📐 Tỉ lệ", ["16:9 (YouTube)","9:16 (Shorts/TikTok)"], index=default_aspect, horizontal=True)
        if aspect != proj.get("aspect"):
            proj["aspect"] = aspect
            save_proj(proj)
        show_sub = st.checkbox("💬 Thêm phụ đề (sub từng chữ)", value=True)
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
            Path.cwd(),
            Path.home() / "Downloads",
            Path.home() / "Music",
            Path.home() / "Desktop",
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

        # Dimensions
        if "9:16" in aspect:
            W, H = 1080, 1920
        else:
            W, H = 1920, 1080

        # ── Action buttons cuối cấu hình ────────────────────────────────────
        st.divider()
        use_ai_images = st.checkbox("🎨 Dùng Ảnh tĩnh AI (100% Unique - Khuyên dùng)", value=True, help="Tự động tạo ảnh bằng AI (Gemini) thay vì dùng video stock, giúp video không bao giờ bị đánh gậy Reused Content của YouTube. Video xuất ra vẫn có hiệu ứng chuyển động.")
        
        gen_script = st.button("📝 Tạo Kịch Bản", type="primary", width="stretch") if not proj.get("script") else None
        run_all    = st.button("🚀 Tạo Video (Footage + TTS + Render)", type="primary", width="stretch") if proj.get("script") else None
        run_render = st.button("🎥 Chỉ Render Video", width="stretch") if proj.get("scenes") else None
        reset_btn  = st.button("🗑️ Xóa & làm lại", width="stretch") if proj.get("script") else None

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
                    _wps_map = {"Vietnamese": 3.8, "Korean": 2.2, "English": 2.2}
                    words_per_sec    = _wps_map.get(lang, 2.2) * rate_val
                    # Minimum words per scene varies by language (Vietnamese needs more to fill time)
                    _min_words_map   = {"Vietnamese": 35, "Korean": 18, "English": 18}
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
                            "SCENE 1 = SHOCK FIRST. Lead with the MOST ALARMING fact or number in the ENTIRE video. "
                            "Do NOT warm up, do NOT define terms, do NOT ask 'Do you know what X is?'. "
                            "Pattern: '[Shocking number/fact]! [One-line personal implication].' "
                            "Example: '집주인이 지금 당신의 수억 원을 위험한 투자에 쓰고 있습니다.' "
                            "Viewer MUST feel: 'Wait, WHAT?!' in the first 2 seconds."
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
                        "The viewer already knows the concept — hit them with the SHOCKING IMPLICATION immediately."
                        + _HOOK_VISUAL_INSTRUCTION
                    )

                    retention_rules = ""
                    if pattern_interrupt:
                        retention_rules += "\n- PATTERN INTERRUPT: Every 2-3 scenes insert a surprising twist or tonal shift."
                    if add_loop_teaser:
                        retention_rules += "\n- LOOP ENDING: The LAST scene must call back to the opening hook."
                    if cta_style != "none":
                        # Map CTA key → localized instruction matching the video language
                        # CRITICAL: must NOT inject Vietnamese text when lang=Korean/English
                        _cta_map = {
                            "follow": {
                                "Korean":     "팔로우해서 더 많은 정보를 받아보세요 (Follow for more)",
                                "Vietnamese": "Follow để biết thêm",
                                "English":    "Follow for more tips like this",
                            },
                            "comment": {
                                "Korean":     "댓글로 여러분의 의견을 남겨주세요 (Leave a comment)",
                                "Vietnamese": "Hãy để lại ý kiến của bạn dưới phần bình luận nhé",
                                "English":    "Drop your thoughts in the comments",
                            },
                            "share": {
                                "Korean":     "친구들과 공유해주세요 (Share with friends)",
                                "Vietnamese": "Chia sẻ cho bạn bè của bạn",
                                "English":    "Share this with someone who needs to hear it",
                            },
                        }
                        _cta_localized = _cta_map.get(cta_style, {}).get(lang, f"Follow for more {lang} content")
                        retention_rules += f'\n- CTA: You MUST append EXACTLY this phrase at the very end of the LAST scene narration: "{_cta_localized}". Do NOT change, translate, or rephrase it. Do NOT add it as a separate scene. Do NOT display it as on-screen text overlay.'
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
                        f"  === VEO 3 PROMPT ===\n"
                        f"  - veo3_prompt: A highly detailed, cinematic English prompt for Google Veo 3 / Sora video generation.\n"
                        f"  Describe lighting, camera angle, subject emotion, and background. (e.g. 'Cinematic close-up of a worried young man looking at bills, dramatic lighting, shallow depth of field, photorealistic, 4k')."
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
                                "- Rhetorical questions ONLY if answered in the SAME or NEXT scene."
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
                                f'"keyword":{kw_example},"veo3_prompt":"detailed cinematic English prompt for Veo 3","retention_note":"why viewer stays"}}]}}'
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
                                f'"keyword":{kw_example},"veo3_prompt":"detailed cinematic English prompt for Veo 3","retention_note":"why viewer stays"}}]}}'
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
                            q_correct_1 = "'2023년 전세 사기 피해액은 3조 원을 넘었습니다. 당신의 보증금도 안전하지 않습니다.'"
                            q_correct_2 = "'집값이 오를 때 정부는 세금을 올립니다. 그러나 실제로 집주인이 아닌 세입자가 그 비용을 냅니다.'"
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
                            f"5. Did you maintain the same Creator Voice Persona as the introduction?\n\n"
                            f"Return ONLY valid JSON (no markdown, no explanation, no trailing commas, escape all double quotes inside text fields, no line breaks inside string values):\n{format_str}"
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
                        scenes.append({
                            "id":        sc_data["id"],
                            "text":      sc_data["text"],
                            "keyword":   sc_data["keyword"],
                            "videoUrl":  vid_url,
                            "veo3Path":  veo3_path,    # ← local path nếu dùng Veo3
                            "imageUrl":  img_url,
                            "audioDone": False,
                            "targetDur": float(target_sec_per_scene),
                            "duration":  round(max(float(target_sec_per_scene), len(sc_data["text"].split()) / words_per_sec + 0.4), 1),
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
                    scenes = proj["scenes"]

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
                                img_path, err = generate_scene_image_ai(_kw, _current_gkey, W, H, img_save)
                                if img_path:
                                    scenes[i]["imageUrl"] = str(img_path)
                                    log(f"  ✅ Đã tạo ảnh AI cho cảnh {i+1}")
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
                    # Tránh lỗi session cũ khiến _CAPCUT_SKIP = True vĩnh viễn → im lặng
                    # Dùng globals() để truy cập đúng module scope (Streamlit chạy as __main__)
                    import sys as _sys
                    _main_mod = _sys.modules.get("__main__") or _sys.modules.get("tool")
                    if _main_mod:
                        _main_mod._CAPCUT_FAIL_COUNT = 0
                        _main_mod._CAPCUT_SKIP = False
                    else:
                        globals()["_CAPCUT_FAIL_COUNT"] = 0
                        globals()["_CAPCUT_SKIP"] = False
                    _tts_label = "CapCut TTS" if (_CAPCUT_OK and voice_cfg_key in _cc.CAPCUT_VOICES) else "Edge TTS"
                    log(f"🎤 TTS: [{_tts_label}] Giọng='{voice_cfg_key}' | Tốc độ={tts_rate}x")
                    log(f"   ℹ️ Hash sẽ thay đổi nếu giọng/tốc độ khác lần trước → auto regenerate")
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
                                # Probe duration thực tế sau copy — quan trọng để actual_dur chính xác
                                try:
                                    _p = subprocess.run(
                                        [FFMPEG, "-i", str(audio_path), "-f", "null", "-"],
                                        capture_output=True, text=True
                                    )
                                    for _ln in _p.stderr.split("\n"):
                                        if "Duration:" in _ln:
                                            _ts = _ln.split("Duration:")[1].split(",")[0].strip()
                                            _hh, _mm, _ss = _ts.split(":")
                                            actual_dur = int(_hh)*3600 + int(_mm)*60 + float(_ss)
                                            break
                                except Exception:
                                    pass
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
                                    str(srt_path) if show_sub else None,
                                    rate=tts_rate
                                )
                                if retry_result:
                                    shutil.copy(retry_result, audio_path)
                                    # Probe duration sau retry
                                    try:
                                        _p2 = subprocess.run(
                                            [FFMPEG, "-i", str(audio_path), "-f", "null", "-"],
                                            capture_output=True, text=True
                                        )
                                        for _ln2 in _p2.stderr.split("\n"):
                                            if "Duration:" in _ln2:
                                                _ts2 = _ln2.split("Duration:")[1].split(",")[0].strip()
                                                _hh2, _mm2, _ss2 = _ts2.split(":")
                                                actual_dur = int(_hh2)*3600 + int(_mm2)*60 + float(_ss2)
                                                break
                                    except Exception:
                                        pass
                                    log(f"  ✅ Retry Edge TTS cảnh {i+1} thành công ({actual_dur:.1f}s)")
                                else:
                                    log(f"  ❌ CẢNH {i+1}: CẢ CapCut + Edge TTS đều THẤT BẠI — cảnh này sẽ KHÔNG có tiếng!")
                                    log(f"     → Nguyên nhân có thể: rate limit CapCut, asyncio conflict, hoặc mất mạng")
                                    log(f"     → Thử: đợi vài phút rồi chạy lại / bỏ tick 'Giữ cache audio' để force regenerate")




                        # ── Update audio duration + path + srtFile cho scene ──
                        aud_dur = actual_dur if (actual_dur and actual_dur > 0) else max(3.0, len(s["text"].split()) / 3.5)
                        scenes[i]["audioDur"] = aud_dur
                        # Chỉ save audioFile nếu file thực sự tồn tại (tránh STEP 4 dùng silence)
                        if audio_path.exists() and audio_path.stat().st_size > 1000:
                            scenes[i]["audioFile"] = str(audio_path)
                        else:
                            log(f"  ❌ TTS cảnh {i+1} THẤT BẠI hoàn toàn — CapCut + Edge đều lỗi! Video sẽ không có giọng đọc.")
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
                        log(f"  ✅ Audio cảnh {i+1}: đọc {aud_dur:.1f}s | target {target_dur:.0f}s → scene {final_dur:.1f}s" + (" + sub" if scenes[i].get('srtFile') else ""))
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

                    # ── Tìm audio file: ưu tiên audioFile trong scene, fallback reconstruct từ hash ──
                    src_audio = None
                    if s.get("audioFile") and Path(s["audioFile"]).exists():
                        src_audio = Path(s["audioFile"])
                        log(f"  📦 Audio cảnh {i+1}: dùng audioFile đã lưu ({src_audio.name})")
                    else:
                        # Reconstruct hash path — dùng khi project cũ chưa lưu audioFile
                        import hashlib as _hl
                        _hash_str = s.get("text", "") + str(voice_cfg_key) + str(tts_rate)
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
                            if _text_hash_file.exists() and _text_hash_file.stat().st_size > 1000:
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
                                    rate=tts_rate
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
                                    log(f"  ❌ Cảnh {i+1}: TTS thất bại hoàn toàn — cảnh này sẽ im lặng!")
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

                    # ── AUDIO: Trim/pad đúng `dur` giây và ép chuẩn Stereo/44100Hz ──
                    audio_path = s_dir / "audio_trimmed.aac"
                    if src_audio and src_audio.exists():
                        ffmpeg("-i", str(src_audio),
                               "-af", f"apad=pad_dur={dur}",
                               "-t", str(dur),
                               "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "128k", "-y", str(audio_path))
                    else:
                        ffmpeg("-f","lavfi","-i","anullsrc=r=44100:cl=stereo",
                               "-t",str(dur),
                               "-c:a","aac", "-ar", "44100", "-ac", "2", "-b:a","128k","-y",str(audio_path))


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
                                 "-map", "0:v", "-map", "1:a",
                                 "-shortest", "-y", str(base_out)]
                            )
                        else:
                            # KHÔNG dùng -an vì sẽ phá concat audio stream!
                            # Luôn tạo silence track để concat nhất quán
                            ffmpeg_cmd = (
                                vid_input_args +
                                ["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
                                 "-vf", scale_crop,
                                 "-t", str(dur),
                                 "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                                 "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                                 "-map", "0:v", "-map", "1:a",
                                 "-shortest", "-y", str(base_out)]
                            )
                    else:
                        # Nền đen + audio (hoặc silence nếu TTS fail)
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
                            # Luôn tạo silence thay vì -an
                            ffmpeg_cmd = [
                                "-f", "lavfi", "-i", color_src,
                                "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
                                "-t", str(dur),
                                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                                "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                                "-map", "0:v", "-map", "1:a",
                                "-shortest", "-y", str(base_out)
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

                # Concat — normalize PTS và giữ audio stream nhất quán
                # Quan trọng: dùng -map 0:v -map 0:a để đảm bảo audio không bị drop
                concat_txt = work / "concat.txt"
                concat_txt.write_text("\n".join(f"file '{p}'" for p in scene_mp4s))
                raw_final = work / "final.mp4"
                ffmpeg(
                    "-f", "concat", "-safe", "0", "-i", str(concat_txt),
                    "-vf", f"fps=30,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
                    "-vsync", "cfr",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                    "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
                    "-map", "0:v", "-map", "0:a",   # ← explicit map — tránh mất audio
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
                title = proj.get("script", {}).get("title", "") or ""

                # ── Tạo safe filename hỗ trợ Unicode (tiếng Việt, Korean, v.v.) ──
                # Bước 1: Normalize NFD rồi encode ASCII (bỏ dấu tiếng Việt → ASCII tương đương)
                import unicodedata as _ucd
                _title_ascii = _ucd.normalize("NFD", title).encode("ascii", "ignore").decode("ascii")
                # Bước 2: Chỉ giữ alphanumeric + khoảng trắng + dấu gạch
                _title_clean = re.sub(r"[^\w\s\-]", "", _title_ascii).strip()
                # Bước 3: Replace khoảng trắng → gạch dưới, giới hạn 60 ký tự
                safe_name = re.sub(r"\s+", "_", _title_clean)[:60]
                # Bước 4: Fallback nếu title rỗng hoàn toàn (ký tự đặc biệt thuần túy)
                if not safe_name:
                    # Dùng timestamp + 4 ký tự đầu của title gốc (transliterate thô)
                    import time as _time_mod
                    _ts_sfx = str(int(_time_mod.time()))[-6:]
                    # Giữ lại ký tự chữ số ASCII trong title gốc nếu có
                    _digits_in_title = re.sub(r"[^0-9a-zA-Z]", "", title)[:10]
                    safe_name = f"ai_video_{_digits_in_title or _ts_sfx}"

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
            edited = False
            
            if total_scenes > 0:
                # Progress Bar
                completed_count = sum(1 for sc in scenes if sc.get("completed"))
                col_prog1, col_prog2 = st.columns([3, 1], vertical_alignment="center")
                with col_prog1:
                    st.progress(completed_count / total_scenes)
                with col_prog2:
                    st.markdown(f"🏆 **Đã duyệt: {completed_count}/{total_scenes}**")
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
                    scene_data = proj.get("scenes", [])
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

                            # ── Veo3 Prompt output: nổi bật để dễ copy gen tay ──
                            st.markdown("**🤖 Veo3 / Sora / Kling Prompt — Copy để gen video thủ công:**")
                            veo3_prompt = scene.get('veo3_prompt', '')
                            _veo_col1, _veo_col2 = st.columns([5, 1])
                            with _veo_col1:
                                new_veo3 = st.text_area(
                                    "veo3_prompt_label",
                                    value=veo3_prompt,
                                    key=f"veo3_{idx}",
                                    height=100,
                                    label_visibility="collapsed",
                                    placeholder="📋 Prompt chưa có — bấm '✨ AI Tạo Prompt' để sinh tự động, hoặc tự nhập tiếng Anh mô tả cảnh này (lighting, camera angle, subject, mood...)"
                                )
                                if new_veo3 != veo3_prompt:
                                    proj["scenes"][idx]["veo3_prompt"] = new_veo3
                                    edited = True
                            with _veo_col2:
                                if st.button("✨ AI Tạo\nPrompt", key=f"gen_veo_{idx}", use_container_width=True, help="AI tự viết prompt tiếng Anh cho Veo3/Sora dựa trên lời đọc"):
                                    with st.spinner("AI đang viết..."):
                                        try:
                                            _txt = scene.get("text", "")
                                            _prompt = f"Write a highly detailed, cinematic English prompt for an AI video generator (like Sora/Veo3) based on this narration: '{_txt}'. Describe lighting, camera angle, subject emotion, and background. Reply ONLY with the prompt string, no markdown."
                                            _res = call_ai(_prompt).strip().strip('"').strip("'")
                                            if _res:
                                                proj["scenes"][idx]["veo3_prompt"] = _res
                                                save_proj(proj)
                                                st.rerun()
                                        except Exception as e:
                                            st.error(f"Lỗi: {e}")
                            
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
                                                    st.rerun()
                                            except Exception as ex:
                                                st.error(f"Lỗi gợi ý: {ex}")
                            
                            # Tự động dịch và tối ưu hóa keyword
                            opt_lang = "Vietnamese" if "Vietnamese" in proj.get("lang", "Vietnamese") or new_region == "Châu Á / Việt Nam" else "English"
                            new_kw = _translate_keyword_to_en(user_kw, lang=opt_lang) if user_kw else ""
                            if new_kw != user_kw:
                                st.caption(f"🇬🇧 Bản dịch/Tối ưu tiếng Anh: `{new_kw}`")
                            else:
                                new_kw = user_kw

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
                                    if st.button("🔎 Tìm Pexels Video", key=f"search_pexels_btn_{idx}"):
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

                            with tab_pixabay_vid:
                                pix_key = cfg.get("pixabay", "")
                                if not pix_key:
                                    st.warning("⚠️ Chưa cấu hình API Key Pixabay. Hãy vào tab Settings để nhập key.")
                                else:
                                    st.markdown("**🔍 Tìm video trên Pixabay:**")
                                    opt_kw = optimize_query_for_region(new_kw, new_region)
                                    if opt_kw != new_kw:
                                        st.caption(f"💡 Từ khóa tối ưu vùng miền: `{opt_kw}`")
                                    if st.button("🔎 Tìm Pixabay Video", key=f"search_pix_btn_{idx}"):
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

                            with tab_coverr_vid:
                                st.markdown("**🔍 Tìm video trên Coverr (Free, không cần API key):**")
                                opt_kw = optimize_query_for_region(new_kw, new_region)
                                if opt_kw != new_kw:
                                    st.caption(f"💡 Từ khóa tối ưu vùng miền: `{opt_kw}`")
                                if st.button("🔎 Tìm Coverr Video", key=f"search_cov_btn_{idx}"):
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

                            with tab_pexels_photo:
                                pexels_key = (cfg.get("pexels") or [None])[0]
                                if not pexels_key:
                                    st.warning("⚠️ Chưa cấu hình API Key Pexels. Hãy vào tab Settings để nhập key.")
                                else:
                                    st.markdown("**🔍 Tìm ảnh trên Pexels (Hiệu ứng Động):**")
                                    opt_kw = optimize_query_for_region(new_kw, new_region)
                                    if opt_kw != new_kw:
                                        st.caption(f"💡 Từ khóa tối ưu vùng miền: `{opt_kw}`")
                                    if st.button("🔎 Tìm Pexels Photo", key=f"search_pex_img_btn_{idx}"):
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
                                                        st.rerun()

                            with tab_pixabay_photo:
                                pix_key = cfg.get("pixabay", "")
                                if not pix_key:
                                    st.warning("⚠️ Chưa cấu hình API Key Pixabay. Hãy vào tab Settings để nhập key.")
                                else:
                                    st.markdown("**🔍 Tìm ảnh trên Pixabay (Hiệu ứng Động):**")
                                    opt_kw = optimize_query_for_region(new_kw, new_region)
                                    if opt_kw != new_kw:
                                        st.caption(f"💡 Từ khóa tối ưu vùng miền: `{opt_kw}`")
                                    if st.button("🔎 Tìm Pixabay Photo", key=f"search_pix_img_btn_{idx}"):
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
                                                        st.rerun()

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
                                    st.rerun()
                                has_any_video = True
                            # Ảnh stock đã chọn
                            elif scene.get("imageUrl"):
                                st.success("🖼️ Ảnh stock (hiệu ứng động)")
                                st.image(scene["imageUrl"], width="stretch")
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
                width="stretch",
            )
            st.caption(f"Hoặc mở thẳng tại: `{final_path}`")

        elif proj.get("step",0) == 0 and not run_all:
            st.info("👈 Chọn cấu hình bên trái và bấm **Bắt Đầu Tự Động**\n\nSettings → thêm API keys trước")


# ════════════════════════════════════════════════════════════
# VEO3 AI STUDIO TAB
# ════════════════════════════════════════════════════════════
with tab_veo:
    st.header("🤖 Veo3 AI Video Studio")
    st.caption("Tạo video chất lượng cao hoàn toàn bằng Google Veo3 AI. Mọi cảnh video đều được vẽ bằng AI (không dùng stock footage).")

    # Đọc cấu hình dự án Veo3
    veo_proj_file = Path.home() / ".avc_project_veo3.json"
    if "veo_proj" not in st.session_state:
        if veo_proj_file.exists():
            try:
                st.session_state.veo_proj = json.loads(veo_proj_file.read_text())
            except:
                st.session_state.veo_proj = {"script": None, "scenes": [], "step": 0}
        else:
            st.session_state.veo_proj = {"script": None, "scenes": [], "step": 0}

    veo_proj = st.session_state.veo_proj

    def save_veo_proj(p):
        veo_proj_file.write_text(json.dumps(p, ensure_ascii=False, indent=2))
        st.session_state.veo_proj = p

    # Cột giao diện
    v_col1, v_col2 = st.columns([1, 1.6])

    with v_col1:
        st.subheader("⚙️ Cấu hình Veo3")
        veo_topic = st.text_input("🎯 Chủ đề Video", value=veo_proj.get("topic", "Khám phá bí ẩn vũ trụ"), key="veo_topic_in")
        veo_desc = st.text_area("📝 Mô tả ý tưởng (tùy chọn)", value=veo_proj.get("description", ""), placeholder="Ví dụ: Kể về lỗ đen, giọng đọc huyền bí, tone màu xanh tối...", height=100, key="veo_desc_in")
        
        col_res1, col_res2 = st.columns(2)
        veo_aspect_sel = col_res1.selectbox("📐 Tỉ lệ", ["9:16 (Shorts)", "16:9 (YouTube)"], index=0, key="veo_aspect_sel")
        veo_resolution_sel = col_res2.selectbox("🖥️ Độ phân giải", ["720p", "1080p"], index=0, key="veo_res_sel")
        
        veo_num_scenes = st.slider("🎬 Số lượng cảnh (scenes)", min_value=2, max_value=8, value=veo_proj.get("num_scenes", 4), key="veo_scenes_slider")
        veo_voice_lang = st.selectbox("🌍 Ngôn ngữ", ["Vietnamese", "English", "Korean"], index=0, key="veo_lang_sel")
        
        # Giọng đọc
        if _CAPCUT_OK:
            _v_flag = {"Vietnamese": "🇻🇳", "English": "🇺🇸", "Korean": "🇰🇷"}.get(veo_voice_lang, "🇺🇸")
            _v_code = {"Vietnamese": "vi", "English": "en", "Korean": "ko"}.get(veo_voice_lang, "en")
            _v_opts = [k for k in _cc.CAPCUT_VOICES if _v_flag in k]
            _v_def  = _cc.CAPCUT_VOICE_DEFAULTS.get(_v_code, _v_opts[0])
            _v_idx  = _v_opts.index(_v_def) if _v_def in _v_opts else 0
            veo_voice_opt = st.selectbox("🔊 Giọng đọc (CapCut)", _v_opts, index=_v_idx, key="veo_voice_opt")
        else:
            veo_voice_opt = st.selectbox("🔊 Giọng đọc (Edge TTS)", ["vi-VN (NamMinh)", "vi-VN (HoaiMy - Female)"], key="veo_voice_opt")

        # Tốc độ đọc cho Veo3 Studio
        _veo_valid_rates = ["0.8", "0.9", "1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "2.0"]
        _veo_default_rate = cfg.get("tts_rate", "1.3")
        if _veo_default_rate not in _veo_valid_rates:
            _veo_default_rate = "1.3"
        veo_tts_rate = st.select_slider(
            "⚡ Tốc độ đọc TTS",
            options=_veo_valid_rates,
            value=_veo_default_rate,
            key="veo_tts_rate_slider",
            help="Tốc độ đọc giọng cho video Veo3. 1.0 = bình thường, 1.3 = nhanh."
        )

        # Cập nhật thông tin vào project
        veo_proj["topic"] = veo_topic
        veo_proj["description"] = veo_desc
        veo_proj["num_scenes"] = veo_num_scenes
        veo_proj["aspect"] = veo_aspect_sel
        veo_proj["resolution"] = veo_resolution_sel
        veo_proj["lang"] = veo_voice_lang
        veo_proj["voice"] = veo_voice_opt
        save_veo_proj(veo_proj)

        st.divider()
        btn_col1, btn_col2 = st.columns(2)
        btn_generate = btn_col1.button("🚀 Bắt đầu Tạo Video", type="primary", use_container_width=True, key="veo_generate_btn")
        btn_reset = btn_col2.button("🗑️ Reset dự án", type="secondary", use_container_width=True, key="veo_reset_btn")

        if btn_reset:
            veo_proj = {"script": None, "scenes": [], "step": 0}
            save_veo_proj(veo_proj)
            st.success("Đã reset dự án Veo3!")
            st.rerun()

    # Log area & progress
    with v_col2:
        st.subheader("📺 Dự án của bạn")
        
        # Nếu đang chạy
        status_box = st.empty()
        log_box = st.empty()
        
        if btn_generate:
            # Bắt đầu chạy pipeline
            log_lines = []
            def vlog(msg):
                log_lines.append(msg)
                log_box.code("\n".join(log_lines), language="text")
                
            status_box.info("⏳ Đang chuẩn bị kịch bản...")
            vlog("🚀 Khởi chạy Veo3 AI Video Creation...")
            
            # --- BƯỚC 1: TẠO KỊCH BẢN ---
            vlog("📝 Đang tạo kịch bản ngắn bằng AI...")
            # Tạo prompt viết kịch bản
            veo_prompt = (
                f"Hãy viết một kịch bản video ngắn {veo_aspect_sel} về chủ đề: {veo_topic}.\n"
                f"Chi tiết ý tưởng: {veo_desc}\n"
                f"Ngôn ngữ: {veo_voice_lang}.\n"
                f"Kịch bản gồm đúng {veo_num_scenes} cảnh.\n"
                f"Trả về kết quả dưới dạng JSON có cấu trúc như sau (không thêm bất kỳ giải thích nào ngoài JSON):\n"
                f"{{\n"
                f"  \"title\": \"Tiêu đề video\",\n"
                f"  \"scenes\": [\n"
                f"    {{\n"
                f"      \"id\": 1,\n"
                f"      \"text\": \"Lời thoại của người thuyết minh cho cảnh này (tối đa 25 từ, ngắn gọn, cuốn hút)\",\n"
                f"      \"keyword\": \"Mô tả chi tiết bằng tiếng Anh dùng để vẽ video (Ví dụ: 'a high quality cinematic shot of a glowing black hole in deep space')\"\n"
                f"    }}\n"
                f"  ]\n"
                f"}}\n"
            )
            
            # Gọi API sinh kịch bản (ưu tiên Gemini)
            gemini_keys = cfg.get("gemini", [])
            script_json = None
            if gemini_keys:
                try:
                    res_raw = call_gemini(gemini_keys[0], veo_prompt)
                    import re
                    cleaned_raw = res_raw.strip()
                    if cleaned_raw.startswith("```"):
                        cleaned_raw = re.sub(r"^```[a-zA-Z]*\n", "", cleaned_raw)
                        cleaned_raw = re.sub(r"\n```$", "", cleaned_raw)
                    cleaned_raw = cleaned_raw.strip()
                    script_json = json.loads(cleaned_raw)
                except Exception as e:
                    vlog(f"⚠️ Thử Gemini viết kịch bản lỗi: {e}")
                    
            if not script_json:
                # Fallback Groq
                groq_keys = cfg.get("groq", [])
                if groq_keys:
                    try:
                        res_raw = call_groq_llm(groq_keys[0], veo_prompt)
                        import re
                        cleaned_raw = res_raw.strip()
                        if cleaned_raw.startswith("```"):
                            cleaned_raw = re.sub(r"^```[a-zA-Z]*\n", "", cleaned_raw)
                            cleaned_raw = re.sub(r"\n```$", "", cleaned_raw)
                        cleaned_raw = cleaned_raw.strip()
                        script_json = json.loads(cleaned_raw)
                    except Exception as e:
                        vlog(f"⚠️ Thử Groq viết kịch bản lỗi: {e}")
            
            if not script_json:
                status_box.error("❌ Không thể tạo kịch bản! Vui lòng kiểm tra lại API key trong tab Settings.")
                st.stop()
                
            vlog(f"✅ Đã tạo kịch bản: \"{script_json.get('title', 'Không tên')}\"")
            
            # Tạo các scenes
            scenes = []
            for sc in script_json.get("scenes", []):
                scenes.append({
                    "id": sc["id"],
                    "text": sc["text"],
                    "keyword": sc["keyword"],
                    "videoUrl": None,
                    "veo3Path": None,
                    "audioFile": None,
                    "duration": 8.0  # Mặc định Veo3 vẽ 8 giây
                })
                
            veo_proj["script"] = script_json
            veo_proj["scenes"] = scenes
            veo_proj["step"] = 1
            save_veo_proj(veo_proj)
            
            # --- BƯỚC 2: VẼ VEO3 AI VIDEO (KHÔNG FALLBACK STOCK) ---
            status_box.info("🎨 Đang dùng Veo3 vẽ các cảnh video (mỗi cảnh mất 1-2 phút)...")
            vlog("🎬 Bắt đầu sinh video AI bằng Google Veo3...")
            
            vid_orientation = "portrait" if "9:16" in veo_aspect_sel else "landscape"
            
            for i, s in enumerate(scenes):
                vlog(f"  [Cảnh {i+1}/{len(scenes)}] Đang vẽ: \"{s['keyword'][:60]}...\"")
                
                # Gọi thẳng hàm vẽ Veo3 (quay vòng key)
                veo_path = None
                for ki, api_key in enumerate(gemini_keys):
                    vlog(f"    🔑 Gọi API Key {ki+1}/{len(gemini_keys)}...")
                    try:
                        res_path = _veo3.generate_video_veo3_best(
                            keyword         = s["keyword"],
                            gemini_api_key  = api_key,
                            orientation     = vid_orientation,
                            scene_text      = s["text"],
                            timeout_seconds = 200,
                            resolution      = veo_resolution_sel,
                            log_cb          = lambda msg: vlog(f"      [Veo3 SDK] {msg}")
                        )
                        if res_path and Path(res_path).exists():
                            veo_path = res_path
                            vlog(f"    ✅ Thành công với Key {ki+1}!")
                            break
                    except Exception as ex:
                        vlog(f"    ⚠️ Lỗi Key {ki+1}: {ex}")
                        
                if not veo_path:
                    vlog(f"  ❌ Cảnh {i+1} VẼ THẤT BẠI hoàn toàn sau khi thử tất cả keys!")
                    vlog("  ⚠️ Tạo video đen thay thế...")
                    dummy_vid = Path.home() / f".avc_veo_cache/dummy_black_{i}.mp4"
                    dummy_vid.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        subprocess.run([
                            FFMPEG, "-f", "lavfi", "-i", f"color=c=black:s={'720x1280' if vid_orientation == 'portrait' else '1280x720'}:d=8",
                            "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-y", str(dummy_vid)
                        ], capture_output=True)
                        veo_path = str(dummy_vid)
                    except Exception as dummy_err:
                        vlog(f"    ⚠️ Tạo clip đen lỗi: {dummy_err}")
                
                scenes[i]["veo3Path"] = veo_path
                veo_proj["scenes"] = scenes
                save_veo_proj(veo_proj)
                
            # --- BƯỚC 3: TẠO THUYẾT MINH (TTS) ---
            status_box.info("🎤 Đang tạo giọng thuyết minh...")
            vlog("🎤 Bắt đầu chạy TTS...")
            
            _legacy_map = {
                "English (Jenny)": "en-female",
                "English (Guy)": "en-male",
                "Vietnamese (HoaiMy)": "vi-female",
                "Vietnamese (NamMinh)": "vi-VN",
                "Korean (SunHi)": "ko-female",
                "Korean (InJoon)": "ko-KR",
            }
            voice_cfg_key = _legacy_map.get(veo_voice_opt, veo_voice_opt)
            
            for i, s in enumerate(scenes):
                vlog(f"  🎤 Thuyết minh cảnh {i+1}...")
                import hashlib
                h = hashlib.md5((s["text"] + voice_cfg_key + veo_tts_rate).encode()).hexdigest()[:12]
                audio_path = AUDIO_DIR / f"veo_s{h}.mp3"
                srt_path   = AUDIO_DIR / f"veo_s{h}.srt"
                
                result = tts(s["text"], voice_cfg_key, rate=veo_tts_rate)
                if result:
                    shutil.copy(result, audio_path)
                    scenes[i]["audioFile"] = str(audio_path)
                    try:
                        _p = subprocess.run([FFMPEG, "-i", str(audio_path), "-f", "null", "-"], capture_output=True, text=True)
                        for _ln in _p.stderr.split("\n"):
                            if "Duration:" in _ln:
                                _ts = _ln.split("Duration:")[1].split(",")[0].strip()
                                _hh, _mm, _ss = _ts.split(":")
                                scenes[i]["duration"] = int(_hh)*3600 + int(_mm)*60 + float(_ss) + 0.3
                                break
                    except Exception:
                        pass
                else:
                    vlog(f"  ⚠️ Cảnh {i+1}: TTS lỗi, dùng âm thanh im lặng")
                    
            veo_proj["scenes"] = scenes
            veo_proj["step"] = 3
            save_veo_proj(veo_proj)
            
            # --- BƯỚC 4: RENDER GHÉP VIDEO ---
            status_box.info("🎞️ Đang render video cuối...")
            vlog("🎞️ Đang xử lý FFmpeg render...")
            
            work_dir = Path.home() / "Desktop" / "AI_Videos" / "Veo3_Work"
            work_dir.mkdir(parents=True, exist_ok=True)
            
            scene_mp4s = []
            W, H = (720, 1280) if vid_orientation == "portrait" else (1280, 720)
            
            for i, s in enumerate(scenes):
                vlog(f"  🎞️ Render cảnh {i+1}/{len(scenes)}...")
                s_dir = work_dir / f"s{i}"
                s_dir.mkdir(exist_ok=True)
                
                vid_in = s["veo3Path"]
                aud_in = s["audioFile"]
                dur = s["duration"]
                
                out_scene = s_dir / "scene_output.mp4"
                
                if aud_in and Path(aud_in).exists():
                    ffmpeg_cmd = [
                        FFMPEG, "-i", str(vid_in), "-i", str(aud_in),
                        "-filter_complex", f"[0:v]fps=30,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},loop=loop=-1:size=240:start=0[v]",
                        "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-c:a", "aac", "-ar", "44100", "-ac", "2",
                        "-t", str(dur), "-y", str(out_scene)
                    ]
                else:
                    ffmpeg_cmd = [
                        FFMPEG, "-i", str(vid_in),
                        "-filter_complex", f"[0:v]fps=30,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},loop=loop=-1:size=240:start=0[v]",
                        "-map", "[v]", "-c:v", "libx264", "-t", str(dur), "-y", str(out_scene)
                    ]
                subprocess.run(ffmpeg_cmd, capture_output=True)
                if out_scene.exists():
                    scene_mp4s.append(out_scene)
                    
            if scene_mp4s:
                concat_txt = work_dir / "concat.txt"
                concat_txt.write_text("\n".join(f"file '{p}'" for p in scene_mp4s))
                
                final_out = Path.home() / "Desktop" / "AI_Videos" / f"veo3_{uuid.uuid4().hex[:8]}.mp4"
                final_out.parent.mkdir(parents=True, exist_ok=True)
                
                subprocess.run([
                    FFMPEG, "-f", "concat", "-safe", "0", "-i", str(concat_txt),
                    "-c", "copy", "-y", str(final_out)
                ], capture_output=True)
                
                if final_out.exists():
                    veo_proj["finalPath"] = str(final_out)
                    veo_proj["step"] = 4
                    save_veo_proj(veo_proj)
                    vlog("🎉 ĐÃ HOÀN THÀNH VIDEO VEO3!")
                    status_box.success("🎉 Video đã render thành công!")
                    st.rerun()
                else:
                    status_box.error("❌ Lỗi ghép video final.")
            else:
                status_box.error("❌ Không có cảnh nào được render thành công.")

        # ── MANUAL PROMPT GEN: Nhập prompt thủ công để gen video Veo3 ──────────
        st.divider()
        st.subheader("✍️ Gen Video Thủ Công từ Prompt")
        st.caption("Nhập prompt tiếng Anh mô tả cảnh muốn Veo3 vẽ, không cần tạo kịch bản tự động.")

        _manual_prompt = st.text_area(
            "🎬 Prompt mô tả cảnh video (tiếng Anh, chi tiết nhất có thể):",
            placeholder="Ví dụ: A cinematic close-up of a young Vietnamese woman looking shocked, staring at her phone, warm afternoon light, shallow depth of field, 4K quality",
            height=100,
            key="veo3_manual_prompt_input"
        )
        _manual_col1, _manual_col2, _manual_col3 = st.columns([2, 1, 1])
        with _manual_col1:
            _manual_aspect = st.radio(
                "📐 Tỉ lệ",
                ["9:16 (Shorts)", "16:9 (YouTube)"],
                horizontal=True,
                key="veo3_manual_aspect"
            )
        with _manual_col2:
            _manual_res = st.selectbox(
                "🖥️ Độ phân giải",
                ["720p", "1080p"],
                key="veo3_manual_res"
            )
        with _manual_col3:
            _manual_btn = st.button(
                "🎬 Gen Video",
                type="primary",
                use_container_width=True,
                key="veo3_manual_gen_btn"
            )

        if _manual_btn:
            if not _manual_prompt.strip():
                st.error("❌ Vui lòng nhập prompt trước khi gen!")
            elif not cfg.get("gemini"):
                st.error("❌ Chưa có Gemini API key! Thêm key trong tab Settings.")
            else:
                _gemini_keys_manual = cfg.get("gemini", [])
                _manual_orientation = "portrait" if "9:16" in _manual_aspect else "landscape"
                with st.spinner(f"⏳ Đang gen video Veo3 (khoảng 60–120s)..."):
                    _manual_result = None
                    for _ki, _ak in enumerate(_gemini_keys_manual):
                        st.caption(f"🔑 Đang thử API Key {_ki+1}/{len(_gemini_keys_manual)}...")
                        try:
                            _manual_result = _veo3.generate_video_veo3_best(
                                keyword         = _manual_prompt.strip(),
                                gemini_api_key  = _ak,
                                orientation     = _manual_orientation,
                                scene_text      = _manual_prompt.strip(),
                                timeout_seconds = 240,
                                resolution      = _manual_res,
                                log_cb          = lambda msg: st.caption(f"SDK: {msg}")
                            )
                            if _manual_result and Path(_manual_result).exists():
                                st.success(f"✅ Gen thành công với Key {_ki+1}!")
                                break
                        except Exception as _ex:
                            st.warning(f"Key {_ki+1} lỗi: {_ex}")
                    if _manual_result and Path(_manual_result).exists():
                        st.video(_manual_result)
                        _manual_vid_bytes = Path(_manual_result).read_bytes()
                        st.download_button(
                            label="⬇️ Tải xuống video này",
                            data=_manual_vid_bytes,
                            file_name=Path(_manual_result).name,
                            mime="video/mp4",
                            use_container_width=True,
                            key="veo3_manual_dl_btn"
                        )
                    else:
                        st.error("❌ Gen video thất bại sau tất cả các API key! Kiểm tra quota và thử lại.")

        st.divider()
        # Hiển thị kịch bản và các video sinh ra
        if veo_proj.get("step", 0) >= 1:
            st.write(f"📝 **Tiêu đề:** {veo_proj['script'].get('title', '')}")
            
            for idx, s in enumerate(veo_proj["scenes"]):
                with st.expander(f"🎬 Cảnh {idx+1}: {s['keyword'][:50]}...", expanded=False):
                    st.write(f"**Lời thoại:** {s['text']}")
                    st.write(f"**Prompt vẽ (keyword):** `{s['keyword']}`")
                    
                    if s.get("veo3Path") and Path(s["veo3Path"]).exists():
                        st.video(s["veo3Path"])
                    else:
                        st.warning("Cảnh này chưa có video hoặc vẽ lỗi.")
                        
                    # Nút vẽ lại cảnh này
                    if st.button(f"🔄 Vẽ lại Cảnh {idx+1} bằng Veo3", key=f"btn_regen_veo_{idx}"):
                        st.info(f"Đang vẽ lại cảnh {idx+1}...")
                        gemini_keys = cfg.get("gemini", [])
                        veo_path = None
                        for ki, api_key in enumerate(gemini_keys):
                            try:
                                res_path = _veo3.generate_video_veo3_best(
                                    keyword         = s["keyword"],
                                    gemini_api_key  = api_key,
                                    orientation     = "portrait" if "9:16" in veo_proj.get("aspect","") else "landscape",
                                    scene_text      = s["text"],
                                    timeout_seconds = 200,
                                    resolution      = veo_proj.get("resolution","720p"),
                                    log_cb          = lambda msg: st.caption(f"SDK: {msg}")
                                )
                                if res_path and Path(res_path).exists():
                                    veo_path = res_path
                                    st.success("Vẽ lại thành công!")
                                    break
                            except Exception as ex:
                                st.error(f"Key {ki+1} lỗi: {ex}")
                        if veo_path:
                            veo_proj["scenes"][idx]["veo3Path"] = veo_path
                            save_veo_proj(veo_proj)
                            st.rerun()

            # Hiển thị video final
            if veo_proj.get("step", 0) == 4 and veo_proj.get("finalPath") and Path(veo_proj["finalPath"]).exists():
                st.subheader("🎉 Video Final")
                final_p = Path(veo_proj["finalPath"])
                video_bytes = final_p.read_bytes()
                st.video(video_bytes)
                st.download_button(
                    label="⬇️ Tải xuống Video Final",
                    data=video_bytes,
                    file_name=final_p.name,
                    mime="video/mp4",
                    use_container_width=True
                )
