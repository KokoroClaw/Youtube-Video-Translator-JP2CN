"""Local Web UI entry point for the subtitle generator."""

from __future__ import annotations

import os
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlparse

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask


ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

from src.glossary import DEFAULT_GLOSSARY_PATH, GlossaryStore
from src.pipeline import PipelineOptions, PipelineResult, run_pipeline
from src.burner import burn_subtitles
from src.bilibili_uploader import (
    BilibiliSubmission,
    biliup_status,
    launch_biliup_login,
    upload_to_bilibili,
)
from src.bilibili_categories import BILIBILI_CATEGORIES, VALID_BILIBILI_TIDS
from src.subtitle_editor import (
    load_subtitle_document,
    render_exact_preview,
    save_subtitle_document,
)


class JobRequest(BaseModel):
    url: str = Field(min_length=1)
    download_video: bool = True
    download_thumbnail: bool = True
    use_separator: bool = False
    initial_prompt: str = "日本語の会話です。芸人のトークやコントが含まれる場合があります。"
    auto_split_subtitles: bool = True
    subtitle_density: Literal["short", "standard", "compact"] = "standard"
    subtitle_max_lines: int = Field(default=2, ge=1, le=3)


class GlossaryCreate(BaseModel):
    source: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=500)
    enabled: bool = True


class GlossaryUpdate(BaseModel):
    source: str | None = Field(default=None, min_length=1, max_length=200)
    target: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None


class BurnRequest(BaseModel):
    subtitle_type: Literal["zh", "dual"]


class BilibiliUploadRequest(BaseModel):
    video_name: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=2000)
    tags: str = Field(min_length=1, max_length=200)
    tid: int = Field(gt=0)
    copyright: Literal[1, 2] = 2
    source: str = Field(default="", max_length=500)
    use_thumbnail: bool = True
    confirm_publish: bool = False


class SubtitleUpdateRequest(BaseModel):
    revision: str = Field(min_length=1, max_length=100)
    cues: list[dict[str, Any]]
    styles: dict[str, dict[str, Any]]


class SubtitlePreviewRequest(BaseModel):
    timestamp: float = Field(ge=0)
    subtitle_type: Literal["zh", "dual"] = "dual"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and (
        host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")
    )


