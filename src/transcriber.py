"""
Audio transcription using OpenAI Whisper.
"""

import whisper
from pathlib import Path

from src.utils import get_ffmpeg_path
import os


def transcribe_audio(audio_path: str | Path, model: str = "large") -> list[dict]:
    """
    Transcribe audio file using Whisper.

    Args:
        audio_path: Path to the audio/video file.
        model: Whisper model size (tiny, base, small, medium, large).

    Returns:
        List of segment dicts with keys: start, end, text, language.
    """
    # Set ffmpeg path for whisper
    model_options = whisper.DecodingOptions(language="ja")

    print(f"  Loading Whisper {model} model...")
    full_model = f"{model}"
    wmodel = whisper.load_model(full_model)

    print(f"  Transcribing {audio_path}...")
    # Run transcription
    result = wmodel.transcribe(
        str(audio_path),
        language="ja",
        fp16=False,  # CPU fallback
        verbose=False,
    )

    # Return only the needed fields
    segments = []
    for seg in result.get("segments", []):
        segments.append({
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"].strip(),
            "language": seg.get("language", "ja"),
        })

    return segments
