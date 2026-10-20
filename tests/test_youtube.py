"""yt-dlp option building and result conversion (no network)."""

import pytest

from clipper_app.config import Settings
from clipper_app.environment import ToolStatus, ytdlp_age_days, ytdlp_release_date
from clipper_app.errors import UserFacingError
from clipper_app.youtube import (
    YdlLogger,
    YouTubeService,
    entry_from_flat,
    entry_from_info,
)


def service(reporter, settings=None, tools=None):
    return YouTubeService(
        settings or Settings(), tools or ToolStatus(), reporter, delays=(0, 0)
    )


class TestOptions:
    def test_metadata_options_ignore_missing_formats(self, reporter):
        options = service(reporter).metadata_options()
        assert options["ignore_no_formats_error"] is True
        assert options["skip_download"] is True
        assert "cookiesfrombrowser" not in options
        assert "cookiefile" not in options
        assert "js_runtimes" not in options

    def test_cookies_file_is_used(self, reporter, tmp_path):
        cookies = tmp_path / "cookies.txt"
        cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
        options = service(reporter, Settings(cookies_path=str(cookies))).base_options()
        assert options["cookiefile"] == str(cookies)
        assert "cookiesfrombrowser" not in options

    def test_missing_cookies_file_gives_clear_error(self, reporter, tmp_path):
        settings = Settings(cookies_path=str(tmp_path / "missing.txt"))
        with pytest.raises(UserFacingError) as error:
            service(reporter, settings).base_options()
        assert "cookies.txt" in str(error.value)

    def test_detected_tools_are_passed_to_yt_dlp(self, reporter, tmp_path):
        deno = str(tmp_path / "deno" / "deno.exe")
        tools = ToolStatus(ffmpeg=str(tmp_path / "bin" / "ffmpeg.exe"), deno=deno)
        options = service(reporter, tools=tools).base_options()
        assert options["js_runtimes"] == {"deno": {"path": deno}}
        assert options["ffmpeg_location"] == str(tmp_path / "bin")


class TestBackoff:
    def test_429_is_retried_and_reported(self, reporter):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise Exception("HTTP Error 429: Too Many Requests")
            return "ok"

        assert service(reporter).with_backoff(flaky, "Subtitles") == "ok"
        assert reporter.waits == [0]
        warnings = reporter.messages("warning")
        assert warnings and "429" in warnings[0] and "Subtitles" in warnings[0]


class TestEntries:
    def test_entry_from_flat(self):
        entry = entry_from_flat(
            {
                "id": "VwD3D2lgIWU",
                "url": "https://www.youtube.com/watch?v=VwD3D2lgIWU",
                "title": "TECHtober",
                "duration": 5510,
                "view_count": 433000,
                "timestamp": 1792195200,
                "ie_key": "Youtube",
                "_type": "url",
            }
        )
        assert entry.video_id == "VwD3D2lgIWU"
        assert entry.url == "https://www.youtube.com/watch?v=VwD3D2lgIWU"
        assert entry.duration == 5510
        assert entry.date_is_approximate is True

    @pytest.mark.parametrize(
        "item",
        [None, "x", {}, {"id": "UCabc", "ie_key": "YoutubeTab", "_type": "url"}],
    )
    def test_non_video_entries_are_skipped(self, item):
        assert entry_from_flat(item) is None

    def test_entry_from_info(self):
        entry = entry_from_info(
            {
                "id": "dQw4w9WgXcQ",
                "title": "Rick",
                "duration": 213,
                "upload_date": "20091025",
            }
        )
        assert entry.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert entry.upload_date == "20091025"
        assert entry.date_is_approximate is False


class TestYdlLogger:
    def test_known_warning_is_explained_once(self, reporter):
        log = YdlLogger(reporter)
        message = "[youtube] No supported JavaScript runtime could be found."
        log.warning(message)
        log.warning(message)
        hints = reporter.messages("warning")
        assert len(hints) == 1
        assert "Deno" in hints[0]

    def test_comment_progress_updates_status(self, reporter):
        YdlLogger(reporter).debug(
            "[youtube] abc: Downloading comment API JSON page 3 (60/~1234)"
        )
        message, progress = reporter.statuses[-1]
        assert "60/500" in message
        assert progress == pytest.approx(60 / 500)

    def test_debug_lines_are_not_shown(self, reporter):
        YdlLogger(reporter).debug("[debug] Command-line config: []")
        assert reporter.logs == [] and reporter.statuses == []


class TestVersionAge:
    def test_release_date(self):
        assert str(ytdlp_release_date("2026.10.10.233141.dev0")) == "2026-10-10"
        assert str(ytdlp_release_date("2025.09.05")) == "2025-09-05"
        assert ytdlp_release_date("unknown") is None
        assert ytdlp_release_date(None) is None

    def test_age(self):
        from datetime import date

        assert ytdlp_age_days("2026.10.10", date(2026, 10, 20)) == 10
        assert ytdlp_age_days(None) is None

    def test_old_deno_is_detected(self):
        assert ToolStatus(deno="d", deno_version="1.46.3").deno_too_old
        assert not ToolStatus(deno="d", deno_version="2.5.4").deno_too_old
        assert not ToolStatus().deno_too_old
