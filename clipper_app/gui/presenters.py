"""Turning analysis results into text for the GUI (no tkinter here)."""

from __future__ import annotations

from ..formatting import format_count, format_date, format_time
from ..models import SOURCE_COMMENTS, SOURCE_HEATMAP, Moment, VideoAnalysis, VideoEntry
from ..transcript import moment_transcript


def video_values(entry: VideoEntry, status: str) -> tuple[str, ...]:
    """Row values for the video table.

    Args:
        entry: The video.
        status: Analysis status text.

    Returns:
        Values for the title, date, views, duration and status columns.
    """
    return (
        entry.title,
        format_date(entry.upload_date, entry.timestamp, entry.date_is_approximate),
        format_count(entry.view_count),
        format_time(entry.duration) if entry.duration else "-",
        status,
    )


def analysis_status(analysis: VideoAnalysis) -> str:
    """Short status for the video table after analysis.

    Args:
        analysis: The finished analysis.

    Returns:
        Text such as ``"Done: 5 moments (heatmap)"``.
    """
    count = len(analysis.moments)
    if analysis.source == SOURCE_HEATMAP:
        return f"Done: {count} moments (heatmap)"
    if analysis.source == SOURCE_COMMENTS:
        return f"Done: {count} moments (comments)"
    return "No data"


def moment_values(index: int, moment: Moment) -> tuple[str, ...]:
    """Row values for the moments table.

    Args:
        index: Zero-based moment index.
        moment: The moment.

    Returns:
        Values for the #, start, end, length, score and details columns.
    """
    if moment.source == SOURCE_HEATMAP:
        average = (moment.avg_score or moment.score) * 100
        info = f"{moment.segment_count} segm., avg {average:.0f}"
    else:
        info = f"{moment.mentions} mentions, {format_count(moment.likes)} likes"
    return (
        str(index + 1),
        format_time(moment.start),
        format_time(moment.end),
        f"{moment.duration:.0f} s",
        moment.score_label(),
        info,
    )


def results_header(analysis: VideoAnalysis) -> str:
    """One-line description of the shown results.

    Args:
        analysis: The analysis.

    Returns:
        Header text with source and subtitle info.
    """
    track = analysis.subtitle_track
    subtitles = (
        f"subtitles: {track.language} ({track.kind_label})"
        if track is not None and analysis.cues
        else "subtitles: none"
    )
    return f"Source: {analysis.source_label}  |  {subtitles}"


def clip_range(
    moment: Moment, lead_in: float, duration: float | None
) -> tuple[float, float]:
    """Default clip range for a moment (with lead-in before it).

    Args:
        moment: The moment.
        lead_in: Seconds to add before the moment.
        duration: Video length, used to clamp the end.

    Returns:
        Tuple of (start, end) in seconds.
    """
    start = max(0.0, moment.start - max(0.0, lead_in))
    end = moment.end if not duration else min(moment.end, float(duration))
    return start, end


def moment_details(analysis: VideoAnalysis, index: int, lead_in: float) -> str:
    """Full description of a moment: score, link, transcript and comments.

    Args:
        analysis: The analysis that contains the moment.
        index: Zero-based moment index.
        lead_in: Seconds of transcript before the moment.

    Returns:
        Multi-line text for the details panel.
    """
    moment = analysis.moments[index]
    lines = [
        f"Moment #{index + 1}: {format_time(moment.start)} - "
        f"{format_time(moment.end)} ({moment.duration:.0f} s)"
    ]
    if moment.source == SOURCE_HEATMAP:
        average = (moment.avg_score or moment.score) * 100
        lines.append(
            f"Score: {moment.score_label()} (avg {average:.0f}), "
            f"merged segments: {moment.segment_count}"
        )
    else:
        lines.append(
            f"Score (1 + likes per comment): {moment.score_label()}  |  "
            f"mentions: {moment.mentions}  |  likes: {format_count(moment.likes)}"
        )
    lines.append(f"Link: {analysis.video.moment_url(moment.start)}")
    lines.append("")

    from_time, text = moment_transcript(
        analysis.cues, moment.start, moment.end, lead_in
    )
    if not analysis.cues:
        lines.append(
            "Transcript not available (the video has no English subtitles or "
            "they could not be downloaded)."
        )
    elif text:
        lines.append(
            f"Transcript (from {format_time(from_time)}, {lead_in:g} s before "
            "the moment):"
        )
        lines.append(text)
    else:
        lines.append("The subtitles contain no text for this part of the video.")

    if moment.examples:
        lines.append("")
        lines.append("Example comments:")
        lines.extend(
            f"• ({format_count(c.likes)} likes) {c.text}" for c in moment.examples
        )
    if analysis.notes:
        lines.append("")
        lines.extend(f"Note: {note}" for note in analysis.notes)
    return "\n".join(lines)
