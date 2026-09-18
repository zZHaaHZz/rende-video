"""
app/effects.py — Hiệu ứng ảnh/video: Ken Burns, intro effects, sound effects.
"""
import math
import random
import shutil
from pathlib import Path

from app.ffmpeg_utils import ffmpeg

# ── Hiệu ứng ảnh tĩnh (Ken Burns variations) ──────────────────────────────
IMAGE_EFFECTS = [
    "zoom_in",    # Zoom in từ 1.0 → 1.2 (giữa)
    "zoom_out",   # Zoom out từ 1.2 → 1.0 (giữa)
    "pan_right",  # Zoom 1.1, pan từ trái → phải
    "pan_left",   # Zoom 1.1, pan từ phải → trái
    "pan_up",     # Zoom 1.1, pan từ dưới → trên
    "pan_down",   # Zoom 1.1, pan từ trên → xuống
]

# ── Hiệu ứng intro video ────────────────────────────────────────────────────
VIDEO_INTRO_EFFECTS = [
    "fade_in",
    "slide_right",
    "slide_up",
    "zoom_punch",
    "none",
]

# ── Sound Effects (FFmpeg lavfi) ─────────────────────────────────────────────
SOUND_EFFECTS = {
    "whoosh":   "sin(2*PI*400*t)*exp(-t/0.1):s=44100:d=0.3,afade=t=in:ss=0:d=0.05,afade=t=out:st=0.25:d=0.05",
    "click":    "sin(2*PI*800*t)*exp(-t/0.01):s=44100:d=0.08,afade=t=out:st=0.02:d=0.06",
    "chime":    "sin(2*PI*880*t)*exp(-t/0.15):s=44100:d=0.5,afade=t=in:ss=0:d=0.05,afade=t=out:st=0.4:d=0.1",
    "deep_hit": "sin(2*PI*60*t)*exp(-t/0.1):s=44100:d=0.4,afade=t=in:ss=0:d=0.05,afade=t=out:st=0.3:d=0.1",
    "none":     None,
}


def make_image_effect_filter(W: int, H: int, dur: float,
                              effect: str = None, cinematic: bool = True) -> str:
    """Tạo FFmpeg filter chain cho ảnh tĩnh với hiệu ứng chuyển động."""
    if effect is None:
        effect = random.choice(IMAGE_EFFECTS)

    d_frames = math.ceil(dur * 30) + 15
    fps_filter = "fps=30"
    base_scale = f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2}"

    if effect == "zoom_in":
        zp = (
            f"zoompan=z='1+0.2*(on/{d_frames})'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={d_frames}:fps=30:s={W*2}x{H*2}"
        )
    elif effect == "zoom_out":
        zp = (
            f"zoompan=z='1.2-0.2*(on/{d_frames})'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={d_frames}:fps=30:s={W*2}x{H*2}"
        )
    elif effect == "pan_right":
        zp = (
            f"zoompan=z='1.1'"
            f":x='(iw-iw/zoom)*(on/{d_frames})'"
            f":y='ih/2-(ih/zoom/2)'"
            f":d={d_frames}:fps=30:s={W*2}x{H*2}"
        )
    elif effect == "pan_left":
        zp = (
            f"zoompan=z='1.1'"
            f":x='(iw-iw/zoom)*(1-on/{d_frames})'"
            f":y='ih/2-(ih/zoom/2)'"
            f":d={d_frames}:fps=30:s={W*2}x{H*2}"
        )
    elif effect == "pan_up":
        zp = (
            f"zoompan=z='1.1'"
            f":x='iw/2-(iw/zoom/2)'"
            f":y='(ih-ih/zoom)*(1-on/{d_frames})'"
            f":d={d_frames}:fps=30:s={W*2}x{H*2}"
        )
    else:  # pan_down
        zp = (
            f"zoompan=z='1.1'"
            f":x='iw/2-(iw/zoom/2)'"
            f":y='(ih-ih/zoom)*(on/{d_frames})'"
            f":d={d_frames}:fps=30:s={W*2}x{H*2}"
        )

    return f"{base_scale},{zp},scale={W}:{H},{fps_filter}"


def make_video_intro_filter(W: int, H: int, dur: float, effect: str = None) -> str:
    """Tạo FFmpeg vf filter cho video intro effect."""
    if effect is None:
        effect = random.choice(["fade_in", "slide_right", "slide_up", "zoom_punch", "none", "none"])
    if effect == "none" or not effect:
        return None
    intro_dur = min(0.4, dur * 0.15)
    if effect == "fade_in":
        return f"fade=t=in:st=0:d={intro_dur:.2f}"
    elif effect == "slide_right":
        return f"fade=t=in:st=0:d={intro_dur:.2f}"  # simplified fallback
    elif effect == "slide_up":
        return f"fade=t=in:st=0:d={intro_dur:.2f}"
    elif effect == "zoom_punch":
        frames = max(1, int(intro_dur * 30))
        return (
            f"zoompan=z='if(lt(on,{frames}),1.05-0.05*(on/{frames}),1.0)'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={frames+1}:s={W}x{H},fps=30"
        )
    return None


def apply_sound_effect_to_scene(scene_mp4: Path, effect_name: str, out_path: Path) -> bool:
    """Mix một sound effect ngắn vào đầu video cảnh."""
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
