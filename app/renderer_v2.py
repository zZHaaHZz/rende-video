"""
app/renderer_v2.py — 2-Layer Video Slide Renderer v2

Kiến trúc tách biệt hoàn toàn:
  Layer 1 (VIDEO): video-only clips → xfade transitions → video_track.mp4 (câm)
  Layer 2 (AUDIO): concat TTS audio liên tục → audio_track.aac
  Layer 2 (SUB):   ASS với timestamp tuyệt đối trên toàn timeline

Final merge: ffmpeg -i video_track.mp4 -i audio_track.aac -vf "ass=sub.ass" output.mp4

Không import bất kỳ thứ gì từ v1 renderer.
"""
from __future__ import annotations

import math
import random
import re as _re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

# ── Public types ──────────────────────────────────────────────────────────────


@dataclass
class SceneV2:
    """Đầu vào chuẩn cho mỗi cảnh trong renderer v2."""

    text: str = ""
    """Lời thoại / narration — dùng để build subtitle."""

    audio_path: str = ""
    """Đường dẫn file audio TTS đã render sẵn (.mp3/.wav/.m4a).
    Nếu rỗng, renderer sẽ tạo silence tương ứng duration."""

    video_url: str = ""
    """URL hoặc path video nền (stock hoặc local). Ưu tiên cao nhất."""

    image_url: str = ""
    """URL hoặc path ảnh nền (fallback khi không có video)."""

    veo3_path: str = ""
    """Path local file MP4 từ Veo3 generation."""

    custom_vid: str = ""
    """Path local video do user upload thủ công."""

    custom_img: str = ""
    """Path local image do user upload thủ công."""

    keyword: str = ""
    """Keyword để fetch stock nếu không có visual nào."""

    duration: float = 0.0
    """Duration dự kiến (giây). Nếu 0, lấy từ audio_path."""

    words: List[dict] = field(default_factory=list)
    """[{word, start, end}] — timing tương đối từ đầu cảnh (giây).
    Dùng để build ASS karaoke chính xác."""

    effect: Optional[str] = None
    """Ken Burns effect override. None = random."""

    transition: str = "fade"
    """xfade transition sang cảnh tiếp theo."""

    sub_style: str = "🟡 TikTok Yellow (Viral)"
    """ASS subtitle style key."""


@dataclass
class RendererV2Options:
    """Tuỳ chọn render cho toàn video."""

    width: int = 1920
    height: int = 1080
    fps: int = 30
    xfade_dur: float = 0.5
    """Thời gian overlap xfade (giây). Tự động giảm nếu cảnh quá ngắn."""

    crf: int = 20
    preset: str = "fast"
    audio_bitrate: str = "192k"

    burn_subtitles: bool = True
    sub_style: str = "🟡 TikTok Yellow (Viral)"
    sub_window: int = 4              # số từ hiển thị cùng lúc trong ASS

    bgm_path: str = ""               # nhạc nền (optional)
    bgm_volume: float = 0.12         # 0.0–1.0
    voice_volume: float = 1.0

    ffmpeg_bin: str = "ffmpeg"
    work_dir: Optional[Path] = None  # None = tự tạo tmpdir

    log_cb: Optional[Callable[[str], None]] = None


# ── Subtitle style presets (độc lập, không import từ subtitle.py) ─────────────

