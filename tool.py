"""
AI Video Creator — Python Streamlit App
Chạy: streamlit run tool.py
"""
import streamlit as st
from vietnamese_tts import normalize_vietnamese_tts
import asyncio, json, os, re, uuid, base64, subprocess, shutil, time, tempfile, random, math
from typing import Optional
from pathlib import Path
import requests

# ── CapCut TTS ────────────────────────────────────────────────────────────────
try:
    import sys as _sys
    if "capcut_tts" in _sys.modules:
        import importlib as _importlib
        _importlib.reload(_sys.modules["capcut_tts"])
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

# ── Standalone Creative Studio ────────────────────────────────────────────────
try:
    import creative_studio as _creative
    # Streamlit reruns tool.py in the same Python process. If creative_studio.py
    # changed while the app was open, a normal import can return the old module
    # object whose render function still accepts only three arguments.
    import importlib as _importlib
    import inspect as _inspect
    if "veo_engine" not in _inspect.signature(
        _creative.render_creative_studio
    ).parameters:
        _creative = _importlib.reload(_creative)
    _CREATIVE_OK = True
except Exception as _creative_error:
    _CREATIVE_OK = False
    print(f"[tool] Creative Studio not loaded: {_creative_error}")


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
        "veo3_provider": "stock",   # "stock" | "gemini_web" | "api" | "google_flow"
        # Google Flow UseAPI settings
        "useapi_token": "",
        "useapi_email": "",
        "useapi_model": "veo-3.1-fast",
    }
    if CFG_FILE.exists():
        try:
            data = json.loads(CFG_FILE.read_text())
            for k, v in default_cfg.items():
                if k not in data:
                    data[k] = v
            return data
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[config] Cannot read {CFG_FILE}: {exc}")
    return default_cfg

