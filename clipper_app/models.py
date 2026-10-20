"""Data classes shared by the analysis, YouTube and GUI modules."""

from __future__ import annotations

from dataclasses import dataclass, field

SOURCE_HEATMAP = "heatmap"
SOURCE_COMMENTS = "comments"
SOURCE_NONE = "none"

SOURCE_LABELS = {
    SOURCE_HEATMAP: '"Most replayed" heatmap',
    SOURCE_COMMENTS: "comment timestamps",
    SOURCE_NONE: "no data",
}


@dataclass(frozen=True)
class HeatSegment:
    """One bar of the YouTube "Most replayed" heatmap.

    Attributes:
        start: Segment start in seconds.
        end: Segment end in seconds.
        value: Normalized replay intensity between 0 and 1.
    """

    start: float
    end: float
    value: float


@dataclass(frozen=True)
class CommentExample:
    """A comment shown as an example for a moment.

    Attributes:
        likes: Number of likes of the comment.
        text: Comment text (single line, possibly shortened).
    """

    likes: int
    text: str


@dataclass
class Moment:
    """A candidate viral moment found in a video.

    Attributes:
        start: Moment start in seconds.
        end: Moment end in seconds.
        score: Heatmap peak (0-1) or likes-weighted comment score.
        source: ``SOURCE_HEATMAP`` or ``SOURCE_COMMENTS``.
        avg_score: Average heatmap value of the merged segments.
        segment_count: Number of merged heatmap segments.
        peak_time: Time of the strongest point inside the moment.
        mentions: Number of comments mentioning this moment.
        likes: Total likes of those comments.
        examples: Example comments, most liked first.
    """

    start: float
    end: float
    score: float
    source: str = SOURCE_HEATMAP
    avg_score: float | None = None
    segment_count: int = 1
    peak_time: float | None = None
    mentions: int = 0
    likes: int = 0
    examples: list[CommentExample] = field(default_factory=list)

    @property
    def duration(self) -> float:
        """Length of the moment in seconds."""
        return max(0.0, self.end - self.start)

    def score_label(self) -> str:
        """Return the score as shown to the user.

        Returns:
            ``"87/100"`` for heatmap moments, the weighted count otherwise.
        """
        if self.source == SOURCE_HEATMAP:
            return f"{self.score * 100:.0f}/100"
        return f"{self.score:,.0f}"


@dataclass(frozen=True)
class Cue:
    """One subtitle line.

    Attributes:
        start: Start time in seconds.
        end: End time in seconds.
        text: Subtitle text.
    """

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SubtitleTrack:
    """A subtitle track selected for download.

    Attributes:
        url: Download URL (json3 format).
        language: Language code as reported by yt-dlp (e.g. ``en-orig``).
        automatic: ``True`` for YouTube's automatic captions.
        impersonate: The ``impersonate`` hint from yt-dlp, if any.
    """

    url: str
    language: str
    automatic: bool
    impersonate: object = None

    @property
    def kind_label(self) -> str:
        """User-facing label for the subtitle kind."""
        return "automatic" if self.automatic else "manual"


@dataclass
class VideoEntry:
    """Basic information about a video (from a channel list or metadata).

    Attributes:
        video_id: YouTube video id.
        url: Watch URL.
        title: Video title.
        duration: Length in seconds, if known.
        view_count: Number of views, if known.
        upload_date: Upload date in ``YYYYMMDD`` format, if known.
        timestamp: Unix timestamp, used when ``upload_date`` is missing.
        date_is_approximate: Date comes from text like "2 weeks ago".
    """

    video_id: str
    url: str
    title: str
    duration: float | None = None
    view_count: int | None = None
    upload_date: str | None = None
    timestamp: float | None = None
    date_is_approximate: bool = False

    def moment_url(self, seconds: float) -> str:
        """Return a link that opens the video at the given time.

        Args:
            seconds: Time in seconds.

        Returns:
            YouTube URL with a ``t`` parameter.
        """
        return (
            f"https://www.youtube.com/watch?v={self.video_id}"
            f"&t={max(0, int(seconds))}s"
        )


@dataclass
class VideoAnalysis:
    """Result of analyzing one video.

    Attributes:
        video: The analyzed video.
        source: Where the moments came from (``SOURCE_*``).
        moments: Moments sorted by time.
        heatmap: Full heatmap (empty if the video has none).
        cues: English subtitle lines (empty if unavailable).
        subtitle_track: The downloaded subtitle track, if any.
        skip_intro: Seconds of intro that were skipped in the heatmap.
        notes: Extra messages for the user.
    """

    video: VideoEntry
    source: str
    moments: list[Moment] = field(default_factory=list)
    heatmap: list[HeatSegment] = field(default_factory=list)
    cues: list[Cue] = field(default_factory=list)
    subtitle_track: SubtitleTrack | None = None
    skip_intro: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def source_label(self) -> str:
        """User-facing description of the data source."""
        return SOURCE_LABELS.get(self.source, self.source)
