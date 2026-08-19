"""Reusable YouTube subtitle processing pipeline for CLI and Web UI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.downloader import download_media, get_video_info
from src.subtitle_builder import build_subtitles
from src.subtitle_splitter import split_oversized_segments
from src.transcriber import transcribe_audio
from src.translator import Translator
from src.utils import clean_filename, merge_audio_video


ProgressCallback = Callable[[int, str, str], None]


@dataclass(slots=True)
class PipelineOptions:
    url: str
    output: str | None = None
    download_video: bool = True
    download_thumbnail: bool = True
    use_separator: bool = False
    initial_prompt: str = "日本語の会話です。芸人のトークやコントが含まれる場合があります。"
    transcription_backend: str | None = None
    local_model: str = "large"
    auto_split_subtitles: bool = True
    subtitle_density: str = "standard"
    subtitle_max_lines: int = 2


@dataclass(slots=True)
class PipelineResult:
    title: str
    output_dir: Path
    files: list[Path]
    segment_count: int
    translation_backend: str


def _default_progress(_percent: int, stage: str, message: str) -> None:
    print(f"[{stage}] {message}")


def run_pipeline(
    options: PipelineOptions,
    progress: ProgressCallback | None = None,
) -> PipelineResult:
    """Run the complete workflow and report stable milestone progress."""
    report = progress or _default_progress

    report(5, "准备视频", "正在获取 YouTube 视频信息")
    info = get_video_info(options.url)
    title = clean_filename(info["title"])

    if options.output:
        base_dir = Path(options.output)
    elif os.environ.get("OUTPUT_DIR", "").strip():
        base_dir = Path(os.environ["OUTPUT_DIR"].strip())
    else:
        base_dir = Path(__file__).parent.parent / "downloads"
    output_dir = base_dir / title
    output_dir.mkdir(parents=True, exist_ok=True)

    report(18, "下载素材", f"正在下载《{info['title']}》")
    video_path, audio_path, _thumb_path = download_media(
        options.url,
        output_dir,
        title,
        download_video=options.download_video,
        download_thumbnail=options.download_thumbnail,
    )

    dual_path = output_dir / f"{title}_dual.ass"
    zh_path = output_dir / f"{title}_zh.ass"
    if dual_path.exists() and zh_path.exists():
        report(67, "复用字幕", "检测到已有字幕，跳过 OpenAI 转写和翻译")
        segment_count = sum(
            1
            for line in zh_path.read_text(encoding="utf-8-sig").splitlines()
            if line.startswith("Dialogue:")
        )
        translation_backend = "已缓存"
    else:
        backend = options.transcription_backend or os.environ.get(
            "TRANSCRIPTION_BACKEND", "openai"
        )
        model = (
            os.environ.get("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
            if backend == "openai"
            else options.local_model
        )
        report(42, "语音识别", f"正在使用 {model} 识别日语")
        segments = transcribe_audio(
            str(audio_path),
            model=options.local_model,
            initial_prompt=options.initial_prompt,
            use_separator=options.use_separator,
            backend=backend,
        )

        report(67, "翻译字幕", f"正在翻译 {len(segments)} 个字幕片段")
        translator = Translator()
        translated_segments = translator.translate_segments(segments)

        if options.auto_split_subtitles:
            report(78, "优化字幕", "正在检查过长字幕并同步拆分时间轴")
            split_result = split_oversized_segments(
                translated_segments,
                info,
                density=options.subtitle_density,
                max_lines=options.subtitle_max_lines,
                semantic_splitter=translator.split_bilingual_segment,
            )
            translated_segments = split_result.segments
            if split_result.split_source_count:
                report(
                    82,
                    "优化字幕",
                    f"已拆分 {split_result.split_source_count} 个过长片段，"
                    f"新增 {split_result.added_segment_count} 段时间轴",
                )
            for warning in split_result.warnings:
                print(f"  [Subtitle Splitter] {warning}")

        report(84, "生成字幕", "正在生成双语与中文字幕")
        build_subtitles(
            translated_segments=translated_segments,
            output_dir=output_dir,
            title=title,
            video_info=info,
        )
        segment_count = len(translated_segments)
        translation_backend = translator.backend_name

    info_path = output_dir / f"{title}_info.txt"
    info_path.write_text(
        f"title: {info['title']}\n"
        f"url: {options.url}\n"
        f"description: {info.get('description', '')[:350]}\n",
        encoding="utf-8",
    )

    if video_path:
        final_video = output_dir / f"{title}_video.mp4"
        if not final_video.exists():
            report(92, "封装视频", "正在合并视频与音频")
            merge_audio_video(video_path, audio_path, final_video)
        for temporary in (video_path, audio_path):
            if temporary.exists() and temporary != final_video:
                temporary.unlink()

    files = sorted(path for path in output_dir.iterdir() if path.is_file())
    report(100, "处理完成", f"已生成 {len(files)} 个结果文件")
    return PipelineResult(
        title=info["title"],
        output_dir=output_dir,
        files=files,
        segment_count=segment_count,
        translation_backend=translation_backend,
    )
