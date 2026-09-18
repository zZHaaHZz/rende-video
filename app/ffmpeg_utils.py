"""
app/ffmpeg_utils.py — FFmpeg wrappers, audio probing, download helpers.
"""
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import requests

from app.config import FFMPEG


def ffmpeg(*args):
    if not FFMPEG:
        raise RuntimeError("Không tìm thấy FFmpeg. Hãy cài FFmpeg trước khi render.")
    cmd = [FFMPEG, "-y", "-loglevel", "error"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"FFmpeg: {result.stderr[:300]}")


def has_subtitles_filter() -> bool:
    """Check if FFmpeg has subtitles filter (requires libass)."""
    if not FFMPEG:
        return False
    try:
        r = subprocess.run([FFMPEG, "-filters"], capture_output=True, text=True)
        return r.returncode == 0 and "subtitles" in r.stdout
    except OSError:
        return False


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


def download_url(url: str, dest: str):
    r = requests.get(url, timeout=60, stream=True, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in r.iter_content(65536):
            if chunk:
                f.write(chunk)
