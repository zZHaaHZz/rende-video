"""
app/subtitle.py — SRT / ASS subtitle generation.
Không phụ thuộc Streamlit — pure Python.
"""
import re


# ── SRT ───────────────────────────────────────────────────────────────────────
def make_srt(words: list, group: int = 4) -> str:
    """Group words into SRT subtitle blocks.
    Uses semantic chunking: prefer to break at punctuation before breaking mid-phrase.
    """
    if not words:
        return ""

    PUNCT_PATTERN = re.compile(r'[,\.!\?;:\-—–]$')

    def _has_punct(word_entry):
        return bool(PUNCT_PATTERN.search(word_entry["word"].strip()))

    chunks, cur_chunk = [], []
    for w in words:
        cur_chunk.append(w)
        if len(cur_chunk) >= group and _has_punct(w):
            chunks.append(cur_chunk)
            cur_chunk = []
        elif len(cur_chunk) >= group * 2:
            chunks.append(cur_chunk)
            cur_chunk = []
    if cur_chunk:
        chunks.append(cur_chunk)

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


def srt_to_words(srt_path: str) -> list:
    """Parse an SRT file → list of {word, start, end} dicts."""
    words = []
    try:
        from pathlib import Path
        text = Path(srt_path).read_text(encoding="utf-8")
        for block in text.strip().split("\n\n"):
            lines = block.strip().split("\n")
            if len(lines) >= 3:
                ts = lines[1].replace(",", ".")
                start_s, end_s = ts.split(" --> ")
                def _p(t):
                    h, m, s = t.strip().split(":")
                    return int(h)*3600 + int(m)*60 + float(s)
                phrase = " ".join(lines[2:]).strip()
                words.append({"word": phrase, "start": _p(start_s), "end": _p(end_s)})
    except Exception as e:
        print(f"[srt_to_words] {e}")
    return words


# ── ASS subtitle style presets ────────────────────────────────────────────────
SUB_STYLES = {
    # ── KIỂU VIRAL CỔ ĐIỂN ─────────────────────────────────────────────────
    "🟡 TikTok Yellow (Viral)":   {"highlight": "&H0000FFFF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 2, "border_style": 1, "outline_w": 2, "spacing": 0},
    "🔥 Fire Orange":              {"highlight": "&H000055FF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 2, "border_style": 1, "outline_w": 2, "spacing": 0},
    "💚 Neon Green":               {"highlight": "&H0000FF66", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 2, "border_style": 1, "outline_w": 2, "spacing": 0},
    "💙 Electric Blue":            {"highlight": "&H00FF8800", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 2, "border_style": 1, "outline_w": 2, "spacing": 0},
    "🩷 Hot Pink":                 {"highlight": "&H006633FF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 2, "border_style": 1, "outline_w": 2, "spacing": 0},
    "⚪ Classic White (Không màu)": {"highlight": "&H00FFFFFF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 1, "border_style": 1, "outline_w": 2, "spacing": 0},
    # ── STYLE MỚI — VIRAL 2025 ──────────────────────────────────────────────
    "🎬 MrBeast 3D":              {"highlight": "&H0000FFFF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 4, "border_style": 1, "outline_w": 5, "spacing": 1},
    "📦 Reels Box (Nền đen mờ)":  {"highlight": "&H0000FFFF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&HA0000000", "bold": -1, "shadow": 0, "border_style": 3, "outline_w": 0, "spacing": 2},
    "🎭 Korean Drama":             {"highlight": "&H000000FF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&HC0000000", "bold": -1, "shadow": 0, "border_style": 3, "outline_w": 0, "spacing": 1},
}


def make_ass(words: list, W: int = 1920, H: int = 1080, window: int = 4,
             offset_s: float = 0.0, style_name: str = "🟡 TikTok Yellow (Viral)") -> str:
    """ASS karaoke subtitle — highlight TỪNG TỪ khi đang nói."""
    if not words:
        return ""

    fs    = 58 if W == 1080 else 34
    margv = 512 if W == 1080 else 120

    st_cfg = SUB_STYLES.get(style_name, SUB_STYLES["🟡 TikTok Yellow (Viral)"])
    highlight_color = st_cfg["highlight"]
    base_color      = st_cfg["base"]
    outline_color   = st_cfg["outline"]
    back_color      = st_cfg["back"]
    bold            = st_cfg["bold"]
    shadow          = st_cfg["shadow"]
    border_style    = st_cfg.get("border_style", 1)
    outline_w       = st_cfg.get("outline_w", 2)
    spacing         = st_cfg.get("spacing", 0)

    # ── Tách từng phrase thành danh sách từ đơn lẻ với timestamp ────────────
    flat_words = []
    for entry in words:
        phrase = entry["word"].strip()
        t_start = entry["start"]
        t_end   = entry["end"]
        tokens = phrase.split()
        if not tokens:
            continue
        dur = (t_end - t_start) / len(tokens)
        for k, tok in enumerate(tokens):
            flat_words.append({
                "word":  tok,
                "start": t_start + k * dur,
                "end":   t_start + (k + 1) * dur,
            })

    if not flat_words:
        return ""

    has_ko = any(any(0xAC00 <= ord(c) <= 0xD7A3 or 0x1100 <= ord(c) <= 0x11FF for c in w["word"]) for w in flat_words)
    font_name = "Apple SD Gothic Neo" if has_ko else "Arial"

    header = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{fs},{base_color},&H000000FF,{outline_color},{back_color},"
        f"{bold},0,0,0,100,100,{spacing},0,{border_style},{outline_w},{shadow},2,30,30,{margv},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    def _t(s):
        s = max(0.0, s + offset_s)
        h = int(s // 3600); m = int((s % 3600) // 60); sec = s % 60
        return f"{h}:{m:02d}:{sec:05.2f}"

    WINDOW = 4
    dlg = []

    _STAT_PATTERN = re.compile(
        r'^[\d,\.]+(%|K|M|B|억|만|triệu|tỷ|ngàn|nghin|lần|x|배|倍|\.)?$',
        re.IGNORECASE
    )
    STAT_COLOR   = "&H002222FF"
    STAT_FS_BUMP = 14

    def _is_stat_word(tok: str) -> bool:
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
                    if is_stat:
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