def _atomic_json_write(path: Path, data, *, ensure_ascii=True):
    """Write JSON without leaving a half-written project after a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=ensure_ascii, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)

def save_cfg(cfg):
    _atomic_json_write(CFG_FILE, cfg)
    # This file contains API keys; keep it private on POSIX systems.
    try:
        CFG_FILE.chmod(0o600)
    except OSError:
        pass

def reset_groq_cache():
    """Reset Groq model cache khi key thay đổi."""
    global _GROQ_LIVE_MODELS, _GROQ_CACHE_KEY_HASH, _GROQ_BLACKLIST
    try:
        _GROQ_LIVE_MODELS = []
        _GROQ_CACHE_KEY_HASH = ""
        _GROQ_BLACKLIST = set()
    except Exception:
        pass


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
        try:
            return json.loads(pf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[project] Cannot read {pf}: {exc}")
    return {"script": None, "scenes": [], "step": 0}

def save_proj(p):
    pf = get_proj_file()
    _atomic_json_write(pf, p, ensure_ascii=False)

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
            json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.65, "maxOutputTokens": 8192, "responseMimeType": "application/json"}},
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
        json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.65, "maxOutputTokens": 8192, "responseMimeType": "application/json"}},
        timeout=60,
    )
    d = r.json()
    if not r.ok: raise Exception(d.get("error", {}).get("message", f"Gemini {r.status_code}"))
    return d["candidates"][0]["content"]["parts"][0]["text"].replace("```json", "").replace("```", "").strip()

def call_groq_llm(key, prompt):
    global _GROQ_LIVE_MODELS, _GROQ_CACHE_KEY_HASH, _GROQ_BLACKLIST
    _key_hash = key[-8:] if key else ""
    if not _GROQ_LIVE_MODELS or _GROQ_CACHE_KEY_HASH != _key_hash:
        try:
            _r = requests.get("https://api.groq.com/openai/v1/models",
                               headers={"Authorization": f"Bearer {key}"}, timeout=5)
            if _r.ok:
                _SKIP = ["whisper","guard","vision","orpheus","allam","canopylabs","tts","embed","rerank"]
                _all = [m["id"] for m in _r.json().get("data",[])
                        if not any(p in m["id"].lower() for p in _SKIP)]
                _pri = ["llama-3.3-70b-versatile","llama-3.1-70b-versatile"]
                _large = [m for m in _all if any(x in m for x in ["70b","70B","compound","maverick"])]
                _small = [m for m in _all if m not in _large]
                _ord = [p for p in _pri if p in _all]+[m for m in _large if m not in _pri]+_small
                _GROQ_LIVE_MODELS = _ord
                _GROQ_CACHE_KEY_HASH = _key_hash
                _GROQ_BLACKLIST = set()
                print(f"[Groq] {len(_GROQ_LIVE_MODELS)} models: {_GROQ_LIVE_MODELS[:4]}")
        except Exception as _fe:
            print(f"[Groq] Fetch failed: {_fe}")
        if not _GROQ_LIVE_MODELS:
            _GROQ_LIVE_MODELS = ["llama-3.3-70b-versatile","llama-3.1-70b-versatile","llama-3.1-8b-instant"]
            _GROQ_CACHE_KEY_HASH = _key_hash

    prompt_chars = len(prompt)
    models = [m for m in _GROQ_LIVE_MODELS if m not in _GROQ_BLACKLIST]
    if not models:
        raise Exception("All Groq models unavailable after retries")

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
                        "temperature": 0.65,
                        "max_tokens": 4096,  # TPM safe
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
                _body = r.json() if r.content else {}
                _emsg = _body.get("error",{}).get("message",f"HTTP {r.status_code}")[:100]
                print(f"[Groq/{model}] {r.status_code} — {_emsg}")
                _GROQ_BLACKLIST.add(model)
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
                "temperature": 0.65,
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
    "ja-JP": "ja-JP-KeitaNeural",      # Male JA
    "ja-female": "ja-JP-NanamiNeural", # Female JA
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

def tts_groq_api(text, voice="troy", out_path=None):
    """Groq Orpheus English TTS fallback (PlayAI was shut down in 2025)."""
    key = (cfg.get("groq") or [None])[0]
    if not key: return None
    # Orpheus currently supports English/Arabic, not Vietnamese/Korean/Japanese.
    # The caller only invokes this fallback for an English voice.
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

def tts(text, voice_cfg="en-US", srt_out=None, rate="1.0",
        allow_edge_fallback=True):
    """Try CapCut TTS (chunked) → Edge TTS → Groq, return audio path.
    voice_cfg: either a CapCut display key (e.g. '🇻🇳 Cô Gái Hoạt Ngôn (BV074)')
               or a legacy Edge key (e.g. 'en-US', 'vi-VN').
    rate: speed string for CapCut TTS ('0.8'...'1.3').
    allow_edge_fallback: When False, a selected CapCut voice must succeed as-is.
                         This prevents silently replacing named voices (for
                         example "Bản Tin Nữ") with a generic Edge voice.
    CapCut giới hạn ~400 ký tự/request → tự động chunk + nối audio lại.
    """
    global _CAPCUT_FAIL_COUNT, _CAPCUT_SKIP
    if "🇻🇳" in voice_cfg or voice_cfg in ("vi-VN", "vi-female"):
        text = normalize_vietnamese_tts(text)
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
                _next_action = "fallback" if allow_edge_fallback else "giữ nguyên giọng, không fallback"
                print(f"[TTS] CapCut chunk {ci+1}/{len(chunks)} failed → {_next_action}")
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
                _CAPCUT_FAIL_COUNT = 0
                return str(final_audio)

        _CAPCUT_FAIL_COUNT += 1
        if allow_edge_fallback and _CAPCUT_FAIL_COUNT >= 4:
            _CAPCUT_SKIP = True
            print(f"[TTS] CapCut failed {_CAPCUT_FAIL_COUNT}x → CIRCUIT BREAKER ON: dùng Edge TTS cho tất cả cảnh còn lại")
        elif allow_edge_fallback:
            print(f"[TTS] CapCut failed ({_CAPCUT_FAIL_COUNT}/4) → fallback Edge TTS lần này, thử lại CapCut cảnh sau")
        else:
            print(f"[TTS] CapCut failed ({_CAPCUT_FAIL_COUNT}x) — chế độ giữ nguyên giọng đang bật")

        if not allow_edge_fallback:
            print(f"[TTS] Giữ nguyên giọng đã chọn '{voice_cfg}' — không tự đổi sang Edge TTS")
            return None

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


    # ── Groq Orpheus last resort (English only) ───────────────────────────────
    _looks_english = (
        voice_cfg in ("en-US", "en-female")
        or "🇺🇸" in voice_cfg
        or "english" in voice_cfg.lower()
        or " en " in f" {voice_cfg.lower()} "
    )
    return tts_groq_api(text, "troy") if _looks_english else None


def probe_audio_duration(audio_path) -> Optional[float]:
    """Return a real decodable audio duration, never a text-length estimate."""
    path = Path(audio_path) if audio_path else None
    if not path or not path.exists() or path.stat().st_size <= 1000 or not FFMPEG:
        return None
    try:
        probe = subprocess.run(
            [FFMPEG, "-v", "error", "-i", str(path), "-f", "null", "-"],
            capture_output=True, text=True,
        )
        # With -v error FFmpeg may omit Duration, so use ffprobe when available.
        ffprobe_bin = str(Path(FFMPEG).with_name("ffprobe"))
        if not Path(ffprobe_bin).exists():
            ffprobe_bin = shutil.which("ffprobe")
        if ffprobe_bin:
            measured = subprocess.run(
                [
                    ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", str(path),
                ],
                capture_output=True, text=True,
            )
            if measured.returncode == 0:
                duration = float(measured.stdout.strip())
                if duration > 0.05:
                    return duration
        for line in probe.stderr.splitlines():
            if "Duration:" in line:
                ts = line.split("Duration:", 1)[1].split(",", 1)[0].strip()
                hours, minutes, seconds = ts.split(":")
                duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                return duration if duration > 0.05 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def is_valid_audio(audio_path) -> bool:
    return probe_audio_duration(audio_path) is not None

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
_GROQ_LIVE_MODELS: list = []
_GROQ_CACHE_KEY_HASH: str = ""
_GROQ_BLACKLIST: set = set()

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

def build_visual_prompts_batch(scenes: list, lang: str, log_cb=None) -> list:
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
            parsed = parse_json_robust(call_ai(prompt))
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
    elif lang == "Japanese":
        region_hint = " (keep 'Japanese'/'Japan'/'Tokyo' in result if describing people, streets, or lifestyle)"

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
                           log_cb=None, force_veo3=False,
                           veo3_prompt: str = "") -> str:
    """
    Smart video fetch: Veo3 AI hoặc stock footage tùy theo cấu hình.

    Returns:
        - str bắt đầu bằng "/" hoặc đường dẫn local → file Veo3 cache
        - str bắt đầu bằng "http" → URL stock footage
        - "" nếu thất bại hoàn toàn
    """
    veo3_provider = cfg.get("veo3_provider", "stock")
    veo3_requested = (
        veo3_provider in ("gemini_web", "google_flow")
        or cfg.get("veo3_enabled", False)
        or force_veo3
    )
    veo3_on = (
        veo3_requested
        and (
            (veo3_provider == "api" and _VEO3_OK)
            or (veo3_provider == "google_flow" and bool(cfg.get("useapi_token")))
        )
    )
    veo3_mode = "all" if force_veo3 else cfg.get("veo3_mode", "fallback")
    gem_keys  = cfg.get("gemini", [])

    if veo3_requested and veo3_provider == "gemini_web":
        if callable(log_cb):
            log_cb("🌐 Gemini Web: bỏ qua API; hãy tạo và nhập MP4 trong editor cảnh")
        # In fallback mode stock remains useful. In all-scenes mode an empty
        # result deliberately leaves the scene pending for a web download.
        if veo3_mode == "all":
            return ""
        return fetch_stock_video(keyword, orientation=orientation, used_urls=used_urls) or ""

    def _veo3_generate():
        """Tạo video qua API (Veo3 SDK/REST hoặc Google Flow UseAPI)."""
        if veo3_provider == "google_flow":
            token = cfg.get("useapi_token", "")
            email = cfg.get("useapi_email", "")
            model = cfg.get("useapi_model", "veo-3.1-fast")
            if not token:
                if callable(log_cb): log_cb("❌ Google Flow: Chưa cấu hình UseAPI Token trong Settings")
                return None
            if callable(log_cb): log_cb("🚀 Gọi Google Flow qua UseAPI...")
            result = _veo3.generate_video_google_flow(
                keyword         = keyword,
                token           = token,
                email           = email if email else None,
                model           = model,
                orientation     = orientation,
                scene_text      = scene_text,
                timeout_seconds = 240,
                log_cb          = log_cb,
                veo3_prompt     = veo3_prompt,
            )
            return result
        else:
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
                    veo3_prompt     = veo3_prompt,
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
    if not FFMPEG:
        raise RuntimeError("Không tìm thấy FFmpeg. Hãy cài FFmpeg trước khi render.")
    cmd = [FFMPEG, "-y", "-loglevel", "error"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"FFmpeg: {result.stderr[:300]}")

# Check if FFmpeg has subtitles filter (requires libass)
@st.cache_data
def has_subtitles_filter():
    if not FFMPEG:
        return False
    try:
        r = subprocess.run([FFMPEG, "-filters"], capture_output=True, text=True)
        return r.returncode == 0 and "subtitles" in r.stdout
    except OSError:
        return False

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

tab_main, tab_veo, tab_creative, tab_settings = st.tabs(
    ["🎬 Pipeline", "🤖 Veo3 Studio", "🎨 Creative Studio", "⚙️ Settings"]
)

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
        cfg.setdefault("groq", []).append(new_q.strip()); changed = True; reset_groq_cache()
    for i, k in enumerate(cfg.get("groq", [])):
        c1, c2 = st.columns([5,1])
        c1.code(k[:8] + "..." + k[-4:])
        if c2.button("✕", key=f"dq{i}"): cfg["groq"].pop(i); changed = True; reset_groq_cache()

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

    _veo3_provider = st.radio(
        "🔌 Nguồn tạo video",
        options=["stock", "gemini_web", "api", "google_flow"],
        format_func=lambda value: {
            "stock": "Stock/ảnh — không tạo Veo, không tốn credit",
            "gemini_web": "Gemini Web — KHÔNG gọi API, dùng gói Pro/Ultra",
            "api": "Veo API — tự động hoàn toàn, CÓ dùng API credit",
            "google_flow": "Google Flow (UseAPI) — tạo video tự động qua UseAPI.net",
        }[value],
        index=["stock", "gemini_web", "api", "google_flow"].index(cfg.get("veo3_provider", "stock")),
        horizontal=True,
        key="veo3_provider_radio",
    )
    if _veo3_provider != cfg.get("veo3_provider", "stock"):
        cfg["veo3_provider"] = _veo3_provider
        changed = True

    if _veo3_provider == "api":
        _veo3_enabled = st.toggle(
            "💳 Bật Veo API (sẽ tiêu tốn API credit)",
            value=cfg.get("veo3_enabled", False),
            key="veo3_toggle",
            help="Chỉ bật nếu bạn chấp nhận sử dụng credit của Gemini/Veo API",
        )
        if _veo3_enabled != cfg.get("veo3_enabled", False):
            cfg["veo3_enabled"] = _veo3_enabled
            changed = True
    elif _veo3_provider == "google_flow":
        _veo3_enabled = True
        if not cfg.get("veo3_enabled", False):
            cfg["veo3_enabled"] = True
            changed = True
    else:
        _veo3_enabled = False
        if cfg.get("veo3_enabled", False):
            cfg["veo3_enabled"] = False
            changed = True

    if _veo3_enabled or _veo3_provider == "gemini_web":

        if _veo3_provider == "google_flow":
            st.write("🔧 **Cấu hình Google Flow (UseAPI.net)**")
            useapi_tok = st.text_input("UseAPI.net API Token", value=cfg.get("useapi_token", ""), type="password", key="useapi_token_in", help="Lấy token tại api.useapi.net")
            if useapi_tok != cfg.get("useapi_token", ""):
                cfg["useapi_token"] = useapi_tok
                changed = True
                
            useapi_em = st.text_input("Google Flow Email (optional)", value=cfg.get("useapi_email", ""), placeholder="your_email@gmail.com", key="useapi_email_in", help="Email của account Google Flow. Để trống để tự động chọn account.")
            if useapi_em != cfg.get("useapi_email", ""):
                cfg["useapi_email"] = useapi_em
                changed = True
                
            useapi_mod = st.selectbox("Model", options=["veo-3.1-fast", "veo-3.1-quality", "veo-3.1-lite", "omni-flash"], index=["veo-3.1-fast", "veo-3.1-quality", "veo-3.1-lite", "omni-flash"].index(cfg.get("useapi_model", "veo-3.1-fast")), key="useapi_model_in")
            if useapi_mod != cfg.get("useapi_model", "veo-3.1-fast"):
                cfg["useapi_model"] = useapi_mod
                changed = True

        _veo3_mode = st.radio(
            "🎯 Chế độ Veo3/Flow",
            options=["fallback", "all"],
            format_func=lambda x: (
                {
                    "fallback": "🔄 Stock trước — chỉ chuẩn bị prompt khi thiếu footage",
                    "all": "🌐 All Scenes — chờ video sinh từ AI, không dùng Stock",
                } if _veo3_provider in ("gemini_web", "google_flow") else {
                    "fallback": "🔄 Fallback — chỉ gọi Veo API khi stock không có",
                    "all": "💳 All Scenes — mọi cảnh gọi Veo API và dùng credit",
                }
            ).get(x, x),
            index=0 if cfg.get("veo3_mode", "fallback") == "fallback" else 1,
            key="veo3_mode_radio",
            horizontal=True,
        )
        if _veo3_mode != cfg.get("veo3_mode", "fallback"):
            cfg["veo3_mode"] = _veo3_mode
            changed = True

        # Resolution (chỉ dùng cho api chính thức)
        if _veo3_provider != "google_flow":
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

        if _veo3_provider == "gemini_web":
            st.info(
                "Gemini Web sẽ không gọi Veo API. App chuẩn bị prompt; bạn mở Gemini, "
                "tạo video, tải MP4 và nhập lại ngay trong editor từng cảnh."
            )

        _gem_keys = cfg.get("gemini", [])
        if _veo3_provider == "gemini_web":
            st.success("✅ Không cần Veo API key; dùng phiên đăng nhập Gemini trên trình duyệt.")
        elif _veo3_provider == "google_flow":
            if cfg.get("useapi_token"):
                st.success("✅ Sẵn sàng: Đã cấu hình UseAPI Token cho Google Flow.")
            else:
                st.error("❌ Chưa cấu hình UseAPI Token! Hãy điền token để sử dụng.")
        elif _gem_keys:
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

        _saved_lang = proj.get("lang", "Vietnamese" if new_mode in ("shorts", "veo3") else "English")
        _lang_opts = ["English", "Vietnamese", "Korean", "Japanese"]
        _lang_idx = _lang_opts.index(_saved_lang) if _saved_lang in _lang_opts else 0
        lang = st.selectbox("🌍 Ngôn ngữ", _lang_opts, index=_lang_idx)
        if lang != proj.get("lang"):
            proj["lang"] = lang
            save_proj(proj)

        # ── Voice selector: CapCut voices if available, else Edge fallback ───
        if lang == "Korean":
            # Voice.json hiện không có giọng CapCut Hàn hợp lệ. Các ID BV700–
            # BV706 cũ trả TTSInvalidText, nên Korean luôn dùng Edge Neural.
            _ko_voice_opts = [
                "ko-KR (SunHi - Female)",
                "ko-KR (InJoon - Male)",
            ]
            _ko_saved = proj.get("voice_cfg_key")
            _ko_default = "ko-KR (SunHi - Female)"
            if _ko_saved == "ko-KR":
                _ko_default = "ko-KR (InJoon - Male)"
            voice = st.selectbox(
                "🔊 Giọng đọc tiếng Hàn (Edge TTS)",
                _ko_voice_opts,
                index=_ko_voice_opts.index(_ko_default),
                key="voice_edge_ko",
            )
            voice_cfg_key = {
                "ko-KR (SunHi - Female)": "ko-female",
                "ko-KR (InJoon - Male)": "ko-KR",
            }[voice]
            if voice_cfg_key != proj.get("voice_cfg_key"):
                proj["voice_cfg_key"] = voice_cfg_key
                save_proj(proj)

            _valid_rates = ["0.8", "0.9", "1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8", "2.0"]
            _default_rate = st.session_state.get("tts_rate_slider") or cfg.get("tts_rate", "1.3")
            if _default_rate not in _valid_rates:
                _default_rate = "1.3"
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
            _allow_voice_fallback = True
            st.info("✅ Tiếng Hàn dùng Edge Neural ổn định; không gửi tới ID CapCut Hàn bị lỗi.")
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
                    if _v == _saved_voice:
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
            _wps_map   = {"Vietnamese": 3.8, "Korean": 2.2, "English": 2.2}
            _min_map   = {"Vietnamese": 35,  "Korean": 18,  "English": 18}
            _wps       = _wps_map.get(lang, 2.2)
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
                f'      "retention_note": "why viewer stays"\n'
                f'    }}\n'
                f'  ]\n'
                f'}}\n\n'
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
            _import_raw = st.text_area(
                "Paste JSON kịch bản vào đây:",
                placeholder='{"title": "...", "scenes": [{"id": 1, "text": "...", "keyword": "...", "veo3_prompt": "..."}]}',
                height=180,
                key="import_json_input",
            )
            if st.button("✅ Nhập JSON → Bắt đầu STEP 2", key="btn_import_json", type="primary"):
                if not _import_raw.strip():
                    st.error("⚠️ Ô JSON trống — hãy paste kết quả từ ChatGPT vào.")
                else:
                    try:
                        _imp = parse_json_robust(_import_raw)
                        _imp_scenes = _imp.get("scenes", [])
                        if not _imp_scenes:
                            st.error("❌ JSON thiếu trường 'scenes' — kiểm tra lại output của ChatGPT.")
                        else:
                            for _s in _imp_scenes:
                                _rt = _s.get("text", "")
                                _ct = re.sub(r'\b(\w+)( \1\b)+', r'\1', _rt)
                                _s["text"] = " ".join(_ct.split())
                                if not _s.get("keyword"):
                                    _s["keyword"] = niche
                                if not _s.get("veo3_prompt"):
                                    _s["veo3_prompt"] = f"Cảnh về {niche}, cinematic, 4K"
                            _imp_script = {
                                "title":       _imp.get("title", custom.strip() or niche),
                                "description": _imp.get("description", ""),
                                "tags":        _imp.get("tags", []),
                                "scenes":      _imp_scenes,
                            }
                            # ── Pre-populate proj["scenes"] để edit UI hoạt động ngay ──
                            _wps_map_imp = {"Vietnamese": 3.8, "Korean": 2.2, "English": 2.2, "Japanese": 2.0}
                            _wps_imp = _wps_map_imp.get(lang, 2.2) * float(tts_rate)
                            _tgt_imp = float(target_sec_per_scene)
                            _imp_built_scenes = []
                            for _ii, _sc in enumerate(_imp_scenes):
                                _txt = _sc.get("text", "")
                                _json_dur = _sc.get("duration")
                                if _json_dur and isinstance(_json_dur, (int, float)) and 3 <= float(_json_dur) <= 60:
                                    _dur = round(float(_json_dur), 1)
                                else:
                                    _is_korean = lang in ("Korean", "Japanese")
                                    if _is_korean or not any("A" <= c <= "z" for c in _txt[:20]):
                                        _dur_raw = max(len(_txt.replace(" ",""))/3.0, len(_txt.split())/max(_wps_imp,0.1))
                                    else:
                                        _dur_raw = len(_txt.split()) / max(_wps_imp, 0.1)
                                    _dur = round(min(max(_dur_raw + 0.4, 3.0), _tgt_imp * 1.5), 1)
                                _imp_built_scenes.append({
                                    "id":          _sc.get("id", _ii + 1),
                                    "text":        _txt,
                                    "keyword":     _sc.get("keyword", niche),
                                    "veo3_prompt": _sc.get("veo3_prompt", f"Cảnh về {niche}, cinematic, 4K"),
                                    "retention_note": _sc.get("retention_note", ""),
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
                            st.session_state.proj["lang"]   = lang
                            st.session_state.proj["target_sec_per_scene"] = _tgt_imp
                            _pid = st.session_state.proj.get("id", "")
                            for _ci in range(len(_imp_built_scenes) + 5):
                                _dk = f"auto_vid_done_{_pid}{_ci}"
                                if _dk in st.session_state: del st.session_state[_dk]
                                for _k in list(st.session_state.keys()):
                                    if _k.startswith(f"kw_trans_{_ci}_"): del st.session_state[_k]
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
                    _wps_map = {"Vietnamese": 3.8, "Korean": 2.2, "English": 2.2, "Japanese": 2.0}
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
                        scenes.append({
                            "id":          sc_data["id"],
                            "text":        sc_data["text"],
                            "keyword":     sc_data["keyword"],
                            "veo3_prompt": sc_data.get("veo3_prompt", ""),  # ← prompt AI gen sẵn từ kịch bản
                            "videoUrl":    vid_url,
                            "veo3Path":    veo3_path,    # ← local path nếu dùng Veo3
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
                        _wps_map       = {"Vietnamese": 3.8, "Korean": 2.2, "English": 2.2}
                        _words_per_sec = _wps_map.get(lang, 2.2) * float(tts_rate)

                        for sc_data in script["scenes"]:
                            _scene_text = str(sc_data.get("text", ""))
                            if lang == "Vietnamese":
                                _scene_text = normalize_vietnamese_tts(_scene_text)
                                sc_data["text"] = _scene_text
                            scenes.append({
                                "id":          sc_data.get("id", len(scenes) + 1),
                                "text":        _scene_text,
                                "keyword":     sc_data.get("keyword", niche),
                                "veo3_prompt": sc_data.get("veo3_prompt", ""),
                                "videoUrl":    None,
                                "veo3Path":    None,
                                "imageUrl":    None,
                                "audioDone":   False,
                                "targetDur":   float(target_sec_per_scene),
                                "duration":    round(
                                    max(float(target_sec_per_scene),
                                        len(_scene_text.split()) / max(_words_per_sec, 0.1) + 0.4),
                                    1
                                ),
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
                        # v2 invalidates files previously cached under a CapCut
                        # voice name even though their actual audio came from Edge.
                        tts_text = (
                            normalize_vietnamese_tts(s["text"])
                            if lang == "Vietnamese" else s["text"]
                        )
                        hash_str = (
                            f"tts-cache-v3|{tts_text}|{voice_cfg_key}|{tts_rate}|"
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
                                         rate=tts_rate,
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
                                    rate=tts_rate
                                )
                                if retry_result and is_valid_audio(retry_result):
                                    shutil.copy(retry_result, audio_path)
                                    actual_dur = probe_audio_duration(audio_path)
                                    tts_succeeded = actual_dur is not None
                                    _duration_label = f"{actual_dur:.1f}s" if actual_dur is not None else "chưa đo được duration"
                                    log(f"  ✅ Retry Edge TTS cảnh {i+1} thành công ({_duration_label})")
                                else:
                                    log(f"  ❌ CẢNH {i+1}: tất cả provider TTS đều thất bại — cảnh này sẽ dùng silence!")
                                    log(f"     → Nguyên nhân có thể: rate limit CapCut, asyncio conflict, hoặc mất mạng")
                                    log(f"     → Chạy Render lại: cảnh đã thành công dùng cache, chỉ cảnh lỗi được tạo lại")
                            else:
                                log(
                                    f"  ❌ CẢNH {i+1}: giọng '{voice_cfg_key}' không tạo được. "
                                    "Không đổi sang Hoài My vì tùy chọn giọng dự phòng đang tắt."
                                )
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
                            log(f"  ❌ TTS cảnh {i+1} THẤT BẠI hoàn toàn — video sẽ dùng silence, không dùng nhầm audio cũ.")
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
                            log(f"  ⚪ Cảnh {i+1}: silence {final_dur:.1f}s; {aud_dur:.1f}s chỉ là ước lượng nhịp, KHÔNG phải audio.")

                        # Lưu tiến độ sau từng cảnh để lần chạy sau tiếp tục đúng
                        # từ cache, kể cả khi CapCut rate-limit giữa một dự án dài.
                        proj.update({"scenes": scenes, "step": 3})
                        save_proj(proj)

                        # Với chế độ giữ nguyên giọng, nhiều lỗi liên tiếp gần như
                        # chắc chắn là provider đang rate-limit. Dừng batch ngay,
                        # không phí hàng chục phút và tuyệt đối không render silence.
                        if (
                            not _allow_voice_fallback
                            and not _force_edge
                            and _consecutive_tts_failures >= 2
                        ):
                            _tts_batch_aborted = True
                            _tts_abort_scene = i + 1
                            log("  🛑 CapCut lỗi 2 cảnh liên tiếp — dừng batch TTS để bảo vệ giọng đã chọn.")
                            log("     Các cảnh thành công đã được lưu cache. Chờ 1–2 phút rồi bấm Render lại để tiếp tục.")
                            break
                    proj.update({"scenes": scenes, "step": 3})
                    save_proj(proj)

                    if _tts_batch_aborted:
                        st.error(
                            f"CapCut đang giới hạn yêu cầu tại cảnh {_tts_abort_scene}. "
                            "Đã dừng trước khi render để video không có cảnh im lặng. "
                            "Các cảnh thành công đã lưu; chờ 1–2 phút rồi bấm Render lại."
                        )
                        st.stop()

                # STEP 4: Render
                log("🎞️ Render video...")
                scene_mp4s = []
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
                                    rate=tts_rate,
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
                        ffmpeg("-i", str(src_audio),
                               # Fade 35ms đủ đưa biên sóng về zero, không làm
                               # mất phụ âm/chữ đầu như fade dài 150ms.
                               "-af", f"afade=t=in:st=0:d=0.035,apad=pad_dur={dur}",
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
                    # Giảm fade xuống 0.15s để chỉ chớp mờ chuyển cảnh, không bị đen lâu
                    v_fade = f",fade=t=in:st=0:d=0.15,fade=t=out:st={dur-0.15}:d=0.15" if enable_transition else ""
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

                    # ── Tính fade filter string ──
                    _fade_str = f",fade=t=in:st=0:d=0.15,fade=t=out:st={max(0.0, dur-0.15):.3f}:d=0.15" if enable_transition else ""

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

                    # Ghi hash cache sau khi render thành công — lần sau sẽ skip
                    if out.exists() and out.stat().st_size > 10000:
                        try:
                            _scene_hash_file.write_text(_scene_hash)
                        except Exception:
                            pass
                    scene_mp4s.append(out)

                # Các scene đã được chuẩn hóa H.264/AAC cùng resolution/fps ở trên.
                # Thử concat stream-copy trước (nhanh, không giảm chất lượng); nếu một
                # project cũ có codec/timebase lệch thì fallback sang normalize encode.
                concat_txt = work / "concat.txt"
                concat_txt.write_text("\n".join(f"file '{p}'" for p in scene_mp4s))
                raw_final = work / "final.mp4"
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

        @st.fragment
        def _scene_editor_fragment():
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
                                                st.rerun(scope="fragment")
                                        except Exception as e:
                                            st.error(f"Lỗi: {e}")

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
                                _show_sub_r = bool(_s.get("srtFile") and Path(_s["srtFile"]).exists())
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
                                            ffmpeg("-f","lavfi","-i","anullsrc=r=44100:cl=stereo",
                                                   "-t",str(_dur_r),"-c:a","aac","-ar","44100","-ac","2",
                                                   "-b:a","128k","-y",str(_audio_trim_r))

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
                                                "-map", "0:v", "-map", "1:a", "-shortest", "-y", str(_base_r)
                                            ]
                                        else:
                                            _black_r = f"color=c=black:s={_W_r}x{_H_r}:r=30"
                                            _cmd_r = [
                                                "-f","lavfi","-i",_black_r,"-i",str(_audio_trim_r),
                                                "-t",str(_dur_r),"-c:v","libx264","-preset","fast","-crf","22",
                                                "-c:a","aac","-b:a","128k","-ar","44100",
                                                "-map","0:v","-map","1:a","-shortest","-y",str(_base_r)
                                            ]
                                        ffmpeg(*_cmd_r)

                                        # Subtitle
                                        _out_r = _s_dir_r / "scene.mp4"
                                        _srt_r = _s.get("srtFile")
                                        _has_srt_r = False
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
# CREATIVE STUDIO TAB — independent non-educational workflow
# ════════════════════════════════════════════════════════════
with tab_creative:
    if _CREATIVE_OK:
        _creative.render_creative_studio(
            call_ai, parse_json_robust, FFMPEG,
            veo_engine=_veo3 if _VEO3_OK else None,
            cfg=cfg,
        )
    else:
        st.error("Creative Studio chưa load được. Kiểm tra file creative_studio.py.")


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
        veo_voice_lang = st.selectbox("🌍 Ngôn ngữ", ["Vietnamese", "English", "Korean", "Japanese"], index=0, key="veo_lang_sel")
        
        # Giọng đọc
        if veo_voice_lang == "Korean":
            veo_voice_opt = st.selectbox(
                "🔊 Giọng đọc tiếng Hàn (Edge TTS)",
                ["ko-KR (SunHi - Female)", "ko-KR (InJoon - Male)"],
                key="veo_voice_opt_ko",
            )
        elif _CAPCUT_OK:
            _v_flag = {"Vietnamese": "🇻🇳", "English": "🇺🇸", "Korean": "🇰🇷", "Japanese": "🇯🇵"}.get(veo_voice_lang, "🇺🇸")
            _v_code = {"Vietnamese": "vi", "English": "en", "Korean": "ko", "Japanese": "ja"}.get(veo_voice_lang, "en")
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
        _veo_api_allowed = cfg.get("veo3_provider") == "api" and cfg.get("veo3_enabled", False)
        btn_generate = btn_col1.button(
            "🚀 Bắt đầu Tạo Video",
            type="primary",
            use_container_width=True,
            key="veo_generate_btn",
            disabled=not _veo_api_allowed,
            help="Chỉ hoạt động khi Settings chọn Veo API và bật công tắc dùng credit.",
        )
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
                f"      \"keyword\": \"Từ khóa stock video ngắn bằng tiếng Anh, 2 đến 5 từ\"\n"
                f"    }}\n"
                f"  ]\n"
                f"}}\n"
            )
            
            # Dùng chung AI routing/parser với Main Pipeline.
            gemini_keys = cfg.get("gemini", [])
            script_json = None
            try:
                script_json = parse_json_robust(call_ai_script(veo_prompt))
            except Exception as e:
                vlog(f"⚠️ AI routing viết kịch bản lỗi: {e}")
            
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
            scenes = build_visual_prompts_batch(scenes, veo_voice_lang, vlog)
                
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
                            veo3_prompt     = s.get("veo3_prompt", ""),
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
                "ko-KR (SunHi - Female)": "ko-female",
                "ko-KR (InJoon - Male)": "ko-KR",
                "Japanese (Nanami)": "ja-female",
                "Japanese (Keita)": "ja-JP",
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
                                # Buffer 0.05s để không cắt tiếng — không dùng +0.3s gây dôi thời gian
                                scenes[i]["duration"] = round(int(_hh)*3600 + int(_mm)*60 + float(_ss) + 0.05, 2)
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
                key="veo3_manual_gen_btn",
                disabled=not (cfg.get("veo3_provider") == "api" and cfg.get("veo3_enabled", False)),
                help="Nút này gọi Veo API và chỉ mở khi bạn bật rõ ràng chế độ dùng credit.",
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
                    if st.button(
                        f"🔄 Vẽ lại Cảnh {idx+1} bằng Veo3",
                        key=f"btn_regen_veo_{idx}",
                        disabled=not (cfg.get("veo3_provider") == "api" and cfg.get("veo3_enabled", False)),
                        help="Có sử dụng Veo API credit.",
                    ):
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
                                    veo3_prompt     = s.get("veo3_prompt", ""),
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
