import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import creative_studio as creative


def sample_brief(**overrides):
    brief = {
        "idea": "An orange robot cat repairs forgotten toys",
        "character_identity": "A small orange robot cat with one glowing blue eye",
        "content_format": "cinematic_story",
        "direction": "emotional_arc",
        "art_style": "cinematic_3d",
        "visual_style": "dreamy",
        "mood": "warm and nostalgic",
        "audience": "families",
        "aspect": "16:9",
        "duration": 16,
        "scene_count": 2,
        "pacing": "balanced",
        "must_include": "old toys",
        "must_avoid": "logo",
    }
    brief.update(overrides)
    return brief


class CreativeStudioTests(unittest.TestCase):
    def test_character_bible_is_locked_into_every_prompt(self):
        raw = {
            "title": "Waiting",
            "character_bible": "A small orange robot cat, round body, chipped left ear, one blue eye",
            "scenes": [
                {"purpose": "hook", "subject": "the cat", "action": "wakes up"},
                {"purpose": "reveal", "subject": "the same cat", "action": "meets its owner"},
            ],
        }
        result = creative.normalize_storyboard(raw, sample_brief())
        for scene in result["scenes"]:
            self.assertIn("CHARACTER LOCK:", scene["veo_prompt"])
            self.assertIn("chipped left ear", scene["veo_prompt"])

    def test_reference_image_instruction_is_added(self):
        brief = sample_brief(
            character_bible="Identical orange robot cat",
            has_reference_image=True,
        )
        prompt = creative.build_veo_prompt(
            {"duration": 8, "subject": "cat", "action": "walks"},
            brief,
            {"creative_direction": "soft light"},
        )
        self.assertIn("REFERENCE IMAGE:", prompt)
        self.assertIn("Identical orange robot cat", prompt)

    def test_prompt_contains_temporal_continuity_handles(self):
        prompt = creative.build_veo_prompt(
            {
                "duration": 8,
                "subject": "cat",
                "action": "runs",
                "entry_frame": "cat enters from frame left",
                "exit_frame": "cat exits frame right",
                "motion_direction": "left-to-right",
            },
            sample_brief(),
            {"creative_direction": "soft light"},
        )
        self.assertIn("ENTRY FRAME: cat enters from frame left", prompt)
        self.assertIn("EXIT FRAME: cat exits frame right", prompt)
        self.assertIn("SCREEN DIRECTION: left-to-right", prompt)
        self.assertIn("EDIT HANDLE:", prompt)

    def test_transition_plan_accounts_for_overlap(self):
        plan, final_duration = creative.build_transition_plan([
            {"duration": 8, "transition": "cut"},
            {"duration": 8, "transition": "dissolve"},
            {"duration": 8, "transition": "whip"},
        ])
        self.assertEqual(2, len(plan))
        self.assertEqual("dissolve", plan[0]["xfade"])
        self.assertEqual("slideleft", plan[1]["xfade"])
        self.assertAlmostEqual(23.16, final_duration, places=2)

    def test_move_scene_reorders_and_renumbers(self):
        scenes = [{"id": 1, "purpose": "a"}, {"id": 2, "purpose": "b"}]
        moved = creative.move_scene(scenes, 1, -1)
        self.assertEqual(["b", "a"], [scene["purpose"] for scene in moved])
        self.assertEqual([1, 2], [scene["id"] for scene in moved])

    def test_storyboard_duration(self):
        self.assertEqual(16.5, creative.storyboard_duration([
            {"duration": 8}, {"duration": 8.5},
        ]))

    def test_v1_project_is_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            project_file = Path(directory) / "project.json"
            project_file.write_text(json.dumps({
                "version": 1,
                "brief": {},
                "scenes": [{"clip_path": ""}],
            }))
            with patch.object(creative, "PROJECT_FILE", project_file):
                loaded = creative.load_project()
        self.assertEqual(2, loaded["version"])
        self.assertEqual(1, loaded["workflow_step"])
        self.assertEqual("waiting", loaded["scenes"][0]["status"])

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required")
    def test_renderer_accepts_mixed_audio_inputs(self):
        ffmpeg = shutil.which("ffmpeg")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with_audio = root / "with_audio.mp4"
            silent = root / "silent.mp4"
            subprocess.run([
                ffmpeg, "-f", "lavfi", "-i", "color=c=red:s=320x180:d=0.4",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=0.4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-shortest", "-y", str(with_audio),
            ], capture_output=True, check=True)
            subprocess.run([
                ffmpeg, "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=0.4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(silent),
            ], capture_output=True, check=True)
            project = {
                "brief": {"aspect": "16:9"},
                "scenes": [
                    {"duration": .4, "transition": "cut", "clip_path": str(with_audio)},
                    {"duration": .4, "transition": "dissolve", "clip_path": str(silent)},
                    {"duration": .4, "transition": "whip", "clip_path": str(with_audio)},
                    {"duration": .4, "transition": "flash", "clip_path": str(silent)},
                    {"duration": .4, "transition": "match", "clip_path": str(with_audio)},
                ],
            }
            with patch.object(creative, "ASSET_DIR", root / "assets"), patch.object(
                creative, "OUTPUT_DIR", root / "outputs"
            ):
                output = Path(creative.render_video(project, ffmpeg))
                self.assertTrue(output.is_file())
                self.assertGreater(output.stat().st_size, 1000)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required")
    def test_renderer_does_not_loop_original_clip_audio(self):
        ffmpeg = shutil.which("ffmpeg")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "short_source.mp4"
            subprocess.run([
                ffmpeg, "-f", "lavfi", "-i", "color=c=black:s=320x180:d=0.4",
                "-f", "lavfi", "-i", "sine=frequency=800:duration=0.4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-shortest", "-y", str(source),
            ], capture_output=True, check=True)
            project = {
                "brief": {"aspect": "16:9"},
                "scenes": [{"duration": 1.2, "transition": "cut", "clip_path": str(source)}],
            }
            with patch.object(creative, "ASSET_DIR", root / "assets"), patch.object(
                creative, "OUTPUT_DIR", root / "outputs"
            ):
                output = creative.render_video(project, ffmpeg)
            tail = subprocess.run([
                ffmpeg, "-ss", "0.75", "-t", "0.3", "-i", output,
                "-af", "volumedetect", "-f", "null", "-",
            ], capture_output=True, text=True)
            self.assertIn("mean_volume: -91.0 dB", tail.stderr)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required")
    def test_scene_sfx_is_mixed_at_requested_offset(self):
        ffmpeg = shutil.which("ffmpeg")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "silent.mp4"
            sfx = root / "impact.wav"
            subprocess.run([
                ffmpeg, "-f", "lavfi", "-i", "color=c=black:s=320x180:d=1.2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(source),
            ], capture_output=True, check=True)
            subprocess.run([
                ffmpeg, "-f", "lavfi", "-i", "sine=frequency=120:duration=0.25",
                "-y", str(sfx),
            ], capture_output=True, check=True)
            project = {
                "brief": {"aspect": "16:9"},
                "scenes": [{
                    "duration": 1.2,
                    "transition": "cut",
                    "clip_path": str(source),
                    "sfx_path": str(sfx),
                    "sfx_offset": 0.7,
                    "sfx_volume": 1.0,
                }],
            }
            with patch.object(creative, "ASSET_DIR", root / "assets"), patch.object(
                creative, "OUTPUT_DIR", root / "outputs"
            ):
                output = creative.render_video(project, ffmpeg)
            impact = subprocess.run([
                ffmpeg, "-ss", "0.72", "-t", "0.2", "-i", output,
                "-af", "volumedetect", "-f", "null", "-",
            ], capture_output=True, text=True)
            self.assertNotIn("mean_volume: -91.0 dB", impact.stderr)


if __name__ == "__main__":
    unittest.main()
