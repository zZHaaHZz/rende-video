"""Creative Studio — a standalone non-educational content workflow.

The module deliberately owns its project file, uploaded assets and render output.
It does not read or mutate the Main Pipeline / Shorts / Veo Studio projects.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Callable, Optional

import streamlit as st


PROJECT_FILE = Path.home() / ".avc_creative_project.json"
ASSET_DIR = Path.home() / ".avc_creative_assets"
OUTPUT_DIR = Path.home() / "Desktop" / "AI_Videos" / "Creative_Studio"

CONTENT_FORMATS = {
    "cinematic_story": "🎞️ Phim ngắn điện ảnh",
    "product_ad": "✨ Quảng cáo sản phẩm",
    "ugc": "📱 UGC / đời thường",
    "mood_film": "🌙 Mood film / cảm xúc",
    "music_visual": "🎵 Music visual",
    "comedy": "😄 Tình huống hài",
    "horror": "🕯️ Kinh dị / bí ẩn",
    "asmr": "🎧 ASMR / satisfying",
}

VISUAL_STYLES = {
    "cinematic": "Cinematic — ánh sáng điện ảnh, camera mượt",
    "raw_ugc": "Raw UGC — chân thật như quay điện thoại",
    "luxury": "Luxury — tối giản, cao cấp, chuyển động chậm",
    "dreamy": "Dreamy — mềm, mơ màng, màu pastel",
    "dark": "Dark — tương phản mạnh, bí ẩn",
    "retro": "Retro — film grain, màu hoài cổ",
    "energetic": "Energetic — nhanh, màu mạnh, nhiều chuyển động",
    "minimal": "Minimal — sạch, ít chi tiết, tập trung chủ thể",
}

ART_STYLES = {
    "photorealistic": "🎥 Người thật / photorealistic",
    "cinematic_3d": "🧸 Hoạt hình 3D điện ảnh",
    "cartoon_2d": "✏️ Hoạt hình 2D",
    "anime": "🌸 Anime Nhật Bản",
    "claymation": "🪨 Đất sét / claymation",
    "stop_motion": "🎞️ Stop-motion thủ công",
    "watercolor": "🎨 Tranh màu nước chuyển động",
    "comic": "💥 Truyện tranh / comic book",
    "paper_cut": "✂️ Giấy cắt lớp / paper cut",
    "pixel_art": "👾 Pixel art",
    "miniature": "🏘️ Mô hình thu nhỏ / miniature",
}

STORY_DIRECTIONS = {
    "transformation": "Biến đổi — từ trạng thái A sang trạng thái B",
    "problem_solution": "Vấn đề → giải pháp",
    "day_in_life": "Một ngày trong cuộc sống",
    "before_after": "Before / After",
    "mystery_reveal": "Bí ẩn → hé lộ",
    "emotional_arc": "Cảm xúc tăng dần → cao trào",
    "loop": "Loop — cảnh cuối nối mượt về cảnh đầu",
    "montage": "Montage — chuỗi khoảnh khắc giàu hình ảnh",
}

PACING_OPTIONS = {
    "slow": "Chậm, có khoảng thở",
    "balanced": "Cân bằng",
    "fast": "Nhanh, giữ nhịp liên tục",
}


def new_project() -> dict:
    return {
        "version": 2,
        "workflow_step": 1,
        "brief": {},
        "concept": {},
        "character_bible": "",
        "reference_image_path": "",
        "scenes": [],
        "final_path": "",
    }


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def load_project() -> dict:
    if not PROJECT_FILE.exists():
        return new_project()
    try:
        data = json.loads(PROJECT_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return new_project()
        defaults = new_project()
        for key, value in defaults.items():
            data.setdefault(key, value)
        data["version"] = 2
        for index, scene in enumerate(data.get("scenes", [])):
            scene.setdefault("id", index + 1)
            scene.setdefault("status", "ready" if Path(scene.get("clip_path", "")).is_file() else "waiting")
        return data
    except (OSError, json.JSONDecodeError):
        return new_project()


def save_project(project: dict) -> None:
    _atomic_write_json(PROJECT_FILE, project)


def _safe_name(name: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", Path(name).name)
    return stem[-100:] or "clip.mp4"


def _project_token(project: dict) -> str:
    payload = json.dumps(project.get("brief", {}), ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def build_idea_prompt(brief: dict) -> str:
    """Build the LLM request for a creative, non-explainer storyboard."""
    duration = int(brief["duration"])
    scene_count = int(brief["scene_count"])
    return f"""
You are a creative director for short-form AI video. This is entertainment,
brand storytelling or visual content — NOT an educational explainer, lecture,
news report, listicle, tutorial, or knowledge-sharing video.

Create one strong visual concept and exactly {scene_count} shots for a
{duration}-second video.

USER BRIEF
- Core idea/product/character: {brief["idea"]}
- Content format: {CONTENT_FORMATS[brief["content_format"]]}
- Story direction: {STORY_DIRECTIONS[brief["direction"]]}
- Video medium / art style: {ART_STYLES[brief.get("art_style", "photorealistic")]}
- Visual style: {VISUAL_STYLES[brief["visual_style"]]}
- Mood: {brief["mood"]}
- Audience: {brief["audience"]}
- Aspect ratio: {brief["aspect"]}
- Pace: {PACING_OPTIONS[brief["pacing"]]}
- Must include: {brief.get("must_include") or "none"}
- Must avoid: {brief.get("must_avoid") or "none"}
- Character identity supplied by user: {brief.get("character_identity") or "AI should define it"}

