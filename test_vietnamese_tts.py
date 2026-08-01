import unittest

from vietnamese_tts import normalize_vietnamese_tts, number_to_vietnamese


class VietnameseTtsNormalizationTests(unittest.TestCase):
    def test_number_ending_in_five_uses_lam(self):
        self.assertEqual("chín mươi lăm", number_to_vietnamese(95))

    def test_expands_percentages(self):
        self.assertEqual(
            "chín mươi lăm phần trăm người xem, bốn mươi phần trăm bỏ qua.",
            normalize_vietnamese_tts("95% người xem, 40% bỏ qua."),
        )

    def test_phoneticizes_common_creator_terms(self):
        self.assertEqual(
            "a phi li ét trên tíc tốc shop dùng ây ai.",
            normalize_vietnamese_tts("Affiliate trên TikTok Shop dùng AI."),
        )

    def test_reads_large_integer(self):
        self.assertEqual("một trăm triệu", number_to_vietnamese(100_000_000))


if __name__ == "__main__":
    unittest.main()
