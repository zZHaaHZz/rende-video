"""Vietnamese text normalization for stable, natural TTS pronunciation."""
from __future__ import annotations

import re


_DIGITS = ("không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín")

_PHONETIC_TERMS = (
    (re.compile(r"\bTikTok\s+Shop\b", re.IGNORECASE), "tíc tốc shop"),
    (re.compile(r"\bTikTok\b", re.IGNORECASE), "tíc tốc"),
    (re.compile(r"\bAffiliate\b", re.IGNORECASE), "a phi li ét"),
    (re.compile(r"\bFacebook\b", re.IGNORECASE), "phây búc"),
    (re.compile(r"\bYouTube\b", re.IGNORECASE), "diu túp"),
    (re.compile(r"\bAI\b", re.IGNORECASE), "ây ai"),
    (re.compile(r"\bKPI\b", re.IGNORECASE), "cây pi ai"),
    (re.compile(r"\bROI\b", re.IGNORECASE), "a roi"),
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


def normalize_vietnamese_tts(text: str) -> str:
    """Expand common symbols, numbers and English product terms before synthesis."""
    normalized = text
    for pattern, replacement in _PHONETIC_TERMS:
        normalized = pattern.sub(replacement, normalized)

    normalized = re.sub(
        r"(?<![\w])(-?\d+)\s*%",
        lambda match: f"{number_to_vietnamese(int(match.group(1)))} phần trăm",
        normalized,
    )
    normalized = re.sub(
        r"(?<![\w])(-?\d+)(?![\w])",
        lambda match: number_to_vietnamese(int(match.group(1))),
        normalized,
    )
    normalized = re.sub(r"\s+([,.;:!?])", r"\1", normalized)
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    return normalized.strip()
