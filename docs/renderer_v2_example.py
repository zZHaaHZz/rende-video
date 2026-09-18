"""
Ví dụ sử dụng renderer_v2.py

Chạy: python3 docs/renderer_v2_example.py
"""
from pathlib import Path
from app.renderer_v2 import SceneV2, RendererV2Options, render_video_v2, scene_from_dict

# ── Ví dụ 1: Dùng SceneV2 trực tiếp ─────────────────────────────────────────
scenes = [
    SceneV2(
        text="Năm 2024, con số 1.5 tỷ đô đã làm cả thế giới chấn động.",
        audio_path="/path/to/scene1_tts.mp3",
        video_url="https://example.com/stock1.mp4",
        transition="fade",
        words=[
            {"word": "Năm 2024", "start": 0.0, "end": 0.6},
            {"word": "con số", "start": 0.6, "end": 1.0},
            {"word": "1.5 tỷ đô", "start": 1.0, "end": 1.8},
            {"word": "đã làm cả thế giới", "start": 1.8, "end": 2.8},
            {"word": "chấn động.", "start": 2.8, "end": 3.5},
        ],
    ),
    SceneV2(
        text="Đây là khoảnh khắc lịch sử không thể quên.",
        audio_path="/path/to/scene2_tts.mp3",
        image_url="/path/to/photo.jpg",   # ảnh tĩnh → tự động Ken Burns
        transition="slideright",
        effect="pan_right",
    ),
    SceneV2(
        text="Subscribe để không bỏ lỡ video tiếp theo!",
        audio_path="/path/to/scene3_tts.mp3",
        video_url="https://example.com/stock3.mp4",
        transition="wipeleft",
    ),
]

opts = RendererV2Options(
    width=1080,        # 9:16 portrait (TikTok/Reels)
    height=1920,
    fps=30,
    xfade_dur=0.5,     # transition 0.5s giữa các cảnh
    crf=20,
    preset="fast",
    burn_subtitles=True,
    sub_style="🟡 TikTok Yellow (Viral)",
    sub_window=4,
    bgm_path="/path/to/bgm.mp3",
    bgm_volume=0.12,
    log_cb=print,
)

output = render_video_v2(
    scenes=scenes,
    out_path=Path("/tmp/output_v2.mp4"),
    opts=opts,
)
print(f"Output: {output}")


# ── Ví dụ 2: Convert từ dict format cũ (tool.py scenes) ─────────────────────
old_scenes = [
    {
        "text": "Xin chào!",
        "audioPath": "/path/to/audio.mp3",
        "videoUrl": "https://example.com/vid.mp4",
        "transition": "fade",
        "words": [{"word": "Xin chào!", "start": 0.0, "end": 0.8}],
    },
]

scenes_v2 = [scene_from_dict(d) for d in old_scenes]

output2 = render_video_v2(
    scenes=scenes_v2,
    out_path=Path("/tmp/output_v2_2.mp4"),
    opts=RendererV2Options(log_cb=print),
)
