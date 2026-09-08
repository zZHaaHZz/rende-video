"""Korean text normalization for TTS pronunciation.

Dùng g2pk (Grapheme-to-Phoneme for Korean) để xử lý:
- Số → Hangul (백, 천, 만...)
- Ký tự đặc biệt (%, ₩, °C...)
- Liên âm / biến âm tự động (닭볶음탕 → 닥뽀끔탕)
- Từ viết tắt tiếng Anh thường gặp trong văn Hàn

Cài đặt: pip install g2pk
"""
from __future__ import annotations

import re

# ── Số có dấu phẩy ngàn → bỏ dấu phẩy trước khi g2pk xử lý ──────────────────
# g2pk xử lý đúng "1500원" nhưng sai "1,500원"
_COMMA_NUMBER = re.compile(r"(\d{1,3}(?:,\d{3})+)")

# ── Brand / từ nước ngoài hay bị đọc sai bởi giọng Hàn ───────────────────────
_KO_PHONETIC_TERMS = (
    # Platform — dùng lookahead để match trước ký tự Hangul (와, 에서, 가...)
    # \b không hoạt động trước ký tự Unicode Hangul
    (re.compile(r"TikTok(?=[\s가-힣,.!?]|$)",   re.IGNORECASE), "틱톡"),
    (re.compile(r"Facebook(?=[\s가-힣,.!?]|$)",  re.IGNORECASE), "페이스북"),
    (re.compile(r"Instagram(?=[\s가-힣,.!?]|$)", re.IGNORECASE), "인스타그램"),
    (re.compile(r"YouTube(?=[\s가-힣,.!?]|$)",   re.IGNORECASE), "유튜브"),
    (re.compile(r"Twitter(?=[\s가-힣,.!?]|$)",   re.IGNORECASE), "트위터"),
    (re.compile(r"ChatGPT(?=[\s가-힣,.!?]|$)",   re.IGNORECASE), "챗지피티"),
    (re.compile(r"OpenAI(?=[\s가-힣,.!?]|$)",    re.IGNORECASE), "오픈에이아이"),
    (re.compile(r"Gemini(?=[\s가-힣,.!?]|$)",    re.IGNORECASE), "제미나이"),
    (re.compile(r"Shopee(?=[\s가-힣,.!?]|$)",    re.IGNORECASE), "쇼피"),
    (re.compile(r"Netflix(?=[\s가-힣,.!?]|$)",   re.IGNORECASE), "넷플릭스"),

    # Từ viết tắt → đọc từng chữ cái tiếng Hàn
    # Phải match trước Hangul hoặc space
    (re.compile(r"\bAI(?=[\s가-힣,.!?]|$)"),     "에이아이"),
    (re.compile(r"\bGPT(?=[\s가-힣,.!?]|$)"),    "지피티"),
    (re.compile(r"\bIT(?=[\s가-힣,.!?]|$)"),     "아이티"),
    (re.compile(r"\bAPI(?=[\s가-힣,.!?]|$)"),    "에이피아이"),
    (re.compile(r"\bUI(?=[\s가-힣,.!?]|$)"),     "유아이"),
    (re.compile(r"\bUX(?=[\s가-힣,.!?]|$)"),     "유엑스"),
    (re.compile(r"\bKPI(?=[\s가-힣,.!?]|$)"),    "케이피아이"),
    (re.compile(r"\bROI(?=[\s가-힣,.!?]|$)"),    "알오아이"),
    (re.compile(r"\bCEO(?=[\s가-힣,.!?]|$)"),    "씨이오"),
    (re.compile(r"\bCTO(?=[\s가-힣,.!?]|$)"),    "씨티오"),
    (re.compile(r"\bSEO(?=[\s가-힣,.!?]|$)"),    "에스이오"),

    # Tiền tệ
    (re.compile(r"\$(\d+)"),                     lambda m: f"{m.group(1)}달러"),
)


# ── Lazy-load g2pk (nặng ~0.4s init) ─────────────────────────────────────────
_g2p_instance = None

def _get_g2p():
    global _g2p_instance
    if _g2p_instance is None:
        try:
            from g2pk import G2p
            _g2p_instance = G2p()
        except ImportError:
            _g2p_instance = False  # đánh dấu không có
    return _g2p_instance if _g2p_instance else None


def normalize_korean_tts(text: str, use_g2pk: bool = False) -> str:
    """Normalize Korean text cho TTS.

    Args:
        text: Văn bản tiếng Hàn gốc.
        use_g2pk: Dùng g2pk để chuyển liên âm/biến âm (mặc định False).
                  CapCut TTS đã có phoneme engine riêng cho tiếng Hàn,
                  nên chỉ cần normalize text (số, brand) mà không cần
                  convert sang phoneme — tránh xung đột với engine nội bộ.
                  Bật True nếu dùng TTS engine khác cần phoneme input.

    Returns:
        Văn bản đã normalize, sẵn sàng gửi TTS.
    """
    normalized = text

    # 1. Bỏ dấu phẩy ngàn trong số (1,500 → 1500) để TTS đọc đúng
    normalized = _COMMA_NUMBER.sub(
        lambda m: m.group(0).replace(",", ""), normalized
    )

    # 2. Thay brand name / từ viết tắt tiếng Anh → Hangul
    for pattern, replacement in _KO_PHONETIC_TERMS:
        normalized = pattern.sub(replacement, normalized)

    # 3. (Tùy chọn) g2pk: xử lý liên âm, biến âm cho engine không tự xử lý
    if use_g2pk:
        g2p = _get_g2p()
        if g2p:
            normalized = g2p(normalized)

    return normalized.strip()


if __name__ == "__main__":
    # Quick test
    tests = [
        "안녕하세요, 오늘 영상 시작하겠습니다",
        "AI 기술이 빠르게 발전하고 있습니다",
        "1,500원짜리 커피 한 잔",
        "YouTube와 TikTok에서 인기 있는 콘텐츠",
        "CEO가 ChatGPT를 활용해 KPI를 개선했습니다",
        "닭볶음탕 한 그릇에 12,000원",
        "20% 할인된 가격으로 구매하세요",
    ]
    for t in tests:
        out = normalize_korean_tts(t)
        print(f"IN : {t}")
        print(f"OUT: {out}")
        print()
