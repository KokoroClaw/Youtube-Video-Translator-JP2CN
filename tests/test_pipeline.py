import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.pipeline import PipelineOptions, run_pipeline


class PipelineTests(unittest.TestCase):
    @patch("src.pipeline.merge_audio_video")
    @patch("src.pipeline.Translator")
    @patch("src.pipeline.transcribe_audio")
    @patch("src.pipeline.download_media")
    @patch("src.pipeline.get_video_info")
    def test_existing_subtitles_resume_without_openai_calls(
        self, get_info, download_media, transcribe, translator_class, merge
    ):
        get_info.return_value = {
            "title": "续跑视频", "description": "", "width": 1920, "height": 1080
        }
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "续跑视频"
            output_dir.mkdir()
            (output_dir / "续跑视频_dual.ass").write_text(
                "Dialogue: dual", encoding="utf-8-sig"
            )
            (output_dir / "续跑视频_zh.ass").write_text(
                "Dialogue: zh", encoding="utf-8-sig"
            )
            video = output_dir / "raw.mp4"
            audio = output_dir / "raw.m4a"
            video.write_bytes(b"video")
            audio.write_bytes(b"audio")
            download_media.return_value = video, audio, None

            def fake_merge(_video, _audio, final):
                final.write_bytes(b"final")
                return final

            merge.side_effect = fake_merge
            result = run_pipeline(
                PipelineOptions(url="https://youtu.be/test", output=directory),
                progress=lambda *_args: None,
            )

            self.assertEqual(result.segment_count, 1)
            self.assertEqual(result.translation_backend, "已缓存")
            transcribe.assert_not_called()
            translator_class.assert_not_called()

    @patch("src.pipeline.merge_audio_video")
    @patch("src.pipeline.build_subtitles")
    @patch("src.pipeline.split_oversized_segments")
    @patch("src.pipeline.Translator")
    @patch("src.pipeline.transcribe_audio")
    @patch("src.pipeline.download_media")
    @patch("src.pipeline.get_video_info")
    def test_pipeline_reports_progress_and_cleans_temporary_media(
        self, get_info, download_media, transcribe, translator_class,
        split_segments, build_subtitles, merge,
    ):
        get_info.return_value = {
            "title": "测试视频", "description": "", "width": 1920, "height": 1080
        }
        transcribe.return_value = [
            {"start": 0, "end": 1, "text": "先輩", "language": "ja"}
        ]
        translator = Mock()
        translator.backend_name = "OpenAI"
        translator.translate_segments.return_value = [
            {"start": 0, "end": 1, "text": "先輩", "translation": "前辈"}
        ]
        translator_class.return_value = translator
        split_segments.return_value = SimpleNamespace(
            segments=translator.translate_segments.return_value,
            split_source_count=0,
            added_segment_count=0,
            warnings=[],
        )

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "测试视频"

            def fake_download(*_args, **_kwargs):
                video = output_dir / "raw.mp4"
                audio = output_dir / "raw.m4a"
                video.write_bytes(b"video")
                audio.write_bytes(b"audio")
                return video, audio, None

            def fake_subtitles(**_kwargs):
                (output_dir / "测试视频_dual.ass").write_text("dual", encoding="utf-8")
                (output_dir / "测试视频_zh.ass").write_text("zh", encoding="utf-8")

            def fake_merge(_video, _audio, final):
                final.write_bytes(b"final")
                return final

            download_media.side_effect = fake_download
            build_subtitles.side_effect = fake_subtitles
            merge.side_effect = fake_merge
            events = []

            result = run_pipeline(
                PipelineOptions(url="https://youtu.be/test", output=directory),
                progress=lambda percent, stage, message: events.append((percent, stage, message)),
            )

            self.assertEqual(result.segment_count, 1)
            split_segments.assert_called_once()
            self.assertEqual(split_segments.call_args.kwargs["density"], "standard")
            self.assertEqual(split_segments.call_args.kwargs["max_lines"], 2)
            self.assertEqual(events[-1][0], 100)
            self.assertTrue((output_dir / "测试视频_video.mp4").exists())
            self.assertFalse((output_dir / "raw.mp4").exists())
            self.assertFalse((output_dir / "raw.m4a").exists())


if __name__ == "__main__":
    unittest.main()
