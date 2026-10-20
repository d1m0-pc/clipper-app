"""Exporting analysis results to .txt or .csv files."""

from __future__ import annotations

import csv
import textwrap
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from .formatting import format_count, format_date, format_time
from .models import SOURCE_HEATMAP, Moment, VideoAnalysis
from .transcript import moment_transcript

CSV_COLUMNS = [
    "Video",
    "Video link",
    "Source",
    "No.",
    "Start",
    "End",
    "Duration (s)",
    "Score",
    "Mentions",
    "Likes",
    "Moment link",
    "Transcript from",
    "Transcript",
    "Example comments",
]

_WRAP_WIDTH = 100


def numeric_score(moment: Moment) -> int:
    """Score as a plain number (0-100 for heatmap, weight for comments).

    Args:
        moment: The moment.

    Returns:
        Rounded score.
    """
    if moment.source == SOURCE_HEATMAP:
        return round(moment.score * 100)
    return round(moment.score)


def build_rows(analyses: Sequence[VideoAnalysis], lead_in: float) -> list[list[str]]:
    """Build one table row per moment.

    Args:
        analyses: Analyzed videos.
        lead_in: Seconds of transcript before each moment.

    Returns:
        Rows matching :data:`CSV_COLUMNS`.
    """
    rows: list[list[str]] = []
    for analysis in analyses:
        video = analysis.video
        for index, moment in enumerate(analysis.moments, start=1):
            from_time, text = moment_transcript(
                analysis.cues, moment.start, moment.end, lead_in
            )
            examples = " | ".join(
                f"({c.likes} likes) {c.text}" for c in moment.examples
            )
            rows.append(
                [
                    video.title,
                    video.url,
                    analysis.source_label,
                    str(index),
                    format_time(moment.start),
                    format_time(moment.end),
                    str(round(moment.duration)),
                    str(numeric_score(moment)),
                    str(moment.mentions) if moment.mentions else "",
                    str(moment.likes) if moment.mentions else "",
                    video.moment_url(moment.start),
                    format_time(from_time) if text else "",
                    text,
                    examples,
                ]
            )
    return rows


def export_csv(
    analyses: Sequence[VideoAnalysis],
    path: Path,
    lead_in: float,
    delimiter: str = ";",
) -> int:
    """Write results as CSV that opens correctly in Excel.

    The file is UTF-8 with BOM so Excel shows non-ASCII characters correctly.

    Args:
        analyses: Analyzed videos.
        path: Destination file.
        lead_in: Seconds of transcript before each moment.
        delimiter: Column separator (``;`` works in most European Excel locales).

    Returns:
        Number of moment rows written.
    """
    rows = build_rows(analyses, lead_in)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(rows)
    return len(rows)


def export_txt(
    analyses: Sequence[VideoAnalysis],
    path: Path,
    lead_in: float,
    now: datetime | None = None,
) -> int:
    """Write results as a readable text report.

    Args:
        analyses: Analyzed videos.
        path: Destination file.
        lead_in: Seconds of transcript before each moment.
        now: Export time shown in the header (defaults to now).

    Returns:
        Number of moments written.
    """
    now = now or datetime.now()
    lines = [
        "Clipper - analysis results",
        f"Exported: {now:%Y-%m-%d %H:%M}",
        f"Transcript starts {lead_in:g} s before each moment.",
        "",
    ]
    count = 0
    for analysis in analyses:
        lines.extend(_video_block(analysis, lead_in))
        count += len(analysis.moments)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return count


def export_results(
    analyses: Sequence[VideoAnalysis],
    path: Path,
    lead_in: float,
    delimiter: str = ";",
) -> int:
    """Export to CSV or TXT depending on the file extension.

    Args:
        analyses: Analyzed videos.
        path: Destination file (``.csv`` or anything else for text).
        lead_in: Seconds of transcript before each moment.
        delimiter: CSV column separator.

    Returns:
        Number of moments written.
    """
    if Path(path).suffix.lower() == ".csv":
        return export_csv(analyses, path, lead_in, delimiter)
    return export_txt(analyses, path, lead_in)


def _video_block(analysis: VideoAnalysis, lead_in: float) -> list[str]:
    video = analysis.video
    date = format_date(video.upload_date, video.timestamp, video.date_is_approximate)
    info = (
        f"Duration: {format_time(video.duration)} | "
        f"Views: {format_count(video.view_count)} | "
        f"Date: {date}"
    )
    lines = [
        "=" * 78,
        f"Video: {video.title}",
        f"Link: {video.url}",
        info,
        f"Moment source: {analysis.source_label}",
    ]
    track = analysis.subtitle_track
    if track is not None:
        lines.append(f"Subtitles: {track.language} ({track.kind_label})")
    else:
        lines.append("Subtitles: not available")
    lines.extend(f"Note: {note}" for note in analysis.notes)
    lines.append("")
    if not analysis.moments:
        lines.extend(["No moments found.", ""])
    for index, moment in enumerate(analysis.moments, start=1):
        lines.extend(_moment_block(analysis, moment, index, lead_in))
    return lines


def _moment_block(
    analysis: VideoAnalysis, moment: Moment, index: int, lead_in: float
) -> list[str]:
    indent = "    "
    lines = [
        f"#{index}  {format_time(moment.start)} - {format_time(moment.end)}  "
        f"({moment.duration:.0f} s)  Score: {moment.score_label()}",
        f"{indent}Link: {analysis.video.moment_url(moment.start)}",
    ]
    if moment.mentions:
        lines.append(
            f"{indent}Mentions: {moment.mentions}, "
            f"likes: {format_count(moment.likes)}"
        )
    from_time, text = moment_transcript(
        analysis.cues, moment.start, moment.end, lead_in
    )
    if text:
        lines.append(f"{indent}Transcript (from {format_time(from_time)}):")
        lines.extend(
            textwrap.wrap(
                text,
                _WRAP_WIDTH,
                initial_indent=indent * 2,
                subsequent_indent=indent * 2,
            )
        )
    if moment.examples:
        lines.append(f"{indent}Example comments:")
        for example in moment.examples:
            lines.append(
                f"{indent * 2}- ({format_count(example.likes)} likes) {example.text}"
            )
    lines.append("")
    return lines
