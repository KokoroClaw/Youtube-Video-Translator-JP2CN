import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from src.bilibili_uploader import (
    BilibiliSubmission,
    prepare_bilibili_cover,
    upload_to_bilibili,
)


class _FakeProcess:
    def __init__(self, lines, return_code=0):
        self.stdout = iter(lines)
        self._return_code = return_code

    def wait(self):
        return self._return_code


class BilibiliUploaderTests(unittest.TestCase):
    def test_mislabeled_webp_cover_is_converted_to_real_jpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "thumb.jpg"
            destination = Path(directory) / "cover.jpg"
            Image.new("RGB", (1280, 720), "white").save(source, format="WEBP")

            prepare_bilibili_cover(source, destination)

            with Image.open(destination) as converted:
                self.assertEqual(converted.format, "JPEG")
                self.assertEqual(converted.mode, "RGB")

    def test_reprint_requires_source_url(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "video.mp4"
            video.write_bytes(b"video")
            submission = BilibiliSubmission(
                video_path=video,
                title="标题",
                description="",
                tags="中字",
                tid=27,
                copyright=2,
                source="",
            )
            cookie = Path(directory) / "cookies.json"
            cookie.write_text("{}", encoding="utf-8")
            with patch("src.bilibili_uploader.find_biliup", return_value="biliup.exe"), \
                 patch("src.bilibili_uploader.biliup_cookie_path", return_value=cookie):
                with self.assertRaisesRegex(ValueError, "来源"):
                    upload_to_bilibili(submission)

    def test_upload_uses_argument_list_and_extracts_bvid(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "video.mp4"
            video.write_bytes(b"video")
            cookie = Path(directory) / "cookies.json"
            cookie.write_text("credential-data", encoding="utf-8")
            submission = BilibiliSubmission(
                video_path=video,
                title="测试标题",
                description="简介",
                tags="日语,中字",
                tid=27,
                copyright=2,
                source="https://youtu.be/source",
            )
            popen = Mock(return_value=_FakeProcess(["投稿成功 BV1ab411c7De\n"]))
            with patch("src.bilibili_uploader.find_biliup", return_value="biliup.exe"), \
                 patch("src.bilibili_uploader.biliup_cookie_path", return_value=cookie), \
                 patch("src.bilibili_uploader.subprocess.Popen", popen):
                bvid = upload_to_bilibili(submission)

            self.assertEqual(bvid, "BV1ab411c7De")
            command = popen.call_args.args[0]
            self.assertIsInstance(command, list)
            self.assertIn("--copyright", command)
            self.assertIn("https://youtu.be/source", command)
            self.assertEqual(command[-1], str(video.resolve()))

    def test_biliup_minus_400_has_readable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "video.mp4"
            video.write_bytes(b"video")
            cookie = Path(directory) / "cookies.json"
            cookie.write_text("credential-data", encoding="utf-8")
            submission = BilibiliSubmission(
                video_path=video,
                title="测试标题",
                description="",
                tags="中字",
                tid=160,
                copyright=1,
            )
            process = _FakeProcess([
                'ResponseData { code: -400, message: "\\u8bf7\\u6c42\\u9519\\u8bef" }\n'
            ], return_code=1)
            with patch("src.bilibili_uploader.find_biliup", return_value="biliup.exe"), \
                 patch("src.bilibili_uploader.biliup_cookie_path", return_value=cookie), \
                 patch("src.bilibili_uploader.subprocess.Popen", return_value=process):
                with self.assertRaisesRegex(RuntimeError, "-400 请求错误"):
                    upload_to_bilibili(submission)


if __name__ == "__main__":
    unittest.main()
