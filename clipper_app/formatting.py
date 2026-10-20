"""Formatting and parsing helpers for times, counts and dates."""

from __future__ import annotations

import math
from datetime import datetime


def format_time(seconds: float | None) -> str:
    """Format a number of seconds as ``M:SS`` or ``H:MM:SS``.

    Args:
        seconds: Time in seconds. ``None`` or negative values give ``0:00``.

    Returns:
        Human readable time, e.g. ``"4:05"`` or ``"1:02:03"``.
    """
    if seconds is None or not math.isfinite(seconds):
        seconds = 0
    total = max(0, int(round(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def parse_time(text: str) -> float:
    """Parse a time typed by the user into seconds.

    Accepted forms: ``"83"``, ``"1:23"``, ``"1:02:03"`` and decimals in the
    last part such as ``"1:23.5"`` or ``"1:23,5"``.

    Args:
        text: The time as typed by the user.

    Returns:
        Time in seconds.

    Raises:
        ValueError: With a user-facing message when the text is not a valid
            time.
    """
    example = "Example: 83, 1:23 or 1:02:03."
    cleaned = (text or "").strip().replace(",", ".")
    if not cleaned:
        raise ValueError(f"No time entered. {example}")
    parts = cleaned.split(":")
    if len(parts) > 3 or any(not part.strip() for part in parts):
        raise ValueError(f'Invalid time: "{text}". {example}')
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        raise ValueError(f'Invalid time: "{text}". {example}') from None
    if any(not math.isfinite(n) or n < 0 for n in numbers):
        raise ValueError(f'Invalid time: "{text}". {example}')
    if any(n != int(n) for n in numbers[:-1]):
        raise ValueError(f'Only seconds can have decimals: "{text}". {example}')
    if any(n >= 60 for n in numbers[1:]):
        raise ValueError(
            f'Minutes and seconds must be less than 60: "{text}". {example}'
        )
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def format_count(value: int | float | None) -> str:
    """Format a count with comma thousands separators (``1,234,567``).

    Args:
        value: The count, or ``None`` when unknown.

    Returns:
        Formatted number or ``"-"`` when unknown.
    """
    if value is None:
        return "-"
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:,}"


def format_date(
    upload_date: str | None,
    timestamp: float | None = None,
    approximate: bool = False,
) -> str:
    """Format a YouTube date as ISO ``YYYY-MM-DD``.

    Args:
        upload_date: Date in yt-dlp ``YYYYMMDD`` format, if known.
        timestamp: Unix timestamp used when ``upload_date`` is missing.
        approximate: Prefix the result with ``~`` (flat channel listings only
            know an approximate date such as "2 weeks ago").

    Returns:
        Formatted date or ``"-"`` when unknown.
    """
    date = None
    if upload_date and len(upload_date) == 8 and upload_date.isdigit():
        try:
            date = datetime.strptime(upload_date, "%Y%m%d")
        except ValueError:
            date = None
    if date is None and timestamp:
        try:
            date = datetime.fromtimestamp(float(timestamp))
        except (OverflowError, OSError, ValueError):
            date = None
    if date is None:
        return "-"
    prefix = "~" if approximate else ""
    return f"{prefix}{date:%Y-%m-%d}"
