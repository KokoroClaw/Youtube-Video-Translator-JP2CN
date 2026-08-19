"""Audio transcription backends for the subtitle pipeline."""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from openai import OpenAI


SEPARATOR_OUTPUT = Path("audio_separator_output")
MAX_OPENAI_UPLOAD_BYTES = 25_000_000


def _audio_separator_vocal_extract(audio_path: str) -> str:
    """Extract vocals and return the resulting WAV path."""
    from audio_separator.separator.separator import Separator

    print("  [Audio-Separator] Extracting vocals...")

    if SEPARATOR_OUTPUT.exists():
        shutil.rmtree(SEPARATOR_OUTPUT)
    SEPARATOR_OUTPUT.mkdir(parents=True, exist_ok=True)

    model_dir = os.path.join(tempfile.gettempdir(), "audio-separator-models")
    separator = Separator(
        output_dir=str(SEPARATOR_OUTPUT),
        output_format="WAV",
        model_file_dir=model_dir,
        output_single_stem="Vocals",
    )
    separator.model_filename = ["htdemucs_ft.yaml"]
    print("  [Audio-Separator] Loading model...")
    separator.load_model("htdemucs_ft.yaml")
    print(f"  [Audio-Separator] Model loaded: {separator.model_filename}")

    separator.separate(audio_path)

    for root, _dirs, files in os.walk(SEPARATOR_OUTPUT):
        for filename in files:
            if filename.lower().endswith(".wav"):
                vocals_path = Path(root, filename).resolve()
                print(f"  [Audio-Separator] Vocals extracted: {vocals_path}")
                return str(vocals_path)

    print("  [Audio-Separator] Warning: vocals file not found; using original audio")
    return audio_path


def _segment_field(segment: Any, field: str, default: Any = None) -> Any:
    """Read a field from either an SDK model object or a dictionary."""
    if isinstance(segment, dict):
        return segment.get(field, default)
    return getattr(segment, field, default)


def _normalize_word(raw_word: Any) -> dict[str, Any] | None:
    """Normalize one provider word timestamp without assuming SDK object types."""
    text = str(
        _segment_field(raw_word, "word", _segment_field(raw_word, "text", ""))
    ).strip()
    if not text:
        return None
    try:
        start = float(_segment_field(raw_word, "start", 0.0))
        end = float(_segment_field(raw_word, "end", start))
    except (TypeError, ValueError):
        return None
    if end < start:
        return None
    return {"word": text, "start": start, "end": end}


def _normalize_segments(
    raw_segments: list[Any] | None,
    raw_words: list[Any] | None = None,
) -> list[dict]:
    """Convert provider segments to the format expected by subtitle_builder."""
    segments = []
    global_words = [
        word for raw in (raw_words or []) if (word := _normalize_word(raw))
    ]
    for raw_segment in raw_segments or []:
        text = str(_segment_field(raw_segment, "text", "")).strip()
        if not text:
            continue
        start = float(_segment_field(raw_segment, "start", 0.0))
        end = float(_segment_field(raw_segment, "end", 0.0))
        own_words = [
            word
            for raw in (_segment_field(raw_segment, "words", None) or [])
            if (word := _normalize_word(raw))
        ]
        words = own_words or [
            word for word in global_words
            if start - 0.02 <= (word["start"] + word["end"]) / 2 <= end + 0.02
        ]
        segments.append({
            "start": start,
            "end": end,
            "text": text,
            "language": "ja",
            "words": words,
        })
    return segments


def _transcribe_openai(
    audio_path: str | Path,
    initial_prompt: str | None = None,
) -> list[dict]:
    """Transcribe Japanese audio with OpenAI whisper-1 and timestamps."""
    path = Path(audio_path)
    if not path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")
    if path.stat().st_size > MAX_OPENAI_UPLOAD_BYTES:
        size_mb = path.stat().st_size / 1_000_000
        raise ValueError(
            f"Audio file is {size_mb:.1f} MB; OpenAI transcription uploads are "
            "limited to 25 MB. Compress or split the audio before retrying."
        )

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key or api_key.startswith("your_"):
        raise RuntimeError("OPENAI_API_KEY is missing or still a placeholder")

    model = os.environ.get("OPENAI_TRANSCRIPTION_MODEL", "whisper-1").strip()
    if model != "whisper-1":
        raise ValueError(
            "OPENAI_TRANSCRIPTION_MODEL must be whisper-1 because this pipeline "
            "requires segment timestamps"
        )

    client = OpenAI(api_key=api_key, max_retries=5, timeout=600.0)
    request = {
        "model": model,
        "language": "ja",
        "response_format": "verbose_json",
        "timestamp_granularities": ["segment", "word"],
        "temperature": 0,
    }
    if initial_prompt:
        request["prompt"] = initial_prompt

    print(f"  Uploading audio to OpenAI {model}...")
    with path.open("rb") as audio_file:
        result = client.audio.transcriptions.create(file=audio_file, **request)

    segments = _normalize_segments(
        getattr(result, "segments", None), getattr(result, "words", None)
    )
    print(f"  OpenAI transcription complete. {len(segments)} segments.")
    return segments


def _transcribe_local(
    audio_path: str | Path,
    model: str = "large",
    initial_prompt: str | None = None,
) -> list[dict]:
    """Transcribe Japanese audio with the locally installed Whisper model."""
    import whisper

    print(f"  Loading local Whisper {model} model...")
    whisper_model = whisper.load_model(model)
    print("  Transcribing audio locally...")
    result = whisper_model.transcribe(
        str(audio_path),
        language="ja",
        initial_prompt=initial_prompt,
        fp16=True,
        verbose=False,
        logprob_threshold=-1.5,
        compression_ratio_threshold=2.4,
        word_timestamps=True,
    )
    segments = _normalize_segments(result.get("segments", []))
    print(f"  Local transcription complete. {len(segments)} segments.")
    return segments


def transcribe_audio(
    audio_path: str | Path,
    model: str = "large",
    initial_prompt: str | None = None,
    use_separator: bool = False,
    backend: str | None = None,
) -> list[dict]:
    """Transcribe audio with the configured OpenAI or local backend."""
    selected_backend = (
        backend or os.environ.get("TRANSCRIPTION_BACKEND", "openai")
    ).strip().lower()
    if selected_backend not in {"openai", "local"}:
        raise ValueError(
            "TRANSCRIPTION_BACKEND must be either 'openai' or 'local'"
        )

    prepared_audio = str(audio_path)
    if use_separator:
        prepared_audio = _audio_separator_vocal_extract(prepared_audio)
    else:
        print("  [Audio-Separator] Skipped")

    if selected_backend == "openai":
        return _transcribe_openai(prepared_audio, initial_prompt=initial_prompt)
    return _transcribe_local(
        prepared_audio,
        model=model,
        initial_prompt=initial_prompt,
    )
