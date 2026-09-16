"""Vietnamese text normalization for stable, natural TTS pronunciation."""
from __future__ import annotations

import re


_DIGITS = ("không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín")

# Giọng multilingual (uranus_bigtts, richgirl...) đọc sai MỘT SỐ từ tiếng Việt
# chủ yếu khi "đ" đứng đầu từ ngắn — model nhầm thành âm "ch".
# CHỈ fix từng từ đã xác nhận bị lỗi, KHÔNG thay toàn bộ đ→d vì sẽ tạo lỗi mới.
# Cách viết thay thế: dùng ký tự mà model đọc gần đúng nhất về mặt ngữ âm.
# Để thêm từ mới: test thực tế với giọng đó rồi tìm cách viết model đọc đúng.
_MULTILINGUAL_VI_FIXES: list[tuple] = [
    # "đây" → model đọc "chây" → thay bằng "đ'ây" dùng apostrophe để tách âm
    # Hoặc thay "day" vì model đọc gần giống "đây" hơn "chây"
    (re.compile(r"(?<!\w)đây(?!\w)",  re.UNICODE), "day"),
    (re.compile(r"(?<!\w)Đây(?!\w)",  re.UNICODE), "Day"),
    # Thêm vào đây các từ bị lỗi khác khi phát hiện:
    # (re.compile(r"(?<!\w)đó(?!\w)",   re.UNICODE), "do"),
    # (re.compile(r"(?<!\w)đến(?!\w)",  re.UNICODE), "dến"),
]


# Giọng multilingual cần apply thêm fix cho chữ "đ"
_MULTILINGUAL_VOICE_PATTERNS = (
    "uranus_bigtts", "richgirl", "multi_female", "multi_male",
)


