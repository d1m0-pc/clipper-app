"""Exceptions and translation of technical errors into readable English."""

from __future__ import annotations


class UserFacingError(Exception):
    """An error whose message is already written for the user."""


class TaskCancelled(Exception):
    """Raised when the user cancels a running task."""


UPDATE_HINT = (
    'Click "Check/update yt-dlp" (on the "Tools & help" tab) '
    "and make sure Deno is installed."
)
COOKIES_HINT = (
    'Create a cookies.txt file (instructions are on the "Settings" tab) '
    "and try again."
)
LOG_HINT = 'Details were written to the log file ("logs" folder).'

# Order matters: the first matching rule wins.
_RULES: list[tuple[tuple[str, ...], str]] = [
    (
        ("http error 429", "too many requests"),
        "YouTube is temporarily limiting requests (error 429). Wait a few "
        "minutes and try again. A cookies.txt file also helps.",
    ),
    (
        (
            "nsig extraction failed",
            "precondition check failed",
            "signature extraction failed",
            "n challenge solving failed",
            "challenge solving failed",
        ),
        f"yt-dlp cannot get past YouTube's protection (the version is probably "
        f"outdated). {UPDATE_HINT}",
    ),
    (
        ("requested format is not available", "no video formats found"),
        f"YouTube did not offer any format for download. {UPDATE_HINT}",
    ),
    (
        ("could not copy chrome cookie database", "failed to decrypt with dpapi"),
        "Reading cookies directly from Brave/Chrome does not work on Windows. "
        'Use a cookies.txt file ("Settings" tab).',
    ),
    (
        ("does not look like a netscape format cookies file",),
        "The cookies.txt file is invalid. Export it again with the "
        '"Get cookies.txt LOCALLY" extension.',
    ),
    (
        ("sign in to confirm your age", "age-restricted", "inappropriate for some"),
        f"The video is age-restricted and requires sign-in. {COOKIES_HINT}",
    ),
    (
        ("not a bot", "sign in to confirm"),
        f"YouTube asks you to confirm you are not a bot. {COOKIES_HINT}",
    ),
    (
        ("members-only", "join this channel to get access"),
        "The video is available to channel members only.",
    ),
    (("private video",), "The video is private."),
    (
        ("this live event will begin", "premieres in", "premiere will begin"),
        "The video is not published yet (scheduled premiere or live stream).",
    ),
    (
        (
            "video unavailable",
            "this video is not available",
            "this video has been removed",
            "video is unavailable",
        ),
        "The video is unavailable (deleted, blocked in your country or private).",
    ),
    (
        ("does not have a videos tab", "this channel does not exist"),
        "The channel does not exist or has no public videos.",
    ),
    (
        ("ffmpeg not found", "ffprobe and ffmpeg not found", "ffmpeg is not installed"),
        "ffmpeg was not found. Install it with: winget install Gyan.FFmpeg",
    ),
    (
        ("unsupported url",),
        "Unsupported link. Enter a YouTube video or channel link.",
    ),
    (("no space left on device",), "Not enough free disk space."),
    (
        ("permission denied", "access is denied", "winerror 5"),
        "No write permission. Choose another clips folder "
        '("Settings" tab) or close the program that is using the file.',
    ),
    (
        (
            "getaddrinfo failed",
            "name or service not known",
            "failed to resolve",
            "temporary failure in name resolution",
            "network is unreachable",
            "timed out",
            "connection reset",
            "connection refused",
            "connection aborted",
            "remote end closed connection",
            "unable to connect",
            "urlopen error",
        ),
        "Internet connection problem. Check your network and try again.",
    ),
]


def friendly_error(error: BaseException | str) -> str:
    """Translate an exception into a short user-facing explanation.

    Args:
        error: The exception (or its message).

    Returns:
        A message for the user. Unknown errors get a generic message that
        points to the log file; the full traceback is logged separately.
    """
    if isinstance(error, UserFacingError):
        return str(error)
    if isinstance(error, TaskCancelled):
        return "Cancelled at your request."
    text = str(error).lower()
    for needles, message in _RULES:
        if any(needle in text for needle in needles):
            return message
    return f"An unexpected error occurred. {LOG_HINT}"


def is_known_error(error: BaseException | str) -> bool:
    """Return ``True`` if :func:`friendly_error` has a specific explanation.

    Args:
        error: The exception (or its message).

    Returns:
        Whether the error matched one of the known patterns.
    """
    if isinstance(error, (UserFacingError, TaskCancelled)):
        return True
    text = str(error).lower()
    return any(any(n in text for n in needles) for needles, _ in _RULES)
