import unittest
from unittest.mock import patch

import capcut_tts


class CapCutVietnameseVoiceTests(unittest.TestCase):
    def test_all_verified_vietnamese_voices_are_exposed(self):
        vietnamese = {
            key: value
            for key, value in capcut_tts.CAPCUT_VOICES.items()
            if key.startswith("🇻🇳")
        }
        self.assertEqual(22, len(vietnamese))
        self.assertEqual(
            ("multi_female_xinwenjieshuo_uranus_bigtts", "7637455039719640327"),
            vietnamese["🇻🇳 Nam Bản Tin"],
        )
        self.assertNotIn("🇻🇳 Hoai My", vietnamese)
        self.assertNotIn("🇻🇳 Nam Minh", vietnamese)

    @patch.object(capcut_tts, "submit_tts_task")
    def test_stale_vietnamese_voice_is_rejected_before_submit(self, submit):
        audio, subtitles = capcut_tts.tts_capcut("Xin chào", "🇻🇳 Nam Minh")
        self.assertIsNone(audio)
        self.assertIsNone(subtitles)
        submit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
