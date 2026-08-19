import os
import unittest
from unittest.mock import patch

from src.downloader import _youtube_runtime_args


class DownloaderRuntimeArgsTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "YTDLP_JS_RUNTIME": "node",
            "YTDLP_FORCE_IPV4": "true",
            "YTDLP_PLAYER_CLIENT": "web_embedded",
        },
        clear=False,
    )
    def test_builds_current_youtube_runtime_options(self):
        self.assertEqual(
            _youtube_runtime_args(),
            [
                "--js-runtimes",
                "node",
                "--force-ipv4",
                "--extractor-args",
                "youtube:player_client=web_embedded",
            ],
        )

    @patch.dict(
        os.environ,
        {
            "YTDLP_JS_RUNTIME": "",
            "YTDLP_FORCE_IPV4": "false",
            "YTDLP_PLAYER_CLIENT": "",
        },
        clear=False,
    )
    def test_allows_optional_runtime_options_to_be_disabled(self):
        self.assertEqual(_youtube_runtime_args(), [])


if __name__ == "__main__":
    unittest.main()