_PHONETIC_TERMS = (
    # ════════════════════════════════════════════════════════════════
    # PLATFORM & MẠNG XÃ HỘI
    # ════════════════════════════════════════════════════════════════
    (re.compile(r"\bTikTok\s+Shop\b",   re.IGNORECASE), "tíc tốc shop"),
    (re.compile(r"\bTikTok\b",          re.IGNORECASE), "tíc tốc"),
    (re.compile(r"\bFacebook\b",        re.IGNORECASE), "phây búc"),
    (re.compile(r"\bInstagram\b",       re.IGNORECASE), "in sờ ta gram"),
    (re.compile(r"\bYouTube\s+Shorts\b",re.IGNORECASE), "diu túp shót"),
    (re.compile(r"\bYouTube\b",         re.IGNORECASE), "diu túp"),
    (re.compile(r"\bTwitter\b",         re.IGNORECASE), "tuy tờ"),
    (re.compile(r"\bSnapchat\b",        re.IGNORECASE), "snép chét"),
    (re.compile(r"\bPinterest\b",       re.IGNORECASE), "pin tơ rét"),
    (re.compile(r"\bLinkedIn\b",        re.IGNORECASE), "linh cờ đin"),
    (re.compile(r"\bZalo\b",            re.IGNORECASE), "za lô"),
    (re.compile(r"\bShopee\b",          re.IGNORECASE), "shop pi"),
    (re.compile(r"\bLazada\b",          re.IGNORECASE), "la za đa"),
    (re.compile(r"\bTemu\b",            re.IGNORECASE), "ti mu"),
    (re.compile(r"\bGrab\b",            re.IGNORECASE), "gờ ráp"),
    (re.compile(r"\bBeing\b",           re.IGNORECASE), "bi ing"),

    # ════════════════════════════════════════════════════════════════
    # CÔNG NGHỆ & AI
    # ════════════════════════════════════════════════════════════════
    (re.compile(r"\bChatGPT\b",         re.IGNORECASE), "trò chuyện ây pê tê"),
    (re.compile(r"\bGemini\b",          re.IGNORECASE), "dê mi ni"),
    (re.compile(r"\bClaude\b",          re.IGNORECASE), "clôd"),
    (re.compile(r"\bOpenAI\b",          re.IGNORECASE), "ô pờ n ây ai"),
    # AI/GPT/LLM/... — phương âm được xử lý trong section CHỮ VIẾT TẮT bên dưới
    (re.compile(r"\bSaaS\b"),           "phần mềm dịch vụ"),
    (re.compile(r"\bIoT\b"),            "internet vạn vật"),
    (re.compile(r"\bURL\b"),            "đường dẫn"),
    (re.compile(r"\bWi-Fi\b",           re.IGNORECASE), "wai fai"),
    (re.compile(r"\bWiFi\b",            re.IGNORECASE), "wai fai"),
    (re.compile(r"\bBluetooth\b",       re.IGNORECASE), "bluu túp"),
    (re.compile(r"\bApp\b"),            "áp"),   # chỉ HOA đầu để tránh "app" trong tên
    (re.compile(r"\bOnline\b",          re.IGNORECASE), "ôn lai"),
    (re.compile(r"\bOffline\b",         re.IGNORECASE), "ốp lai"),
    (re.compile(r"\bUpload\b",          re.IGNORECASE), "áp lôt"),
    (re.compile(r"\bDownload\b",        re.IGNORECASE), "đao lôt"),
    (re.compile(r"\bWebsite\b",         re.IGNORECASE), "wép sai"),
    (re.compile(r"\bStreaming\b",       re.IGNORECASE), "strìm minh"),

    # ════════════════════════════════════════════════════════════════
    # BUSINESS & MARKETING
    # ════════════════════════════════════════════════════════════════
    (re.compile(r"\bAffiliate\b",       re.IGNORECASE), "a phi li ét"),
    (re.compile(r"\bMarketing\b",       re.IGNORECASE), "ma kê tinh"),
    (re.compile(r"\bBrand\b",           re.IGNORECASE), "bran"),
    (re.compile(r"\bStartup\b",         re.IGNORECASE), "stát áp"),
    (re.compile(r"\bVoucher\b",         re.IGNORECASE), "vau chờ"),
    (re.compile(r"\bDiscount\b",        re.IGNORECASE), "đi cao"),
    (re.compile(r"\bFeedback\b",        re.IGNORECASE), "phít béc"),
    (re.compile(r"\bContent\b",         re.IGNORECASE), "cốn ten"),
    (re.compile(r"\bReview\b",          re.IGNORECASE), "ri viu"),
    (re.compile(r"\bTrend\b",           re.IGNORECASE), "tren"),
    (re.compile(r"\bViral\b",           re.IGNORECASE), "vai rồ"),
    (re.compile(r"\bLivestream\b",      re.IGNORECASE), "lai strìm"),
    (re.compile(r"\bLive\b"),           "lai"),   # chỉ HOA đầu để không ảnh hưởng từ Việt
    (re.compile(r"\bHashtag\b",         re.IGNORECASE), "hét tắc"),
    (re.compile(r"\bReels?\b",          re.IGNORECASE), "ri ơn"),
    (re.compile(r"\bShorts?\b"),        "shót"),
    (re.compile(r"\bFollow\b",          re.IGNORECASE), "phô lô"),
    (re.compile(r"\bFollower\b",        re.IGNORECASE), "phô lô ờ"),
    (re.compile(r"\bSubscribe\b",       re.IGNORECASE), "sắp bờ rai bờ"),
    (re.compile(r"\bComment\b",         re.IGNORECASE), "cơm men"),
    (re.compile(r"\bShare\b"),          "shêr"),
    (re.compile(r"\bClick\b",           re.IGNORECASE), "cờ lic"),
    (re.compile(r"\bLink\b"),           "líc"),
    (re.compile(r"\bOK\b"),             "ô kê"),
    (re.compile(r"\bOkay\b",            re.IGNORECASE), "ô kê"),
    (re.compile(r"\bPremium\b",         re.IGNORECASE), "pri mi ơm"),
    (re.compile(r"\bFreeship\b",        re.IGNORECASE), "phri ship"),

    # ════════════════════════════════════════════════════════════════
    # CHỮ VIẾT TẮT — phiên âm thẳng để donglao-g2p không re-process
    # ════════════════════════════════════════════════════════════════
    (re.compile(r"\bAI\b"),             "ây ai"),
    (re.compile(r"\bKPI\b"),            "kê pê i"),
    (re.compile(r"\bROI\b"),            "a roi"),
    (re.compile(r"\bSEO\b"),            "sê ê ô"),
    (re.compile(r"\bCEO\b"),            "xê ê ô"),
    (re.compile(r"\bCOO\b"),            "xê ô ô"),
    (re.compile(r"\bCMO\b"),            "xê em ô"),
    (re.compile(r"\bCTO\b"),            "xê tê ô"),
    (re.compile(r"\bCFO\b"),            "xê ép ô"),
    (re.compile(r"\bGPT\b"),            "gê pê tê"),
    (re.compile(r"\bLLM\b"),            "en en em"),
    (re.compile(r"\bAPI\b"),            "ây pê i"),
    (re.compile(r"\bUI\b"),             "diu ai"),
    (re.compile(r"\bUX\b"),             "diu ét"),
    (re.compile(r"\bIT\b"),             "ai ti"),
    (re.compile(r"\bHR\b"),             "hét a"),
    (re.compile(r"\bPR\b"),             "pê a"),
    (re.compile(r"\bB2B\b"),            "bi tu bi"),
    (re.compile(r"\bB2C\b"),            "bi tu xi"),
    (re.compile(r"\bP&L\b"),            "P và L"),

    # ════════════════════════════════════════════════════════════════
    # TIỀN TỆ & ĐƠN VỊ — chạy trước donglao-g2p
    # ════════════════════════════════════════════════════════════════
    (re.compile(r"\bUSD\b"),            "đô la Mỹ"),
    (re.compile(r"\bVND\b"),            "đồng"),
    (re.compile(r"\bBTC\b"),            "Bitcoin"),
    (re.compile(r"\bETH\b"),            "Ethereum"),
    # Số kèm K/M/B → expand trước vì donglao-g2p không hiểu unit này
    (re.compile(r"(\d+)\s*K\b", re.IGNORECASE), lambda m: f"{m.group(1)} nghìn"),
    (re.compile(r"(\d+)\s*M\b", re.IGNORECASE), lambda m: f"{m.group(1)} triệu"),
    (re.compile(r"(\d+)\s*B\b", re.IGNORECASE), lambda m: f"{m.group(1)} tỷ"),
)


