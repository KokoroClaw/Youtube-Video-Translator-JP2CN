import tempfile
import unittest
from pathlib import Path

from src.burner import _ass_duration_seconds


class BurnerTests(unittest.TestCase):
    def test_reads_last_ass_dialogue_end_time(self):
        with tempfile.TemporaryDirectory() as directory:
            subtitle = Path(directory) / "test.ass"
            subtitle.write_text(
                "[Events]\n"
                "Dialogue: 0,0:00:01.00,0:00:03.50,ZH,Default,0,0,0,,第一句\n"
                "Dialogue: 0,0:01:00.00,1:02:03.25,ZH,Default,0,0,0,,最后一句\n",
                encoding="utf-8-sig",
            )

            self.assertEqual(_ass_duration_seconds(subtitle), 3723.25)


if __name__ == "__main__":
    unittest.main()
