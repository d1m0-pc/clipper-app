"""Settings persistence, cookies.txt validation and result export."""

import csv
import json
from datetime import datetime

from clipper_app.config import (
    DEFAULT_OUTPUT_DIR,
    Settings,
    load_settings,
    normalized,
    save_settings,
    validate_cookies_file,
)
from clipper_app.exporter import CSV_COLUMNS, export_csv, export_results, export_txt
from clipper_app.models import (
    SOURCE_COMMENTS,
    SOURCE_HEATMAP,
    CommentExample,
    Cue,
    Moment,
    SubtitleTrack,
    VideoAnalysis,
    VideoEntry,
)


class TestSettings:
    def test_defaults(self):
        settings = Settings()
        assert settings.channel_video_count == 20
        assert settings.lead_in_seconds == 15
        assert settings.skip_intro_seconds == 60
        assert settings.top_segments == 10
        assert settings.output_path == DEFAULT_OUTPUT_DIR
        assert settings.output_path.name == "clips"
        assert settings.cookies_file is None

    def test_round_trip(self, tmp_path):
        path = tmp_path / "settings.json"
        original = Settings(
            cookies_path=str(tmp_path / "cookies.txt"),
            channel_video_count=7,
            lead_in_seconds=20,
            output_dir=str(tmp_path / "out"),
        )
        save_settings(original, path)
        assert load_settings(path) == original

    def test_missing_file_gives_defaults(self, tmp_path):
        assert load_settings(tmp_path / "nope.json") == Settings()

    def test_broken_file_gives_defaults(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text("{not json", encoding="utf-8")
        assert load_settings(path) == Settings()

    def test_unknown_keys_and_bad_values(self, tmp_path):
        path = tmp_path / "settings.json"
        data = {"channel_video_count": "abc", "lead_in_seconds": 9999, "unknown": 1}
        path.write_text(json.dumps(data), encoding="utf-8")
        settings = load_settings(path)
        assert settings.channel_video_count == 20
        assert settings.lead_in_seconds == 120

    def test_normalized_clamps(self):
        settings = normalized(Settings(channel_video_count=0, top_segments=1000))
        assert settings.channel_video_count == 1
        assert settings.top_segments == 50

    def test_no_browser_cookie_option_exists(self):
        assert not any("browser" in name for name in Settings().__dataclass_fields__)


class TestValidateCookies:
    def test_valid_file(self, tmp_path):
        path = tmp_path / "cookies.txt"
        path.write_text(
            "# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tTRUE\t1999999999\tPREF\tf6=40000000\n",
            encoding="utf-8",
        )
        assert validate_cookies_file(str(path)) is None

    def test_missing_file(self, tmp_path):
        assert "does not exist" in validate_cookies_file(str(tmp_path / "x.txt"))

    def test_wrong_format(self, tmp_path):
        path = tmp_path / "cookies.txt"
        path.write_text('{"cookies": []}', encoding="utf-8")
        assert "Netscape" in validate_cookies_file(str(path))

    def test_no_youtube_cookies(self, tmp_path):
        path = tmp_path / "cookies.txt"
        path.write_text(
            "# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tFALSE\t0\ta\tb\n",
            encoding="utf-8",
        )
        assert "youtube.com" in validate_cookies_file(str(path))


def sample_analyses():
    heat_video = VideoEntry(
        "abcdefghijk",
        "https://www.youtube.com/watch?v=abcdefghijk",
        'Test; video, "quoted" č ć',
        600,
        1500,
        "20261001",
    )
    heat = VideoAnalysis(
        heat_video,
        SOURCE_HEATMAP,
        moments=[
            Moment(120, 150, 0.87, SOURCE_HEATMAP, avg_score=0.8, segment_count=3)
        ],
        cues=[Cue(100, 110, "before"), Cue(110, 130, "during the moment")],
        subtitle_track=SubtitleTrack("u", "en-orig", True),
    )
    comment_video = VideoEntry(
        "zyxwvutsrqp",
        "https://www.youtube.com/watch?v=zyxwvutsrqp",
        "Comment video",
        900,
    )
    comments = VideoAnalysis(
        comment_video,
        SOURCE_COMMENTS,
        moments=[
            Moment(
                300,
                360,
                42,
                SOURCE_COMMENTS,
                mentions=3,
                likes=39,
                examples=[CommentExample(30, "5:00 lol")],
            )
        ],
    )
    return [heat, comments]


class TestExport:
    def test_csv(self, tmp_path):
        path = tmp_path / "out.csv"
        assert export_csv(sample_analyses(), path, lead_in=15) == 2
        raw = path.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")  # BOM so Excel shows non-ASCII text
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle, delimiter=";"))
        assert rows[0] == CSV_COLUMNS
        heat_row = dict(zip(CSV_COLUMNS, rows[1], strict=True))
        assert heat_row["Video"] == 'Test; video, "quoted" č ć'
        assert heat_row["Start"] == "2:00"
        assert heat_row["Score"] == "87"
        assert heat_row["Moment link"].endswith("&t=120s")
        assert heat_row["Transcript from"] == "1:45"
        assert heat_row["Transcript"] == "before during the moment"
        comment_row = dict(zip(CSV_COLUMNS, rows[2], strict=True))
        assert comment_row["Mentions"] == "3"
        assert comment_row["Likes"] == "39"
        assert "5:00 lol" in comment_row["Example comments"]
        assert comment_row["Transcript"] == ""

    def test_csv_with_comma_delimiter(self, tmp_path):
        path = tmp_path / "out.csv"
        export_csv(sample_analyses(), path, lead_in=15, delimiter=",")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle, delimiter=","))
        assert len(rows) == 3

    def test_txt(self, tmp_path):
        path = tmp_path / "out.txt"
        count = export_txt(
            sample_analyses(), path, lead_in=15, now=datetime(2026, 10, 20, 14, 5)
        )
        text = path.read_text(encoding="utf-8")
        assert count == 2
        assert "Exported: 2026-10-20 14:05" in text
        assert "#1  2:00 - 2:30  (30 s)  Score: 87/100" in text
        assert "Transcript (from 1:45):" in text
        assert "during the moment" in text
        assert "Subtitles: en-orig (automatic)" in text
        assert "(30 likes) 5:00 lol" in text
        assert "Subtitles: not available" in text

    def test_export_results_picks_format_by_extension(self, tmp_path):
        assert export_results(sample_analyses(), tmp_path / "a.CSV", 15) == 2
        assert (tmp_path / "a.CSV").read_bytes().startswith(b"\xef\xbb\xbf")
        export_results(sample_analyses(), tmp_path / "a.txt", 15)
        assert (tmp_path / "a.txt").read_text(encoding="utf-8").startswith("Clipper")

    def test_video_without_moments(self, tmp_path):
        empty = VideoAnalysis(VideoEntry("aaaaaaaaaaa", "u", "Empty"), "none")
        export_txt([empty], tmp_path / "e.txt", 15)
        assert "No moments found." in (tmp_path / "e.txt").read_text(encoding="utf-8")
