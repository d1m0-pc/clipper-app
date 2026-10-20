"""Clip file names, range validation and the commands/options used to cut."""

from pathlib import Path

import pytest

from clipper_app.clipping import (
    DOWNLOAD_FORMAT,
    VERTICAL_FILTER,
    ClipCutter,
    ClipRequest,
    clip_filename,
    sanitize_filename,
    time_tag,
    unique_path,
    validate_range,
    vertical_command,
)
from clipper_app.config import Settings
from clipper_app.environment import ToolStatus
from clipper_app.errors import UserFacingError
from clipper_app.models import VideoEntry


class TestFileNames:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Normal title", "Normal title"),
            (
                'What? A "crazy" <video>: part 1/2 | wow*',
                "What A crazy video part 1 2 wow",
            ),
            ("Ćevapi i šljivovica – đak", "Ćevapi i šljivovica – đak"),
            ("ends with dots...", "ends with dots"),
            ("  spaces   everywhere  ", "spaces everywhere"),
            ("", "clip"),
            ("???", "clip"),
            ("CON", "_CON"),
            ("nul.txt", "_nul.txt"),
            ("tab\there\nnewline", "tab here newline"),
        ],
    )
    def test_sanitize_filename(self, title, expected):
        assert sanitize_filename(title) == expected

    def test_long_title_is_shortened(self):
        assert len(sanitize_filename("a" * 300)) == 80

    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [(0, "00m00s"), (83.9, "01m23s"), (754, "12m34s"), (3723, "1h02m03s")],
    )
    def test_time_tag(self, seconds, expected):
        assert time_tag(seconds) == expected

    def test_clip_filename(self):
        assert (
            clip_filename("My: video", 754, 790, False) == "My video_12m34s-13m10s.mp4"
        )
        assert (
            clip_filename("My video", 754, 790, True)
            == "My video_12m34s-13m10s_9x16.mp4"
        )

    def test_unique_path(self, tmp_path):
        target = tmp_path / "clip.mp4"
        assert unique_path(target) == target
        target.write_bytes(b"x")
        second = unique_path(target)
        assert second.name == "clip (2).mp4"
        second.write_bytes(b"x")
        assert unique_path(target).name == "clip (3).mp4"


class TestValidateRange:
    def test_valid(self):
        assert validate_range(10, 40, 600) == (10, 40)

    def test_end_clamped_to_duration(self):
        assert validate_range(590, 700, 600) == (590, 600)

    def test_unknown_duration(self):
        assert validate_range(10, 40, None) == (10, 40)

    @pytest.mark.parametrize(
        ("start", "end", "duration"),
        [(-1, 10, 600), (50, 50, 600), (50, 40, 600), (50, 50.5, 600), (600, 610, 600)],
    )
    def test_invalid(self, start, end, duration):
        with pytest.raises(UserFacingError):
            validate_range(start, end, duration)


def test_vertical_command_center_crops_to_9_16():
    command = vertical_command("ffmpeg.exe", Path("in.mp4"), Path("out.mp4"))
    assert command[0] == "ffmpeg.exe"
    assert command[command.index("-i") + 1] == "in.mp4"
    assert command[-1] == "out.mp4"
    video_filter = command[command.index("-vf") + 1]
    assert video_filter == VERTICAL_FILTER
    assert "crop=" in video_filter and "ih*9/16" in video_filter
    assert "scale=1080:1920" in video_filter
    assert "libx264" in command and "+faststart" in command


def test_cut_without_ffmpeg_is_refused(reporter, tmp_path):
    video = VideoEntry(
        "abcdefghijk", "https://www.youtube.com/watch?v=abcdefghijk", "T", 600
    )
    cutter = ClipCutter(Settings(), ToolStatus(ffmpeg=None), reporter)
    with pytest.raises(UserFacingError) as error:
        cutter.cut(ClipRequest(video, 10, 20, False, tmp_path))
    assert "winget install Gyan.FFmpeg" in str(error.value)


def test_download_options_only_fetch_the_section(reporter, tmp_path):
    pytest.importorskip("yt_dlp")
    video = VideoEntry(
        "abcdefghijk", "https://www.youtube.com/watch?v=abcdefghijk", "T", 600
    )
    tools = ToolStatus(
        ffmpeg=str(tmp_path / "ffmpeg.exe"), deno=str(tmp_path / "deno.exe")
    )
    cutter = ClipCutter(Settings(), tools, reporter)
    options = cutter.download_options(
        ClipRequest(video, 12.5, 40, True, tmp_path), tmp_path
    )

    assert options["format"] == DOWNLOAD_FORMAT
    assert options["force_keyframes_at_cuts"] is True
    assert options["merge_output_format"] == "mp4"
    assert options["ffmpeg_location"] == str(tmp_path)
    assert options["js_runtimes"] == {"deno": {"path": str(tmp_path / "deno.exe")}}
    # A real download must not hide "no formats" errors.
    assert "ignore_no_formats_error" not in options
    assert "cookiesfrombrowser" not in options
    sections = list(options["download_ranges"]({}, None))
    assert sections == [{"start_time": 12.5, "end_time": 40}]
