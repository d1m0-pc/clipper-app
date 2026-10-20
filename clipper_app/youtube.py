"""Everything that talks to YouTube, through yt-dlp."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

from .config import Settings
from .environment import ToolStatus
from .errors import UserFacingError
from .models import Cue, SubtitleTrack, VideoEntry
from .reporting import LEVEL_WARNING, Reporter
from .retry import DEFAULT_BACKOFF, call_with_backoff
from .transcript import parse_json3, pick_subtitle_track
from .urls import watch_url

logger = logging.getLogger(__name__)

T = TypeVar("T")

MAX_COMMENTS = 500
SOCKET_TIMEOUT = 30

# yt-dlp warnings worth explaining to the user (shown once per task).
_WARNING_HINTS: list[tuple[tuple[str, ...], str]] = [
    (
        ("no supported javascript runtime",),
        "Deno (JavaScript runtime) was not found, so YouTube may not work "
        'correctly. Instructions are on the "Tools & help" tab.',
    ),
    (
        (
            "nsig extraction failed",
            "precondition check failed",
            "signature extraction failed",
            "challenge solving failed",
        ),
        "yt-dlp has a problem with YouTube's protection. Click \"Check/update "
        'yt-dlp" (on the "Tools & help" tab) and make sure Deno is installed.',
    ),
    (
        ("older than 90 days",),
        'Your yt-dlp version is outdated. Click "Check/update yt-dlp".',
    ),
]
_COMMENT_PROGRESS_RE = re.compile(r"Downloading comment.*?\((\d+)/~?(\d+)\)")


def import_yt_dlp() -> Any:
    """Import yt-dlp only when it is needed.

    Importing lazily lets the app start (and offer the update button) even
    if yt-dlp is missing or broken.

    Returns:
        The ``yt_dlp`` module.

    Raises:
        UserFacingError: If yt-dlp is not installed.
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise UserFacingError(
            "yt-dlp is not installed. Run setup.bat or click "
            '"Check/update yt-dlp" on the "Tools & help" tab.'
        ) from exc
    return yt_dlp


def entry_from_flat(entry: Mapping | None) -> VideoEntry | None:
    """Convert a flat-playlist entry into a :class:`VideoEntry`.

    Args:
        entry: One item of ``info["entries"]`` from a flat extraction.

    Returns:
        The entry, or ``None`` for items that are not videos.
    """
    if not isinstance(entry, Mapping):
        return None
    video_id = entry.get("id")
    if not video_id or entry.get("ie_key") not in (None, "Youtube"):
        return None
    upload_date = entry.get("upload_date")
    timestamp = entry.get("timestamp")
    return VideoEntry(
        video_id=str(video_id),
        url=watch_url(str(video_id)),
        title=str(entry.get("title") or video_id),
        duration=entry.get("duration"),
        view_count=entry.get("view_count"),
        upload_date=upload_date,
        timestamp=timestamp,
        date_is_approximate=not upload_date and bool(timestamp),
    )


def entry_from_info(info: Mapping) -> VideoEntry:
    """Convert a full yt-dlp info dict into a :class:`VideoEntry`.

    Args:
        info: Info dict of a single video.

    Returns:
        The video entry.
    """
    video_id = str(info.get("id") or "")
    return VideoEntry(
        video_id=video_id,
        url=watch_url(video_id) if video_id else str(info.get("webpage_url") or ""),
        title=str(info.get("title") or video_id),
        duration=info.get("duration"),
        view_count=info.get("view_count"),
        upload_date=info.get("upload_date"),
        timestamp=info.get("timestamp"),
    )


