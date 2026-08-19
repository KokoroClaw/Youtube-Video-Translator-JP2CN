import unittest

from src.subtitle_splitter import (
    split_oversized_segments,
    subtitle_capacity,
    visual_units,
)


class SubtitleSplitterTests(unittest.TestCase):
    def test_vertical_capacity_is_stricter_than_horizontal_and_density_changes_it(self):
        vertical = {"width": 360, "height": 640}
        horizontal = {"width": 1920, "height": 1080}

        self.assertLess(
            subtitle_capacity(vertical, "standard", 2),
            subtitle_capacity(horizontal, "standard", 2),
        )
        self.assertLess(
            subtitle_capacity(vertical, "short", 2),
            subtitle_capacity(vertical, "compact", 2),
        )

    def test_long_bilingual_segment_is_split_with_word_timestamp_boundary(self):
        segment = {
            "start": 0.0,
            "end": 4.0,
            "text": "これはとても長い日本語字幕なので自然な場所で分割します",
            "translation": "这是一段非常长的中文字幕内容需要根据竖屏视频宽度在自然的位置自动切成两个独立的时间轴片段",
            "language": "ja",
            "words": [
                {"word": "これは", "start": 0.0, "end": 0.9},
                {"word": "とても長い", "start": 1.0, "end": 1.9},
                {"word": "日本語字幕", "start": 2.0, "end": 2.9},
                {"word": "分割します", "start": 3.0, "end": 4.0},
            ],
        }
        semantic = lambda jp, zh, _count: [
            {"jp": jp[:14], "zh": zh[:24]},
            {"jp": jp[14:], "zh": zh[24:]},
        ]

        result = split_oversized_segments(
            [segment], {"width": 360, "height": 640},
            density="short", max_lines=2, semantic_splitter=semantic,
        )

        self.assertEqual(result.split_source_count, 1)
        self.assertEqual(len(result.segments), 2)
        self.assertEqual(result.segments[0]["end"], result.segments[1]["start"])
        self.assertGreaterEqual(result.segments[0]["end"], 0.7)
        self.assertEqual(
            "".join(item["translation"] for item in result.segments),
            segment["translation"],
        )
        self.assertTrue(all(item["auto_split"] for item in result.segments))

    def test_invalid_semantic_split_falls_back_without_losing_text(self):
        segment = {
            "start": 0,
            "end": 5,
            "text": "あ" * 50,
            "translation": "中" * 80,
            "words": [],
        }

        result = split_oversized_segments(
            [segment], {"width": 360, "height": 640},
            density="standard", max_lines=2,
            semantic_splitter=lambda *_args: [{"jp": "改写", "zh": "错误"}],
        )

        self.assertGreater(len(result.segments), 1)
        self.assertEqual(
            "".join(item["text"] for item in result.segments), segment["text"]
        )
        self.assertEqual(
            "".join(item["translation"] for item in result.segments),
            segment["translation"],
        )
        self.assertTrue(any("本地边界" in warning for warning in result.warnings))

    def test_too_short_segment_is_not_split_into_flashes(self):
        segment = {
            "start": 0,
            "end": 0.6,
            "text": "長い日本語",
            "translation": "中" * 100,
            "words": [],
        }

        result = split_oversized_segments(
            [segment], {"width": 360, "height": 640}
        )

        self.assertEqual(len(result.segments), 1)
        self.assertTrue(any("时长不足" in warning for warning in result.warnings))

    def test_visual_units_treat_cjk_as_wider_than_ascii(self):
        self.assertGreater(visual_units("中文字幕"), visual_units("abcd"))


if __name__ == "__main__":
    unittest.main()