_SUB_STYLES: dict = {
    "🟡 TikTok Yellow (Viral)":    {"highlight": "&H0000FFFF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 2, "border_style": 1, "outline_w": 2, "spacing": 0},
    "🔥 Fire Orange":              {"highlight": "&H000055FF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 2, "border_style": 1, "outline_w": 2, "spacing": 0},
    "💚 Neon Green":               {"highlight": "&H0000FF66", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 2, "border_style": 1, "outline_w": 2, "spacing": 0},
    "💙 Electric Blue":            {"highlight": "&H00FF8800", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 2, "border_style": 1, "outline_w": 2, "spacing": 0},
    "🩷 Hot Pink":                 {"highlight": "&H006633FF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 2, "border_style": 1, "outline_w": 2, "spacing": 0},
    "⚪ Classic White (Không màu)": {"highlight": "&H00FFFFFF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 1, "border_style": 1, "outline_w": 2, "spacing": 0},
    "🎬 MrBeast 3D":              {"highlight": "&H0000FFFF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&H00000000", "bold": -1, "shadow": 4, "border_style": 1, "outline_w": 5, "spacing": 1},
    "📦 Reels Box (Nền đen mờ)":  {"highlight": "&H0000FFFF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&HA0000000", "bold": -1, "shadow": 0, "border_style": 3, "outline_w": 0, "spacing": 2},
    "🎭 Korean Drama":             {"highlight": "&H000000FF", "base": "&H00FFFFFF", "outline": "&H00000000", "back": "&HC0000000", "bold": -1, "shadow": 0, "border_style": 3, "outline_w": 0, "spacing": 1},
}

_STAT_PATTERN = _re.compile(
    r'^[\d,\.]+(%|K|M|B|억|만|triệu|tỷ|ngàn|lần|x|배|倍|\.)?$',
    _re.IGNORECASE,
)

IMAGE_EFFECTS_V2 = ["zoom_in", "zoom_out", "pan_right", "pan_left", "pan_up", "pan_down"]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _log(opts: RendererV2Options, msg: str):
    if callable(opts.log_cb):
        opts.log_cb(msg)
    else:
        print(msg)


def _ffmpeg(opts: RendererV2Options, *args):
    cmd = [opts.ffmpeg_bin, "-y", "-loglevel", "error"] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg:\n{r.stderr[:600]}")


def _probe_dur(path: Path, ffmpeg_bin: str = "ffmpeg") -> float:
    ffprobe = str(Path(ffmpeg_bin).parent / "ffprobe")
    if not Path(ffprobe).exists():
        ffprobe = shutil.which("ffprobe") or "ffprobe"
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        val = float(r.stdout.strip())
        return val if val > 0 else 0.0
    except Exception:
        return 0.0


def _download(url: str, dest: Path):
    if url.startswith("/") or (len(url) > 1 and url[1] == ":"):
        shutil.copy2(url, dest)
        return
    import requests as _req
    r = _req.get(url, timeout=60, stream=True, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(65536):
            if chunk:
                f.write(chunk)


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _is_stat_word(tok: str) -> bool:
    t = tok.strip().upper()
    return bool(_STAT_PATTERN.match(t)) and any(c.isdigit() for c in t)


def _t_ass(s: float) -> str:
    """Giây → ASS timestamp h:mm:ss.cc"""
    s = max(0.0, s)
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h}:{m:02d}:{sec:05.2f}"


def _ken_burns_filter(W: int, H: int, d_frames: int, effect: str) -> str:
    base = (
        f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
        f"crop={W*2}:{H*2}"
    )
    if effect == "zoom_in":
        zp = f"zoompan=z='1+0.2*(on/{d_frames})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={d_frames}:fps=30:s={W*2}x{H*2}"
    elif effect == "zoom_out":
        zp = f"zoompan=z='1.2-0.2*(on/{d_frames})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={d_frames}:fps=30:s={W*2}x{H*2}"
    elif effect == "pan_right":
        zp = f"zoompan=z='1.1':x='(iw-iw/zoom)*(on/{d_frames})':y='ih/2-(ih/zoom/2)':d={d_frames}:fps=30:s={W*2}x{H*2}"
    elif effect == "pan_left":
        zp = f"zoompan=z='1.1':x='(iw-iw/zoom)*(1-on/{d_frames})':y='ih/2-(ih/zoom/2)':d={d_frames}:fps=30:s={W*2}x{H*2}"
    elif effect == "pan_up":
        zp = f"zoompan=z='1.1':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*(1-on/{d_frames})':d={d_frames}:fps=30:s={W*2}x{H*2}"
    else:  # pan_down
        zp = f"zoompan=z='1.1':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*(on/{d_frames})':d={d_frames}:fps=30:s={W*2}x{H*2}"
    return f"{base},{zp},scale={W}:{H},fps=30"


# ── Step 1: Render mỗi cảnh thành video-only clip (câm) ─────────────────────

def _render_scene_silent(
    scene: SceneV2,
    idx: int,
    clip_dur: float,
    opts: RendererV2Options,
    work_dir: Path,
) -> Path:
    """Render 1 scene → video-only MP4 (không audio)."""
    W, H = opts.width, opts.height
    out = work_dir / f"vid_{idx:04d}.mp4"

    def _black():
        _ffmpeg(opts,
            "-f", "lavfi", "-i", f"color=black:s={W}x{H}:r={opts.fps}",
            "-t", str(clip_dur),
            "-c:v", "libx264", "-preset", opts.preset, "-crf", str(opts.crf),
            "-pix_fmt", "yuv420p", "-an", str(out),
        )
        return out

    # Chọn visual source (thứ tự ưu tiên)
    visual_src = (
        scene.veo3_path or scene.custom_vid or scene.custom_img
        or scene.video_url or scene.image_url or ""
    )

    if not visual_src:
        _log(opts, f"  ⚠️ Scene {idx+1}: không có visual → background đen")
        return _black()

    # Resolve path local
    if visual_src.startswith("http"):
        ext = Path(visual_src.split("?")[0]).suffix or ".mp4"
        local = work_dir / f"src_{idx:04d}{ext}"
        try:
            _download(visual_src, local)
        except Exception as e:
            _log(opts, f"  ⚠️ Scene {idx+1}: download lỗi ({e}) → background đen")
            return _black()
    else:
        local = Path(visual_src)
        if not local.exists():
            _log(opts, f"  ⚠️ Scene {idx+1}: file không tồn tại ({local}) → background đen")
            return _black()

    scale_vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},fps={opts.fps}"
    )

    # ── Ảnh tĩnh → Ken Burns ──────────────────────────────────────────────
    if _is_image(local):
        effect = scene.effect or random.choice(IMAGE_EFFECTS_V2)
        d_frames = math.ceil(clip_dur * 30) + 15
        vf = _ken_burns_filter(W, H, d_frames, effect)
        try:
            _ffmpeg(opts,
                "-loop", "1", "-i", str(local),
                "-t", str(clip_dur),
                "-vf", vf,
                "-c:v", "libx264", "-preset", opts.preset, "-crf", str(opts.crf),
                "-pix_fmt", "yuv420p", "-r", str(opts.fps), "-an",
                str(out),
            )
        except Exception as e:
            _log(opts, f"  ⚠️ Ken Burns fail ({e}) → scale thường")
            try:
                _ffmpeg(opts,
                    "-loop", "1", "-i", str(local),
                    "-t", str(clip_dur),
                    "-vf", scale_vf,
                    "-c:v", "libx264", "-preset", opts.preset, "-crf", str(opts.crf),
                    "-pix_fmt", "yuv420p", "-an", str(out),
                )
            except Exception:
                return _black()
        return out

    # ── Video nền → cắt / loop ───────────────────────────────────────────
    if _is_video(local):
        src_dur = _probe_dur(local, opts.ffmpeg_bin)
        try:
            if src_dur >= clip_dur:
                _ffmpeg(opts,
                    "-i", str(local),
                    "-t", str(clip_dur),
                    "-vf", scale_vf,
                    "-c:v", "libx264", "-preset", opts.preset, "-crf", str(opts.crf),
                    "-pix_fmt", "yuv420p", "-an", str(out),
                )
            else:
                loops = math.ceil(clip_dur / max(src_dur, 0.1)) + 1
                _ffmpeg(opts,
                    "-stream_loop", str(loops), "-i", str(local),
                    "-t", str(clip_dur),
                    "-vf", scale_vf,
                    "-c:v", "libx264", "-preset", opts.preset, "-crf", str(opts.crf),
                    "-pix_fmt", "yuv420p", "-an", str(out),
                )
        except Exception as e:
            _log(opts, f"  ⚠️ Video render fail ({e}) → background đen")
            return _black()
        return out

    _log(opts, f"  ⚠️ Scene {idx+1}: không nhận dạng được file type → background đen")
    return _black()


# ── Step 2: xfade-concat video clips (không có audio) ───────────────────────

def _build_video_track(
    clips: List[Path],
    clip_durs: List[float],
    transitions: List[str],
    xfade_dur: float,
    opts: RendererV2Options,
    work_dir: Path,
) -> Path:
    """Nối clips câm với xfade → video_track.mp4 (câm)."""
    out = work_dir / "video_track.mp4"
    n = len(clips)

    if n == 1:
        shutil.copy2(clips[0], out)
        return out

    inputs = []
    for c in clips:
        inputs.extend(["-i", str(c)])

    fparts = [f"[{j}:v]copy[v{j}]" for j in range(n)]

    offset = clip_durs[0] - xfade_dur
    cur = "[v0]"
    for j in range(1, n):
        nxt = f"[xv{j}]" if j < n - 1 else "[vout]"
        tr = transitions[j - 1] if (j - 1) < len(transitions) else "fade"
        fparts.append(
            f"{cur}[v{j}]xfade=transition={tr}"
            f":duration={xfade_dur:.3f}:offset={max(0.0, offset):.3f}{nxt}"
        )
        cur = nxt
        if j < n - 1:
            offset += clip_durs[j] - xfade_dur

    _ffmpeg(opts,
        *inputs,
        "-filter_complex", ";".join(fparts),
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", opts.preset, "-crf", str(opts.crf),
        "-pix_fmt", "yuv420p", "-an",
        str(out),
    )
    return out


def _concat_fallback(
    clips: List[Path],
    opts: RendererV2Options,
    work_dir: Path,
) -> Path:
    """Concat thô (không transition) dùng làm fallback."""
    out = work_dir / "video_track.mp4"
    lst = work_dir / "concat_list.txt"
    lst.write_text("\n".join(f"file '{c.as_posix()}'" for c in clips))
    _ffmpeg(opts,
        "-f", "concat", "-safe", "0", "-i", str(lst),
        "-c:v", "libx264", "-preset", opts.preset, "-crf", str(opts.crf),
        "-pix_fmt", "yuv420p", "-an",
        str(out),
    )
    return out


# ── Step 3: Concat audio liên tục ───────────────────────────────────────────

def _build_audio_track(
    audio_paths: List[Path],
    audio_durs: List[float],
    opts: RendererV2Options,
    work_dir: Path,
) -> Path:
    """Concat TTS audio → 1 track liên tục audio_track.aac."""
    out = work_dir / "audio_track.aac"
    n = len(audio_paths)

    if n == 1:
        _ffmpeg(opts,
            "-i", str(audio_paths[0]),
            "-t", str(audio_durs[0]),
            "-c:a", "aac", "-b:a", opts.audio_bitrate, "-ar", "44100",
            "-vn", str(out),
        )
        return out

    inputs = []
    for p in audio_paths:
        inputs.extend(["-i", str(p)])

    fparts = []
    for j in range(n):
        trim = max(0.1, audio_durs[j])
        fparts.append(
            f"[{j}:a]atrim=0:{trim:.4f},asetpts=PTS-STARTPTS,"
            f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[a{j}]"
        )
    a_in = "".join(f"[a{j}]" for j in range(n))
    fparts.append(f"{a_in}concat=n={n}:v=0:a=1[aout]")

    _ffmpeg(opts,
        *inputs,
        "-filter_complex", ";".join(fparts),
        "-map", "[aout]",
        "-c:a", "aac", "-b:a", opts.audio_bitrate, "-ar", "44100",
        "-vn", str(out),
    )
    return out


# ── Step 4: ASS subtitle với timestamp tuyệt đối ────────────────────────────

def _build_ass(
    scenes: List[SceneV2],
    audio_durs: List[float],
    W: int, H: int,
    window: int = 4,
    style_name: str = "🟡 TikTok Yellow (Viral)",
) -> str:
    """
    Build file .ass với timestamp tuyệt đối trên toàn timeline.
    audio_durs[i] = duration thực của cảnh i (giây).
    """
    fs = 58 if W == 1080 else 34
    margv = 512 if W == 1080 else 120

    cfg = _SUB_STYLES.get(style_name, _SUB_STYLES["🟡 TikTok Yellow (Viral)"])
    hi   = cfg["highlight"]
    base = cfg["base"]
    out  = cfg["outline"]
    back = cfg["back"]
    bold = cfg["bold"]
    shad = cfg["shadow"]
    bs   = cfg.get("border_style", 1)
    ow   = cfg.get("outline_w", 2)
    sp   = cfg.get("spacing", 0)

    all_text = " ".join(s.text for s in scenes)
    has_ko = any(0xAC00 <= ord(c) <= 0xD7A3 or 0x1100 <= ord(c) <= 0x11FF for c in all_text)
    font = "Apple SD Gothic Neo" if has_ko else "Arial"

    header = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{fs},{base},&H000000FF,{out},{back},"
        f"{bold},0,0,0,100,100,{sp},0,{bs},{ow},{shad},2,30,30,{margv},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    STAT_COLOR = "&H002222FF"
    STAT_BUMP  = 14

    def _cw(ch):
        cp = ord(ch)
        if (0xAC00 <= cp <= 0xD7A3 or 0x1100 <= cp <= 0x11FF
                or 0x4E00 <= cp <= 0x9FFF or 0x3040 <= cp <= 0x30FF):
            return 1.8
        return 1.0

    dlg: List[str] = []
    timeline_offset = 0.0  # ← KEY: cumulative timeline position

    for scene, adur in zip(scenes, audio_durs):

        # ── Build flat word list với timing tương đối trong cảnh ────────
        flat: List[dict] = []

        if scene.words:
            # Word-level timing có sẵn (Edge TTS / CapCut)
            for entry in scene.words:
                phrase = entry.get("word", "").strip()
                ts = float(entry.get("start", 0))
                te = float(entry.get("end", ts + 0.1))
                tokens = phrase.split()
                if not tokens:
                    continue
                d = (te - ts) / len(tokens)
                for k, tok in enumerate(tokens):
                    flat.append({"word": tok, "start": ts + k * d, "end": ts + (k + 1) * d})
        else:
            # Không có word timing → phân bổ theo số ký tự
            tokens = scene.text.split()
            if tokens and adur > 0:
                cl = [max(1.0, sum(_cw(c) for c in w)) for w in tokens]
                tc = sum(cl)
                t = 0.0
                for w, c in zip(tokens, cl):
                    wd = adur * c / tc
                    flat.append({"word": w, "start": t, "end": t + wd})
                    t += wd

        if not flat:
            timeline_offset += adur
            continue

        # ── Emit ASS dialogue lines ──────────────────────────────────────
        i = 0
        while i < len(flat):
            block = flat[i:i + window]
            for wi, active in enumerate(block):
                # ← ABSOLUTE timestamps
                t_start = timeline_offset + active["start"]
                t_end   = timeline_offset + active["end"]

                parts = []
                for wj, w in enumerate(block):
                    tok = w["word"].upper()
                    stat = _is_stat_word(tok)
                    if wj == wi:
                        if stat:
                            parts.append(
                                f"{{\\c{STAT_COLOR}\\fs{fs+STAT_BUMP}\\b1\\shad4\\3c&H00000066&}}{tok}"
                                f"{{\\c{base}\\fs{fs}\\b{abs(bold)}\\shad{shad}}}"
                            )
                        else:
                            parts.append(
                                f"{{\\c{hi}\\fs{fs+8}\\b1\\shad3}}{tok}"
                                f"{{\\c{base}\\fs{fs}\\b{abs(bold)}\\shad{shad}}}"
                            )
                    else:
                        if stat:
                            parts.append(
                                f"{{\\c{STAT_COLOR}\\alpha&H60&\\fs{fs+4}\\b1}}{tok}"
                                f"{{\\c{base}\\fs{fs}\\alpha&H80&\\b{abs(bold)}}}"
                            )
                        else:
                            parts.append(
                                f"{{\\c{base}\\alpha&H80&}}{tok}{{\\alpha&H00&}}"
                            )

                dlg.append(
                    f"Dialogue: 0,{_t_ass(t_start)},{_t_ass(t_end)},Default,,0,0,0,,"
                    + "\\h".join(parts)
                )
            i += window

        timeline_offset += adur  # advance timeline chính xác theo audio thực

    return header + "\n".join(dlg)


# ── Step 5: Final merge ───────────────────────────────────────────────────────

def _final_merge(
    video_track: Path,
    audio_track: Path,
    ass_file: Optional[Path],
    total_dur: float,
    opts: RendererV2Options,
    out_path: Path,
) -> Path:
    W, H = opts.width, opts.height
    sub_vf = ""
    if opts.burn_subtitles and ass_file and ass_file.exists():
        ass_esc = str(ass_file).replace("\\", "/").replace(":", "\\:")
        sub_vf = f",ass='{ass_esc}'"

    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2{sub_vf}"
    )

    if opts.bgm_path and Path(opts.bgm_path).exists():
        bvol = max(0.0, min(1.0, opts.bgm_volume))
        vvol = max(0.0, min(2.0, opts.voice_volume))
        _ffmpeg(opts,
            "-i", str(video_track),
            "-i", str(audio_track),
            "-stream_loop", "-1", "-i", opts.bgm_path,
            "-filter_complex",
            f"[1:a]volume={vvol:.3f}[v];"
            f"[2:a]volume={bvol:.3f}[b];"
            f"[v][b]amix=inputs=2:duration=first:dropout_transition=2[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-vf", vf,
            "-t", f"{total_dur:.4f}",
            "-c:v", "libx264", "-preset", opts.preset, "-crf", str(opts.crf),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", opts.audio_bitrate, "-ar", "44100",
            "-movflags", "+faststart",
            str(out_path),
        )
    else:
        _ffmpeg(opts,
            "-i", str(video_track),
            "-i", str(audio_track),
            "-map", "0:v", "-map", "1:a",
            "-vf", vf,
            "-t", f"{total_dur:.4f}",
            "-c:v", "libx264", "-preset", opts.preset, "-crf", str(opts.crf),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", opts.audio_bitrate, "-ar", "44100",
            "-movflags", "+faststart",
            str(out_path),
        )
    return out_path


# ── Public API ────────────────────────────────────────────────────────────────

def render_video_v2(
    scenes: List[SceneV2],
    out_path: Path,
    opts: Optional[RendererV2Options] = None,
) -> Path:
    """
    Entry point chính của renderer v2.

    Parameters
    ----------
    scenes   : Danh sách SceneV2. Mỗi scene cần audio_path + ít nhất 1 visual.
    out_path : Đường dẫn file output MP4.
    opts     : RendererV2Options. Dùng default nếu None.

    Returns
    -------
    Path: out_path sau khi render thành công.

    Raises
    ------
    RuntimeError: nếu render thất bại hoàn toàn.
    """
    if opts is None:
        opts = RendererV2Options()

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if opts.work_dir:
        work_dir = Path(opts.work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        _cleanup = False
    else:
        _tmp = tempfile.mkdtemp(prefix="avc_v2_")
        work_dir = Path(_tmp)
        _cleanup = True

    try:
        return _run(scenes, out_path, opts, work_dir)
    finally:
        if _cleanup:
            shutil.rmtree(work_dir, ignore_errors=True)


def _run(
    scenes: List[SceneV2],
    out_path: Path,
    opts: RendererV2Options,
    work_dir: Path,
) -> Path:
    W, H = opts.width, opts.height
    n = len(scenes)
    xfade = opts.xfade_dur
    _log(opts, f"[v2] Render {n} cảnh — {W}x{H} @ {opts.fps}fps  xfade={xfade}s")

    # ── Probe / prep audio ───────────────────────────────────────────────────
    audio_paths: List[Path] = []
    audio_durs:  List[float] = []

    for i, sc in enumerate(scenes):
        ap = Path(sc.audio_path) if sc.audio_path else None
        if not ap or not ap.exists():
            dur = sc.duration if sc.duration > 0 else 3.0
            silence = work_dir / f"silence_{i:04d}.aac"
            _ffmpeg(opts,
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", str(dur), "-c:a", "aac", "-b:a", "128k", str(silence),
            )
            audio_paths.append(silence)
            audio_durs.append(dur)
            _log(opts, f"  Scene {i+1}: no audio → silence {dur:.2f}s")
        else:
            dur = _probe_dur(ap, opts.ffmpeg_bin)
            if dur <= 0:
                dur = sc.duration if sc.duration > 0 else 3.0
            audio_paths.append(ap)
            audio_durs.append(dur)
            _log(opts, f"  Scene {i+1}: audio {dur:.3f}s  ({ap.name})")

    total_audio = sum(audio_durs)
    _log(opts, f"[v2] Tổng audio = {total_audio:.3f}s")

    # ── Tính clip_dur cho video (audio + xfade buffer) ───────────────────────
    # Buffer = xfade_dur để xfade không bị "ran out of frames" ở clip biên
    # Buffer chỉ là silence/trailing video — KHÔNG ảnh hưởng audio track
    xfade_buf = xfade
    clip_durs = [
        (adur + xfade_buf if i < n - 1 else adur + 0.1)
        for i, adur in enumerate(audio_durs)
    ]

    # Auto-reduce xfade nếu cảnh quá ngắn
    safe_xfade = xfade
    for cd in clip_durs:
        safe_xfade = min(safe_xfade, cd * 0.4)
    safe_xfade = max(0.0, safe_xfade)
    if safe_xfade < xfade:
        _log(opts, f"  ℹ️ xfade_dur auto-reduced: {xfade:.2f} → {safe_xfade:.2f}s")

    # ── Step 1: Render video clips (câm) ─────────────────────────────────────
    _log(opts, "[v2] Step 1: Render video clips (silent)...")
    clips: List[Path] = []
    for i, sc in enumerate(scenes):
        _log(opts, f"  [{i+1}/{n}] Rendering video...")
        clip = _render_scene_silent(sc, i, clip_durs[i], opts, work_dir)
        clips.append(clip)
    _log(opts, f"[v2] Step 1 done: {len(clips)} clips")

    # ── Step 2: xfade concat → video track (câm) ─────────────────────────────
    _log(opts, "[v2] Step 2: xfade concat video track...")
    transitions = [sc.transition for sc in scenes]
    if safe_xfade > 0 and n > 1:
        try:
            video_track = _build_video_track(
                clips, clip_durs, transitions, safe_xfade, opts, work_dir
            )
        except Exception as e:
            _log(opts, f"  ⚠️ xfade fail ({e}) → concat thô")
            video_track = _concat_fallback(clips, opts, work_dir)
    else:
        video_track = _concat_fallback(clips, opts, work_dir)
    _log(opts, f"[v2] Step 2 done: {video_track}")

    # ── Step 3: Concat audio → 1 track liên tục ──────────────────────────────
    _log(opts, "[v2] Step 3: Concat audio track (continuous)...")
    audio_track = _build_audio_track(audio_paths, audio_durs, opts, work_dir)
    _log(opts, f"[v2] Step 3 done: {audio_track}")

    # ── Step 4: Build ASS subtitle với absolute timestamps ───────────────────
    ass_file = None
    if opts.burn_subtitles:
        _log(opts, "[v2] Step 4: Build ASS subtitle (absolute timestamps)...")
        ass_str = _build_ass(
            scenes=scenes,
            audio_durs=audio_durs,
            W=W, H=H,
            window=opts.sub_window,
            style_name=opts.sub_style or "🟡 TikTok Yellow (Viral)",
        )
        ass_file = work_dir / "subtitle.ass"
        ass_file.write_text(ass_str, encoding="utf-8")
        _log(opts, f"[v2] Step 4 done: {ass_file.stat().st_size // 1024}KB ASS")

    # ── Step 5: Final merge ───────────────────────────────────────────────────
    _log(opts, "[v2] Step 5: Final merge (video + audio + subtitle)...")
    result = _final_merge(
        video_track=video_track,
        audio_track=audio_track,
        ass_file=ass_file,
        total_dur=total_audio,
        opts=opts,
        out_path=out_path,
    )

    if not result.exists() or result.stat().st_size < 10_000:
        raise RuntimeError(f"Output không hợp lệ: {result}")

    size_mb = result.stat().st_size / 1_048_576
    _log(opts, f"[v2] ✅ Done! {result.name}  ({size_mb:.1f} MB, {total_audio:.1f}s)")
    return result


# ── Convenience: convert dict scene (format cũ) → SceneV2 ───────────────────

def scene_from_dict(d: dict) -> SceneV2:
    """
    Tạo SceneV2 từ dict theo format cũ (tool.py scenes).
    Không phụ thuộc gì vào v1 — chỉ đọc các key thông dụng.
    """
    return SceneV2(
        text=d.get("text", ""),
        audio_path=d.get("audio_path", "") or d.get("audioPath", ""),
        video_url=d.get("videoUrl", "") or d.get("video_url", ""),
        image_url=d.get("imageUrl", "") or d.get("image_url", ""),
        veo3_path=d.get("veo3Path", "") or d.get("veo3_path", ""),
        custom_vid=d.get("customVid", "") or d.get("custom_vid", ""),
        custom_img=d.get("customImg", "") or d.get("custom_img", ""),
        keyword=d.get("keyword", ""),
        duration=float(d.get("duration", 0) or 0),
        words=d.get("words", []) or [],
        effect=d.get("effect") or d.get("imageEffect"),
        transition=d.get("transition", "fade") or "fade",
        sub_style=d.get("sub_style", "🟡 TikTok Yellow (Viral)"),
    )
