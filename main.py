"""
YouTube JP→CN Subtitle Generator
YouTube日语字幕 → 中文翻译字幕生成器

Usage:
    python main.py <url> [--transcription-backend {openai,local}] [--model MODEL]
                   [--output DIR] [--no-video] [--no-thumb]

Default whisper model: large
Default output dir: {script_dir}/downloads/{video_title}/
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env file
dotenv_path = Path(__file__).parent / ".env"
if dotenv_path.exists():
    load_dotenv(dotenv_path)

from src.pipeline import PipelineOptions, run_pipeline


def parse_args():
    parser = argparse.ArgumentParser(
        description="YouTube JP→CN Subtitle Generator / YouTube日语字幕生成中文翻译",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python main.py "https://www.youtube.com/watch?v=xxxxx"
    python main.py "https://www.youtube.com/watch?v=xxxxx" --model medium
    python main.py "https://www.youtube.com/watch?v=xxxxx" --output ./output --no-video
        """
    )
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument(
        "--model",
        choices=["tiny", "base", "small", "medium", "large"],
        default="large",
        help="Local Whisper model size; ignored by OpenAI transcription (default: large)"
    )
    parser.add_argument(
        "--transcription-backend",
        choices=["openai", "local"],
        default=None,
        help="Transcription backend (default: TRANSCRIPTION_BACKEND or openai)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output directory (default: from OUTPUT_DIR in .env, else {script_dir}/downloads/)"
    )
    parser.add_argument(
        "--no-video",
        action="store_true",
        help="Skip video download (audio only for Whisper)"
    )
    parser.add_argument(
        "--no-thumb",
        action="store_true",
        help="Skip thumbnail download"
    )
    separator_group = parser.add_mutually_exclusive_group()
    separator_group.add_argument(
        "--separator",
        dest="use_separator",
        action="store_true",
        help="Enable vocal extraction before transcription (disabled by default)"
    )
    separator_group.add_argument(
        "--no-separator",
        dest="use_separator",
        action="store_false",
        help="Disable vocal extraction (default)"
    )
    parser.set_defaults(use_separator=False)
    parser.add_argument(
        "--no-auto-split",
        action="store_true",
        help="Disable automatic splitting of visually oversized subtitles",
    )
    parser.add_argument(
        "--subtitle-density",
        choices=["short", "standard", "compact"],
        default="standard",
        help="Automatic subtitle split density (default: standard)",
    )
    parser.add_argument(
        "--subtitle-lines",
        type=int,
        choices=[1, 2, 3],
        default=2,
        help="Maximum visual lines per timed subtitle event (default: 2)",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default="日本語の会話です。芸人のトークやコントが含まれる場合があります。",
        help="initial_prompt passed to Whisper to guide transcription (default: Japanese conversation hint)"
    )
    return parser.parse_args()


def main():
    # Avoid CP932 crashes when Chinese/Japanese text is printed on Windows.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()

    result = run_pipeline(PipelineOptions(
        url=args.url,
        output=args.output,
        download_video=not args.no_video,
        download_thumbnail=not args.no_thumb,
        use_separator=args.use_separator,
        initial_prompt=args.prompt,
        transcription_backend=args.transcription_backend,
        local_model=args.model,
        auto_split_subtitles=not args.no_auto_split,
        subtitle_density=args.subtitle_density,
        subtitle_max_lines=args.subtitle_lines,
    ))
    print(f"\n完成：{result.title}")
    print(f"输出目录：{result.output_dir}")


if __name__ == "__main__":
    main()
