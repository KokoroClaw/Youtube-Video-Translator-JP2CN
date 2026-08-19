import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from web import create_app
from web import JobManager
from src.subtitle_builder import build_dual_ass, build_zh_ass


class WebApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp_dir.name) / "glossary.json")
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.temp_dir.cleanup()

    def test_home_and_health_are_available(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn('id="editorWorkspace"', home.text)
        self.assertIn('id="subtitleVideo"', home.text)
        self.assertIn('id="cueTable"', home.text)
        self.assertIn('id="styleTrack"', home.text)
        self.assertIn('id="autoSplitSubtitles"', home.text)
        self.assertIn('id="subtitleDensity"', home.text)
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.json()["ok"])

    def test_glossary_crud(self):
        created = self.client.post("/api/glossary", json={
            "source": "先輩", "target": "前辈", "note": "称呼"
        })
        self.assertEqual(created.status_code, 201)
        term_id = created.json()["id"]

        updated = self.client.patch(
            f"/api/glossary/{term_id}", json={"enabled": False}
        )
        self.assertEqual(updated.status_code, 200)
        self.assertFalse(updated.json()["enabled"])

        deleted = self.client.delete(f"/api/glossary/{term_id}")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get("/api/glossary").json(), [])

    def test_invalid_job_url_is_rejected_without_starting_work(self):
        response = self.client.post("/api/jobs", json={"url": "https://example.com/video"})
        self.assertEqual(response.status_code, 422)

    def test_subtitle_split_settings_are_validated_before_job_start(self):
        response = self.client.post("/api/jobs", json={
            "url": "https://youtu.be/example",
            "subtitle_density": "standard",
            "subtitle_max_lines": 4,
        })

        self.assertEqual(response.status_code, 422)

    def test_latest_job_is_empty_before_work_starts(self):
        response = self.client.get("/api/jobs/latest")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())

    def test_result_urls_encode_hash_characters(self):
        manager = JobManager(Path(self.temp_dir.name) / "history.json")
        manager._jobs["job-id"] = {
            "id": "job-id",
            "created_at": "2026-01-01T00:00:00+00:00",
            "files": [{"name": "标题 #标签_video.mp4", "size": 1, "url": "old"}],
        }

        result = manager.get("job-id")

        self.assertIn("%23", result["files"][0]["url"])
        self.assertNotIn("#", result["files"][0]["url"])

    def test_old_job_recovers_source_url_from_info_file(self):
        root = Path(self.temp_dir.name)
        output_dir = root / "output"
        output_dir.mkdir()
        source_url = "https://www.youtube.com/watch?v=source123"
        (output_dir / "video_info.txt").write_text(
            f"title: test\nurl: {source_url}\ndescription: \n",
            encoding="utf-8",
        )
        history = root / "history.json"
        history.write_text(
            '{"id":"old-job","status":"completed",'
            '"created_at":"2026-01-01T00:00:00+00:00",'
            f'"output_dir":{json.dumps(str(output_dir))},"files":[]}}',
            encoding="utf-8",
        )

        manager = JobManager(history)

        self.assertEqual(manager.latest()["source_url"], source_url)
        self.assertIn(source_url, history.read_text(encoding="utf-8"))

    def test_bilibili_status_does_not_expose_cookie_contents(self):
        response = self.client.get("/api/bilibili/status")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("cookie", " ".join(map(str, response.json().values())).lower())

    def test_bilibili_categories_include_full_reference_values(self):
        response = self.client.get("/api/bilibili/categories")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["categories"]), 20)
        fashion = next(item for item in payload["categories"] if item["name"] == "时尚")
        self.assertIn({"id": 158, "name": "穿搭"}, fashion["children"])
        animation = next(item for item in payload["categories"] if item["name"] == "动画")
        self.assertIn({"id": 27, "name": "综合"}, animation["children"])
        self.assertEqual(payload["default_tid"], 158)

    def test_bilibili_upload_requires_explicit_publish_confirmation(self):
        response = self.client.post("/api/jobs/missing/upload", json={
            "video_name": "video.mp4",
            "title": "标题",
            "tags": "中字",
            "tid": 27,
            "copyright": 2,
            "source": "https://youtu.be/source",
            "confirm_publish": False,
        })
        self.assertEqual(response.status_code, 422)
        self.assertIn("确认", response.json()["detail"])

    def test_subtitle_editor_loads_and_saves_both_ass_files(self):
        output = Path(self.temp_dir.name) / "editor-output"
        output.mkdir()
        segments = [{"start": 0.5, "end": 2, "text": "元気", "translation": "精神吗"}]
        (output / "demo_dual.ass").write_text(
            build_dual_ass(segments, "demo"), encoding="utf-8-sig"
        )
        (output / "demo_zh.ass").write_text(
            build_zh_ass(segments, "demo"), encoding="utf-8-sig"
        )
        video = output / "demo_video.mp4"
        video.write_bytes(b"placeholder")
        self.app.state.jobs._jobs["editor-job"] = {
            "id": "editor-job", "status": "completed", "progress": 100,
            "stage": "处理完成", "message": "完成", "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00", "logs": [], "error": None,
            "output_dir": str(output), "title": "demo", "burn": None, "upload": None,
            "files": [
                {"name": "demo_dual.ass", "size": (output / "demo_dual.ass").stat().st_size, "url": ""},
                {"name": "demo_zh.ass", "size": (output / "demo_zh.ass").stat().st_size, "url": ""},
                {"name": video.name, "size": video.stat().st_size, "url": ""},
                {"name": "demo_hardsub_zh.mp4", "size": 1, "url": ""},
            ],
        }

        loaded = self.client.get("/api/jobs/editor-job/subtitles")
        self.assertEqual(loaded.status_code, 200)
        document = loaded.json()
        self.assertEqual(document["cues"][0]["jp"], "元気")
        document["cues"][0]["zh"] = "还好吗"
        saved = self.client.put("/api/jobs/editor-job/subtitles", json={
            "revision": document["revision"], "cues": document["cues"], "styles": document["styles"],
        })

        self.assertEqual(saved.status_code, 200)
        self.assertIn("还好吗", (output / "demo_zh.ass").read_text(encoding="utf-8-sig"))
        self.assertIn("还好吗", (output / "demo_dual.ass").read_text(encoding="utf-8-sig"))
        job = self.app.state.jobs.get("editor-job")
        self.assertEqual(job["burn"]["status"], "stale")
        self.assertFalse(any("_hardsub_" in item["name"] for item in job["files"]))


if __name__ == "__main__":
    unittest.main()
