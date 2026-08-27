import ast
from pathlib import Path
import unittest


TOOL_PATH = Path(__file__).with_name("tool.py")


def _literal_assignment(name):
    tree = ast.parse(TOOL_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError(f"Không tìm thấy assignment {name}")


class KoreanTtsPolicyTests(unittest.TestCase):
    def test_all_live_korean_edge_voices_are_selectable(self):
        voices = _literal_assignment("KOREAN_EDGE_VOICES")
        edge_voices = _literal_assignment("EDGE_VOICES")
        self.assertEqual(
            [
                "🇰🇷 Hyunsu Đa Ngôn Ngữ (Nam)",
                "🇰🇷 InJoon (Nam)",
                "🇰🇷 SunHi (Nữ)",
            ],
            voices,
        )
        self.assertEqual(
            {
                "ko-KR-HyunsuMultilingualNeural",
                "ko-KR-InJoonNeural",
                "ko-KR-SunHiNeural",
            },
            {edge_voices[name] for name in voices},
        )

    def test_render_paths_explicitly_stop_when_audio_is_missing(self):
        source = TOOL_PATH.read_text(encoding="utf-8")
        self.assertIn("if _missing_audio_scenes:", source)
        self.assertIn("if _veo_missing_audio:", source)
        self.assertIn("if not is_valid_audio(_src_audio_r):", source)
        self.assertNotIn("TTS lỗi, dùng âm thanh im lặng", source)
        self.assertNotIn("anullsrc=r=44100", source)


if __name__ == "__main__":
    unittest.main()