def _under_hundred(value: int, *, full: bool = False) -> str:
    tens, unit = divmod(value, 10)
    if tens == 0:
        return (f"lẻ {_DIGITS[unit]}" if full and unit else _DIGITS[unit]).strip()
    if tens == 1:
        prefix = "mười"
    else:
        prefix = f"{_DIGITS[tens]} mươi"
    if unit == 0:
        return prefix
    if unit == 1 and tens > 1:
        suffix = "mốt"
    elif unit == 5:
        suffix = "lăm"
    else:
        suffix = _DIGITS[unit]
    return f"{prefix} {suffix}"


def _under_thousand(value: int, *, full: bool = False) -> str:
    hundreds, rest = divmod(value, 100)
    parts: list[str] = []
    if hundreds:
        parts.append(f"{_DIGITS[hundreds]} trăm")
    elif full and rest:
        parts.append("không trăm")
    if rest:
        parts.append(_under_hundred(rest, full=bool(hundreds)))
    return " ".join(parts) if parts else "không"


def number_to_vietnamese(value: int) -> str:
    """Read a non-negative integer using common Vietnamese speech rules."""
    if value == 0:
        return "không"
    if value < 0:
        return f"âm {number_to_vietnamese(-value)}"

    scales = ("", "nghìn", "triệu", "tỷ")
    groups: list[int] = []
    while value:
        groups.append(value % 1000)
        value //= 1000

    words: list[str] = []
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if not group:
            continue
        full = bool(words) and group < 100
        words.append(_under_thousand(group, full=full))
        if index:
            words.append(scales[index])
    return " ".join(words)


def normalize_vietnamese_tts(text: str, voice_key: str = "") -> str:
    """Expand common symbols, numbers and English product terms before synthesis.
    voice_key: key từ CAPCUT_VOICES — nếu là giọng multilingual sẽ apply
               thêm fix phát âm chữ 'đ' và các âm Việt đặc thù.
    """
    normalized = text

    # 1. Brand name / từ viết tắt tiếng Anh (phải chạy TRƯỚC donglao-g2p
    #    để tránh bị g2p convert sai trước khi kịp fix)
    for pattern, replacement in _PHONETIC_TERMS:
        normalized = pattern.sub(replacement, normalized)

    # 2. Fix phát âm cho giọng multilingual (đọc sai chữ 'đ' → 'ch')
    _voice_type = voice_key
    try:
        from capcut_tts import CAPCUT_VOICES as _CV
        if voice_key in _CV:
            _voice_type = _CV[voice_key][0]
    except Exception:
        pass
    _is_multilingual = any(p in _voice_type for p in _MULTILINGUAL_VOICE_PATTERNS)
    if _is_multilingual:
        for pattern, replacement in _MULTILINGUAL_VI_FIXES:
            normalized = pattern.sub(replacement, normalized)

    # 3. Số, %, đơn vị → donglao-g2p (nhanh, chính xác, pure Python)
    #    Fallback về code thủ công nếu thư viện chưa cài.
    try:
        import donglao_g2p as _dg
        normalized = _dg.normalize(normalized)
    except ImportError:
        # Fallback thủ công
        normalized = re.sub(
            r"(?<![\w])(-?\d+)\s*%",
            lambda m: f"{number_to_vietnamese(int(m.group(1)))} phần trăm",
            normalized,
        )
        normalized = re.sub(
            r"(?<![\w])(-?\d+)(?![\w])",
            lambda m: number_to_vietnamese(int(m.group(1))),
            normalized,
        )

    normalized = re.sub(r"\s+([,.;:!?])", r"\1", normalized)
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    return normalized.strip()
