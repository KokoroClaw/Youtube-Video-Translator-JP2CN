"""Split visually oversized bilingual subtitles into timed ASS events."""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable


SemanticSplitter = Callable[[str, str, int], list[dict[str, str]] | None]

DENSITY_MULTIPLIERS = {
    "short": 0.78,
    "standard": 1.0,
    "compact": 1.2,
}
DENSITY_LINE_CAPS = {
    "short": 16.0,
    "standard": 24.0,
    "compact": 30.0,
}


@dataclass(slots=True)
class SplitResult:
    segments: list[dict[str, Any]]
    split_source_count: int
    added_segment_count: int
    capacity_units: float
    warnings: list[str]


def visual_units(text: str) -> float:
    """Approximate rendered width in CJK full-width character units."""
    total = 0.0
    for character in text.replace("\\N", "\n"):
        if character in "\r\n":
            continue
        if character.isspace():
            total += 0.35
        elif ord(character) > 127 or unicodedata.east_asian_width(character) in {"W", "F", "A"}:
            total += 1.0
        elif character.isupper():
            total += 0.7
        else:
            total += 0.55
    return total


def subtitle_capacity(
    video_info: dict[str, Any], density: str = "standard", max_lines: int = 2
) -> float:
    """Estimate how many CJK units fit in one timed subtitle event."""
    if density not in DENSITY_MULTIPLIERS:
        raise ValueError("字幕密度必须是 short、standard 或 compact")
    if not 1 <= max_lines <= 3:
        raise ValueError("每段字幕最多行数必须在 1 到 3 之间")
    width = max(1, int(video_info.get("width") or 1920))
    height = max(1, int(video_info.get("height") or 1080))
    scale = height / 1080

    # Use the stricter of the Chinese-only and bilingual layouts. This mirrors
    # the current presets while capping wide videos for comfortable reading.
    dual_font = max(8.0, 27 * scale)
    dual_margin = max(1.0, 45 * scale)
    dual_per_line = max(8.0, (width - 2 * dual_margin) / (dual_font * 0.95))
    zh_margin = max(0.0, 20 * scale)
    zh_only_per_line = max(8.0, (width - 2 * zh_margin) / (20 * 0.95))
    physical_per_line = min(dual_per_line, zh_only_per_line)
    adjusted = physical_per_line * DENSITY_MULTIPLIERS[density]
    per_line = math.floor(min(adjusted, DENSITY_LINE_CAPS[density]))
    return float(max(8, per_line) * max_lines)


def _cut_bonus(text: str, index: int) -> float:
    before = text[index - 1] if index else ""
    after = text[index] if index < len(text) else ""
    if before in "。！？!?；;：:、":
        return 4.0
    if before.isspace() or after.isspace():
        return 3.0
    if before in "はがをにでとへもやのねよわかけどし":
        return 1.2
    return 0.0


def _balanced_text_chunks(text: str, chunk_count: int) -> list[str]:
    """Split text near equal visual widths while preferring natural boundaries."""
    value = text.strip()
    if chunk_count <= 1 or not value:
        return [value]
    if len(value) < chunk_count:
        chunk_count = len(value)
    total = visual_units(value)
    boundaries: list[int] = []
    previous = 0
    for part in range(1, chunk_count):
        target = total * part / chunk_count
        best_index = previous + 1
        best_score = float("inf")
        for index in range(previous + 1, len(value) - (chunk_count - part) + 1):
            current = visual_units(value[:index])
            distance = abs(current - target)
            score = distance - _cut_bonus(value, index)
            if score < best_score:
                best_score = score
                best_index = index
        boundaries.append(best_index)
        previous = best_index
    chunks: list[str] = []
    start = 0
    for boundary in boundaries + [len(value)]:
        chunk = value[start:boundary].strip()
        if chunk:
            chunks.append(chunk)
        start = boundary
    if len(chunks) != chunk_count:
        # A whitespace-only slice is rare; a character-balanced fallback still
        # guarantees the requested number of non-empty chunks.
        chunks = []
        for index in range(chunk_count):
            start = round(len(value) * index / chunk_count)
            end = round(len(value) * (index + 1) / chunk_count)
            chunks.append(value[start:end].strip() or value[start:end])
    return chunks


def _valid_semantic_chunks(
    chunks: list[dict[str, str]] | None,
    japanese: str,
    chinese: str,
    chunk_count: int,
    capacity: float,
) -> bool:
    if not chunks or len(chunks) != chunk_count:
        return False
    if any(not part.get("jp", "").strip() or not part.get("zh", "").strip() for part in chunks):
        return False
    compact = lambda value: "".join(value.split())
    if compact("".join(part["jp"] for part in chunks)) != compact(japanese):
        return False
    if compact("".join(part["zh"] for part in chunks)) != compact(chinese):
        return False
    return (
        max(visual_units(part["zh"]) for part in chunks) <= capacity * 1.3
        and max(visual_units(part["jp"]) for part in chunks) <= capacity * 1.65
    )