class YdlLogger:
    """Sends yt-dlp output to the log file and important hints to the GUI."""

    def __init__(self, reporter: Reporter) -> None:
        """Create a logger bound to a task reporter.

        Args:
            reporter: Where user-facing hints and progress go.
        """
        self._reporter = reporter
        self._shown: set[str] = set()

    def debug(self, message: str) -> None:
        """Handle yt-dlp debug/screen output."""
        if message.startswith("[debug] "):
            logger.debug("yt-dlp: %s", message)
            return
        logger.info("yt-dlp: %s", message)
        match = _COMMENT_PROGRESS_RE.search(message)
        if match:
            done, total = int(match.group(1)), max(1, int(match.group(2)))
            total = min(total, MAX_COMMENTS)
            self._reporter.status(
                f"Downloading comments... {min(done, total)}/{total}",
                min(done / total, 1.0),
            )

    def info(self, message: str) -> None:
        """Handle yt-dlp info output."""
        logger.info("yt-dlp: %s", message)

    def warning(self, message: str) -> None:
        """Log a warning and explain known ones to the user once."""
        logger.warning("yt-dlp: %s", message)
        lowered = message.lower()
        for needles, hint in _WARNING_HINTS:
            if hint not in self._shown and any(n in lowered for n in needles):
                self._shown.add(hint)
                self._reporter.log(hint, LEVEL_WARNING)

    def error(self, message: str) -> None:
        """Log an error (the GUI shows a translated message separately)."""
        logger.error("yt-dlp: %s", message)


