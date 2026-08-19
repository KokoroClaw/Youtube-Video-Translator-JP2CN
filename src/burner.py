"""Burn ASS subtitles into an MP4 using a compatibility-focused H.264 profile."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from src.utils import resolve_ffmpeg_command


BurnProgress = Callable[[int, str], None]


def _ass_duration_seconds(subtitle_path: Path) -> float:
    """Read the last ASS Dialogue end timestamp for progress estimation."""
    duration = 0.0
    for line in subtitle_path.read_text(encoding="utf-8-sig").splitlines():
        if not line.startswith("Dialogue:"):
            continue
        fields = line.split(",", 3)
        if len(fields) < 3:
            continue
        match = re.fullmatch(r"(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", fields[2])
        if not match:
            continue
        hours, minutes, seconds = match.groups()
        duration = max(
            duration,
            int(hours) * 3600 + int(minutes) * 60 + float(seconds),
        )
    return duration


def burn_subtitles(
    video_path: Path | str,
    subtitle_path: Path | str,
    output_path: Path | str,
    progress: BurnProgress | None = None,
) -> Path:
    """Create a hard-subbed H.264 MP4 without modifying source files."""
    video = Path(video_path).resolve()
    subtitle = Path(subtitle_path).resolve()
    output = Path(output_path).resolve()
    if not video.is_file():
        raise FileNotFoundError(f"找不到原始视频：{video}")
    if not subtitle.is_file() or subtitle.suffix.lower() != ".ass":
        raise FileNotFoundError(f"找不到 ASS 字幕：{subtitle}")
    if output == video:
        raise ValueError("压制输出不能覆盖原始视频")

    output.parent.mkdir(parents=True, exist_ok=True)
    safe_subtitle = output.parent / ".kotoba_burn.ass"
    temporary_output = output.with_suffix(".tmp.mp4")
    duration = _ass_duration_seconds(subtitle)
    ffmpeg_command, env = resolve_ffmpeg_command()
    callback = progress or (lambda _percent, _message: None)

    if temporary_output.exists():
        temporary_output.unlink()
    shutil.copy2(subtitle, safe_subtitle)
    callback(1, "正在准备字幕与编码器")

    command = [
        ffmpeg_command,
        "-y",
        "-i", video.name,
        "-vf", f"ass={safe_subtitle.name}",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        "-nostats",
        temporary_output.name,
    ]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(
            command,
            cwd=output.parent,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
        )
        output_tail: list[str] = []
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            output_tail.append(line)
            output_tail = output_tail[-30:]
            if line.startswith(("out_time_ms=", "out_time_us=")) and duration > 0:
                try:
                    elapsed = int(line.split("=", 1)[1]) / 1_000_000
                    percent = min(99, max(1, int(elapsed / duration * 100)))
                    callback(percent, f"正在压制字幕 {percent}%")
                except ValueError:
                    pass
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(
                "FFmpeg 字幕压制失败：\n" + "\n".join(output_tail[-12:])
            )
        temporary_output.replace(output)
        callback(100, "字幕压制完成")
        return output
    except PermissionError as exc:
        raise RuntimeError(
            f"Windows 拒绝执行 FFmpeg：{ffmpeg_command}。"
            "请从普通 PowerShell 启动 Web 服务。"
        ) from exc
    finally:
        safe_subtitle.unlink(missing_ok=True)
        if temporary_output.exists():
            temporary_output.unlink()
