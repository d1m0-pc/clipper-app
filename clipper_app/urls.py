"""Recognizing YouTube video, channel and playlist links."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, unquote, urlsplit

KIND_VIDEO = "video"
KIND_CHANNEL = "channel"
KIND_PLAYLIST = "playlist"

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_HANDLE_RE = re.compile(r"^@[^/\s?#]+$")
_YOUTUBE_HOSTS = {
    "youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
}
_VIDEO_PATH_PREFIXES = {"shorts", "live", "embed", "v", "e"}
_CHANNEL_PREFIXES = {"channel", "c", "user"}
_KEPT_CHANNEL_TABS = {"shorts", "streams"}

_HELP = (
    "Examples: https://www.youtube.com/watch?v=dQw4w9WgXcQ "
    "or https://youtube.com/@waveform"
)


@dataclass(frozen=True)
class YouTubeLink:
    """A recognized YouTube link.

    Attributes:
        kind: ``KIND_VIDEO``, ``KIND_CHANNEL`` or ``KIND_PLAYLIST``.
        url: Normalized URL to pass to yt-dlp.
        video_id: The video id for video links.
    """

    kind: str
    url: str
    video_id: str | None = None

    @property
    def is_list(self) -> bool:
        """``True`` for channels and playlists (links with many videos)."""
        return self.kind in (KIND_CHANNEL, KIND_PLAYLIST)


def watch_url(video_id: str) -> str:
    """Return the canonical watch URL for a video id.

    Args:
        video_id: 11 character YouTube id.

    Returns:
        ``https://www.youtube.com/watch?v=<id>``.
    """
    return f"https://www.youtube.com/watch?v={video_id}"


def parse_youtube_link(text: str) -> YouTubeLink:
    """Recognize what kind of YouTube link the user entered.

    Channel links are normalized to their "Videos" tab (unless the user
    explicitly chose Shorts or Live), so yt-dlp lists only videos.

    Args:
        text: Link (or bare video id / ``@handle``) typed by the user.

    Returns:
        The recognized link.

    Raises:
        ValueError: With a user-facing message if the link is not recognized.
    """
    raw = (text or "").strip().strip("\"'<>")
    if not raw:
        raise ValueError(f"Enter a YouTube link. {_HELP}")
    if _VIDEO_ID_RE.match(raw):
        return YouTubeLink(KIND_VIDEO, watch_url(raw), raw)
    if _HANDLE_RE.match(raw):
        return YouTubeLink(KIND_CHANNEL, _channel_url(raw, None))
    if not re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.IGNORECASE):
        raw = f"https://{raw}"

    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    segments = [unquote(s) for s in parts.path.split("/") if s]
    query = parse_qs(parts.query)

    if host == "youtu.be":
        if segments and _VIDEO_ID_RE.match(segments[0]):
            return YouTubeLink(KIND_VIDEO, watch_url(segments[0]), segments[0])
        raise ValueError(f"The link does not contain a valid video ID. {_HELP}")
    if host not in _YOUTUBE_HOSTS:
        raise ValueError(f"This is not a YouTube link. {_HELP}")

    first = segments[0].lower() if segments else ""
    if first == "watch":
        video_id = (query.get("v") or [""])[0]
        if _VIDEO_ID_RE.match(video_id):
            return YouTubeLink(KIND_VIDEO, watch_url(video_id), video_id)
        raise ValueError(f"The link does not contain a valid video ID. {_HELP}")
    if first in _VIDEO_PATH_PREFIXES and len(segments) > 1:
        if _VIDEO_ID_RE.match(segments[1]):
            return YouTubeLink(KIND_VIDEO, watch_url(segments[1]), segments[1])
    if first == "playlist":
        list_id = (query.get("list") or [""])[0]
        if list_id:
            return YouTubeLink(
                KIND_PLAYLIST,
                f"https://www.youtube.com/playlist?list={quote(list_id)}",
            )
    if segments and segments[0].startswith("@"):
        tab = segments[1] if len(segments) > 1 else None
        return YouTubeLink(KIND_CHANNEL, _channel_url(segments[0], tab))
    if first in _CHANNEL_PREFIXES and len(segments) > 1:
        tab = segments[2] if len(segments) > 2 else None
        return YouTubeLink(
            KIND_CHANNEL, _channel_url(f"{segments[0]}/{segments[1]}", tab)
        )
    raise ValueError(f"The link was not recognized as a video or a channel. {_HELP}")


def _channel_url(base: str, tab: str | None) -> str:
    tab_name = (tab or "").lower()
    if tab_name not in _KEPT_CHANNEL_TABS:
        tab_name = "videos"
    return f"https://www.youtube.com/{quote(base, safe='@/')}/{tab_name}"
