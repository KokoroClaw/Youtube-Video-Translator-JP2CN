"""
Utility functions for YouTube subtitle generator.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Any


def clean_filename(name: str) -> str:
    """
    Remove characters illegal in Windows filenames.

    Args:
        name: Original filename/title string.

    Returns:
        Cleaned string safe for use as filename or folder name.
    """
    # Windows illegal chars: \ / : * ? " < > |
    cleaned = re.sub(r'[\\/:*?"<>|]+', '_', name)
    # Also remove leading/trailing dots and spaces
    cleaned = cleaned.strip('. ')
    # Collapse multiple underscores
    cleaned = re.sub(r'_+', '_', cleaned)
    return cleaned


def get_ffmpeg_path() -> str:
    """Return the configured FFMPEG path (from FFMPEG_PATH env var)."""
    return os.environ.get("FFMPEG_PATH", "")


def get_ytdlp_path() -> str:
    """Return the configured YT-DLP path (from YTDLP_PATH env var)."""
    return os.environ.get("YTDLP_PATH", "")


def resolve_ffmpeg_command() -> tuple[str, dict[str, str]]:
    """Resolve ffmpeg.exe from FFMPEG_PATH and return its execution environment."""
    configured_value = get_ffmpeg_path()
    env = os.environ.copy()
    if not configured_value:
        return "ffmpeg", env

    configured = Path(configured_value)
    if configured.is_file():
        return str(configured), env

    candidate = configured / "ffmpeg.exe"
    if candidate.is_file():
        return str(candidate), env

    env["PATH"] = configured_value + os.pathsep + env.get("PATH", "")
    return "ffmpeg", env


def run_command(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """
    Run a shell command with proper encoding for Windows.

    Args:
        cmd: Command list to execute.
        **kwargs: Additional arguments to subprocess.run.

    Returns:
        CompletedProcess instance.
    """
    defaults = {
        "encoding": "utf-8",
        "errors": "replace",
        "capture_output": True,
    }
    defaults.update(kwargs)
    return subprocess.run(cmd, **defaults)


def format_timestamp(seconds: float) -> str:
    """
    Format seconds into ASS timestamp format (H:MM:SS.cc).

    Args:
        seconds: Time in seconds (float).

    Returns:
        ASS-formatted timestamp string.
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def merge_audio_video(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """
    Merge a video file and an audio file into a single MP4 using ffmpeg.
    Writes to a temp file first to avoid overwriting the input video.

    Args:
        video_path: Path to the video-only file (no audio track).
        audio_path: Path to the audio file (m4a).
        output_path: Path for the merged output file.

    Returns:
        Path to the merged output file.
    """
    ffmpeg_command, env = resolve_ffmpeg_command()

    # Write to a temp file first to avoid overwriting input
    temp_output = output_path.with_suffix(".tmp.mp4")

    cmd = [
        ffmpeg_command, "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-strict", "experimental",
        str(temp_output),
    ]
    try:
        result = run_command(cmd, env=env)
    except PermissionError as exc:
        raise RuntimeError(
            f"Windows 拒绝执行 FFmpeg：{ffmpeg_command}。"
            "请在普通 PowerShell 中运行 Web 服务，或检查该文件的执行权限。"
        ) from exc
    except FileNotFoundError as exc:
        raise RuntimeError(
            "找不到 ffmpeg.exe，请检查 .env 中的 FFMPEG_PATH。"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg merge failed:\n{result.stderr or result.stdout}")

    # Replace original with merged result
    temp_output.replace(output_path)
    return output_path
