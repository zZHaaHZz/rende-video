"""
app/ai_client.py — AI API clients: Gemini, Groq LLM, OpenAI.
Các hàm call_ai() dùng cfg được truyền vào — không dùng global.
"""
import json
import re
import time

import requests

# ── Groq model cache (module-level globals) ───────────────────────────────────
_GROQ_LIVE_MODELS: list = []
_GROQ_CACHE_KEY_HASH: str = ""
_GROQ_BLACKLIST: set = set()


def reset_groq_cache():
    """Reset Groq model cache khi key thay đổi."""
    global _GROQ_LIVE_MODELS, _GROQ_CACHE_KEY_HASH, _GROQ_BLACKLIST
    try:
        _GROQ_LIVE_MODELS = []
        _GROQ_CACHE_KEY_HASH = ""
        _GROQ_BLACKLIST = set()
    except Exception:
        pass


# ── Gemini ────────────────────────────────────────────────────────────────────
def call_gemini(key: str, prompt: str) -> str:
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
    if not r.ok:
        raise Exception(d.get("error", {}).get("message", f"Gemini {r.status_code}"))
    return d["candidates"][0]["content"]["parts"][0]["text"].replace("```json", "").replace("```", "").strip()


# ── Groq LLM ──────────────────────────────────────────────────────────────────
def call_groq_llm(key: str, prompt: str) -> str:
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
                        "max_tokens": 4096,
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


# ── OpenAI ────────────────────────────────────────────────────────────────────
def call_openai(key: str, prompt: str, model: str = "gpt-4o-mini") -> str:
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


# ── High-level dispatchers ────────────────────────────────────────────────────
def call_ai_script(prompt: str, cfg: dict) -> str:
    """Ưu tiên OpenAI gpt-4o (chất lượng cao nhất). Fallback: gpt-4o-mini → Gemini → Groq."""
    last_err = None
    oai_key = cfg.get("openai", "") or ""
    if oai_key.startswith("sk-"):
        for model in ["gpt-4o", "gpt-4o-mini"]:
            try:
                result = call_openai(oai_key, prompt, model=model)
                print(f"[Script] Dùng OpenAI {model}")
                return result
            except Exception as e:
                last_err = str(e)
                print(f"[Script/OpenAI/{model}] skip: {str(e)[:100]}")
                continue
    for key in cfg.get("gemini", []):
        try:
            return call_gemini(key, prompt)
        except Exception as e:
            last_err = str(e)
            print(f"[Script/Gemini] skip: {str(e)[:80]}")
            continue
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


def call_ai(prompt: str, cfg: dict) -> str:
    """Generic AI call: OpenAI → Gemini → Groq."""
    last_err = None
    oai_key = cfg.get("openai", "") or ""
    if oai_key.startswith("sk-"):
        try:
            return call_openai(oai_key, prompt)
        except Exception as e:
            last_err = str(e)
            print(f"[OpenAI] skip: {str(e)[:100]}")
    for key in cfg.get("gemini", []):
        try:
            return call_gemini(key, prompt)
        except Exception as e:
            last_err = str(e)
            print(f"[Gemini] skip: {str(e)[:80]}")
            continue
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


# ── JSON parser ───────────────────────────────────────────────────────────────
def parse_json_robust(raw: str) -> dict:
    """Parse AI-generated JSON that may contain common formatting issues."""
    import re as _re
    text = raw.strip()
    text = _re.sub(r'^```(?:json)?\s*', '', text, flags=_re.MULTILINE)
    text = _re.sub(r'```\s*$', '', text, flags=_re.MULTILINE)
    text = text.strip()

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

    text = text[brace_start:brace_end + 1]

    for src, dst in [('\u201c', '"'), ('\u201d', '"'), ('\u2018', "'"), ('\u2019', "'")]:
        text = text.replace(src, dst)

    text = _re.sub(r',\s*([\]}])', r'\1', text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    text2 = _re.sub(r'(?<!\\)\n', ' ', text)
    try:
        return json.loads(text2)
    except json.JSONDecodeError:
        pass

    import ast as _ast
    try:
        obj = _ast.literal_eval(text)
        return json.loads(json.dumps(obj, ensure_ascii=False))
    except Exception:
        pass

    raise json.JSONDecodeError(
        f"parse_json_robust: all parse attempts failed. First 300 chars: {raw[:300]!r}",
        raw, 0
    )
