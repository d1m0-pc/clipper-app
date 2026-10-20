"""Cutting clips: download only the needed section, optionally crop to 9:16."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .environment import (
    FFMPEG_INSTALL_COMMAND,
    ToolStatus,
    no_window_flags,
    prepend_to_path,
)
from .errors import TaskCancelled, UserFacingError
from .formatting import format_time
from .models import VideoEntry
from .reporting import Reporter, check_cancelled
from .youtube import YouTubeService, import_yt_dlp

logger = logging.getLogger(__name__)

MAX_TITLE_LENGTH = 80
MIN_CLIP_SECONDS = 1.0
# Up to 1080p keeps downloads small; the last fallbacks take anything.
DOWNLOAD_FORMAT = "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b"
VERTICAL_SIZE = (1080, 1920)
# Center crop to 9:16. min() keeps it valid for sources that are already
# narrow; trunc(x/2)*2 keeps the size even, which libx264 requires.
VERTICAL_FILTER = (
    "crop='trunc(min(iw,ih*9/16)/2)*2':'trunc(min(ih,iw*16/9)/2)*2',"
    f"scale={VERTICAL_SIZE[0]}:{VERTICAL_SIZE[1]}:flags=lanczos,setsar=1"
)

_INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass(frozen=True)
class ClipRequest:
    """What the user wants to cut.

    Attributes:
        video: The source video.
        start: Clip start in seconds.
        end: Clip end in seconds.
        vertical: ``True`` for a 9:16 center crop, ``False`` for original.
        output_dir: Folder for the finished clip.
    """

    video: VideoEntry
    start: float
    end: float
    vertical: bool
    output_dir: Path


def sanitize_filename(name: str, max_length: int = MAX_TITLE_LENGTH) -> str:
    """Make a video title safe to use as a Windows file name.

    Args:
        name: Original title.
        max_length: Maximum length of the result.

    Returns:
        A file-name-safe version of the title (never empty).
    """
    cleaned = " ".join(_INVALID_CHARS_RE.sub(" ", name or "").split()).strip(" .")
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" .")
    if not cleaned:
        cleaned = "clip"
    if cleaned.split(".")[0].upper() in _WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned


def time_tag(seconds: float) -> str:
    """Format a time for file names (no colons): ``01m23s`` or ``1h02m03s``.

    Args:
        seconds: Time in seconds.

    Returns:
        The tag.
    """
    total = max(0, int(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    return f"{minutes:02d}m{secs:02d}s"


def clip_filename(title: str, start: float, end: float, vertical: bool) -> str:
    """Build the clip file name: video title + time range.

    Args:
        title: Video title.
        start: Clip start in seconds.
        end: Clip end in seconds.
        vertical: Adds a ``_9x16`` suffix for vertical clips.

    Returns:
        File name such as ``My video_12m34s-13m10s_9x16.mp4``.
    """
    suffix = "_9x16" if vertical else ""
    return f"{sanitize_filename(title)}_{time_tag(start)}-{time_tag(end)}{suffix}.mp4"


def unique_path(path: Path) -> Path:
    """Return ``path`` or ``name (2).ext``, ``name (3).ext``... if it exists.

    Args:
        path: Desired path.

    Returns:
        A path that does not exist yet.
    """
    if not path.exists():
        return path
    for number in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise UserFacingError("Too many files with the same name in the clips folder.")


def validate_range(
    start: float, end: float, duration: float | None
) -> tuple[float, float]:
    """Check a clip range and clamp the end to the video length.

    Args:
        start: Clip start in seconds.
        end: Clip end in seconds.
        duration: Video length in seconds, if known.

    Returns:
        The (start, end) range to cut.

    Raises:
        UserFacingError: If the range is not valid.
    """
    if start < 0:
        raise UserFacingError("The clip start cannot be negative.")
    if duration:
        if start >= duration:
            raise UserFacingError(
                "The start is after the end of the video "
                f"(length {format_time(duration)})."
            )
        end = min(end, float(duration))
    if end - start < MIN_CLIP_SECONDS:
        raise UserFacingError("The clip end must be at least 1 second after the start.")
    return start, end


def vertical_command(ffmpeg: str, source: Path, target: Path) -> list[str]:
    """ffmpeg command that center-crops a video to 9:16 (1080x1920).

    Args:
        ffmpeg: Path to ffmpeg.
        source: Input file.
        target: Output file.

    Returns:
        The command as an argument list.
    """
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-vf",
        VERTICAL_FILTER,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        str(target),
    ]


class ClipCutter:
    """Downloads a section of a video with yt-dlp and finishes it with ffmpeg."""

    def __init__(
        self, settings: Settings, tools: ToolStatus, reporter: Reporter
    ) -> None:
        """Create a cutter.

        Args:
            settings: Current settings (cookies).
            tools: Detected tools; ffmpeg is required.
            reporter: Progress/log channel.
        """
        self._settings = settings
        self._tools = tools
        self._reporter = reporter

    def download_options(self, request: ClipRequest, folder: Path) -> dict[str, Any]:
        """yt-dlp options that download only the requested section.

        ``force_keyframes_at_cuts`` re-encodes at the cut points so the clip
        starts exactly at ``start`` instead of the nearest keyframe.

        Args:
            request: The clip to cut.
            folder: Temporary folder for the download.

        Returns:
            Options for ``yt_dlp.YoutubeDL``.
        """
        yt_dlp = import_yt_dlp()
        service = YouTubeService(self._settings, self._tools, self._reporter)
        return {
            **service.base_options(),
            "format": DOWNLOAD_FORMAT,
            "merge_output_format": "mp4",
            "download_ranges": yt_dlp.utils.download_range_func(
                None, [(request.start, request.end)]
            ),
            "force_keyframes_at_cuts": True,
            "outtmpl": {"default": str(folder / "section.%(ext)s")},
            "overwrites": True,
            "progress_hooks": [self._progress_hook],
        }

    def cut(self, request: ClipRequest) -> Path:
        """Cut the clip and save it in the output folder.

        Args:
            request: The clip to cut.

        Returns:
            Path of the finished clip.

        Raises:
            UserFacingError: If ffmpeg is missing or cutting fails.
            TaskCancelled: If the user cancels.
        """
        if not self._tools.ffmpeg:
            raise UserFacingError(
                "ffmpeg is not installed, so cutting is not possible. Install it "
                f"with: {FFMPEG_INSTALL_COMMAND}"
            )
        start, end = validate_range(request.start, request.end, request.video.duration)
        request = ClipRequest(
            request.video, start, end, request.vertical, request.output_dir
        )
        request.output_dir.mkdir(parents=True, exist_ok=True)
        work_dir = Path(tempfile.mkdtemp(prefix=".clipper_", dir=request.output_dir))
        try:
            section = self._download_section(request, work_dir)
            check_cancelled(self._reporter)
            target = unique_path(
                request.output_dir
                / clip_filename(request.video.title, start, end, request.vertical)
            )
            if request.vertical:
                self._make_vertical(section, target, end - start)
            else:
                shutil.move(str(section), str(target))
            return target
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _download_section(self, request: ClipRequest, folder: Path) -> Path:
        self._reporter.status(
            f"Downloading video section {format_time(request.start)} - "
            f"{format_time(request.end)} (this may take a while)...",
            None,
        )
        _make_ffmpeg_visible_to_yt_dlp(self._tools.ffmpeg_dir)
        service = YouTubeService(self._settings, self._tools, self._reporter)
        options = self.download_options(request, folder)

        def attempt() -> Any:
            with service.open_ydl(options) as ydl:
                return ydl.extract_info(request.video.url, download=True)

        info = service.with_backoff(attempt, "Clip download")
        path = _downloaded_file(info, folder)
        if path is None:
            raise UserFacingError(
                "Downloading the video section failed (no file was created). "
                "Details are in the log file."
            )
        logger.info(
            "Downloaded video section: %s (%d bytes)", path, path.stat().st_size
        )
        return path

    def _make_vertical(self, source: Path, target: Path, length: float) -> None:
        assert self._tools.ffmpeg is not None
        self._reporter.status("Making the vertical 9:16 version...", 0.0)
        command = vertical_command(self._tools.ffmpeg, source, target)
        logger.info("ffmpeg: %s", command)
        cancelled = False
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=errors,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=no_window_flags(),
            )
            assert process.stdout is not None
            for line in process.stdout:
                key, _, value = line.strip().partition("=")
                if key in ("out_time_us", "out_time_ms") and value.isdigit():
                    done = min(int(value) / 1_000_000 / max(length, 0.1), 1.0)
                    self._reporter.status(
                        f"Making the vertical 9:16 version... {done:.0%}", done
                    )
                if self._reporter.cancelled():
                    cancelled = True
                    process.kill()
                    break
            code = process.wait()
            errors.seek(0)
            details = errors.read().decode("utf-8", errors="replace")[-4000:]
        if cancelled:
            target.unlink(missing_ok=True)
            raise TaskCancelled()
        if code != 0:
            logger.error("ffmpeg error (%s): %s", code, details)
            target.unlink(missing_ok=True)
            raise UserFacingError(
                "ffmpeg failed to make the vertical clip. Details are in the "
                "log file."
            )

    def _progress_hook(self, data: dict[str, Any]) -> None:
        if self._reporter.cancelled():
            yt_dlp = import_yt_dlp()
            raise yt_dlp.utils.DownloadCancelled("Cancelled")
        if data.get("status") != "downloading":
            return
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        done = data.get("downloaded_bytes")
        if total and done:
            fraction = min(done / total, 1.0)
            self._reporter.status(
                f"Downloading video section... {fraction:.0%}", fraction
            )


def _make_ffmpeg_visible_to_yt_dlp(ffmpeg_dir: str | None) -> None:
    """Work around yt-dlp checking only PATH before section downloads.

    yt-dlp decides whether ffmpeg can download a section by looking at PATH
    (not ``ffmpeg_location``) and remembers a negative answer for the whole
    process. If ffmpeg was installed while the app was running, that stale
    answer would block cutting until a restart.

    Args:
        ffmpeg_dir: Folder that contains ffmpeg.
    """
    prepend_to_path(ffmpeg_dir)
    try:
        from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor

        cache = FFmpegPostProcessor._version_cache  # private yt-dlp detail
        for key in [k for k, v in cache.items() if k is not None and not v]:
            del cache[key]
    except Exception:  # noqa: BLE001 - only an optimization, never fatal
        logger.debug("yt-dlp ffmpeg cache was not cleared", exc_info=True)


def _downloaded_file(info: Any, folder: Path) -> Path | None:
    for item in (info or {}).get("requested_downloads") or []:
        path = Path(str(item.get("filepath") or ""))
        if path.is_file() and path.stat().st_size > 0:
            return path
    candidates = [
        path
        for path in folder.glob("section.*")
        if path.suffix not in (".part", ".ytdl") and path.stat().st_size > 0
    ]
    return max(candidates, key=lambda p: p.stat().st_size) if candidates else None