Return ONLY valid JSON:
{{
  "title": "short working title",
  "logline": "one sentence creative premise",
  "creative_direction": "color, lighting, texture and rhythm in 2-3 sentences",
  "music_direction": "genre, tempo and sound design",
  "character_bible": "one immutable English description of recurring character identity, body, face, wardrobe and signature props",
  "scenes": [
    {{
      "id": 1,
      "purpose": "story function of this shot",
      "duration": 8,
      "subject": "specific visible subject with consistent appearance",
      "action": "one clear filmable action",
      "environment": "specific location and time",
      "camera": "framing, lens feeling and camera movement",
      "lighting_color": "lighting and color palette",
      "audio": "natural ambience or dialogue captured inside the generated clip",
      "foley": "specific real-world close-up sound synchronized to visible contact",
      "designed_sfx": "stylized electronic, magical or mechanical accent for this stage",
      "music_energy": "low, building, high or climax",
      "entry_frame": "what is visible and moving in the first half-second",
      "exit_frame": "what is visible and moving in the final half-second",
      "motion_direction": "left-to-right, right-to-left, toward-camera, away-from-camera or static",
      "transition": "cut, dissolve, whip, flash, fade or match"
    }}
  ]
}}

Rules:
- Durations should total approximately {duration} seconds.
- Each shot must be visually generatable and continue the same world/characters.
- The exit_frame of shot N must visually and directionally connect to the
  entry_frame of shot N+1. Preserve screen direction and camera momentum.
- For match transitions, repeat one matching shape, pose, prop or composition
  on both sides. For whip transitions, keep the same pan direction.
- Sound must evolve with the story. Do not repeat one generic loop across shots.
- Foley describes only visible contact; designed_sfx supports transformation;
  music_energy rises toward the visual reveal.
