import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.transcriber import _normalize_segments, _transcribe_openai


class TranscriberTests(unittest.TestCase):
    def test_normalize_segments_accepts_sdk_objects_and_dicts(self):
        result = _normalize_segments([
            SimpleNamespace(
                start=1, end=2.5, text="  日本語  ",
                words=[SimpleNamespace(start=1.1, end=1.8, word="日本語")],
            ),
            {"start": 3, "end": 4, "text": "次です"},
            {"start": 5, "end": 6, "text": "   "},
        ])

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["text"], "日本語")
        self.assertEqual(result[1]["start"], 3.0)
        self.assertEqual(result[0]["words"][0]["word"], "日本語")
        self.assertTrue(all(item["language"] == "ja" for item in result))

    @patch.dict(
        os.environ,
        {
            "OPENAI_API_KEY": "sk-test-not-a-real-key",
            "OPENAI_TRANSCRIPTION_MODEL": "whisper-1",
        },
        clear=False,
    )
    @patch("src.transcriber.OpenAI")
    def test_openai_transcription_requests_segment_timestamps(self, openai_cls):
        fake_create = Mock(return_value=SimpleNamespace(segments=[
            SimpleNamespace(start=0.25, end=1.75, text=" テストです ")
        ]))
        openai_cls.return_value.audio.transcriptions.create = fake_create

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir, "sample.m4a")
            audio_path.write_bytes(b"fake audio")
            result = _transcribe_openai(audio_path, initial_prompt="日本語")

        self.assertEqual(result[0]["text"], "テストです")
        kwargs = fake_create.call_args.kwargs
        self.assertEqual(kwargs["model"], "whisper-1")
        self.assertEqual(kwargs["language"], "ja")
        self.assertEqual(kwargs["response_format"], "verbose_json")
        self.assertEqual(kwargs["timestamp_granularities"], ["segment", "word"])
        self.assertEqual(kwargs["prompt"], "日本語")


if __name__ == "__main__":
    unittest.main()
