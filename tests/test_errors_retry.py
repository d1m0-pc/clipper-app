"""User-facing error messages and the HTTP 429 retry/backoff logic."""

import pytest

from clipper_app.errors import (
    TaskCancelled,
    UserFacingError,
    friendly_error,
    is_known_error,
)
from clipper_app.retry import DEFAULT_BACKOFF, call_with_backoff, is_rate_limited


class FakeHTTPError(Exception):
    """Mimics yt_dlp.networking.exceptions.HTTPError."""

    def __init__(self, status):
        super().__init__(f"HTTP Error {status}: Something")
        self.status = status


class FakeDownloadError(Exception):
    """Mimics yt_dlp.utils.DownloadError, which keeps the cause in exc_info."""

    def __init__(self, message, cause):
        super().__init__(message)
        self.exc_info = (type(cause), cause, None)


class TestFriendlyError:
    @pytest.mark.parametrize(
        ("message", "expected_part"),
        [
            (
                "ERROR: [youtube] abc: nsig extraction failed: Some formats may "
                "be missing",
                "outdated",
            ),
            (
                "ERROR: [youtube] abc: Precondition check failed.",
                "Check/update yt-dlp",
            ),
            (
                "ERROR: [youtube] abc: Requested format is not available. "
                "Use --list-formats",
                "format",
            ),
            ("HTTP Error 429: Too Many Requests", "429"),
            (
                "Unable to download webpage: HTTP Error 429: Too Many Requests "
                "(caused by ...)",
                "429",
            ),
            (
                "ERROR: Could not copy Chrome cookie database. See https://...",
                "cookies.txt",
            ),
            ("Sign in to confirm you’re not a bot. Use --cookies-from-browser", "bot"),
            (
                "Sign in to confirm your age. This video may be inappropriate",
                "age-restricted",
            ),
            (
                "ERROR: [youtube] abc: Private video. Sign in if you've been "
                "granted access",
                "private",
            ),
            ("ERROR: [youtube] abc: Video unavailable", "unavailable"),
            (
                "ERROR: Postprocessing: ffprobe and ffmpeg not found",
                "winget install Gyan.FFmpeg",
            ),
            ("ERROR: Unsupported URL: https://example.com", "Unsupported link"),
            ("<urlopen error [Errno 11001] getaddrinfo failed>", "Internet"),
            (
                "'cookies.txt' does not look like a Netscape format cookies file",
                "Get cookies.txt LOCALLY",
            ),
            ("[Errno 13] Permission denied: 'clips/a.mp4'", "permission"),
        ],
    )
    def test_known_errors(self, message, expected_part):
        text = friendly_error(Exception(message))
        assert expected_part in text
        assert "Traceback" not in text
        assert is_known_error(message)

    def test_rate_limit_wins_over_network_words(self):
        message = (
            "Unable to download webpage: HTTP Error 429: Too Many Requests (timed out)"
        )
        assert "429" in friendly_error(message)

    def test_unknown_error_points_to_log(self):
        text = friendly_error(RuntimeError("KeyError: 'foo' in some module"))
        assert "log" in text
        assert not is_known_error("KeyError: 'foo'")

    def test_user_facing_error_is_returned_as_is(self):
        assert (
            friendly_error(UserFacingError("Message for the user."))
            == "Message for the user."
        )

    def test_cancelled(self):
        assert "Cancelled" in friendly_error(TaskCancelled())


class TestIsRateLimited:
    def test_status_attribute(self):
        assert is_rate_limited(FakeHTTPError(429))
        assert not is_rate_limited(FakeHTTPError(404))

    def test_message_only(self):
        assert is_rate_limited(Exception("ERROR: HTTP Error 429: Too Many Requests"))
        assert not is_rate_limited(Exception("HTTP Error 403: Forbidden"))

    def test_wrapped_in_download_error(self):
        wrapped = FakeDownloadError("ERROR: unable to download", FakeHTTPError(429))
        assert is_rate_limited(wrapped)

    def test_chained_cause(self):
        try:
            try:
                raise FakeHTTPError(429)
            except FakeHTTPError as inner:
                raise RuntimeError("download failed") from inner
        except RuntimeError as outer:
            assert is_rate_limited(outer)


class TestCallWithBackoff:
    def test_default_delays(self):
        assert DEFAULT_BACKOFF == (30.0, 60.0, 120.0)

    def test_success_without_retry(self):
        waits = []
        assert call_with_backoff(lambda: 42, wait=waits.append) == 42
        assert waits == []

    def test_retries_with_growing_delays_then_succeeds(self):
        attempts = {"count": 0}
        waits, retries = [], []

        def flaky():
            attempts["count"] += 1
            if attempts["count"] < 4:
                raise FakeHTTPError(429)
            return "ok"

        result = call_with_backoff(
            flaky,
            wait=waits.append,
            on_retry=lambda attempt, total, delay, _: retries.append(
                (attempt, total, delay)
            ),
        )
        assert result == "ok"
        assert waits == [30.0, 60.0, 120.0]
        assert retries == [(2, 4, 30.0), (3, 4, 60.0), (4, 4, 120.0)]

    def test_gives_up_after_last_delay(self):
        waits = []

        def always_429():
            raise FakeHTTPError(429)

        with pytest.raises(FakeHTTPError):
            call_with_backoff(always_429, wait=waits.append)
        assert waits == [30.0, 60.0, 120.0]

    def test_other_errors_are_not_retried(self):
        waits = []

        def broken():
            raise ValueError("bad data")

        with pytest.raises(ValueError):
            call_with_backoff(broken, wait=waits.append)
        assert waits == []

    def test_cancel_during_wait(self):
        def always_429():
            raise FakeHTTPError(429)

        with pytest.raises(TaskCancelled):
            call_with_backoff(always_429, wait=lambda _: True)

    def test_task_cancelled_is_never_retried(self):
        waits = []

        def cancelled():
            raise TaskCancelled()

        with pytest.raises(TaskCancelled):
            call_with_backoff(cancelled, wait=waits.append, should_retry=lambda _: True)
        assert waits == []
