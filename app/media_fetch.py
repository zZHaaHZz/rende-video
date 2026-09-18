"""
app/media_fetch.py — Stock media fetching: Pexels, Pixabay, Coverr.
Tất cả hàm nhận cfg làm tham số — không dùng global.
"""
import random
import re
from typing import Optional

import requests

from app.ai_client import call_gemini, call_groq_llm

# ── Relevance ─────────────────────────────────────────────────────────────────
MIN_RELEVANCE = 0.25

# ── Topic context modifiers ───────────────────────────────────────────────────
TOPIC_CONTEXT_MODIFIERS = {
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

_ENRICH_BLACKLIST = {"worker", "labor", "construction", "factory", "industrial",
                     "manual", "bricklayer", "builder", "welder", "crane"}

_HUMAN_LIFESTYLE_TERMS = {
    "person", "people", "man", "woman", "couple", "family", "student",
    "worker", "adult", "young", "elderly", "crowd", "street", "market",
    "city", "urban", "district", "neighborhood", "food", "cafe", "restaurant",
    "commute", "subway", "bus", "traffic", "pedestrian", "lifestyle", "daily",
    "home", "apartment", "house", "office", "school",
}

_REGION_TERMS = {
    "vietnamese", "vietnam", "hanoi", "saigon", "ho chi minh", "hoi an",
    "korean", "korea", "seoul", "busan", "incheon",
    "japanese", "japan", "tokyo", "osaka",
    "chinese", "china", "beijing", "shanghai",
    "thai", "thailand", "bangkok",
    "american", "european", "western", "british", "french",
}

_UNIVERSAL_CONTENT = {
    "nature", "ocean", "mountain", "forest", "sky", "sunset", "space",
    "abstract", "bokeh", "background", "chart", "data", "graph",
    "technology", "science", "lab", "research",
}

# ── Translation cache ─────────────────────────────────────────────────────────
_KW_TRANSLATE_CACHE: dict = {}


def _keyword_relevance_score(title: str, keyword: str) -> float:
    if not title or not keyword:
        return 0.0
    kw_words = set(keyword.lower().split())
    title_lower = title.lower()
    matches = sum(1 for w in kw_words if w in title_lower)
    return matches / len(kw_words) if kw_words else 0.0


def _translate_keyword_to_en(kw: str, lang: str = "", cfg: dict = None) -> str:
    """Dịch keyword VN/KR → EN ngắn gọn cho stock search."""
    global _KW_TRANSLATE_CACHE
    cfg = cfg or {}
    cache_key = f"{kw}|{lang}"
    if cache_key in _KW_TRANSLATE_CACHE:
        return _KW_TRANSLATE_CACHE[cache_key]

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
    _re2 = re
    for key in cfg.get("groq", []):
        try:
            result = call_groq_llm(key, prompt)
            if result and len(result) < 80:
                translated = _re2.sub(r'[^\w\s-]', '', result).strip()[:50]
                break
        except Exception:
            continue
    if not translated:
        for key in cfg.get("gemini", []):
            try:
                result = call_gemini(key, prompt)
                if result and len(result) < 80:
                    translated = _re2.sub(r'[^\w\s-]', '', result).strip()[:50]
                    break
            except Exception:
                continue

    out = translated or kw
    _KW_TRANSLATE_CACHE[cache_key] = out
    if translated:
        print(f"[KW] '{kw}' → '{out}' (lang={lang or 'auto'})")
    return out


def clean_keyword(kw: str, lang: str = "", cfg: dict = None) -> str:
    """Sanitize AI-generated keyword: extract from URLs, auto-translate VN/KR → EN."""
    cfg = cfg or {}
    kw = kw or ""
    m = re.search(r'pexels\.com/(?:[^/]+/)*([^/?&\s]+)', kw)
    if m:
        kw = m.group(1).replace('-', ' ').replace('_', ' ')
    kw = re.sub(r'https?://\S+', '', kw)
    kw = kw.replace('/', ' ').replace('\\', ' ')
    kw = re.sub(r'[^\w\s-]', '', kw).strip()
    kw = ' '.join(kw.split()[:5]) or "nature"

    has_vi = any(c in kw for c in "àáảãạăắặẳẵặâấầẩẫậèéẹẻẽêềếểễệìíịỉĩòóọỏõôồốổỗộơờớởỡợùúụủũưừứửữựỳýỵỷỹđ")
    has_ko = any(0xAC00 <= ord(c) <= 0xD7A3 or 0x1100 <= ord(c) <= 0x11FF for c in kw)
    if has_vi or has_ko:
        kw = _translate_keyword_to_en(kw, lang=lang, cfg=cfg)
    return kw


def enrich_keyword_with_context(keyword: str, niche: str) -> str:
    kw_words = [w for w in keyword.split() if w.lower() not in _ENRICH_BLACKLIST]
    clean_kw = " ".join(kw_words) or keyword
    modifier = TOPIC_CONTEXT_MODIFIERS.get(niche.lower(), "")
    if modifier and modifier.split()[0] not in clean_kw.lower():
        return f"{clean_kw} {modifier}"
    return clean_kw


def inject_region_into_keyword(keyword: str, lang: str) -> str:
    if lang not in ("Vietnamese", "Korean"):
        return keyword
    kw_lower = keyword.lower()
    if any(rt in kw_lower for rt in _REGION_TERMS):
        return keyword
    if any(ut in kw_lower for ut in _UNIVERSAL_CONTENT):
        return keyword
    kw_words = set(kw_lower.split())
    if kw_words & _HUMAN_LIFESTYLE_TERMS:
        region_prefix = "Vietnamese" if lang == "Vietnamese" else "Korean"
        result = f"{region_prefix} {keyword}"
        print(f"[KW-Region] '{keyword}' → '{result}' (lang={lang})")
        return result
    return keyword


def optimize_query_for_region(keyword: str, region: str) -> str:
    if not keyword:
        return keyword
    if region == "Châu Á / Việt Nam":
        kw_lower = keyword.lower()
        if any(w in kw_lower for w in ["asian", "vietnam", "korean", "japan", "china", "chinese", "vietnamese"]):
            return keyword
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


def is_image_file(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            h = f.read(4)
            return h.startswith(b'\xff\xd8\xff') or h.startswith(b'\x89PNG') or h.startswith(b'RIFF')
    except Exception:
        return False


# ── Pexels ────────────────────────────────────────────────────────────────────
def fetch_pexels(keyword: str, orientation: str = "landscape",
                  used_urls=None, cfg: dict = None) -> Optional[str]:
    cfg = cfg or {}
    key = (cfg.get("pexels") or [None])[0]
    if not key:
        return None
    if used_urls is None:
        used_urls = set()

    global_used = set(cfg.get("used_videos", []))

    def _save_url(link):
        if "used_videos" not in cfg:
            cfg["used_videos"] = []
        if link not in cfg["used_videos"]:
            cfg["used_videos"].append(link)
            if len(cfg["used_videos"]) > 1000:
                cfg["used_videos"].pop(0)

    def _search_vid(kw, o, check_global=True):
        url = f"https://api.pexels.com/videos/search?query={requests.utils.quote(kw)}&per_page=30"
        if o: url += f"&orientation={o}"
        r = requests.get(url, headers={"Authorization": key}, timeout=15)
        if not r.ok: return None
        videos = r.json().get("videos", [])
        random.shuffle(videos)
        for v in videos:
            files = v.get("video_files", [])
            if not files: continue
            valid = [f for f in files if (f.get("width", 0) >= 1080 or f.get("height", 0) >= 1080)]
            if not valid: valid = files
            valid = sorted(valid, key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
            f = valid[0]
            if not f: continue
            link = f["link"]
            if link in used_urls: continue
            if check_global and link in global_used: continue
            _save_url(link)
            return link
        return None

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
            _save_url(link)
            return link
        return None

    SAFE_FALLBACKS = ["nature", "landscape", "cityscape", "abstract", "technology", "scenery"]

    for check in [True, False]:
        res = _search_vid(keyword, orientation, check)
        if not res and orientation != "": res = _search_vid(keyword, "", check)
        if not res:
            fb = random.choice(SAFE_FALLBACKS)
            res = _search_vid(fb, orientation, check)
            if not res and orientation != "": res = _search_vid(fb, "", check)
        if res: return res

    for check in [True, False]:
        res = _search_photo(keyword, orientation, check)
        if not res and orientation != "": res = _search_photo(keyword, "", check)
        if res: return res

    return None


def search_pexels_videos(keyword: str, orientation: str = "landscape", cfg: dict = None) -> list:
    cfg = cfg or {}
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
            valid = [f for f in files if (f.get("width", 0) >= 1080 or f.get("height", 0) >= 1080)]
            if not valid: valid = files
            valid = sorted(valid, key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
            f = valid[0]
            if f:
                results.append({"id": v["id"], "url": f["link"], "image": v["image"], "duration": v["duration"]})
        return results
    except Exception as e:
        print(f"[Pexels Search] Error: {e}")
        return []


def search_pexels_photos_only(keyword: str, orientation: str = "landscape", cfg: dict = None) -> list:
    results = []
    cfg = cfg or {}
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


# ── Pixabay ───────────────────────────────────────────────────────────────────
def fetch_pixabay(keyword: str, orientation: str = "landscape",
                   used_urls=None, cfg: dict = None) -> Optional[str]:
    cfg = cfg or {}
    key = cfg.get("pixabay", "")
    if not key: return None
    if used_urls is None: used_urls = set()
    global_used = set(cfg.get("used_videos", []))

    def _save_url(link):
        if "used_videos" not in cfg: cfg["used_videos"] = []
        if link not in cfg["used_videos"]:
            cfg["used_videos"].append(link)
            if len(cfg["used_videos"]) > 1000:
                cfg["used_videos"].pop(0)

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
                res_list = [r2 for r2 in res_list if r2.get("url") and r2.get("width") and r2.get("height")]
                if not res_list: continue
                w2, h2 = res_list[0]["width"], res_list[0]["height"]
                is_landscape = w2 >= h2
                if o == "landscape" and not is_landscape: continue
                if o == "portrait" and is_landscape: continue
                res_list = sorted(res_list, key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
                link = res_list[0]["url"]
                if link in used_urls: continue
                if check_global and link in global_used: continue
                _save_url(link)
                return link
            return None
        except Exception as e:
            print(f"[Pixabay] {e}")
            return None

    SAFE = ["nature", "landscape", "cityscape", "abstract", "technology", "scenery"]
    for check in [True, False]:
        res = _search(keyword, orientation, check)
        if not res and orientation != "": res = _search(keyword, "", check)
        if not res:
            fb = random.choice(SAFE)
            res = _search(fb, orientation, check)
            if not res and orientation != "": res = _search(fb, "", check)
        if res: return res
    return None


def search_pixabay_videos(keyword: str, orientation: str = "landscape", cfg: dict = None) -> list:
    cfg = cfg or {}
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
            res_list = [r2 for r2 in res_list if r2.get("url") and r2.get("width") and r2.get("height")]
            if not res_list: continue
            w2, h2 = res_list[0]["width"], res_list[0]["height"]
            is_landscape = w2 >= h2
            if orientation == "landscape" and not is_landscape: continue
            if orientation == "portrait" and is_landscape: continue
            res_list = sorted(res_list, key=lambda x: x.get("width", 0) * x.get("height", 0), reverse=True)
            best = res_list[0]
            results.append({
                "id": str(v["id"]),
                "url": best["url"],
                "image": f"https://i.vimeocdn.com/video/{v.get('picture_id')}_640x360.jpg",
                "duration": v.get("duration", 0)
            })
        return results
    except Exception as e:
        print(f"[Pixabay Search] Error: {e}")
        return []


def search_pixabay_photos_only(keyword: str, orientation: str = "landscape", cfg: dict = None) -> list:
    results = []
    cfg = cfg or {}
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


# ── Coverr ────────────────────────────────────────────────────────────────────
def _coverr_video_url(v: dict) -> Optional[str]:
    base = v.get("base_filename", "")
    if base:
        return f"https://cdn.coverr.co/videos/{base}/1080p.mp4"
    return None


def fetch_coverr(keyword: str, orientation: str = "landscape",
                  used_urls=None, cfg: dict = None) -> Optional[str]:
    cfg = cfg or {}
    if used_urls is None: used_urls = set()
    global_used = set(cfg.get("used_videos", []))

    def _save_url(link):
        if "used_videos" not in cfg: cfg["used_videos"] = []
        if link not in cfg["used_videos"]:
            cfg["used_videos"].append(link)
            if len(cfg["used_videos"]) > 1000:
                cfg["used_videos"].pop(0)

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
                if v.get("is_premium"): continue
                is_vert = v.get("is_vertical", False)
                if orientation == "landscape" and is_vert: continue
                if orientation == "portrait" and not is_vert: continue
                link = _coverr_video_url(v)
                if not link: continue
                if link in used_urls: continue
                if check_global and link in global_used: continue
                _save_url(link)
                print(f"[Coverr] ✅ {v.get('title','?')[:40]}")
                return link
        except Exception as e:
            print(f"[Coverr] {e}")
        return None

    SAFE = ["nature", "city", "abstract", "technology", "sky", "ocean"]
    for check in [True, False]:
        res = _search(keyword, check)
        if not res: res = _search(random.choice(SAFE), check)
        if res: return res
    return None


def search_coverr_videos(keyword: str, orientation: str = "landscape") -> list:
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


# ── Combined stock photo/video search ────────────────────────────────────────
def search_stock_photos(keyword: str, orientation: str = "landscape", cfg: dict = None) -> list:
    """Tìm kiếm ảnh stock để hiển thị lựa chọn trong UI editor."""
    cfg = cfg or {}
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
                            "id": str(p["id"]), "url": link, "image": preview or link,
                            "source": "pexels_photo", "already_used": link in global_used,
                            "photographer": p.get("photographer", ""),
                        })
        except Exception as e:
            print(f"[Pexels Photo Search] {e}")

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
                            "id": str(p["id"]), "url": link, "image": preview or link,
                            "source": "pixabay_photo", "already_used": link in global_used,
                            "photographer": p.get("user", ""),
                        })
        except Exception as e:
            print(f"[Pixabay Photo Search] {e}")

    results.sort(key=lambda x: x["already_used"])
    return results


def fetch_stock_photo(keyword: str, orientation: str = "landscape",
                       used_urls=None, cfg: dict = None):
    """Lấy ẢNH stock từ Pexels + Pixabay."""
    cfg = cfg or {}
    if used_urls is None: used_urls = set()
    global_used = set(cfg.get("used_videos", []))
    candidates = []

    pexels_key = (cfg.get("pexels") or [None])[0]
    if pexels_key:
        try:
            for kw in [keyword, random.choice(["nature", "city", "abstract", "technology", "sky"])]:
                o_param = "portrait" if orientation == "portrait" else "landscape"
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

    return chosen_url, chosen_preview


def fetch_stock_video(keyword: str, orientation: str = "landscape",
                       used_urls=None, cfg: dict = None) -> Optional[str]:
    """Lấy video từ TẤT CẢ providers, lọc theo relevance keyword."""
    cfg = cfg or {}
    if used_urls is None: used_urls = set()
    global_used = set(cfg.get("used_videos", []))

    keyword_candidates  = []
    fallback_candidates = []
    SAFE_FALLBACKS = ["nature scenery", "city street", "ocean waves", "mountain landscape", "forest path"]

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
                    w2, h2 = res_list[0]["width"], res_list[0]["height"]
                    is_ls = w2 >= h2
                    if orientation == "landscape" and not is_ls: continue
                    if orientation == "portrait" and is_ls: continue
                    res_list = sorted(res_list, key=lambda x: x.get("width",0)*x.get("height",0), reverse=True)
                    vid_title = v.get("tags", "").lower()
                    score = _keyword_relevance_score(vid_title, keyword)
                    keyword_candidates.append((res_list[0]["url"], "pixabay", vid_title, score))
        except Exception as e:
            print(f"[Pixabay pool] {e}")

    try:
        url_q = f"https://api.coverr.co/videos?query={requests.utils.quote(keyword)}&per_page=30"
        r = requests.get(url_q, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if r.ok:
            for v in r.json().get("hits", []):
                files = v.get("urls", {})
                link = files.get("mp4_url") or files.get("mobile_url") or v.get("mp4_url") or v.get("url")
                if not link: continue
                w2, h2 = v.get("width", 0), v.get("height", 0)
                is_ls = (w2 >= h2) if (w2 and h2) else True
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
                    if link: fallback_candidates.append((link, "coverr_fb", "", 0.0))
    except Exception as e:
        print(f"[Coverr pool] {e}")

    relevant   = [(u, s, t, sc) for u, s, t, sc in keyword_candidates if sc >= MIN_RELEVANCE]
    weak       = [(u, s, t, sc) for u, s, t, sc in keyword_candidates if sc < MIN_RELEVANCE]
    relevant.sort(key=lambda x: x[3], reverse=True)

    print(f"[Stock] keyword='{keyword}' → {len(relevant)} relevant, {len(weak)} weak, {len(fallback_candidates)} fallbacks")
    for u, s, t, sc in relevant[:3]:
        print(f"  [{s}] score={sc:.2f} title='{t[:50]}'")

    if relevant:
        all_candidates = [(u, s) for u, s, t, sc in relevant]
    elif weak:
        all_candidates = [(u, s) for u, s, t, sc in weak]
    else:
        all_candidates = [(u, s) for u, s, t, sc in fallback_candidates]

    if not all_candidates:
        return None

    random.shuffle(all_candidates)
    fresh   = [(u, s) for u, s in all_candidates if u not in global_used and u not in used_urls]
    session = [(u, s) for u, s in all_candidates if u not in used_urls]
    pool    = fresh or session or all_candidates

    chosen_url, chosen_src = random.choice(pool)
    print(f"[Stock] ✅ {chosen_src}: {chosen_url[:70]}...")

    if "used_videos" not in cfg: cfg["used_videos"] = []
    if chosen_url not in cfg["used_videos"]:
        cfg["used_videos"].append(chosen_url)
        if len(cfg["used_videos"]) > 1000:
            cfg["used_videos"].pop(0)

    return chosen_url


def search_stock_videos(keyword: str, orientation: str = "landscape", cfg: dict = None) -> list:
    """Tìm video và ảnh stock cho UI editor."""
    cfg = cfg or {}
    results = []
    if (cfg.get("pexels") or [None])[0]: results.extend(search_pexels_videos(keyword, orientation, cfg))
    if cfg.get("pixabay", ""): results.extend(search_pixabay_videos(keyword, orientation, cfg))
    results.extend(search_coverr_videos(keyword, orientation))

    global_used = set(cfg.get("used_videos", []))
    for item in results:
        item["already_used"] = item.get("url", "") in global_used

    random.shuffle(results)
    results.sort(key=lambda x: 1 if x.get("already_used") else 0)
    return results[:30]