class YouTubeService:
    """Fetches channel lists, video metadata, comments and subtitles."""

    def __init__(
        self,
        settings: Settings,
        tools: ToolStatus,
        reporter: Reporter,
        delays: tuple[float, ...] = DEFAULT_BACKOFF,
    ) -> None:
        """Create the service.

        Args:
            settings: Current user settings (cookies path etc.).
            tools: Detected external tools (Deno, ffmpeg).
            reporter: Progress/log channel for the running task.
            delays: Pauses before retries after HTTP 429.
        """
        self._settings = settings
        self._tools = tools
        self._reporter = reporter
        self._delays = delays
        self._logger = YdlLogger(reporter)

    def base_options(self) -> dict[str, Any]:
        """yt-dlp options shared by all requests.

        Cookies are only read from a cookies.txt file. Reading them straight
        from Brave/Chrome (``cookiesfrombrowser``) fails on Windows, so it is
        deliberately never used.

        Returns:
            Options for ``yt_dlp.YoutubeDL``.

        Raises:
            UserFacingError: If the configured cookies.txt does not exist.
        """
        options: dict[str, Any] = {
            "quiet": True,
            "noprogress": True,
            "logger": self._logger,
            "socket_timeout": SOCKET_TIMEOUT,
            "retries": 3,
            "extractor_retries": 3,
            "noplaylist": True,
        }
        cookies = self._settings.cookies_file
        if cookies:
            if not Path(cookies).is_file():
                raise UserFacingError(
                    "The cookies.txt file was not found. Check the path on "
                    'the "Settings" tab or clear it.'
                )
            options["cookiefile"] = cookies
        if self._tools.deno:
            options["js_runtimes"] = {"deno": {"path": self._tools.deno}}
        if self._tools.ffmpeg_dir:
            options["ffmpeg_location"] = self._tools.ffmpeg_dir
        return options

    def metadata_options(self) -> dict[str, Any]:
        """Options for metadata-only requests.

        ``ignore_no_formats_error`` is required here; otherwise yt-dlp fails
        with "Requested format is not available" although no video is
        downloaded.

        Returns:
            Options for ``yt_dlp.YoutubeDL``.
        """
        return {
            **self.base_options(),
            "skip_download": True,
            "ignore_no_formats_error": True,
        }

    @contextmanager
    def open_ydl(self, options: dict[str, Any]) -> Iterator[Any]:
        """Create a ``YoutubeDL`` instance as a context manager.

        Args:
            options: yt-dlp options.

        Yields:
            The ``YoutubeDL`` object.
        """
        yt_dlp = import_yt_dlp()
        with yt_dlp.YoutubeDL(options) as ydl:
            yield ydl

    def with_backoff(self, func: Callable[[], T], what: str) -> T:
        """Run ``func`` with retries (30 s, 60 s, 120 s) on HTTP 429.

        Args:
            func: The request to run.
            what: Short description for status messages.

        Returns:
            The result of ``func``.
        """

        def on_retry(attempt: int, total: int, delay: float, _: BaseException) -> None:
            self._reporter.log(
                f"{what}: YouTube returned error 429 (too many requests). "
                f"Attempt {attempt}/{total} in {delay:.0f} s.",
                LEVEL_WARNING,
            )

        def wait(delay: float) -> bool:
            return self._reporter.wait(delay, f"{what}: waiting because of error 429.")

        return call_with_backoff(
            func, delays=self._delays, on_retry=on_retry, wait=wait
        )

    def list_videos(self, url: str, count: int) -> tuple[str, list[VideoEntry]]:
        """List the latest videos of a channel or playlist (fast, flat).

        Args:
            url: Normalized channel or playlist URL.
            count: Maximum number of videos.

        Returns:
            Tuple of (channel/playlist title, videos).

        Raises:
            UserFacingError: If YouTube returns nothing.
        """
        options = {
            **self.metadata_options(),
            "extract_flat": "in_playlist",
            "playlistend": count,
            "noplaylist": False,
            "extractor_args": {"youtubetab": {"approximate_date": [""]}},
        }

        def attempt() -> Any:
            with self.open_ydl(options) as ydl:
                return ydl.extract_info(url, download=False)

        info = self.with_backoff(attempt, "Video list")
        if not info:
            raise UserFacingError("YouTube did not return a video list.")
        title = info.get("channel") or info.get("uploader") or info.get("title")
        entries = [entry_from_flat(item) for item in info.get("entries") or []]
        videos = [entry for entry in entries if entry is not None][:count]
        return str(title or url), videos

    def fetch_info(self, url: str) -> dict[str, Any]:
        """Fetch full metadata (incl. heatmap and subtitle list) of a video.

        Args:
            url: Video URL.

        Returns:
            yt-dlp info dict.

        Raises:
            UserFacingError: If the link is not a single video.
        """

        def attempt() -> Any:
            with self.open_ydl(self.metadata_options()) as ydl:
                return ydl.extract_info(url, download=False)

        info = self.with_backoff(attempt, "Video info")
        if not info:
            raise UserFacingError("YouTube did not return video info.")
        if info.get("_type") in ("playlist", "multi_video"):
            raise UserFacingError(
                "The link points to a list of videos, not a single video."
            )
        return info

    def fetch_comments(self, url: str, limit: int = MAX_COMMENTS) -> list[dict]:
        """Fetch top-level comments sorted by "Top comments".

        Args:
            url: Video URL.
            limit: Maximum number of comments.

        Returns:
            yt-dlp comment dicts.
        """
        options = {
            **self.metadata_options(),
            "getcomments": True,
            "extractor_args": {
                "youtube": {
                    # total, parents, replies -> no replies needed
                    "max_comments": [str(limit), "all", "0"],
                    "comment_sort": ["top"],
                }
            },
        }

        def attempt() -> Any:
            with self.open_ydl(options) as ydl:
                return ydl.extract_info(url, download=False)

        info = self.with_backoff(attempt, "Comments")
        comments = (info or {}).get("comments") or []
        top_level = [
            c
            for c in comments
            if isinstance(c, dict) and c.get("parent", "root") == "root"
        ]
        return top_level[:limit]

    def fetch_subtitles(
        self, info: Mapping, language: str = "en"
    ) -> tuple[list[Cue], SubtitleTrack | None]:
        """Download subtitles (manual first, then automatic) in json3 format.

        Args:
            info: yt-dlp info dict of the video.
            language: Subtitle language.

        Returns:
            Tuple of (cues, track). Both are empty/``None`` without subtitles.

        Raises:
            ValueError: If the downloaded data is not valid json3.
        """
        track = pick_subtitle_track(info, language)
        if track is None:
            return [], None
        import_yt_dlp()
        from yt_dlp.networking import Request

        def attempt() -> bytes:
            with self.open_ydl(self.metadata_options()) as ydl:
                request = Request(track.url, extensions=_impersonation(ydl, track))
                with ydl.urlopen(request) as response:
                    return response.read()

        raw = self.with_backoff(attempt, "Subtitles")
        return parse_json3(raw), track


def _impersonation(ydl: Any, track: SubtitleTrack) -> dict[str, Any]:
    """Request extensions that mimic a browser when yt-dlp supports it."""
    if not track.impersonate:
        return {}
    try:
        target, _ = ydl._parse_impersonate_targets(track.impersonate)
    except Exception:  # private yt-dlp API, may change between versions
        logger.debug("Impersonation is not available", exc_info=True)
        return {}
    return {"impersonate": target} if target else {}
