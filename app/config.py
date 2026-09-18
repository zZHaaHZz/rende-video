"""
app/config.py — Cấu hình toàn cục: FFMPEG, thư mục, load/save cfg, secret config.
"""
import json, os, uuid, tempfile, shutil
import re
from pathlib import Path
from typing import Optional

from secret_config import ENV_FILE, SECRET_ENV_MAP, extract_legacy_secrets, load_secrets, save_secrets

# ── File cấu hình ─────────────────────────────────────────────────────────────
CFG_FILE = Path.home() / ".avc_config.json"

TMP = Path(tempfile.gettempdir()) / "avc"
TMP.mkdir(exist_ok=True)
AUDIO_DIR = Path.home() / ".avc_audio"   # Permanent audio cache
AUDIO_DIR.mkdir(exist_ok=True)


# ── Tìm FFmpeg ────────────────────────────────────────────────────────────────
def _find_ffmpeg():
    """Tìm ffmpeg hoạt động được — ưu tiên ffmpeg-full (có libass/ass filter) để burn sub.
    Validate runtime thực sự chạy được trước khi dùng."""
    import os as _os, subprocess as _sp
    candidates = [
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",  # ffmpeg-full — có libass để burn sub
        "/opt/homebrew/Cellar/ffmpeg-full/9.0.1_1/bin/ffmpeg",  # fallback Cellar path
        "/opt/homebrew/Cellar/ffmpeg-full/8.1.2/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg",           # standard Homebrew — không có libass
        "/usr/local/bin/ffmpeg",
        "/usr/bin/ffmpeg",
    ]
    best = None  # ffmpeg chạy được nhưng không có libass
    for c in candidates:
        if not (_os.path.isfile(c) and _os.access(c, _os.X_OK)):
            continue
        try:
            r = _sp.run([c, "-version"], capture_output=True, timeout=5)
            if r.returncode != 0:
                continue
        except Exception:
            continue
        try:
            rf = _sp.run([c, "-filters"], capture_output=True, text=True, timeout=10)
            if "subtitles" in rf.stdout or "ass" in rf.stdout:
                return c
        except Exception:
            pass
        if best is None:
            best = c
    return best or shutil.which("ffmpeg")


FFMPEG = _find_ffmpeg()


# ── File path helpers ─────────────────────────────────────────────────────────
def output_file_stem(name: str, fallback: str = "ai_video") -> str:
    """Return a portable filename stem while keeping Vietnamese input usable."""
    import unicodedata
    candidate = Path((name or "").strip()).stem
    candidate = unicodedata.normalize("NFD", candidate).encode("ascii", "ignore").decode("ascii")
    candidate = re.sub(r"[^A-Za-z0-9_-]+", "_", candidate).strip("._-")
    return candidate[:80] or fallback


def available_output_path(directory: Path, stem: str) -> Path:
    """Avoid silently replacing an earlier render with the same chosen name."""
    candidate = directory / f"{stem}.mp4"
    number = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{number}.mp4"
        number += 1
    return candidate


# ── JSON atomic write ─────────────────────────────────────────────────────────
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


# ── Load / Save config ────────────────────────────────────────────────────────
def load_cfg():
    default_cfg = {
        "used_videos": [],
        # Veo3 settings
        "veo3_enabled": False,
        "veo3_mode":    "fallback",
        "veo3_provider": "stock",
        # Google Flow UseAPI settings
        "useapi_model": "veo-3.1-fast",
    }
    data = dict(default_cfg)
    if CFG_FILE.exists():
        try:
            data = json.loads(CFG_FILE.read_text())
            for k, v in default_cfg.items():
                if k not in data:
                    data[k] = v
            legacy_secrets = extract_legacy_secrets(data)
            if legacy_secrets:
                current_secrets = load_secrets()
                for key, value in legacy_secrets.items():
                    if not current_secrets.get(key):
                        current_secrets[key] = value
                save_secrets(current_secrets)
                _atomic_json_write(CFG_FILE, data)
                CFG_FILE.chmod(0o600)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[config] Cannot read {CFG_FILE}: {exc}")
    data.update(load_secrets())
    return data


def save_cfg(cfg):
    save_secrets({key: cfg.get(key) for key in SECRET_ENV_MAP})
    public_cfg = {key: value for key, value in cfg.items() if key not in SECRET_ENV_MAP}
    _atomic_json_write(CFG_FILE, public_cfg)
    try:
        CFG_FILE.chmod(0o600)
    except OSError:
        pass
