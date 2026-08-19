import unittest

from src.subtitle_builder import build_dual_ass, build_zh_ass


class SubtitleBuilderTests(unittest.TestCase):
    def test_dual_styles_scale_for_portrait_canvas(self):
        content = build_dual_ass(
            [{"start": 0, "end": 1, "text": "日本語", "translation": "中文"}],
            "portrait",
            width=360,
            height=640,
        )

        self.assertIn("Style: Dual_JP,Arial,12,", content)
        self.assertIn(",2,27,27,17,134", content)
        self.assertIn("Style: Dual_ZH,Microsoft JhengHei UI,16,", content)
        self.assertIn(",8,27,27,47,134", content)
        self.assertIn("PlayResX: 360", content)
        self.assertIn("PlayResY: 640", content)

    def test_dual_text_wraps_long_cjk_lines(self):
        content = build_dual_ass(
            [{
                "start": 0,
                "end": 1,
                "text": "あ" * 30,
                "translation": "中" * 24,
            }],
            "wrap",
            width=360,
            height=640,
        )

        self.assertIn("中" * 19 + "\\N" + "中" * 5, content)
        self.assertIn("あ" * 25 + "\\N" + "あ" * 5, content)

    def test_dual_wrap_does_not_orphan_punctuation(self):
        content = build_dual_ass(
            [{"start": 0, "end": 1, "text": "あ" * 25 + "?", "translation": "中文"}],
            "punctuation",
            width=360,
            height=640,
        )

        self.assertNotIn("あ" * 25 + "?\\N", content)
        self.assertIn("あ" * 25 + "?", content)

    def test_chinese_only_subtitle_wraps_for_portrait_width(self):
        content = build_zh_ass(
            [{"start": 0, "end": 1, "translation": "中" * 30}],
            "portrait",
            width=360,
            height=640,
        )

        self.assertIn("中" * 17 + "\\N" + "中" * 13, content)


if __name__ == "__main__":
    unittest.main()