class JobManager:
    """In-memory, single-worker job manager for a local desktop workflow."""

    def __init__(self, history_path: Path | str = ROOT / "data" / "last_job.json"):
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._active_job_id: str | None = None
        self._active_operation: str | None = None
        self._history_path = Path(history_path)
        self._load_history()

    def _load_history(self) -> None:
        if not self._history_path.exists():
            return
        try:
            job = json.loads(self._history_path.read_text(encoding="utf-8"))
            if job.get("id") and job.get("status") in {"completed", "failed"}:
                recovered = self._recover_source_url(job)
                self._jobs[job["id"]] = job
                if recovered:
                    self._persist(job)
        except (OSError, ValueError, TypeError):
            return

    @staticmethod
    def _recover_source_url(job: dict[str, Any]) -> bool:
        """Backfill source_url for jobs created before it was persisted."""
        if _valid_youtube_url(str(job.get("source_url") or "")):
            return False
        output_dir = Path(str(job.get("output_dir") or ""))
        if not output_dir.is_dir():
            return False
        for info_path in output_dir.glob("*_info.txt"):
            try:
                lines = info_path.read_text(encoding="utf-8-sig").splitlines()
            except OSError:
                continue
            for line in lines:
                if not line.lower().startswith("url:"):
                    continue
                candidate = line.partition(":")[2].strip()
                if _valid_youtube_url(candidate):
                    job["source_url"] = candidate
                    return True
        return False

    def _persist(self, job: dict[str, Any]) -> None:
        payload = {key: value for key, value in job.items() if key != "result"}
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._history_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self._history_path)

    def start(self, request: JobRequest) -> dict[str, Any]:
        if not _valid_youtube_url(request.url):
            raise ValueError("请输入有效的 YouTube 视频地址")
        with self._lock:
            if self._active_job_id:
                active = self._jobs.get(self._active_job_id)
                if active and active["status"] in {"queued", "running"}:
                    raise RuntimeError("已有任务正在运行，请等待它完成")
            job_id = uuid.uuid4().hex
            job = {
                "id": job_id,
                "status": "queued",
                "progress": 0,
                "stage": "等待开始",
                "message": "任务已加入本地队列",
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
                "logs": [],
                "files": [],
                "error": None,
                "result": None,
                "source_url": request.url.strip(),
                "burn": None,
                "upload": None,
            }
            self._jobs[job_id] = job
            self._active_job_id = job_id
        thread = threading.Thread(
            target=self._run,
            args=(job_id, request),
            daemon=True,
            name=f"subtitle-job-{job_id[:8]}",
        )
        thread.start()
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return self._public_job(self._jobs[job_id])

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._jobs:
                return None
            latest_job = max(
                self._jobs.values(), key=lambda item: item["created_at"]
            )
            return self._public_job(latest_job)

    @staticmethod
    def _public_job(job: dict[str, Any]) -> dict[str, Any]:
        public = {
            key: value
            for key, value in job.items()
            if key not in {"result", "output_dir"}
        }
        public["files"] = [
            {
                **item,
                "url": (
                    f"/api/jobs/{job['id']}/files/"
                    f"{quote(item['name'], safe='')}"
                ),
            }
            for item in job.get("files", [])
        ]
        return public

    def result_file(self, job_id: str, filename: str) -> Path:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or not job.get("output_dir"):
                raise KeyError(job_id)
            output_dir = Path(job["output_dir"]).resolve()
            allowed_names = {item["name"] for item in job.get("files", [])}
            allowed = {
                name: (output_dir / name).resolve()
                for name in allowed_names
            }
            if filename not in allowed:
                raise KeyError(filename)
            path = allowed[filename]
            if path.parent != output_dir or not path.is_file():
                raise KeyError(filename)
            return path

    def _subtitle_output_dir(self, job_id: str) -> Path:
        job = self._jobs.get(job_id)
        if not job or job.get("status") != "completed" or not job.get("output_dir"):
            raise ValueError("只能编辑已经完成的字幕任务")
        return Path(job["output_dir"]).resolve()

    def get_subtitles(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            output_dir = self._subtitle_output_dir(job_id)
            job = self._jobs[job_id]
            video = next(output_dir.glob("*_video.mp4"), None)
            document = load_subtitle_document(output_dir)
            document["video_url"] = f"/api/jobs/{job_id}/media" if video else None
            document["operation_active"] = bool(self._active_operation)
            document["job_title"] = job.get("title") or document.get("title")
            return document

    def save_subtitles(
        self, job_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            output_dir = self._subtitle_output_dir(job_id)
            if self._active_operation:
                raise RuntimeError("压制或上传进行中，暂时不能保存字幕")
            document = save_subtitle_document(output_dir, payload)
            job = self._jobs[job_id]
            # Existing hard-subbed videos no longer represent the edited ASS.
            # Keep them on disk for recovery, but remove them from UI/upload choices.
            job["files"] = [
                item for item in job.get("files", [])
                if "_hardsub_" not in item["name"]
            ]
            for item in job["files"]:
                if item["name"].lower().endswith(".ass"):
                    path = output_dir / item["name"]
                    if path.is_file():
                        item["size"] = path.stat().st_size
            job["burn"] = {
                "status": "stale",
                "subtitle_type": None,
                "progress": 0,
                "message": "字幕已修改，请重新压制硬字幕",
                "output_name": None,
                "error": None,
            }
            if job.get("upload"):
                job["upload"].update({
                    "status": "stale",
                    "message": "字幕已修改，历史投稿不包含本次修改",
                    "error": None,
                })
            job["updated_at"] = _utc_now()
            self._persist(job)
            document["video_url"] = (
                f"/api/jobs/{job_id}/media" if document["video"].get("name") else None
            )
            document["operation_active"] = False
            document["job_title"] = job.get("title") or document.get("title")
            return document

    def preview_paths(self, job_id: str) -> Path:
        with self._lock:
            return self._subtitle_output_dir(job_id)

    def preview_video(self, job_id: str) -> Path:
        with self._lock:
            output_dir = self._subtitle_output_dir(job_id)
            video = next(output_dir.glob("*_video.mp4"), None)
            if not video or not video.is_file():
                raise FileNotFoundError("当前任务没有可预览的原视频")
            return video

    def start_burn(self, job_id: str, subtitle_type: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.get("status") != "completed" or not job.get("output_dir"):
                raise ValueError("只能压制已经完成的字幕任务")
            if self._active_operation:
                raise RuntimeError("已有压制或上传任务正在运行")
            output_dir = Path(job["output_dir"])
            video = next(output_dir.glob("*_video.mp4"), None)
            subtitle = next(output_dir.glob(f"*_{subtitle_type}.ass"), None)
            if not video or not subtitle:
                raise FileNotFoundError("缺少原始视频或所选 ASS 字幕")
            prefix = video.stem.removesuffix("_video")
            output = output_dir / f"{prefix}_hardsub_{subtitle_type}.mp4"
            job["burn"] = {
                "status": "queued",
                "subtitle_type": subtitle_type,
                "progress": 0,
                "message": "字幕压制已加入队列",
                "output_name": output.name,
                "error": None,
            }
            self._active_operation = f"burn:{job_id}"
        threading.Thread(
            target=self._run_burn,
            args=(job_id, video, subtitle, output),
            daemon=True,
            name=f"burn-{job_id[:8]}",
        ).start()
        return self.get(job_id)

    def _run_burn(
        self, job_id: str, video: Path, subtitle: Path, output: Path
    ) -> None:
        try:
            def update(percent: int, message: str) -> None:
                with self._lock:
                    self._jobs[job_id]["burn"].update({
                        "status": "running",
                        "progress": percent,
                        "message": message,
                    })

            result = burn_subtitles(video, subtitle, output, update)
            with self._lock:
                job = self._jobs[job_id]
                file_item = {
                    "name": result.name,
                    "size": result.stat().st_size,
                    "url": "",
                }
                job["files"] = [
                    item for item in job["files"] if item["name"] != result.name
                ] + [file_item]
                job["burn"].update({
                    "status": "completed",
                    "progress": 100,
                    "message": "硬字幕视频已经生成",
                })
                self._persist(job)
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job["burn"].update({
                    "status": "failed", "message": str(exc), "error": str(exc)
                })
                self._persist(job)
        finally:
            with self._lock:
                self._active_operation = None

    def start_upload(
        self, job_id: str, request: BilibiliUploadRequest
    ) -> dict[str, Any]:
        if not request.confirm_publish:
            raise ValueError("公开投稿前必须勾选发布确认")
        if request.tid not in VALID_BILIBILI_TIDS:
            raise ValueError("请选择分区表中的有效 B 站视频分区")
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or not job.get("output_dir"):
                raise ValueError("字幕任务不存在")
            if self._active_operation:
                raise RuntimeError("已有压制或上传任务正在运行")
            allowed_names = {item["name"] for item in job.get("files", [])}
            if request.video_name not in allowed_names:
                raise ValueError("只能上传当前任务生成的文件")
            video = Path(job["output_dir"]) / request.video_name
            if video.suffix.lower() != ".mp4" or not video.is_file():
                raise ValueError("请选择有效的 MP4 文件")
            cover = None
            if request.use_thumbnail:
                cover = next(Path(job["output_dir"]).glob("*_thumb.jpg"), None)
            submission = BilibiliSubmission(
                video_path=video,
                title=request.title,
                description=request.description,
                tags=request.tags,
                tid=request.tid,
                copyright=request.copyright,
                source=request.source,
                cover_path=cover,
            )
            job["upload"] = {
                "status": "queued",
                "message": "投稿已加入队列",
                "logs": [],
                "bvid": None,
                "error": None,
                "request": {
                    "video_name": request.video_name,
                    "title": request.title,
                    "description": request.description,
                    "tags": request.tags,
                    "tid": request.tid,
                    "copyright": request.copyright,
                    "source": request.source,
                    "use_thumbnail": request.use_thumbnail,
                },
            }
            self._active_operation = f"upload:{job_id}"
        threading.Thread(
            target=self._run_upload,
            args=(job_id, submission),
            daemon=True,
            name=f"upload-{job_id[:8]}",
        ).start()
        return self.get(job_id)

    def _run_upload(self, job_id: str, submission: BilibiliSubmission) -> None:
        try:
            def add_log(line: str) -> None:
                with self._lock:
                    upload = self._jobs[job_id]["upload"]
                    upload["status"] = "running"
                    upload["message"] = line[-240:]
                    upload["logs"].append(line[-500:])
                    upload["logs"] = upload["logs"][-80:]

            bvid = upload_to_bilibili(submission, add_log)
            with self._lock:
                job = self._jobs[job_id]
                job["upload"].update({
                    "status": "completed",
                    "message": "B 站投稿已提交",
                    "bvid": bvid,
                })
                self._persist(job)
        except Exception as exc:
            with self._lock:
                job = self._jobs[job_id]
                job["upload"].update({
                    "status": "failed", "message": str(exc), "error": str(exc)
                })
                self._persist(job)
        finally:
            with self._lock:
                self._active_operation = None

    def _progress(self, job_id: str, percent: int, stage: str, message: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.update({
                "status": "running",
                "progress": percent,
                "stage": stage,
                "message": message,
                "updated_at": _utc_now(),
            })
            job["logs"].append({"time": _utc_now(), "stage": stage, "message": message})

    def _run(self, job_id: str, request: JobRequest) -> None:
        try:
            result = run_pipeline(
                PipelineOptions(
                    url=request.url.strip(),
                    download_video=request.download_video,
                    download_thumbnail=request.download_thumbnail,
                    use_separator=request.use_separator,
                    initial_prompt=request.initial_prompt.strip(),
                    auto_split_subtitles=request.auto_split_subtitles,
                    subtitle_density=request.subtitle_density,
                    subtitle_max_lines=request.subtitle_max_lines,
                ),
                progress=lambda percent, stage, message: self._progress(
                    job_id, percent, stage, message
                ),
            )
            files = [
                {
                    "name": path.name,
                    "size": path.stat().st_size,
                    "url": f"/api/jobs/{job_id}/files/{quote(path.name, safe='')}",
                }
                for path in result.files
            ]
            with self._lock:
                self._jobs[job_id].update({
                    "status": "completed",
                    "progress": 100,
                    "stage": "处理完成",
                    "message": f"{result.segment_count} 个字幕片段已生成",
                    "updated_at": _utc_now(),
                    "files": files,
                    "result": result,
                    "output_dir": str(result.output_dir.resolve()),
                    "title": result.title,
                })
                self._persist(self._jobs[job_id])
        except Exception as exc:
            with self._lock:
                self._jobs[job_id].update({
                    "status": "failed",
                    "stage": "处理失败",
                    "message": str(exc),
                    "error": str(exc),
                    "updated_at": _utc_now(),
                })
                self._persist(self._jobs[job_id])
        finally:
            with self._lock:
                if self._active_job_id == job_id:
                    self._active_job_id = None


def create_app(glossary_path: Path | str = DEFAULT_GLOSSARY_PATH) -> FastAPI:
    app = FastAPI(title="Kotoba Studio", docs_url=None, redoc_url=None)
    history_path = Path(glossary_path).with_name("last_job.json")
    app.state.jobs = JobManager(history_path)
    app.state.glossary = GlossaryStore(glossary_path)
    static_dir = ROOT / "web" / "static"
    app.mount("/assets", StaticFiles(directory=static_dir), name="assets")

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html")

    @app.get("/api/health")
    def health():
        return {
            "ok": True,
            "openai_configured": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
            "transcription_model": os.environ.get("OPENAI_TRANSCRIPTION_MODEL", "whisper-1"),
            "translation_model": os.environ.get("OPENAI_TRANSLATION_MODEL", "gpt-4o-mini"),
        }

    @app.post("/api/jobs", status_code=202)
    def create_job(request: JobRequest):
        try:
            return app.state.jobs.start(request)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409 if isinstance(exc, RuntimeError) else 422, detail=str(exc))

    @app.get("/api/jobs/latest")
    def get_latest_job():
        return app.state.jobs.latest()

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        try:
            return app.state.jobs.get(job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="任务不存在")

    @app.get("/api/jobs/{job_id}/files/{filename}")
    def get_result_file(job_id: str, filename: str):
        try:
            path = app.state.jobs.result_file(job_id, filename)
        except KeyError:
            raise HTTPException(status_code=404, detail="结果文件不存在")
        return FileResponse(path, filename=path.name)

    @app.get("/api/jobs/{job_id}/subtitles")
    def get_subtitles(job_id: str):
        try:
            return app.state.jobs.get_subtitles(job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="字幕任务不存在")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @app.get("/api/jobs/{job_id}/media")
    def get_preview_video(job_id: str):
        try:
            video = app.state.jobs.preview_video(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        return FileResponse(
            video,
            media_type="video/mp4",
            filename=video.name,
            content_disposition_type="inline",
        )

    @app.put("/api/jobs/{job_id}/subtitles")
    def save_subtitles(job_id: str, payload: SubtitleUpdateRequest):
        try:
            return app.state.jobs.save_subtitles(job_id, payload.model_dump())
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/api/jobs/{job_id}/subtitles/preview")
    def exact_subtitle_preview(job_id: str, payload: SubtitlePreviewRequest):
        try:
            output_dir = app.state.jobs.preview_paths(job_id)
            image_path = render_exact_preview(
                output_dir, payload.timestamp, payload.subtitle_type
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        return FileResponse(
            image_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
            background=BackgroundTask(image_path.unlink, missing_ok=True),
        )

    @app.get("/api/bilibili/status")
    def get_bilibili_status():
        return biliup_status()

    @app.get("/api/bilibili/categories")
    def get_bilibili_categories():
        return {"categories": BILIBILI_CATEGORIES, "default_tid": 158}

    @app.post("/api/bilibili/login", status_code=202)
    def start_bilibili_login():
        try:
            launch_biliup_login()
            return {"ok": True, "message": "扫码登录窗口已打开"}
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/api/jobs/{job_id}/burn", status_code=202)
    def start_burn(job_id: str, payload: BurnRequest):
        try:
            return app.state.jobs.start_burn(job_id, payload.subtitle_type)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.post("/api/jobs/{job_id}/upload", status_code=202)
    def start_upload(job_id: str, payload: BilibiliUploadRequest):
        try:
            return app.state.jobs.start_upload(job_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.get("/api/glossary")
    def list_glossary():
        return app.state.glossary.list_terms()

    @app.post("/api/glossary", status_code=201)
    def add_glossary_term(payload: GlossaryCreate):
        try:
            return app.state.glossary.add_term(**payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @app.patch("/api/glossary/{term_id}")
    def update_glossary_term(term_id: str, payload: GlossaryUpdate):
        try:
            return app.state.glossary.update_term(
                term_id, payload.model_dump(exclude_unset=True)
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="术语不存在")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @app.delete("/api/glossary/{term_id}", status_code=204)
    def delete_glossary_term(term_id: str):
        try:
            app.state.glossary.delete_term(term_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="术语不存在")

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8787)
