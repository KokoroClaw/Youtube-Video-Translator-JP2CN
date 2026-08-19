"""Safe subprocess adapter for the third-party biliup command-line uploader."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, UnidentifiedImageError


UploadLog = Callable[[str], None]
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
UNICODE_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")


def bilibili_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA", "").strip()
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / "KotobaStudio" / "bilibili"


def biliup_cookie_path() -> Path:
    return bilibili_data_dir() / "cookies.json"


def find_biliup() -> str | None:
    configured = os.environ.get("BILIUP_PATH", "").strip()
    if configured and Path(configured).is_file():
        return str(Path(configured).resolve())
    bundled = Path(__file__).parent.parent / "tools" / "biliup.exe"
    if bundled.is_file():
        return str(bundled.resolve())
    return shutil.which("biliup")


def biliup_status() -> dict[str, object]:
    executable = find_biliup()
    cookie = biliup_cookie_path()
    return {
        "installed": executable is not None,
        "logged_in": cookie.is_file() and cookie.stat().st_size > 20,
        "cookie_location": str(cookie.parent),
    }


def launch_biliup_login() -> None:
    executable = find_biliup()
    if not executable:
        raise RuntimeError("尚未安装 biliup，请先配置 BILIUP_PATH")
    cookie = biliup_cookie_path()
    cookie.parent.mkdir(parents=True, exist_ok=True)
    creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    subprocess.Popen(
        [executable, "-u", str(cookie), "login"],
        cwd=cookie.parent,
        creationflags=creation_flags,
    )


@dataclass(slots=True)
class BilibiliSubmission:
    video_path: Path
    title: str
    description: str
    tags: str
    tid: int
    copyright: int = 2
    source: str = ""
    cover_path: Path | None = None


def prepare_bilibili_cover(source: Path, destination: Path) -> Path:
    """Convert a thumbnail to a real RGB JPEG regardless of its file suffix."""
    source = Path(source)
    destination = Path(destination)
    try:
        with Image.open(source) as image:
            image.convert("RGB").save(
                destination,
                format="JPEG",
                quality=92,
                optimize=True,
            )
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"封面不是有效图片：{source.name}") from exc
    return destination


def _clean_biliup_line(line: str) -> str:
    line = ANSI_ESCAPE.sub("", line)
    return UNICODE_ESCAPE.sub(lambda match: chr(int(match.group(1), 16)), line).strip()


def upload_to_bilibili(
    submission: BilibiliSubmission,
    log: UploadLog | None = None,
) -> str | None:
    """Upload one video after the caller has obtained explicit user confirmation."""
    executable = find_biliup()
    if not executable:
        raise RuntimeError("尚未安装 biliup，请先配置 BILIUP_PATH")
    cookie = biliup_cookie_path()
    if not cookie.is_file():
        raise RuntimeError("尚未登录 B 站，请先扫码登录")
    video = Path(submission.video_path).resolve()
    if not video.is_file():
        raise FileNotFoundError(f"找不到投稿视频：{video}")
    if submission.copyright not in {1, 2}:
        raise ValueError("copyright 只能是 1（自制）或 2（转载）")
    if submission.copyright == 2 and not submission.source.strip():
        raise ValueError("转载投稿必须填写来源地址")

    callback = log or (lambda _line: None)
    callback(
        f"准备投稿：分区 {submission.tid}，"
        f"{'转载' if submission.copyright == 2 else '自制'}，"
        f"{len([tag for tag in submission.tags.split(',') if tag.strip()])} 个标签"
    )

    with tempfile.TemporaryDirectory(prefix="kotoba-bili-cover-") as temp_dir:
        command = [
            executable,
            "-u", str(cookie),
            "upload",
            "--copyright", str(submission.copyright),
            "--source", submission.source.strip(),
            "--tid", str(submission.tid),
            "--title", submission.title.strip(),
            "--desc", submission.description.strip(),
            "--tag", submission.tags.strip(),
        ]
        if submission.cover_path:
            cover = Path(submission.cover_path).resolve()
            if cover.is_file():
                prepared_cover = prepare_bilibili_cover(
                    cover, Path(temp_dir) / "cover.jpg"
                )
                command.extend(["--cover", str(prepared_cover)])
                callback("封面已转换为标准 JPEG")
        command.append(str(video))

        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            command,
            cwd=video.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
        )
        output: list[str] = []
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = _clean_biliup_line(raw_line)
            if line:
                output.append(line)
                callback(line)
        return_code = process.wait()
    if return_code != 0:
        detail = "\n".join(output[-15:])
        if "code: -400" in detail:
            raise RuntimeError(
                "B 站返回 -400 请求错误。请检查分区 ID、标题、标签、"
                "稿件类型和转载来源后重试。\n" + detail
            )
        raise RuntimeError("B 站上传失败：\n" + detail)
    joined = "\n".join(output)
    match = re.search(r"\b(BV[0-9A-Za-z]{10})\b", joined)
    return match.group(1) if match else None