- No narrator, facts, advice, teaching, bullet points, captions, logos or watermark.
- Use dialogue only when it strengthens the scene; keep it under 10 words.
""".strip()


def build_veo_prompt(scene: dict, brief: dict, concept: dict) -> str:
    """Create a production-ready prompt that can be pasted into Veo 3."""
    audio = scene.get("audio", "Natural location ambience only")
    foley = scene.get("foley", "No additional Foley")
    designed_sfx = scene.get("designed_sfx", "No designed sound effect")
    avoid = brief.get("must_avoid") or "text, subtitles, logo, watermark, distorted anatomy"
    character_bible = (
        scene.get("character_bible")
        or brief.get("character_bible")
        or brief.get("character_identity")
        or ""
    )
    identity = (
        f"CHARACTER LOCK: {character_bible}. Repeat this exact identity without redesign. "
        if character_bible else ""
    )
    reference = (
        "REFERENCE IMAGE: Use the attached character reference as the primary visual anchor. "
        if brief.get("has_reference_image") else ""
    )
    temporal_continuity = (
        f"ENTRY FRAME: {scene.get('entry_frame', 'Begin with stable readable composition')}. "
        f"EXIT FRAME: {scene.get('exit_frame', 'End on a clean composition ready for the next shot')}. "
        f"SCREEN DIRECTION: {scene.get('motion_direction', 'consistent')}. "
        f"EDIT HANDLE: Hold the opening and closing composition for about 0.35 seconds "
        f"without abrupt subject or camera changes. "
    )
    return (
        f"Create a {scene.get('duration', 8)}-second {brief['aspect']} video shot. "
        f"VIDEO MEDIUM: {ART_STYLES[brief.get('art_style', 'photorealistic')]}. "
        f"{identity}{reference}"
        f"SUBJECT: {scene.get('subject', '')}. "
        f"ACTION: {scene.get('action', '')}. "
        f"ENVIRONMENT: {scene.get('environment', '')}. "
        f"CAMERA: {scene.get('camera', '')}. "
        f"LIGHTING AND COLOR: {scene.get('lighting_color', '')}. "
        f"OVERALL LOOK: {VISUAL_STYLES[brief['visual_style']]}; "
        f"{concept.get('creative_direction', '')}. "
        f"AUDIO BED: {audio}. "
        f"SYNCED FOLEY: {foley}. "
        f"DESIGNED SFX: {designed_sfx}. Do not use a repeating generic sound loop. "
        f"{temporal_continuity}"
        f"CONTINUITY: Keep recurring characters, wardrobe, props and color palette "
        f"consistent with adjacent shots. "
        f"AVOID: {avoid}. No added captions or interface elements."
    )


def normalize_storyboard(raw: dict, brief: dict) -> dict:
    concept = {
        "title": str(raw.get("title", "Untitled Creative")),
        "logline": str(raw.get("logline", "")),
        "creative_direction": str(raw.get("creative_direction", "")),
        "music_direction": str(raw.get("music_direction", "")),
    }
    character_bible = str(
        raw.get("character_bible")
        or brief.get("character_identity")
        or ""
    ).strip()
    prompt_brief = {**brief, "character_bible": character_bible}
    source_scenes = raw.get("scenes", [])
    if not isinstance(source_scenes, list) or not source_scenes:
        raise ValueError("AI không trả về danh sách cảnh hợp lệ.")

    default_duration = max(2, round(int(brief["duration"]) / len(source_scenes)))
    scenes = []
    for index, source in enumerate(source_scenes):
        if not isinstance(source, dict):
            continue
        scene = {
            "id": index + 1,
            "purpose": str(source.get("purpose", "")),
            "duration": max(2, min(20, int(source.get("duration") or default_duration))),
            "subject": str(source.get("subject", "")),
            "action": str(source.get("action", "")),
            "environment": str(source.get("environment", "")),
            "camera": str(source.get("camera", "")),
            "lighting_color": str(source.get("lighting_color", "")),
            "audio": str(source.get("audio", "Natural ambience only")),
            "foley": str(source.get("foley", "No additional Foley")),
            "designed_sfx": str(source.get("designed_sfx", "No designed sound effect")),
            "music_energy": str(source.get("music_energy", "building")).lower(),
            "sfx_path": "",
            "sfx_volume": 0.8,
            "sfx_offset": 0.0,
            "entry_frame": str(source.get("entry_frame", "Stable opening composition")),
            "exit_frame": str(source.get("exit_frame", "Clean closing composition")),
            "motion_direction": str(source.get("motion_direction", "static")).lower(),
            "transition": str(source.get("transition", "cut")).lower(),
            "clip_path": "",
            "status": "waiting",
            "character_bible": character_bible,
        }
        scene["veo_prompt"] = build_veo_prompt(scene, prompt_brief, concept)
        scenes.append(scene)
    if not scenes:
        raise ValueError("Không thể chuẩn hoá storyboard.")
    return {"concept": concept, "character_bible": character_bible, "scenes": scenes}


def storyboard_duration(scenes: list[dict]) -> float:
    return round(sum(float(scene.get("duration", 0) or 0) for scene in scenes), 2)


def move_scene(scenes: list[dict], index: int, offset: int) -> list[dict]:
    target = index + offset
    if index < 0 or index >= len(scenes) or target < 0 or target >= len(scenes):
        return scenes
    scenes[index], scenes[target] = scenes[target], scenes[index]
    for position, scene in enumerate(scenes):
        scene["id"] = position + 1
    return scenes


def refresh_scene_prompts(project: dict) -> None:
    brief = {
        **project.get("brief", {}),
        "character_bible": project.get("character_bible", ""),
        "has_reference_image": bool(project.get("reference_image_path")),
    }
    for scene in project.get("scenes", []):
        scene["character_bible"] = project.get("character_bible", "")
        scene["veo_prompt"] = build_veo_prompt(scene, brief, project.get("concept", {}))


def _run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True)


def _has_audio_stream(ffmpeg_path: str, media_path: str) -> bool:
    ffprobe = str(Path(ffmpeg_path).with_name("ffprobe"))
    if not Path(ffprobe).is_file():
        ffprobe = shutil.which("ffprobe") or ""
    if not ffprobe:
        return False
    result = _run([
        ffprobe, "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=index", "-of", "csv=p=0", media_path,
    ])
    return result.returncode == 0 and bool(result.stdout.strip())


TRANSITION_PRESETS = {
    # xfade name, overlap duration. "cut" keeps a tiny two-frame blend so the
    # whole timeline can use one deterministic filter graph.
    "cut": ("fadefast", 0.06),
    "fade": ("fadeblack", 0.35),
    "dissolve": ("dissolve", 0.60),
    "whip": ("slideleft", 0.24),
    "flash": ("fadewhite", 0.20),
    "match": ("fadefast", 0.16),
}


def build_transition_plan(scenes: list[dict]) -> tuple[list[dict], float]:
    """Return transition overlaps and the final visual timeline duration."""
    if not scenes:
        return [], 0.0
    total = float(scenes[0].get("duration", 0) or 0)
    plan = []
    for index in range(1, len(scenes)):
        previous_duration = float(scenes[index - 1].get("duration", 0) or 0)
        current_duration = float(scenes[index].get("duration", 0) or 0)
        name = str(scenes[index].get("transition", "cut")).lower()
        xfade_name, requested = TRANSITION_PRESETS.get(name, TRANSITION_PRESETS["cut"])
        overlap = min(requested, max(0.04, previous_duration / 3), max(0.04, current_duration / 3))
        offset = max(0.0, total - overlap)
        plan.append({
            "scene_index": index,
            "kind": name,
            "xfade": xfade_name,
            "duration": round(overlap, 3),
            "offset": round(offset, 3),
        })
        total += current_duration - overlap
    return plan, round(total, 3)


def _transition_filter_graph(scenes: list[dict]) -> tuple[str, str, str]:
    """Build chained video xfade and audio acrossfade labels."""
    plan, _ = build_transition_plan(scenes)
    if not plan:
        return "", "0:v", "0:a"
    filters = []
    video_label = "[0:v]"
    audio_label = "[0:a]"
    for transition in plan:
        index = transition["scene_index"]
        next_video = f"[{index}:v]"
        next_audio = f"[{index}:a]"
        out_video = f"[v{index}]"
        out_audio = f"[a{index}]"
        filters.append(
            f"{video_label}{next_video}xfade=transition={transition['xfade']}:"
            f"duration={transition['duration']}:offset={transition['offset']}{out_video}"
        )
        filters.append(
            f"{audio_label}{next_audio}acrossfade=d={transition['duration']}:"
            f"c1=tri:c2=tri{out_audio}"
        )
        video_label, audio_label = out_video, out_audio
    return ";".join(filters), video_label.strip("[]"), audio_label.strip("[]")


def render_video(
    project: dict,
    ffmpeg_path: str,
    music_path: Optional[str] = None,
    music_volume: float = 0.18,
    keep_clip_audio: bool = True,
    progress: Optional[Callable[[int, str], None]] = None,
) -> str:
    """Normalize uploaded clips and concatenate them without touching other modules."""
    if not ffmpeg_path:
        raise RuntimeError("Không tìm thấy FFmpeg.")
    scenes = project.get("scenes", [])
    missing = [i + 1 for i, scene in enumerate(scenes) if not Path(scene.get("clip_path", "")).is_file()]
    if missing:
        raise ValueError(f"Thiếu video ở cảnh: {', '.join(map(str, missing))}")

    brief = project["brief"]
    width, height = (1080, 1920) if brief["aspect"] == "9:16" else (1920, 1080)
    token = _project_token(project)
    work = ASSET_DIR / token / "render"
    work.mkdir(parents=True, exist_ok=True)
    normalized = []

    for index, scene in enumerate(scenes):
        if progress:
            progress(index, f"Chuẩn hoá cảnh {index + 1}/{len(scenes)}")
        src = str(scene["clip_path"])
        out = work / f"scene_{index:03d}.mp4"
        duration = float(scene.get("duration", 8))
        transition = scene.get("transition", "cut")
        fade = "fade=t=in:st=0:d=0.18," if transition in {"fade", "dissolve", "flash"} else ""
        video_filter = (
            f"fps=30,scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},{fade}format=yuv420p"
        )
        # Input 0 loops the picture only. Input 1 is deliberately non-looped:
        # its original sound plays once, then apad adds silence. This prevents
        # the mechanical repeating "click-click" heard when Veo clips are
        # shorter than the storyboard scene.
        command = [ffmpeg_path, "-stream_loop", "-1", "-i", src]
        if keep_clip_audio and _has_audio_stream(ffmpeg_path, src):
            command += ["-i", src]
        else:
            command += [
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            ]
        sfx_path = scene.get("sfx_path", "")
        has_sfx = bool(sfx_path and Path(sfx_path).is_file())
        if has_sfx:
            offset = max(0.0, float(scene.get("sfx_offset", 0) or 0))
            command += ["-i", str(sfx_path)]
        audio_filter = (
            f"[1:a]aresample=48000,apad=whole_dur={duration},"
            f"atrim=0:{duration},asetpts=PTS-STARTPTS[base]"
        )
        if has_sfx:
            sfx_volume = max(0.0, min(2.0, float(scene.get("sfx_volume", 0.8) or 0.8)))
            delay_ms = round(offset * 1000)
            audio_filter += (
                f";[2:a]aresample=48000,volume={sfx_volume},"
                f"adelay={delay_ms}:all=1,"
                f"apad=whole_dur={duration},atrim=0:{duration}[sfx]"
                f";[base][sfx]amix=inputs=2:duration=longest:"
                f"dropout_transition=0:normalize=0,atrim=0:{duration}[aout]"
            )
            audio_map = "[aout]"
        else:
            audio_map = "[base]"
        command += [
            "-vf", video_filter, "-filter_complex", audio_filter,
            "-map", "0:v:0", "-map", audio_map,
            "-c:v", "libx264", "-preset", "medium", "-crf", "19",
            "-c:a", "aac", "-ar", "48000", "-ac", "2",
            "-t", str(duration), "-y", str(out),
        ]
        result = _run(command)
        if result.returncode != 0 or not out.exists():
            raise RuntimeError(f"Render cảnh {index + 1} lỗi: {result.stderr[-500:]}")
        normalized.append(out)

    base_video = work / "base.mp4"
    if len(normalized) == 1:
        shutil.copy2(normalized[0], base_video)
        result = subprocess.CompletedProcess([], 0, "", "")
    else:
        filter_graph, video_map, audio_map = _transition_filter_graph(scenes)
        command = [ffmpeg_path]
        for path in normalized:
            command += ["-i", str(path)]
        command += [
            "-filter_complex", filter_graph,
            "-map", f"[{video_map}]", "-map", f"[{audio_map}]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19",
            "-c:a", "aac", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", "-y", str(base_video),
        ]
        result = _run(command)
    if result.returncode != 0:
        raise RuntimeError(f"Ghép/chuyển cảnh lỗi: {result.stderr[-800:]}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    final = OUTPUT_DIR / f"creative_{uuid.uuid4().hex[:8]}.mp4"
    if music_path and Path(music_path).is_file():
        if progress:
            progress(len(scenes), "Mix nhạc nền")
        result = _run([
            ffmpeg_path, "-i", str(base_video), "-stream_loop", "-1", "-i", str(music_path),
            "-filter_complex",
            f"[0:a]volume=1.0[original];[1:a]volume={music_volume}[music];"
            f"[music][original]sidechaincompress="
            f"threshold=0.025:ratio=8:attack=20:release=450[ducked];"
            f"[original][ducked]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
            "-shortest", "-y", str(final),
        ])
    else:
        shutil.copy2(base_video, final)
        result = subprocess.CompletedProcess([], 0, "", "")
    if result.returncode != 0 or not final.exists():
        raise RuntimeError(f"Xuất video lỗi: {result.stderr[-500:]}")
    return str(final)


def render_creative_studio(
    call_ai: Callable[[str], str],
    parse_json: Callable[[str], dict],
    ffmpeg_path: Optional[str],
    veo_engine=None,
    cfg: Optional[dict] = None,
) -> None:
    """Render the four-step Creative Studio wizard."""
    cfg = cfg or {}
    st.header("🎨 Creative Studio")
    st.caption(
        "Ý tưởng → Storyboard → Tạo/nhập clip Veo 3 → Dựng và xuất bản."
    )
    if "creative_project" not in st.session_state:
        st.session_state.creative_project = load_project()
    project = st.session_state.creative_project
    scenes = project.get("scenes", [])
    assets_ready = bool(scenes) and all(Path(s.get("clip_path", "")).is_file() for s in scenes)
    current_step = max(1, min(4, int(project.get("workflow_step", 1))))
    labels = ["1 · Ý tưởng", "2 · Storyboard", "3 · Sản xuất", "4 · Xuất bản"]
    step_cols = st.columns(4)
    for number, label in enumerate(labels, 1):
        allowed = number == 1 or (number == 2 and bool(scenes)) or (
            number == 3 and bool(scenes)) or (number == 4 and assets_ready
        )
        if step_cols[number - 1].button(
            ("✅ " if number < current_step else "▶ " if number == current_step else "") + label,
            disabled=not allowed, use_container_width=True, key=f"creative_step_{number}",
        ):
            project["workflow_step"] = number
            save_project(project)
            st.rerun()
    st.progress(current_step / 4, text=f"Bước {current_step}/4")

    if current_step == 1:
        _render_setup_step(project, call_ai, parse_json)
    elif current_step == 2:
        _render_storyboard_step(project)
    elif current_step == 3:
        _render_production_step(project, veo_engine, cfg)
    else:
        _render_export_step(project, ffmpeg_path)


def _option_index(options: dict, value: str, fallback: int = 0) -> int:
    keys = list(options)
    return keys.index(value) if value in options else fallback


def _commit_project(project: dict) -> None:
    save_project(project)
    st.session_state.creative_project = project


def _render_setup_step(project: dict, call_ai: Callable, parse_json: Callable) -> None:
    st.subheader("Bước 1 — Thiết lập ý tưởng")
    old = project.get("brief", {})
    left, right = st.columns([1.15, 1])
    with left:
        idea = st.text_area(
            "Ý tưởng, sản phẩm hoặc nhân vật", value=old.get("idea", ""),
            placeholder="VD: Một chú mèo máy sửa đồ chơi cũ và chờ cô chủ quay về...",
            height=130, key="creative_v2_idea",
        )
        character_identity = st.text_area(
            "Nhân vật cố định (khuyến nghị)",
            value=old.get("character_identity", ""),
            placeholder="VD: Chú mèo máy nhỏ màu cam, thân tròn, tai trái sứt nhẹ, một mắt xanh phát sáng...",
            help="Mô tả này được khóa và lặp nguyên văn trong mọi prompt.",
            key="creative_v2_identity",
        )
        content_format = st.selectbox(
            "Dạng nội dung", list(CONTENT_FORMATS), format_func=CONTENT_FORMATS.get,
            index=_option_index(CONTENT_FORMATS, old.get("content_format", "")),
            key="creative_v2_format",
        )
        direction = st.selectbox(
            "Hướng kể chuyện", list(STORY_DIRECTIONS), format_func=STORY_DIRECTIONS.get,
            index=_option_index(STORY_DIRECTIONS, old.get("direction", "")),
            key="creative_v2_direction",
        )
    with right:
        art_style = st.selectbox(
            "Loại hình video", list(ART_STYLES), format_func=ART_STYLES.get,
            index=_option_index(ART_STYLES, old.get("art_style", "")),
            key="creative_v2_art",
        )
        visual_style = st.selectbox(
            "Phong cách hình ảnh", list(VISUAL_STYLES), format_func=VISUAL_STYLES.get,
            index=_option_index(VISUAL_STYLES, old.get("visual_style", "")),
            key="creative_v2_visual",
        )
        mood = st.text_input("Mood", old.get("mood", "cuốn hút, giàu cảm xúc"), key="creative_v2_mood")
        audience = st.text_input("Khán giả", old.get("audience", "người xem mạng xã hội 18–35"), key="creative_v2_audience")
        c1, c2 = st.columns(2)
        aspect = c1.radio(
            "Tỉ lệ", ["9:16", "16:9"], index=1 if old.get("aspect") == "16:9" else 0,
            key="creative_v2_aspect",
        )
        duration = c2.number_input("Thời lượng", 8, 180, int(old.get("duration", 32)), 8, key="creative_v2_duration")
        c3, c4 = st.columns(2)
        scene_count = c3.number_input("Số cảnh", 1, 20, int(old.get("scene_count", 4)), 1, key="creative_v2_count")
        pacing = c4.selectbox(
            "Nhịp dựng", list(PACING_OPTIONS), format_func=PACING_OPTIONS.get,
            index=_option_index(PACING_OPTIONS, old.get("pacing", "balanced"), 1),
            key="creative_v2_pacing",
        )
    with st.expander("Ràng buộc sáng tạo"):
        must_include = st.text_area("Bắt buộc có", old.get("must_include", ""), key="creative_v2_include")
        must_avoid = st.text_area("Không được có", old.get("must_avoid", ""), key="creative_v2_avoid")

    brief = {
        "idea": idea.strip(), "character_identity": character_identity.strip(),
        "content_format": content_format, "direction": direction, "art_style": art_style,
        "visual_style": visual_style, "mood": mood.strip(), "audience": audience.strip(),
        "aspect": aspect, "duration": int(duration), "scene_count": int(scene_count),
        "pacing": pacing, "must_include": must_include.strip(), "must_avoid": must_avoid.strip(),
    }
    a, b = st.columns([3, 1])
    generate = a.button("✨ Tạo storyboard", type="primary", use_container_width=True)
    if b.button("🗑️ Dự án mới", use_container_width=True):
        clean = new_project()
        _commit_project(clean)
        st.rerun()
    if generate:
        if not brief["idea"]:
            st.error("Hãy nhập ý tưởng chính trước.")
            return
        with st.spinner("AI đang xây dựng concept, Character Bible và storyboard..."):
            try:
                normalized = normalize_storyboard(parse_json(call_ai(build_idea_prompt(brief))), brief)
                new_data = {
                    "version": 2, "workflow_step": 2, "brief": brief, **normalized,
                    "reference_image_path": "", "final_path": "",
                }
                _commit_project(new_data)
                st.rerun()
            except Exception as exc:
                st.error(f"Không tạo được storyboard: {exc}")


def _render_storyboard_step(project: dict) -> None:
    st.subheader("Bước 2 — Duyệt storyboard và khóa nhân vật")
    concept = project.get("concept", {})
    st.markdown(f"### {concept.get('title', 'Storyboard')}")
    st.write(concept.get("logline", ""))
    st.caption(f"🎨 {concept.get('creative_direction', '')}")
    st.caption(f"🎵 {concept.get('music_direction', '')}")
    token = _project_token(project)
    upload_dir = ASSET_DIR / token / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    left, right = st.columns([1.2, 1])
    bible = left.text_area(
        "Character Bible — mô tả bất biến",
        value=project.get("character_bible", ""), height=140,
        key=f"creative_bible_{token}",
        help="Giữ nguyên màu sắc, khuôn mặt, tỷ lệ, trang phục và đạo cụ nhận diện.",
    )
    reference = right.file_uploader(
        "Ảnh tham chiếu nhân vật", type=["png", "jpg", "jpeg", "webp"],
        key=f"creative_reference_{token}",
        help="Khi tạo trên Gemini Web, hãy đính kèm ảnh này cùng prompt.",
    )
    changed = False
    if bible != project.get("character_bible", ""):
        project["character_bible"] = bible.strip()
        changed = True
    if reference is not None:
        payload = bytes(reference.getbuffer())
        digest = hashlib.sha1(payload).hexdigest()
        if digest != project.get("reference_image_digest"):
            destination = upload_dir / f"character_reference_{digest[:10]}_{_safe_name(reference.name)}"
            destination.write_bytes(payload)
            project["reference_image_path"] = str(destination)
            project["reference_image_digest"] = digest
            changed = True
    ref_path = project.get("reference_image_path", "")
    if ref_path and Path(ref_path).is_file():
        right.image(ref_path, caption="Ảnh khóa nhân vật", width=240)
    if changed:
        refresh_scene_prompts(project)
        _commit_project(project)

    total = storyboard_duration(project["scenes"])
    target = float(project.get("brief", {}).get("duration", total))
    if abs(total - target) > 1:
        st.warning(f"Timeline hiện tại {total:g}s, khác thời lượng mục tiêu {target:g}s.")
    else:
        st.success(f"Timeline {total:g}s khớp mục tiêu.")

    for index, scene in enumerate(project["scenes"]):
        with st.expander(f"Cảnh {index + 1} · {scene.get('purpose', '')}", expanded=index == 0):
            c1, c2, c3 = st.columns([1, 1, 4])
            if c1.button("↑", disabled=index == 0, key=f"creative_up_{token}_{index}"):
                project["scenes"] = move_scene(project["scenes"], index, -1)
                _commit_project(project); st.rerun()
            if c2.button("↓", disabled=index == len(project["scenes"]) - 1, key=f"creative_down_{token}_{index}"):
                project["scenes"] = move_scene(project["scenes"], index, 1)
                _commit_project(project); st.rerun()
            duration = c3.number_input(
                "Thời lượng cảnh", 2, 20, int(scene.get("duration", 8)), 1,
                key=f"creative_scene_duration_{token}_{index}",
            )
            with st.expander("🔗 Điểm nối chuyển động giữa các cảnh"):
                entry_frame = st.text_input(
                    "Khung hình mở đầu", value=scene.get("entry_frame", ""),
                    key=f"creative_entry_{token}_{index}",
                )
                exit_frame = st.text_input(
                    "Khung hình kết thúc", value=scene.get("exit_frame", ""),
                    key=f"creative_exit_{token}_{index}",
                )
                motion_options = [
                    "static", "left-to-right", "right-to-left",
                    "toward-camera", "away-from-camera",
                ]
                current_motion = scene.get("motion_direction", "static")
                motion_direction = st.selectbox(
                    "Hướng chuyển động", motion_options,
                    index=motion_options.index(current_motion) if current_motion in motion_options else 0,
                    key=f"creative_motion_{token}_{index}",
                )
                continuity_changed = (
                    entry_frame != scene.get("entry_frame", "")
                    or exit_frame != scene.get("exit_frame", "")
                    or motion_direction != scene.get("motion_direction", "static")
                )
                if continuity_changed:
                    scene.update(
                        entry_frame=entry_frame,
                        exit_frame=exit_frame,
                        motion_direction=motion_direction,
                    )
                    prompt_brief = {
                        **project.get("brief", {}),
                        "character_bible": project.get("character_bible", ""),
                        "has_reference_image": bool(project.get("reference_image_path")),
                    }
                    scene["veo_prompt"] = build_veo_prompt(
                        scene, prompt_brief, project.get("concept", {})
                    )
                    _commit_project(project)
                    st.rerun()
            prompt = st.text_area(
                "Prompt Veo 3", value=scene.get("veo_prompt", ""), height=180,
                key=f"creative_story_prompt_{token}_{index}",
            )
            transition = st.selectbox(
                "Chuyển cảnh", ["cut", "fade", "dissolve", "whip", "flash", "match"],
                index=["cut", "fade", "dissolve", "whip", "flash", "match"].index(
                    scene.get("transition", "cut") if scene.get("transition", "cut") in
                    ["cut", "fade", "dissolve", "whip", "flash", "match"] else "cut"
                ),
                key=f"creative_transition_{token}_{index}",
            )
            if duration != scene.get("duration") or prompt != scene.get("veo_prompt") or transition != scene.get("transition"):
                scene.update(duration=int(duration), veo_prompt=prompt, transition=transition)
                _commit_project(project)
    prompts = "\n\n".join(
        f"SCENE {i + 1}\n{scene.get('veo_prompt', '')}"
        for i, scene in enumerate(project["scenes"])
    )
    a, b = st.columns(2)
    a.download_button("⬇️ Tải prompt pack", prompts, "veo3_prompt_pack.txt", "text/plain", use_container_width=True)
    if b.button("✅ Duyệt storyboard → Sản xuất", type="primary", use_container_width=True):
        project["workflow_step"] = 3
        _commit_project(project)
        st.rerun()


def _render_production_step(project: dict, veo_engine, cfg: dict) -> None:
    st.subheader("Bước 3 — Tạo và nhập video")
    token = _project_token(project)
    upload_dir = ASSET_DIR / token / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    api_ready = bool(
        veo_engine and (
            (cfg.get("veo3_provider") == "api" and cfg.get("veo3_enabled") and cfg.get("gemini"))
            or (cfg.get("veo3_provider") == "google_flow" and cfg.get("useapi_token"))
        )
    )
    mode = st.radio(
        "Phương thức sản xuất",
        ["manual", "api"],
        format_func=lambda value: {
            "manual": "🌐 Gemini Web — copy prompt, tạo clip rồi upload",
            "api": "⚡ Tạo video tự động — gọi API sinh các cảnh còn thiếu",
        }[value],
        horizontal=True, key=f"creative_production_mode_{token}",
    )
    if project.get("reference_image_path"):
        st.info(
            "Ảnh tham chiếu đã được khóa trong prompt. Với Gemini Web, hãy đính kèm ảnh "
            "cho mỗi lần tạo. Engine API hiện tại dùng text prompt + Character Bible."
        )
    if mode == "api":
        if not api_ready:
            st.warning("Vào Settings → chọn Veo API hoặc Google Flow, cấu hình key/token và bật nguồn tương ứng.")
        
        provider = cfg.get("veo3_provider", "api")
        provider_name = "Google Flow API" if provider == "google_flow" else "Veo API"
        
        if st.button(
            f"⚡ Tạo tất cả cảnh còn thiếu bằng {provider_name}", type="primary",
            disabled=not api_ready, use_container_width=True,
        ):
            progress = st.progress(0, text=f"Chuẩn bị {provider_name}...")
            orientation = "portrait" if project["brief"]["aspect"] == "9:16" else "landscape"
            resolution = cfg.get("veo3_resolution", "720p")
            missing = [
                (i, scene) for i, scene in enumerate(project["scenes"])
                if not Path(scene.get("clip_path", "")).is_file()
            ]
            for position, (index, scene) in enumerate(missing):
                result_path = None
                progress.progress(position / max(1, len(missing)), text=f"Tạo cảnh {index + 1}/{len(project['scenes'])}")
                
                if provider == "google_flow":
                    try:
                        candidate = veo_engine.generate_video_google_flow(
                            keyword=scene.get("subject", ""),
                            token=cfg.get("useapi_token", ""),
                            email=cfg.get("useapi_email") or None,
                            model=cfg.get("useapi_model", "veo-3.1-fast"),
                            orientation=orientation,
                            scene_text=scene.get("action", ""),
                            veo3_prompt=scene.get("veo_prompt", ""),
                            timeout_seconds=240,
                        )
                        if candidate and Path(candidate).is_file():
                            result_path = candidate
                    except Exception as exc:
                        scene["last_error"] = str(exc)[:300]
                else:
                    for api_key in cfg.get("gemini", []):
                        try:
                            candidate = veo_engine.generate_video_veo3_best(
                                keyword=scene.get("subject", ""),
                                gemini_api_key=api_key,
                                orientation=orientation,
                                scene_text=scene.get("action", ""),
                                veo3_prompt=scene.get("veo_prompt", ""),
                                timeout_seconds=240,
                                resolution=resolution,
                            )
                            if candidate and Path(candidate).is_file():
                                result_path = candidate
                                break
                        except Exception as exc:
                            scene["last_error"] = str(exc)[:300]
                if result_path:
                    scene["clip_path"] = result_path
                    scene["status"] = "ready"
                    scene.pop("last_error", None)
                else:
                    scene["status"] = "error"
                _commit_project(project)
            progress.progress(1.0, text="Hoàn tất lượt tạo Veo API")
            st.rerun()

    ready_count = 0
    for index, scene in enumerate(project["scenes"]):
        clip_path = scene.get("clip_path", "")
        ready = bool(clip_path and Path(clip_path).is_file())
        ready_count += int(ready)
        icon = "✅" if ready else "❌" if scene.get("status") == "error" else "⏳"
        with st.expander(f"{icon} Cảnh {index + 1} · {scene.get('purpose', '')}", expanded=not ready):
            st.text_area(
                "Prompt", value=scene.get("veo_prompt", ""), height=150,
                key=f"creative_production_prompt_{token}_{index}",
                disabled=True,
            )
            st.caption(
                f"🎧 Foley: {scene.get('foley', '—')}  \n"
                f"⚡ SFX: {scene.get('designed_sfx', '—')}  \n"
                f"🎵 Music energy: {scene.get('music_energy', 'building')}"
            )
            uploaded = st.file_uploader(
                f"Upload clip cảnh {index + 1}", type=["mp4", "mov", "m4v", "webm"],
                key=f"creative_clip_v2_{token}_{index}",
            )
            if uploaded is not None:
                payload = bytes(uploaded.getbuffer())
                digest = hashlib.sha1(payload).hexdigest()
                if digest != scene.get("upload_digest"):
                    destination = upload_dir / f"{index:03d}_{digest[:10]}_{_safe_name(uploaded.name)}"
                    destination.write_bytes(payload)
                    scene.update(clip_path=str(destination), upload_digest=digest, status="ready")
                    _commit_project(project)
                    st.rerun()
            sfx_upload = st.file_uploader(
                f"SFX/Foley riêng cho cảnh {index + 1} (không bắt buộc)",
                type=["wav", "mp3", "m4a", "aac", "ogg"],
                key=f"creative_sfx_{token}_{index}",
                help="Ví dụ: nhựa va chạm, magnetic click, servo, điện xẹt, bass impact.",
            )
            if sfx_upload is not None:
                sfx_payload = bytes(sfx_upload.getbuffer())
                sfx_digest = hashlib.sha1(sfx_payload).hexdigest()
                if sfx_digest != scene.get("sfx_digest"):
                    sfx_dest = upload_dir / f"sfx_{index:03d}_{sfx_digest[:10]}_{_safe_name(sfx_upload.name)}"
                    sfx_dest.write_bytes(sfx_payload)
                    scene.update(sfx_path=str(sfx_dest), sfx_digest=sfx_digest)
                    _commit_project(project)
                    st.rerun()
            if scene.get("sfx_path") and Path(scene["sfx_path"]).is_file():
                st.audio(scene["sfx_path"])
                s1, s2 = st.columns(2)
                sfx_volume = s1.slider(
                    "Âm lượng SFX", 0.0, 2.0, float(scene.get("sfx_volume", 0.8)),
                    0.05, key=f"creative_sfx_volume_{token}_{index}",
                )
                sfx_offset = s2.number_input(
                    "SFX bắt đầu tại giây", 0.0, float(scene.get("duration", 8)),
                    float(scene.get("sfx_offset", 0.0)), 0.1,
                    key=f"creative_sfx_offset_{token}_{index}",
                )
                if sfx_volume != scene.get("sfx_volume") or sfx_offset != scene.get("sfx_offset"):
                    scene.update(sfx_volume=float(sfx_volume), sfx_offset=float(sfx_offset))
                    _commit_project(project)
            if ready:
                st.video(clip_path)
            if scene.get("last_error"):
                st.error(scene["last_error"])
    st.progress(ready_count / max(1, len(project["scenes"])), text=f"{ready_count}/{len(project['scenes'])} cảnh đã sẵn sàng")
    a, b = st.columns(2)
    if a.button("← Quay lại storyboard", use_container_width=True):
        project["workflow_step"] = 2; _commit_project(project); st.rerun()
    if b.button(
        "Dựng video →", type="primary", use_container_width=True,
        disabled=ready_count != len(project["scenes"]),
    ):
        project["workflow_step"] = 4; _commit_project(project); st.rerun()


def _render_export_step(project: dict, ffmpeg_path: Optional[str]) -> None:
    st.subheader("Bước 4 — Dựng hình và xuất bản")
    token = _project_token(project)
    upload_dir = ASSET_DIR / token / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    raw_total = storyboard_duration(project.get("scenes", []))
    transition_plan, final_total = build_transition_plan(project.get("scenes", []))
    overlap = round(raw_total - final_total, 2)
    st.info(
        f"Timeline: {len(project.get('scenes', []))} cảnh · "
        f"{final_total:g}s final ({overlap:g}s transition overlap) · "
        f"{project.get('brief', {}).get('aspect', '9:16')}"
    )
    with st.expander("Xem transition timeline"):
        for item in transition_plan:
            st.write(
                f"Cảnh {item['scene_index']} → {item['scene_index'] + 1}: "
                f"**{item['kind']}** · overlap {item['duration']}s"
            )
    music = st.file_uploader(
        "Nhạc nền (không bắt buộc)", type=["mp3", "wav", "m4a", "aac"],
        key=f"creative_music_v2_{token}",
    )
    if music is not None:
        payload = bytes(music.getbuffer())
        digest = hashlib.sha1(payload).hexdigest()
        if digest != project.get("music_digest"):
            destination = upload_dir / f"music_{digest[:10]}_{_safe_name(music.name)}"
            destination.write_bytes(payload)
            project.update(music_path=str(destination), music_digest=digest)
            _commit_project(project)
    a, b = st.columns(2)
    keep_audio = a.checkbox("Giữ audio gốc", value=True, key=f"creative_audio_v2_{token}")
    music_volume = b.slider("Âm lượng nhạc", 0.0, 0.5, 0.18, 0.01, key=f"creative_volume_v2_{token}")
    st.caption(
        "Audio gốc mỗi clip chỉ phát một lần rồi được pad silence — hình có thể loop "
        "nhưng tiếng click không bị lặp. SFX từng cảnh được sync theo offset; nhạc nền tự duck."
    )
    if not ffmpeg_path:
        st.error("Không tìm thấy FFmpeg.")
    if st.button("🎬 Ghép video final", type="primary", use_container_width=True, disabled=not ffmpeg_path):
        bar = st.progress(0, text="Chuẩn bị...")
        try:
            final_path = render_video(
                project, ffmpeg_path, project.get("music_path") or None,
                music_volume, keep_audio,
                lambda step, message: bar.progress(
                    min(1.0, (step + 1) / max(1, len(project["scenes"]) + 1)), text=message
                ),
            )
            project["final_path"] = final_path
            _commit_project(project)
            st.rerun()
        except Exception as exc:
            st.error(f"Dựng video thất bại: {exc}")
    final_path = project.get("final_path", "")
    if final_path and Path(final_path).is_file():
        st.success(f"Hoàn tất: {final_path}")
        st.video(final_path)
        st.download_button(
            "⬇️ Tải video final", Path(final_path).read_bytes(),
            Path(final_path).name, "video/mp4", use_container_width=True,
        )
