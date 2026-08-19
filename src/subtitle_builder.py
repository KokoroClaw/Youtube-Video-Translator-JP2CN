"""
ASS subtitle builder - generates bilingual and Chinese-only ASS subtitles.
Loads style templates from preset .ass files in presets/styles/.
"""

import re
from pathlib import Path
from typing import Any

from src.utils import format_timestamp


def _scale_style_metrics(styles_block: str, scale: float) -> str:
    """Scale ASS style sizes from the 1080p preset canvas to the video canvas."""
    scalable_fields = (2, 16, 17, 19, 20, 21)
    scaled_lines: list[str] = []

    for line in styles_block.splitlines(keepends=True):
        if not line.startswith("Style: "):
            scaled_lines.append(line)
            continue

        newline = "\n" if line.endswith("\n") else ""
        fields = line.removeprefix("Style: ").rstrip("\r\n").split(",")
        if len(fields) < 22:
            scaled_lines.append(line)
            continue

        for index in scalable_fields:
            try:
                value = float(fields[index]) * scale
            except ValueError:
                continue
            if index in (2, 19, 20, 21):
                fields[index] = str(max(1, round(value)))
            else:
                fields[index] = f"{max(0, value):.1f}".rstrip("0").rstrip(".")

        scaled_lines.append("Style: " + ",".join(fields) + newline)

    return "".join(scaled_lines)


def _wrap_ass_text(text: str, max_chars: int) -> str:
    """Wrap CJK-friendly ASS text without changing its visible wording."""
    if max_chars < 1:
        return text

    lines: list[str] = []
    for source_line in text.replace("\\n", "\\N").split("\\N"):
        current = ""
        for word in source_line.split():
            chunks = [word[i:i + max_chars] for i in range(0, len(word), max_chars)] or [""]
            if len(chunks) > 1 and len(chunks[-1]) == 1 and chunks[-1] in "，。！？、,.!?：；:;）】』》」":
                punctuation = chunks.pop()
                chunks[-1] += punctuation
            for chunk in chunks:
                candidate = f"{current} {chunk}".strip() if current else chunk
                if current and len(candidate) > max_chars:
                    lines.append(current)
                    current = chunk
                else:
                    current = candidate
        if current:
            lines.append(current)

    return "\\N".join(lines) if lines else text


def load_preset(preset_name: str) -> str:
    """
    Load an ASS preset file and return its content.

    Args:
        preset_name: Name of preset file without extension (e.g. "dual", "zh").

    Returns:
        Full content of the preset file.
    """
    preset_dir = Path(__file__).parent.parent / "presets" / "styles"
    preset_path = preset_dir / f"{preset_name}.ass"
    if not preset_path.exists():
        raise FileNotFoundError(f"Preset not found: {preset_path}")
    with open(preset_path, "r", encoding="utf-8-sig") as f:
        return f.read()


