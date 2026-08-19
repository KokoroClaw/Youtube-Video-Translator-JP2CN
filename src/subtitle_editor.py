"""Safe, job-local subtitle editing for the Web UI.

The editor keeps one canonical JSON document under ``.kotoba`` and regenerates
both Chinese-only and bilingual ASS files from it. Existing jobs are imported
from their ASS files on first use.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils import resolve_ffmpeg_command


STYLE_NAMES = {
    "zh_only": "ZH_Only",
    "dual_zh": "Dual_ZH",
    "dual_jp": "Dual_JP",
}

DEFAULT_STYLES: dict[str, dict[str, Any]] = {
    "zh_only": {
        "font_name": "Microsoft JhengHei UI", "font_size": 40,
        "primary_color": "#FFFFFF", "outline_color": "#000000",
        "bold": True, "outline": 4, "shadow": 0,
        "alignment": 2, "margin_v": 40,
    },
    "dual_zh": {
        "font_name": "Microsoft JhengHei UI", "font_size": 54,
        "primary_color": "#FFFFFF", "outline_color": "#000000",
        "bold": True, "outline": 3, "shadow": 0,
        "alignment": 2, "margin_v": 92,
    },
    "dual_jp": {
        "font_name": "Arial", "font_size": 40,
        "primary_color": "#D0D0D0", "outline_color": "#000000",
        "bold": False, "outline": 2, "shadow": 0,
        "alignment": 2, "margin_v": 38,
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_hashes(zh_path: Path, dual_path: Path) -> dict[str, str]:
    return {"zh": _hash_file(zh_path), "dual": _hash_file(dual_path)}


def _atomic_write(path: Path, content: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding=encoding)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _ass_time_to_seconds(value: str) -> float:
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})(?:[.:](\d{1,3}))?", value.strip())
    if not match:
        raise ValueError(f"无效 ASS 时间：{value}")
    hours, minutes, seconds, fraction = match.groups()
    fraction_seconds = int((fraction or "0").ljust(3, "0")[:3]) / 1000
    return round(int(hours) * 3600 + int(minutes) * 60 + int(seconds) + fraction_seconds, 3)


def _seconds_to_ass_time(value: float) -> str:
    centiseconds = max(0, round(float(value) * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{fraction:02d}"


def _ass_color_to_hex(value: str, fallback: str) -> str:
    match = re.search(r"&H(?:[0-9A-Fa-f]{2})?([0-9A-Fa-f]{6})", value)
    if not match:
        return fallback
    bbggrr = match.group(1)
    return f"#{bbggrr[4:6]}{bbggrr[2:4]}{bbggrr[0:2]}".upper()


def _hex_to_ass_color(value: str) -> str:
    match = re.fullmatch(r"#([0-9A-Fa-f]{6})", value)
    if not match:
        raise ValueError(f"无效颜色：{value}")
    rrggbb = match.group(1).upper()
    return f"&H00{rrggbb[4:6]}{rrggbb[2:4]}{rrggbb[0:2]}"


def _visible_text(value: str) -> str:
    value = re.sub(r"\{[^{}]*\}", "", value)
    return value.replace(r"\N", "\n").replace(r"\n", "\n").replace(r"\h", " ")


def _ass_text(value: str) -> str:
    if "{" in value or "}" in value:
        raise ValueError("字幕文本暂不支持 ASS 样式标签或花括号")
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", r"\N")


def _parse_ass(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    width_match = re.search(r"^PlayResX:\s*(\d+)", text, re.MULTILINE)
    height_match = re.search(r"^PlayResY:\s*(\d+)", text, re.MULTILINE)
    title_match = re.search(r"^Title:\s*(.*)$", text, re.MULTILINE)
    styles: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    section = ""
    for line in text.splitlines():
        if line.startswith("[") and line.endswith("]"):
            section = line
            continue
        if section == "[V4+ Styles]" and line.startswith("Style:"):
            fields = line.partition(":")[2].strip().split(",")
            if len(fields) < 23:
                continue
            name = fields[0].strip()
            default_key = {
                "Dual_JP": "dual_jp", "Dual_ZH": "dual_zh", "ZH_Only": "zh_only"
            }.get(name, "dual_zh")
            fallback = DEFAULT_STYLES[default_key]
            try:
                styles[name] = {
                    "font_name": fields[1].strip() or fallback["font_name"],
                    "font_size": float(fields[2]),
                    "primary_color": _ass_color_to_hex(fields[3], fallback["primary_color"]),
                    "outline_color": _ass_color_to_hex(fields[5], fallback["outline_color"]),
                    "bold": int(fields[7]) != 0,
                    "outline": float(fields[16]),
                    "shadow": float(fields[17]),
                    "alignment": int(fields[18]),
                    "margin_v": int(float(fields[21])),
                }
            except (TypeError, ValueError):
                continue
        elif section == "[Events]" and line.startswith("Dialogue:"):
            fields = line.partition(":")[2].lstrip().split(",", 9)
            if len(fields) != 10:
                continue
            try:
                events.append({
                    "start": _ass_time_to_seconds(fields[1]),
                    "end": _ass_time_to_seconds(fields[2]),
                    "style": fields[3].strip(),
                    "text": _visible_text(fields[9]),
                })
            except ValueError:
                continue
    return {
        "title": title_match.group(1).strip() if title_match else path.stem,
        "width": int(width_match.group(1)) if width_match else 1920,
        "height": int(height_match.group(1)) if height_match else 1080,
        "styles": styles,
        "events": events,
    }


def _find_project_files(
    output_dir: Path, require_video: bool = False
) -> tuple[Path, Path, Path | None]:
    zh_path = next(output_dir.glob("*_zh.ass"), None)
    dual_path = next(output_dir.glob("*_dual.ass"), None)
    video_path = next(output_dir.glob("*_video.mp4"), None)
    if not zh_path or not dual_path:
        raise FileNotFoundError("缺少 zh.ass 或 dual.ass 字幕文件")
    if require_video and not video_path:
        raise FileNotFoundError("缺少用于字幕预览的原视频")
    return zh_path, dual_path, video_path


def _style_from(parsed: dict[str, Any], name: str, default_key: str) -> dict[str, Any]:
    return {**DEFAULT_STYLES[default_key], **parsed["styles"].get(name, {})}


def _import_document(
    output_dir: Path, zh_path: Path, dual_path: Path, video_path: Path | None
) -> dict[str, Any]:
    zh = _parse_ass(zh_path)
    dual = _parse_ass(dual_path)
    grouped: dict[tuple[float, float], dict[str, Any]] = {}
    order: list[tuple[float, float]] = []

    def cue_for(start: float, end: float) -> dict[str, Any]:
        key = (start, end)
        if key not in grouped:
            grouped[key] = {"start": start, "end": end, "jp": "", "zh": ""}
            order.append(key)
        return grouped[key]

    for event in dual["events"]:
        cue = cue_for(event["start"], event["end"])
        language = "jp" if event["style"] == "Dual_JP" else "zh"
        cue[language] = "\n".join(filter(None, [cue[language], event["text"]]))
    for event in zh["events"]:
        cue = cue_for(event["start"], event["end"])
        if not cue["zh"]:
            cue["zh"] = event["text"]

    cues = []
    for index, key in enumerate(sorted(order), start=1):
        cue = grouped[key]
        if cue["zh"] or cue["jp"]:
            cues.append({"id": f"cue-{index:04d}", **cue})

    return {
        "schema_version": 1,
        "revision": hashlib.sha256((
            _hash_file(zh_path) + _hash_file(dual_path)
        ).encode("ascii")).hexdigest()[:24],
        "updated_at": _utc_now(),
        "title": dual["title"].removesuffix(" (Bilingual)"),
        "video": {"name": video_path.name if video_path else "", "width": dual["width"], "height": dual["height"]},
        "styles": {
            "zh_only": _style_from(zh, "ZH_Only", "zh_only"),
            "dual_zh": _style_from(dual, "Dual_ZH", "dual_zh"),
            "dual_jp": _style_from(dual, "Dual_JP", "dual_jp"),
        },
        "cues": cues,
        "source_hashes": _source_hashes(zh_path, dual_path),
    }


def _sidecar_path(output_dir: Path) -> Path:
    return output_dir / ".kotoba" / "subtitles.json"


def _write_sidecar(output_dir: Path, document: dict[str, Any]) -> None:
    _atomic_write(
        _sidecar_path(output_dir),
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
    )


def load_subtitle_document(output_dir: Path | str) -> dict[str, Any]:
    output = Path(output_dir).resolve()
    zh_path, dual_path, video_path = _find_project_files(output)
    sidecar = _sidecar_path(output)
    if sidecar.is_file():
        try:
            document = json.loads(sidecar.read_text(encoding="utf-8"))
            if document.get("source_hashes") == _source_hashes(zh_path, dual_path):
                return _public_document(document)
        except (OSError, ValueError, TypeError):
            pass
    document = _import_document(output, zh_path, dual_path, video_path)
    _write_sidecar(output, document)
    return _public_document(document)


def _validate_style(style: dict[str, Any]) -> dict[str, Any]:
    font_name = str(style.get("font_name", "")).strip()
    if not font_name or len(font_name) > 100 or "," in font_name:
        raise ValueError("字体名称无效")
    result = {
        "font_name": font_name,
        "font_size": float(style["font_size"]),
        "primary_color": str(style["primary_color"]).upper(),
        "outline_color": str(style["outline_color"]).upper(),
        "bold": bool(style.get("bold", False)),
        "outline": float(style["outline"]),
        "shadow": float(style["shadow"]),
        "alignment": int(style["alignment"]),
        "margin_v": int(style["margin_v"]),
    }
    if not 8 <= result["font_size"] <= 200:
        raise ValueError("字号必须在 8 到 200 之间")
    if not 0 <= result["outline"] <= 20 or not 0 <= result["shadow"] <= 20:
        raise ValueError("描边和阴影必须在 0 到 20 之间")
    if result["alignment"] not in range(1, 10):
        raise ValueError("字幕对齐位置无效")
    if not 0 <= result["margin_v"] <= 2000:
        raise ValueError("字幕边距必须在 0 到 2000 之间")
    _hex_to_ass_color(result["primary_color"])
    _hex_to_ass_color(result["outline_color"])
    return result


def _validate_document(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    raw_cues = payload.get("cues")
    raw_styles = payload.get("styles")
    if not isinstance(raw_cues, list) or not 1 <= len(raw_cues) <= 10000:
        raise ValueError("字幕必须包含 1 到 10000 个片段")
    if not isinstance(raw_styles, dict):
        raise ValueError("字幕样式无效")
    styles = {
        key: _validate_style(raw_styles.get(key, {}))
        for key in STYLE_NAMES
    }
    cues: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_cues, start=1):
        cue_id = str(raw.get("id") or f"cue-{index:04d}")[:80]
        if cue_id in seen_ids:
            cue_id = f"cue-{index:04d}-{uuid.uuid4().hex[:6]}"
        seen_ids.add(cue_id)
        start = round(float(raw["start"]), 3)
        end = round(float(raw["end"]), 3)
        if start < 0 or end <= start:
            raise ValueError(f"第 {index} 行的结束时间必须晚于开始时间")
        jp = str(raw.get("jp", "")).strip()
        zh = str(raw.get("zh", "")).strip()
        if len(jp) > 4000 or len(zh) > 4000:
            raise ValueError(f"第 {index} 行字幕过长")
        if not jp and not zh:
            raise ValueError(f"第 {index} 行不能同时缺少日文和中文")
        _ass_text(jp)
        _ass_text(zh)
        cues.append({"id": cue_id, "start": start, "end": end, "jp": jp, "zh": zh})
    cues.sort(key=lambda item: (item["start"], item["end"]))
    return cues, styles


def _style_line(name: str, style: dict[str, Any]) -> str:
    return (
        f"Style: {name},{style['font_name']},{style['font_size']:g},"
        f"{_hex_to_ass_color(style['primary_color'])},&H000000FF,"
        f"{_hex_to_ass_color(style['outline_color'])},&H80000000,"
        f"{-1 if style['bold'] else 0},0,0,0,100,100,0,0,1,"
        f"{style['outline']:g},{style['shadow']:g},{style['alignment']},"
        f"45,45,{style['margin_v']},134"
    )


def _header(title: str, width: int, height: int, style_lines: list[str]) -> str:
    return "\n".join([
        "[Script Info]", f"Title: {title}", "ScriptType: v4.00+", "WrapStyle: 0",
        f"PlayResX: {width}", f"PlayResY: {height}",
        "ScaledBorderAndShadow: yes", "YCbCr Matrix: None", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *style_lines, "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])


def _build_ass_files(document: dict[str, Any]) -> tuple[str, str]:
    title = str(document.get("title") or "Kotoba Subtitle")
    video = document["video"]
    width, height = int(video["width"]), int(video["height"])
    styles = document["styles"]
    zh_lines = [_header(
        f"{title} (中文)", width, height,
        [_style_line("ZH_Only", styles["zh_only"])],
    )]
    dual_lines = [_header(
        f"{title} (Bilingual)", width, height,
        [_style_line("Dual_JP", styles["dual_jp"]), _style_line("Dual_ZH", styles["dual_zh"])],
    )]
    for cue in document["cues"]:
        start, end = _seconds_to_ass_time(cue["start"]), _seconds_to_ass_time(cue["end"])
        if cue["zh"]:
            text = _ass_text(cue["zh"])
            zh_lines.append(f"Dialogue: 0,{start},{end},ZH_Only,Default,0,0,0,,{text}")
            dual_lines.append(f"Dialogue: 0,{start},{end},Dual_ZH,Default,0,0,0,,{text}")
        if cue["jp"]:
            dual_lines.append(
                f"Dialogue: 0,{start},{end},Dual_JP,Default,0,0,0,,{_ass_text(cue['jp'])}"
            )
    return "\n".join(zh_lines) + "\n", "\n".join(dual_lines) + "\n"


def _warnings(cues: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for index in range(1, len(cues)):
        if cues[index]["start"] < cues[index - 1]["end"]:
            warnings.append(f"第 {index} 行与第 {index + 1} 行时间重叠")
    return warnings[:100]


def _public_document(document: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in document.items() if key != "source_hashes"
    } | {"warnings": _warnings(document.get("cues", []))}


def save_subtitle_document(output_dir: Path | str, payload: dict[str, Any]) -> dict[str, Any]:
    output = Path(output_dir).resolve()
    zh_path, dual_path, video_path = _find_project_files(output)
    current = load_subtitle_document(output)
    if str(payload.get("revision", "")) != current["revision"]:
        raise RuntimeError("字幕已被其他程序修改，请重新载入后再保存")
    cues, styles = _validate_document(payload)
    document = {
        "schema_version": 1,
        "revision": uuid.uuid4().hex,
        "updated_at": _utc_now(),
        "title": current["title"],
        "video": {**current["video"], "name": video_path.name if video_path else ""},
        "styles": styles,
        "cues": cues,
    }
    zh_content, dual_content = _build_ass_files(document)
    backup_dir = output / ".kotoba" / "backups"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(zh_path, backup_dir / f"{stamp}_{zh_path.name}")
    shutil.copy2(dual_path, backup_dir / f"{stamp}_{dual_path.name}")
    sidecar = _sidecar_path(output)
    if sidecar.is_file():
        shutil.copy2(sidecar, backup_dir / f"{stamp}_subtitles.json")
    _atomic_write(zh_path, zh_content, encoding="utf-8-sig")
    _atomic_write(dual_path, dual_content, encoding="utf-8-sig")
    document["source_hashes"] = _source_hashes(zh_path, dual_path)
    _write_sidecar(output, document)
    return _public_document(document)


def render_exact_preview(
    output_dir: Path | str, timestamp: float, subtitle_type: str
) -> Path:
    output = Path(output_dir).resolve()
    zh_path, dual_path, video_path = _find_project_files(output, require_video=True)
    assert video_path is not None
    subtitle = zh_path if subtitle_type == "zh" else dual_path
    if subtitle_type not in {"zh", "dual"}:
        raise ValueError("预览类型必须是 zh 或 dual")
    if timestamp < 0:
        raise ValueError("预览时间不能小于零")
    work_dir = output / ".kotoba"
    work_dir.mkdir(parents=True, exist_ok=True)
    safe_ass = work_dir / f"preview-{uuid.uuid4().hex}.ass"
    preview = work_dir / f"preview-{uuid.uuid4().hex}.jpg"
    shutil.copy2(subtitle, safe_ass)
    ffmpeg_command, env = resolve_ffmpeg_command()
    command = [
        ffmpeg_command, "-y", "-i", str(video_path), "-ss", f"{timestamp:.3f}",
        "-vf", f"ass={safe_ass.name}", "-frames:v", "1", "-q:v", "2", preview.name,
    ]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            command, cwd=work_dir, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", creationflags=creation_flags,
            timeout=60, check=False,
        )
        if result.returncode != 0 or not preview.is_file():
            raise RuntimeError("精确预览生成失败：" + result.stderr[-1000:])
        return preview
    finally:
        safe_ass.unlink(missing_ok=True)
