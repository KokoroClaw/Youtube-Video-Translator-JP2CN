"""
YouTube JP→CN Subtitle Generator
YouTube日语字幕 → 中文翻译字幕生成器

Usage:
    python main.py <url> [--model {tiny,base,small,medium,large}] [--output DIR] [--no-video] [--no-thumb]

Default whisper model: large
Default output dir: {script_dir}/downloads/{video_title}/
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env file
dotenv_path = Path(__file__).parent / ".env"
if dotenv_path.exists():
    load_dotenv(dotenv_path)

from src.downloader import download_media, get_video_info
from src.transcriber import transcribe_audio
from src.translator import Translator
from src.subtitle_builder import build_subtitles
from src.utils import clean_filename, merge_audio_video


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
        help="Whisper model size (default: large)"
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
    return parser.parse_args()


def main():
    args = parse_args()

    print(f"\n{'='*60}")
    print("  YouTube JP→CN Subtitle Generator")
    print(f"{'='*60}\n")

    # Step 1: Get video info (metadata only, fast)
    print("[1/5] Fetching video metadata...")
    info = get_video_info(args.url)
    title = clean_filename(info["title"])
    print(f"  Title: {info['title']}")

    # Determine output directory (priority: CLI arg > OUTPUT_DIR env > default)
    if args.output:
        base_dir = Path(args.output)
    elif os.environ.get("OUTPUT_DIR", "").strip():
        base_dir = Path(os.environ["OUTPUT_DIR"].strip())
    else:
        base_dir = Path(__file__).parent / "downloads"
    output_dir = base_dir / title

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"  Output: {output_dir}")

    # Step 2: Download video + audio separately
    print("\n[2/5] Downloading media streams...")
    video_path, audio_path, thumb_path = download_media(
        args.url,
        output_dir,
        title,
        download_video=not args.no_video,
        download_thumbnail=not args.no_thumb
    )
    print(f"  Audio: {audio_path.name}")
    if video_path:
        print(f"  Video: {video_path.name}")

    # Step 3: Transcribe audio with Whisper (always uses audio, not video)
    print(f"\n[3/5] Transcribing audio with Whisper ({args.model})...")
    segments = transcribe_audio(str(audio_path), model=args.model)
    print(f"  Transcribed {len(segments)} segments")

    # Step 4: Translate Japanese → Chinese
    print("\n[4/5] Translating Japanese → Chinese...")
    translator = Translator()
    translated_segments = translator.translate_segments(segments)
    print(f"  Translated {len(translated_segments)} segments via {translator.backend_name}")

    # Step 5: Build ASS subtitles
    print("\n[5/5] Building ASS subtitles...")
    build_subtitles(
        translated_segments=translated_segments,
        output_dir=output_dir,
        title=title,
        video_info=info
    )

    # Write info.txt
    info_path = output_dir / f"{title}_info.txt"
    with open(info_path, "w", encoding="utf-8") as f:
        f.write(f"title: {info['title']}\n")
        f.write(f"url: {args.url}\n")
        desc = info.get("description", "")[:350]
        f.write(f"description: {desc}\n")
    print(f"  Written: {info_path.name}")

    # Step 6: Merge video + audio (if video was downloaded)
    if video_path:
        print("\n[6/6] Merging video + audio into final MP4...")
        final_video = output_dir / f"{title}_video.mp4"
        merge_audio_video(video_path, audio_path, final_video)
        print(f"  Merged: {final_video.name}")
        # Clean up temp files: raw video and audio are both temporary now
        video_path.unlink()
        audio_path.unlink()
        print(f"  Cleaned up temporary files")

    print(f"\n{'='*60}")
    print("  Done! Output files:")
    print(f"{'='*60}")
    for f in sorted(output_dir.iterdir()):
        print(f"  {f.name}")
    print(f"\n  All files in: {output_dir}\n")


if __name__ == "__main__":
    main()
