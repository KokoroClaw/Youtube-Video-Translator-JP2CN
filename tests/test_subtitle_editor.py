import tempfile
import unittest
from pathlib import Path

from src.subtitle_builder import build_dual_ass, build_zh_ass
from src.subtitle_editor import load_subtitle_document, save_subtitle_document


class SubtitleEditorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.output = Path(self.temporary.name)
        segments = [{
            "start": 1.0,
            "end": 2.5,
            "text": "こんにちは",
            "translation": "你好",
        }]
        (self.output / "test_dual.ass").write_text(
            build_dual_ass(segments, "test"), encoding="utf-8-sig"
        )
        (self.output / "test_zh.ass").write_text(
            build_zh_ass(segments, "test"), encoding="utf-8-sig"
        )
        (self.output / "test_video.mp4").write_bytes(b"video-placeholder")

    def tearDown(self):
        self.temporary.cleanup()

    def test_imports_existing_dual_and_zh_ass(self):
        document = load_subtitle_document(self.output)

        self.assertEqual(len(document["cues"]), 1)
        self.assertEqual(document["cues"][0]["jp"], "こんにちは")
        self.assertEqual(document["cues"][0]["zh"], "你好")
        self.assertIn("zh_only", document["styles"])
        self.assertTrue((self.output / ".kotoba" / "subtitles.json").is_file())

    def test_save_updates_both_ass_files_and_creates_backups(self):
        document = load_subtitle_document(self.output)
        document["cues"][0]["zh"] = "早上好"
        document["styles"]["dual_zh"]["font_name"] = "Microsoft YaHei"

        saved = save_subtitle_document(self.output, document)

        self.assertNotEqual(saved["revision"], document["revision"])
        self.assertIn("早上好", (self.output / "test_zh.ass").read_text(encoding="utf-8-sig"))
        dual = (self.output / "test_dual.ass").read_text(encoding="utf-8-sig")
        self.assertIn("早上好", dual)
        self.assertIn("Microsoft YaHei", dual)
        backups = list((self.output / ".kotoba" / "backups").glob("*.ass"))
        self.assertEqual(len(backups), 2)

    def test_stale_revision_refuses_to_overwrite_external_change(self):
        document = load_subtitle_document(self.output)
        dual_path = self.output / "test_dual.ass"
        dual_path.write_text(
            dual_path.read_text(encoding="utf-8-sig") + "; external edit\n",
            encoding="utf-8-sig",
        )

        with self.assertRaisesRegex(RuntimeError, "重新载入"):
            save_subtitle_document(self.output, document)

    def test_overlap_is_reported_as_warning_but_can_be_saved(self):
        document = load_subtitle_document(self.output)
        document["cues"].append({
            "id": "cue-overlap",
            "start": 2.0,
            "end": 3.0,
            "jp": "次",
            "zh": "下一句",
        })

        saved = save_subtitle_document(self.output, document)

        self.assertEqual(len(saved["warnings"]), 1)
        self.assertIn("重叠", saved["warnings"][0])

    def test_can_edit_subtitles_when_video_was_not_downloaded(self):
        (self.output / "test_video.mp4").unlink()

        document = load_subtitle_document(self.output)
        document["cues"][0]["zh"] = "没有视频也能保存"
        saved = save_subtitle_document(self.output, document)

        self.assertEqual(saved["video"]["name"], "")
        self.assertIn(
            "没有视频也能保存",
            (self.output / "test_zh.ass").read_text(encoding="utf-8-sig"),
        )


if __name__ == "__main__":
    unittest.main()
