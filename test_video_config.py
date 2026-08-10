import unittest

from video_config import normalize_import_video_config


class ImportedVideoConfigTests(unittest.TestCase):
    def test_normalizes_supported_fields(self):
        result = normalize_import_video_config({
            "topic": " Lịch sử ra đời của Sushi ",
            "language": "Vietnamese",
            "total_duration": 60,
            "target_seconds_per_scene": 7,
            "aspect_ratio": "9:16",
            "tts_rate": 1.3,
            "tts_speed": 1.6,
            "subtitles": True,
        })
        self.assertEqual("Lịch sử ra đời của Sushi", result["topic"])
        self.assertEqual("Vietnamese", result["language"])
        self.assertEqual(60, result["total_duration"])
        self.assertEqual(7, result["target_seconds_per_scene"])
        self.assertEqual("9:16 (Shorts/TikTok)", result["aspect"])
        self.assertEqual("1.3", result["tts_rate"])
        self.assertTrue(result["subtitles"])

    def test_accepts_tts_speed_alias_and_clamps_widget_ranges(self):
        result = normalize_import_video_config({
            "total_duration": 5,
            "target_seconds_per_scene": 99,
            "tts_speed": 1.34,
        })
        self.assertEqual(15, result["total_duration"])
        self.assertEqual(30, result["target_seconds_per_scene"])
        self.assertEqual("1.3", result["tts_rate"])

    def test_ignores_derived_and_invalid_fields(self):
        result = normalize_import_video_config({
            "language": "French",
            "base_words_per_second": 100,
            "actual_words_per_second": 100,
            "target_words_per_scene": 999,
        })
        self.assertEqual({}, result)


if __name__ == "__main__":
    unittest.main()
