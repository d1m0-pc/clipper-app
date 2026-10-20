"""Finding popular moments from timestamps written in comments.

Used as a fallback when a video has no "Most replayed" heatmap. Viewers
often write things like "4:12 I lost it", so timestamps that are mentioned
often (and liked a lot) point to the best moments.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from .models import SOURCE_COMMENTS, CommentExample, Moment

DEFAULT_TOP_N = 10
# Comments with more timestamps than this are usually chapter lists
# ("0:00 intro, 1:20 ..."), not reactions to one moment.
DEFAULT_MAX_TIMESTAMPS_PER_COMMENT = 4
DEFAULT_MOMENT_LENGTH = 60.0
DEFAULT_EXAMPLES = 3
MAX_EXAMPLE_LENGTH = 300

_TIMESTAMP_RE = re.compile(
    r"(?<![\d:.])"  # not part of a longer number or time
    r"(?:(\d{1,2}):)?(\d{1,3}):([0-5]\d)"
    r"(?![\d:])"
    r"(?!\s?[ap]\.?m\b)",  # skip clock times such as "10:30 pm"
    re.IGNORECASE,
)


def extract_timestamps(text: str, max_seconds: float | None = None) -> list[int]:
    """Find video timestamps such as ``4:12`` or ``1:02:03`` in text.

    Args:
        text: Comment text.
        max_seconds: Ignore timestamps after this time (the video length).

    Returns:
        Unique timestamps in seconds, in order of appearance.
    """
    found: list[int] = []
    for match in _TIMESTAMP_RE.finditer(text or ""):
        hours_text, minutes_text, seconds_text = match.groups()
        hours = int(hours_text) if hours_text else 0
        minutes = int(minutes_text)
        if hours_text and minutes >= 60:
            continue
        total = hours * 3600 + minutes * 60 + int(seconds_text)
        if max_seconds is not None and total > max_seconds:
            continue
        if total not in found:
            found.append(total)
    return found


@dataclass(frozen=True)
class _Mention:
    likes: int
    example: CommentExample

    @property
    def weight(self) -> int:
        return 1 + self.likes


@dataclass
class _MinuteBucket:
    minute: int
    comment_ids: set[int] = field(default_factory=set)
    second_weights: Counter = field(default_factory=Counter)

    def weight(self, mentions: list[_Mention]) -> int:
        return sum(mentions[i].weight for i in self.comment_ids)

    def key_second(self) -> int:
        weights = self.second_weights
        return min(weights, key=lambda s: (-weights[s], s))


def find_comment_moments(
    comments: Iterable[Mapping],
    duration: float | None = None,
    top_n: int = DEFAULT_TOP_N,
    skip_intro: float = 0.0,
    max_timestamps_per_comment: int = DEFAULT_MAX_TIMESTAMPS_PER_COMMENT,
    examples: int = DEFAULT_EXAMPLES,
    moment_length: float = DEFAULT_MOMENT_LENGTH,
) -> list[Moment]:
    """Group comment timestamps by minute and rank them by likes.

    Every comment adds ``1 + likes`` to each minute it mentions. A moment
    starts at the most-weighted exact second of its minute. Moments that
    overlap (e.g. 3:58 and 4:00, which fall into different minutes) are
    merged, and each comment is counted only once per merged moment.
    ``0:00`` is ignored: it is a chapter marker ("0:00 intro"), not a
    reaction.

    Args:
        comments: yt-dlp comment dicts (``text``, ``like_count``).
        duration: Video length in seconds; later timestamps are ignored.
        top_n: Maximum number of moments to return.
        skip_intro: Ignore timestamps before this many seconds.
        max_timestamps_per_comment: Comments with more timestamps are treated
            as chapter lists and ignored.
        examples: Number of example comments to keep per moment.
        moment_length: Length of each moment in seconds; merged moments are
            at most twice as long.

    Returns:
        Moments sorted by time. ``score`` is the likes-weighted total.
    """
    mentions: list[_Mention] = []
    buckets: dict[int, _MinuteBucket] = {}
    for comment in comments:
        if not isinstance(comment, Mapping):
            continue
        text = str(comment.get("text") or "")
        stamps = extract_timestamps(text, duration)
        if not stamps or len(stamps) > max_timestamps_per_comment:
            continue
        stamps = [s for s in stamps if s > 0 and s >= skip_intro]
        if not stamps:
            continue
        likes = _to_int(comment.get("like_count"))
        comment_id = len(mentions)
        mentions.append(_Mention(likes, CommentExample(likes, _shorten(text))))
        for second in stamps:
            bucket = buckets.setdefault(second // 60, _MinuteBucket(second // 60))
            bucket.comment_ids.add(comment_id)
            bucket.second_weights[second] += 1 + likes

    groups = _merge_overlapping(
        sorted(buckets.values(), key=lambda b: b.key_second()), moment_length
    )
    moments = [
        _moment_from_group(group, mentions, duration, examples, moment_length)
        for group in groups
    ]
    ranked = sorted(moments, key=lambda m: (-m.score, -m.mentions, m.start))
    return sorted(ranked[: max(0, top_n)], key=lambda m: m.start)


def _merge_overlapping(
    buckets: list[_MinuteBucket], moment_length: float
) -> list[list[_MinuteBucket]]:
    groups: list[list[_MinuteBucket]] = []
    group_end = 0.0
    for bucket in buckets:
        start = bucket.key_second()
        if groups and start < group_end:
            groups[-1].append(bucket)
            group_start = groups[-1][0].key_second()
            group_end = min(start + moment_length, group_start + 2 * moment_length)
        else:
            groups.append([bucket])
            group_end = start + moment_length
    return groups


def _moment_from_group(
    group: list[_MinuteBucket],
    mentions: list[_Mention],
    duration: float | None,
    examples: int,
    moment_length: float,
) -> Moment:
    start = group[0].key_second()
    last = group[-1].key_second()
    end = min(last + moment_length, start + 2 * moment_length)
    if duration:
        end = min(end, duration)
    end = max(end, start + 1)
    ids = set().union(*(bucket.comment_ids for bucket in group))
    strongest = max(group, key=lambda b: (b.weight(mentions), -b.minute))
    top_comments = sorted(
        (mentions[i].example for i in ids), key=lambda c: (-c.likes, c.text)
    )[:examples]
    return Moment(
        start=float(start),
        end=float(end),
        score=float(sum(mentions[i].weight for i in ids)),
        source=SOURCE_COMMENTS,
        peak_time=float(strongest.key_second()),
        mentions=len(ids),
        likes=sum(mentions[i].likes for i in ids),
        examples=top_comments,
    )


def _to_int(value: object) -> int:
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _shorten(text: str) -> str:
    single_line = " ".join(text.split())
    if len(single_line) <= MAX_EXAMPLE_LENGTH:
        return single_line
    return single_line[: MAX_EXAMPLE_LENGTH - 1].rstrip() + "…"
