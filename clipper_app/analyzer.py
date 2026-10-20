"""Analyzing one video: heatmap first, comments as fallback, then subtitles."""

from __future__ import annotations

import logging

from .comments import find_comment_moments
from .config import Settings
from .errors import TaskCancelled, UserFacingError, friendly_error
from .heatmap import merge_adjacent, parse_heatmap, select_top_segments
from .models import (
    SOURCE_COMMENTS,
    SOURCE_HEATMAP,
    SOURCE_NONE,
    Cue,
    Moment,
    SubtitleTrack,
    VideoAnalysis,
)
from .reporting import (
    LEVEL_INFO,
    LEVEL_SUCCESS,
    LEVEL_WARNING,
    Reporter,
    check_cancelled,
)
from .youtube import MAX_COMMENTS, YouTubeService, entry_from_info

logger = logging.getLogger(__name__)


def analyze_video(
    service: YouTubeService,
    url: str,
    settings: Settings,
    reporter: Reporter,
) -> VideoAnalysis:
    """Find the best moments of a video.

    Steps: fetch metadata, use the "Most replayed" heatmap (skipping the
    intro and merging adjacent segments), fall back to comment timestamps
    when there is no heatmap, then download English subtitles.

    Args:
        service: YouTube access.
        url: Video URL.
        settings: Current settings (top N, intro to skip).
        reporter: Progress/log channel.

    Returns:
        The analysis result.

    Raises:
        UserFacingError: For videos that cannot be analyzed (e.g. upcoming).
        TaskCancelled: If the user cancels.
    """
    check_cancelled(reporter)
    reporter.status("Downloading video info...", None)
    info = service.fetch_info(url)
    video = entry_from_info(info)
    reporter.log(f"Video: {video.title}")

    notes: list[str] = []
    live_status = info.get("live_status")
    if live_status == "is_upcoming":
        raise UserFacingError(
            "The video is not published yet (scheduled premiere or live stream)."
        )
    if live_status == "is_live":
        notes.append("The stream is live right now, data may be incomplete.")

    heatmap = parse_heatmap(info.get("heatmap"))
    skip_intro = float(settings.skip_intro_seconds)
    moments: list[Moment] = []
    source = SOURCE_NONE
    if heatmap:
        top = select_top_segments(heatmap, settings.top_segments, skip_intro)
        if not top:
            skip_intro = 0.0
            notes.append("The video is short, so the intro was not skipped.")
            top = select_top_segments(heatmap, settings.top_segments, 0.0)
        moments = merge_adjacent(top)
        source = SOURCE_HEATMAP
        reporter.log(
            f'"Most replayed": {len(top)} top segments merged into '
            f"{len(moments)} moments.",
            LEVEL_SUCCESS,
        )
    else:
        skip_intro = 0.0
        reporter.log(
            'This video has no "Most replayed" (heatmap) data. '
            "Looking for timestamps in comments...",
            LEVEL_WARNING,
        )
        moments = _moments_from_comments(
            service, url, video.duration, settings, reporter, notes
        )
        if moments:
            source = SOURCE_COMMENTS

    check_cancelled(reporter)
    cues: list[Cue] = []
    track: SubtitleTrack | None = None
    if moments:
        cues, track = _load_subtitles(service, info, reporter, notes)
    return VideoAnalysis(
        video=video,
        source=source,
        moments=moments,
        heatmap=heatmap,
        cues=cues,
        subtitle_track=track,
        skip_intro=skip_intro,
        notes=notes,
    )


def _moments_from_comments(
    service: YouTubeService,
    url: str,
    duration: float | None,
    settings: Settings,
    reporter: Reporter,
    notes: list[str],
) -> list[Moment]:
    check_cancelled(reporter)
    reporter.status("Downloading comments (up to 500, top first)...", None)
    try:
        comments = service.fetch_comments(url, MAX_COMMENTS)
    except TaskCancelled:
        raise
    except Exception as exc:
        logger.exception("Comments were not downloaded")
        reporter.log(
            f"Comments were not downloaded: {friendly_error(exc)}", LEVEL_WARNING
        )
        notes.append("Comments could not be downloaded.")
        return []
    if not comments:
        # yt-dlp returns an empty list (no error) when comments are disabled.
        reporter.log(
            "The video has no comments (they are probably disabled) and no "
            '"Most replayed" data, so there are no automatic suggestions. You '
            'can still enter a start and end manually and click "Cut".',
            LEVEL_WARNING,
        )
        notes.append(
            'No "Most replayed" data, and comments are disabled or missing. '
            "Cutting works by entering the start and end manually."
        )
        return []
    reporter.log(f"Comments downloaded: {len(comments)}.", LEVEL_INFO)
    moments = find_comment_moments(comments, duration, top_n=settings.top_segments)
    if moments:
        reporter.log(
            f"From comments: {len(moments)} most mentioned moments.",
            LEVEL_SUCCESS,
        )
        notes.append(
            'The video has no "Most replayed" data, moments were found from '
            "comment timestamps (weight = 1 + number of likes)."
        )
    else:
        reporter.log(
            "The comments contain no timestamps either, so there are no "
            "suggestions for this video.",
            LEVEL_WARNING,
        )
        notes.append("No heatmap data and no timestamps in comments.")
    return moments


def _load_subtitles(
    service: YouTubeService,
    info: dict,
    reporter: Reporter,
    notes: list[str],
) -> tuple[list[Cue], SubtitleTrack | None]:
    check_cancelled(reporter)
    reporter.status("Downloading English subtitles...", None)
    try:
        cues, track = service.fetch_subtitles(info, "en")
    except TaskCancelled:
        raise
    except Exception as exc:
        logger.exception("Subtitles were not downloaded")
        reason = str(exc) if isinstance(exc, ValueError) else friendly_error(exc)
        reporter.log(f"Subtitles were not downloaded: {reason}", LEVEL_WARNING)
        notes.append("Subtitles could not be downloaded, no transcript is shown.")
        return [], None
    if track is None:
        reporter.log(
            "The video has no English subtitles, so no transcript will be shown.",
            LEVEL_WARNING,
        )
        notes.append("The video has no English subtitles.")
    elif not cues:
        reporter.log("The English subtitles are empty.", LEVEL_WARNING)
    else:
        reporter.log(
            f"Subtitles downloaded ({track.language}, {track.kind_label}).",
            LEVEL_SUCCESS,
        )
    return cues, track
