"""
YouTube video downloader using yt-dlp.
"""

import json
import os
from pathlib import Path
from typing import Any

from src.utils import get_ytdlp_path, get_ffmpeg_path, run_command


def _youtube_runtime_args() -> list[str]:
    """Return runtime and client options required by current YouTube extraction."""
    args = []
    runtime = os.environ.get("YTDLP_JS_RUNTIME", "node").strip()
    if runtime:
        args.extend(["--js-runtimes", runtime])

    force_ipv4 = os.environ.get("YTDLP_FORCE_IPV4", "true").strip().lower()
    if force_ipv4 in {"1", "true", "yes", "on"}:
        args.append("--force-ipv4")

    player_client = os.environ.get(
        "YTDLP_PLAYER_CLIENT", "web_embedded"
    ).strip()
    if player_client:
        args.extend([
            "--extractor-args",
            f"youtube:player_client={player_client}",
        ])
    return args


def get_video_info(url: str) -> dict[str, Any]:
    """
    Fetch video metadata via yt-dlp --dump-json.

    Args:
        url: YouTube video URL.

    Returns:
        Dictionary with keys: title, description, thumbnail, etc.
    """
    ytdlp = get_ytdlp_path()
    cmd = [ytdlp, *_youtube_runtime_args(), "--dump-json", "--no-download", url]
    result = run_command(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp --dump-json failed:\n{result.stderr or result.stdout}")
    if not result.stdout:
        raise RuntimeError(f"yt-dlp --dump-json returned no output:\n{result.stderr}")
    data = json.loads(result.stdout)
    return {
        "title": data.get("title", "unknown"),
        "description": data.get("description", ""),
        "thumbnail": data.get("thumbnail", ""),
        "duration": data.get("duration", 0),
        "width": data.get("width", 1920),
        "height": data.get("height", 1080),
    }


def download_media(
    url: str,
    output_dir: Path,
    title: str,
    download_video: bool = True,
    download_thumbnail: bool = True,
) -> tuple[Path, Path | None, Path | None]:
    """
    Download YouTube video and audio separately.

    Downloads:
    - Video stream (mp4) → title_video.mp4
    - Audio stream (m4a)  → title_audio.m4a  (for Whisper)

    Args:
        url: YouTube video URL.
        output_dir: Directory to save files.
        title: Cleaned video title (used for filenames).
        download_video: If True, download video + audio; if False, audio only.
        download_thumbnail: If True, also download thumbnail.

    Returns:
        Tuple of (video_path, audio_path, thumbnail_path or None).
        audio_path is always returned (needed for Whisper).
        video_path is None if download_video=False.
    """
    ytdlp = get_ytdlp_path()
    output_dir = Path(output_dir)

    # Always download audio (needed for Whisper)
    audio_path = output_dir / f"{title}_audio.m4a"
    if audio_path.exists():
        print("  Audio already exists, skipping download.")
    else:
        print("  Downloading audio stream...")
        audio_cmd = [
            ytdlp,
            *_youtube_runtime_args(),
            "-f", "bestaudio[ext=m4a]/bestaudio",
            "-o", str(audio_path),
            "--no-playlist",
            url,
        ]
        audio_result = run_command(audio_cmd)
        if audio_result.returncode != 0:
            raise RuntimeError(f"yt-dlp audio download failed:\n{audio_result.stderr}")

    # Download video stream separately
    video_path = None
    if download_video:
        video_path = output_dir / f"{title}_video_raw.mp4"
        if video_path.exists():
            print("  Video already exists, skipping download.")
        else:
            print("  Downloading video stream...")
            video_cmd = [
                ytdlp,
                *_youtube_runtime_args(),
                "-f", "bestvideo/best",
                "-o", str(video_path),
                "--no-playlist",
                url,
            ]
            video_result = run_command(video_cmd)
            if video_result.returncode != 0:
                raise RuntimeError(f"yt-dlp video download failed:\n{video_result.stderr}")

    # Download thumbnail
    thumb_path = None
    if download_thumbnail:
        thumb_name = f"{title}_thumb.jpg"
        thumb_path = output_dir / thumb_name
        if thumb_path.exists():
            print("  Thumbnail already exists, skipping download.")
        else:
            print("  Downloading thumbnail...")
            thumb_cmd = [
                ytdlp,
                *_youtube_runtime_args(),
                "--write-thumbnail",
                "--no-warnings",
                "--output", str(thumb_path.with_suffix(".%(ext)s")),
                "--no-download",
                url,
            ]
            thumb_result = run_command(thumb_cmd)
            if thumb_result.returncode == 0:
                for ext in ["webp", "jpg", "png"]:
                    candidate = thumb_path.with_suffix(f".{ext}")
                    if candidate.exists() and candidate != thumb_path:
                        candidate.rename(thumb_path)
            else:
                thumb_path = None

    return video_path, audio_path, thumb_path