def _timed_boundaries(
    segment: dict[str, Any], japanese_chunks: list[str], min_duration: float
) -> list[float]:
    start = float(segment["start"])
    end = float(segment["end"])
    chunk_count = len(japanese_chunks)
    if chunk_count <= 1:
        return [start, end]
    units = [max(0.1, visual_units(chunk)) for chunk in japanese_chunks]
    total_units = sum(units)
    ratios: list[float] = []
    running = 0.0
    for units_in_chunk in units[:-1]:
        running += units_in_chunk
        ratios.append(running / total_units)

    words = sorted(
        [
            word for word in segment.get("words", [])
            if isinstance(word, dict)
            and start <= float(word.get("start", start)) <= end
            and start <= float(word.get("end", end)) <= end + 0.05
        ],
        key=lambda word: float(word["start"]),
    )
    word_units = [max(0.1, visual_units(str(word.get("word", "")))) for word in words]
    word_total = sum(word_units)
    boundaries = [start]
    for index, ratio in enumerate(ratios, start=1):
        candidate = start + (end - start) * ratio
        if len(words) >= chunk_count and word_total > 0:
            target = word_total * ratio
            accumulated = 0.0
            word_index = 0
            for word_index, width in enumerate(word_units):
                accumulated += width
                if accumulated >= target:
                    break
            if word_index < len(words) - 1:
                candidate = (
                    float(words[word_index]["end"])
                    + float(words[word_index + 1]["start"])
                ) / 2
        earliest = boundaries[-1] + min_duration
        latest = end - (chunk_count - index) * min_duration
        boundaries.append(round(min(max(candidate, earliest), latest), 3))
    boundaries.append(end)
    return boundaries


def split_oversized_segments(
    segments: list[dict[str, Any]],
    video_info: dict[str, Any],
    *,
    density: str = "standard",
    max_lines: int = 2,
    min_duration: float = 0.7,
    semantic_splitter: SemanticSplitter | None = None,
) -> SplitResult:
    """Return bilingual segments whose text and time ranges are both split."""
    capacity = subtitle_capacity(video_info, density=density, max_lines=max_lines)
    output: list[dict[str, Any]] = []
    warnings: list[str] = []
    split_sources = 0
    added = 0

    for source_index, segment in enumerate(segments, start=1):
        japanese = str(segment.get("text", "")).strip()
        chinese = str(segment.get("translation", "")).strip()
        required = max(
            1,
            math.ceil(visual_units(chinese) / capacity),
            math.ceil(visual_units(japanese) / (capacity * 1.25)),
        )
        duration = max(0.0, float(segment["end"]) - float(segment["start"]))
        possible = max(1, int(duration // min_duration))
        chunk_count = min(required, possible, 8)
        if required <= 1 or chunk_count <= 1:
            if required > 1:
                warnings.append(
                    f"第 {source_index} 段文字过长但时长不足 {min_duration:.1f} 秒，未强制切分"
                )
            output.append(dict(segment))
            continue

        chunks: list[dict[str, str]] | None = None
        if semantic_splitter:
            try:
                candidate = semantic_splitter(japanese, chinese, chunk_count)
                if _valid_semantic_chunks(candidate, japanese, chinese, chunk_count, capacity):
                    chunks = candidate
                else:
                    warnings.append(f"第 {source_index} 段语义切分结果不平衡，已使用本地边界")
            except Exception:
                warnings.append(f"第 {source_index} 段语义切分失败，已使用本地边界")
        if chunks is None:
            jp_chunks = _balanced_text_chunks(japanese, chunk_count)
            zh_chunks = _balanced_text_chunks(chinese, chunk_count)
            chunks = [
                {"jp": jp_chunks[index], "zh": zh_chunks[index]}
                for index in range(chunk_count)
            ]

        boundaries = _timed_boundaries(
            segment, [chunk["jp"] for chunk in chunks], min_duration
        )
        for part_index, chunk in enumerate(chunks):
            output.append({
                "start": boundaries[part_index],
                "end": boundaries[part_index + 1],
                "text": chunk["jp"],
                "translation": chunk["zh"],
                "language": segment.get("language", "ja"),
                "words": [
                    word for word in segment.get("words", [])
                    if boundaries[part_index] <= float(word.get("start", 0))
                    and float(word.get("end", 0)) <= boundaries[part_index + 1] + 0.05
                ],
                "auto_split": True,
                "split_source_index": source_index,
                "split_part": part_index + 1,
            })
        split_sources += 1
        added += chunk_count - 1

    return SplitResult(
        segments=output,
        split_source_count=split_sources,
        added_segment_count=added,
        capacity_units=capacity,
        warnings=warnings,
    )