def build_ass_header(title: str, preset_name: str = "dual",
                     width: int = 1920, height: int = 1080) -> str:
    """
    Build ASS header by loading a preset and replacing the Title field.

    Loads the full [Script Info] + [V4+ Styles] blocks from the preset file,
    replaces the Title, PlayResX and PlayResY values, and returns the complete
    header up to [Events].

    Args:
        title: Subtitle track title.
        preset_name: Preset file name (without .ass extension).
        width: Video width in pixels (for PlayResX). Defaults to 1920.
        height: Video height in pixels (for PlayResY). Defaults to 1080.

    Returns:
        ASS header content up to (but not including) [Events].
    """
    preset = load_preset(preset_name)

    # Extract both [Script Info] and [V4+ Styles] blocks from preset
    # Structure in preset: [Script Info] ... [V4+ Styles] ... [Events]
    match = re.search(
        r'(\[Script Info\].*?)(\[V4\+ Styles\].*?)(\[Events\])',
        preset,
        re.DOTALL
    )
    if not match:
        raise ValueError(f"Could not parse preset: {preset_name}.ass")

    script_info = match.group(1)  # [Script Info] block (includes PlayResX/Y)
    styles_block = match.group(2)  # [V4+ Styles] block

    # Style presets are authored against a 1080-line canvas. Scale their
    # font/outline/margins when the source uses another ASS PlayRes so that a
    # portrait 360x640 video does not receive 1080p-sized text.
    if preset_name == "dual" and height > 0:
        styles_block = _scale_style_metrics(styles_block, height / 1080)

    # Replace Title, PlayResX, PlayResY in [Script Info]
    script_info = re.sub(r'(Title: ).*', f'\\1{title}', script_info, count=1)
    script_info = re.sub(r'(PlayResX: )\d+', f'\\g<1>{width}', script_info, count=1)
    script_info = re.sub(r'(PlayResY: )\d+', f'\\g<1>{height}', script_info, count=1)

    return (
        script_info
        + styles_block
        + "[Events]\n"
        + "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def build_dual_ass(translated_segments: list[dict], title: str,
                   width: int = 1920, height: int = 1080) -> str:
    """
    Build bilingual ASS (Japanese + Chinese) from translated segments.
    Loads styles from presets/styles/dual.ass.

    Format: Chinese on top (white, larger), Japanese below (gray, smaller).

    Args:
        translated_segments: List of dicts with start, end, text, translation.
        title: Subtitle track title.
        width: Video width in pixels (for PlayResX). Defaults to 1920.
        height: Video height in pixels (for PlayResY). Defaults to 1080.

    Returns:
        Full ASS file content as string.
    """
    lines = [build_ass_header(f"{title} (Bilingual)", preset_name="dual",
                              width=width, height=height)]

    scale = height / 1080 if height > 0 else 1
    horizontal_margin = max(1, round(45 * scale))
    usable_width = max(1, width - 2 * horizontal_margin)
    zh_max_chars = max(12, usable_width // max(1, round(27 * scale)))
    jp_max_chars = max(16, usable_width // max(1, round(20 * scale)))

    for seg in translated_segments:
        start = format_timestamp(seg["start"])
        end = format_timestamp(seg["end"])
        zh = _wrap_ass_text(seg.get("translation", "").strip(), zh_max_chars)
        jp = _wrap_ass_text(seg.get("text", "").strip(), jp_max_chars)

        if not zh and not jp:
            continue

        # Top line: Chinese (Dual_ZH)
        if zh:
            lines.append(
                f"Dialogue: 0,{start},{end},Dual_ZH,Default,0,0,0,,{zh}"
            )
        # Bottom line: Japanese (Dual_JP)
        if jp:
            lines.append(
                f"Dialogue: 0,{start},{end},Dual_JP,Default,0,0,0,,{jp}"
            )

    return "\n".join(lines)


def build_zh_ass(translated_segments: list[dict], title: str,
                width: int = 1920, height: int = 1080) -> str:
    """
    Build Chinese-only ASS from translated segments.
    Loads styles from presets/styles/zh.ass.
    Reuses the same timing data (no re-translation needed).

    Args:
        translated_segments: List of dicts with start, end, text, translation.
        title: Subtitle track title.
        width: Video width in pixels (for PlayResX). Defaults to 1920.
        height: Video height in pixels (for PlayResY). Defaults to 1080.

    Returns:
        Full ASS file content as string.
    """
    lines = [build_ass_header(f"{title} (中文)", preset_name="zh",
                              width=width, height=height)]

    horizontal_margin = max(0, round(20 * (height / 1080 if height > 0 else 1)))
    usable_width = max(1, width - 2 * horizontal_margin)
    zh_max_chars = max(8, usable_width // 19)

    for seg in translated_segments:
        start = format_timestamp(seg["start"])
        end = format_timestamp(seg["end"])
        zh = _wrap_ass_text(seg.get("translation", "").strip(), zh_max_chars)

        if not zh:
            continue

        lines.append(
            f"Dialogue: 0,{start},{end},ZH_Only,Default,0,0,0,,{zh}"
        )

    return "\n".join(lines)


def build_subtitles(
    translated_segments: list[dict],
    output_dir: Path,
    title: str,
    video_info: dict[str, Any]
) -> tuple[Path, Path]:
    """
    Generate both dual.ass and zh.ass subtitle files.

    Args:
        translated_segments: Translated segment list with timing data.
        output_dir: Directory to write ASS files.
        title: Clean video title (for filenames).
        video_info: Dict with title/description/width/height (for ASS header).

    Returns:
        Tuple of (dual_ass_path, zh_ass_path).
    """
    output_dir = Path(output_dir)
    width = video_info.get("width", 1920)
    height = video_info.get("height", 1080)

    # Build and write dual ASS
    dual_content = build_dual_ass(
        translated_segments, video_info.get("title", title),
        width=width, height=height
    )
    dual_path = output_dir / f"{title}_dual.ass"
    with open(dual_path, "w", encoding="utf-8-sig") as f:
        f.write(dual_content)
    print(f"  Written: {dual_path.name}")

    # Build and write Chinese-only ASS (same data, different styles)
    zh_content = build_zh_ass(
        translated_segments, video_info.get("title", title),
        width=width, height=height
    )
    zh_path = output_dir / f"{title}_zh.ass"
    with open(zh_path, "w", encoding="utf-8-sig") as f:
        f.write(zh_content)
    print(f"  Written: {zh_path.name}")

    # Keep a structured, job-local editor document ready for the Web UI. It is
    # stored under .kotoba so it does not appear among downloadable result files.
    from src.subtitle_editor import load_subtitle_document
    load_subtitle_document(output_dir)

    return dual_path, zh_path
