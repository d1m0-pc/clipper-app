"""Parsing the "Most replayed" heatmap and turning it into moments.

yt-dlp exposes the heatmap as ``info["heatmap"]``: a list of dicts with
``start_time``, ``end_time`` and ``value`` (0-1, the highest bar is 1.0).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

from .models import SOURCE_HEATMAP, HeatSegment, Moment

DEFAULT_TOP_N = 10
DEFAULT_SKIP_INTRO = 60.0
# Heatmap boundaries are floats (e.g. 2.14, 4.28), so allow a little slack
# when deciding whether two segments touch.
DEFAULT_MAX_GAP = 0.5


def parse_heatmap(raw: Iterable[Mapping] | None) -> list[HeatSegment]:
    """Convert yt-dlp's heatmap list into validated segments.

    Invalid entries (missing keys, non-numbers, negative or empty ranges)
    are skipped instead of raising.

    Args:
        raw: The ``heatmap`` field from a yt-dlp info dict, or ``None``.

    Returns:
        Segments sorted by start time, with values clamped to 0-1.
    """
    segments: list[HeatSegment] = []
    if not raw:
        return segments
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        try:
            start = float(item["start_time"])
            end = float(item["end_time"])
            value = float(item.get("value") or 0.0)
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(x) for x in (start, end, value)):
            continue
        if start < 0 or end <= start:
            continue
        segments.append(HeatSegment(start, end, min(max(value, 0.0), 1.0)))
    segments.sort(key=lambda seg: seg.start)
    return segments


def select_top_segments(
    segments: Sequence[HeatSegment],
    top_n: int = DEFAULT_TOP_N,
    skip_intro: float = DEFAULT_SKIP_INTRO,
) -> list[HeatSegment]:
    """Pick the strongest segments, ignoring the intro.

    The intro is skipped because almost everyone watches the first seconds,
    so the heatmap is always high there.

    Args:
        segments: Parsed heatmap segments.
        top_n: How many segments to keep.
        skip_intro: Segments starting before this many seconds are ignored.

    Returns:
        Up to ``top_n`` segments with the highest values, sorted by time.
        Ties are resolved in favour of the earlier segment.
    """
    candidates = [seg for seg in segments if seg.start >= skip_intro]
    ranked = sorted(candidates, key=lambda seg: (-seg.value, seg.start))
    return sorted(ranked[: max(0, top_n)], key=lambda seg: seg.start)


def merge_adjacent(
    segments: Iterable[HeatSegment],
    max_gap: float = DEFAULT_MAX_GAP,
) -> list[Moment]:
    """Merge segments that touch each other into longer moments.

    Args:
        segments: Selected segments (any order).
        max_gap: Maximum gap in seconds between two segments that are still
            considered adjacent.

    Returns:
        Moments sorted by time. ``score`` is the peak value of the merged
        segments and ``avg_score`` their average.
    """
    moments: list[Moment] = []
    group: list[HeatSegment] = []
    for seg in sorted(segments, key=lambda s: s.start):
        if group and seg.start - max(s.end for s in group) > max_gap:
            moments.append(_moment_from_group(group))
            group = []
        group.append(seg)
    if group:
        moments.append(_moment_from_group(group))
    return moments


def find_heatmap_moments(
    raw: Iterable[Mapping] | None,
    top_n: int = DEFAULT_TOP_N,
    skip_intro: float = DEFAULT_SKIP_INTRO,
    max_gap: float = DEFAULT_MAX_GAP,
) -> list[Moment]:
    """Full pipeline: parse, skip intro, take top segments and merge them.

    Args:
        raw: The ``heatmap`` field from a yt-dlp info dict.
        top_n: Number of top segments to select before merging.
        skip_intro: Seconds at the start of the video to ignore.
        max_gap: Gap tolerance used when merging.

    Returns:
        Moments sorted by time (empty if there is no usable heatmap).
    """
    top = select_top_segments(parse_heatmap(raw), top_n, skip_intro)
    return merge_adjacent(top, max_gap)


def _moment_from_group(group: Sequence[HeatSegment]) -> Moment:
    peak = max(group, key=lambda seg: seg.value)
    return Moment(
        start=group[0].start,
        end=max(seg.end for seg in group),
        score=peak.value,
        source=SOURCE_HEATMAP,
        avg_score=sum(seg.value for seg in group) / len(group),
        segment_count=len(group),
        peak_time=peak.start,
    )
