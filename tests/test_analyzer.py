"""The analysis flow with a fake YouTube service (heatmap, fallback, errors)."""

import pytest
from conftest import FakeReporter, make_heatmap

from clipper_app.analyzer import analyze_video
from clipper_app.config import Settings
from clipper_app.errors import TaskCancelled, UserFacingError
from clipper_app.models import (
    SOURCE_COMMENTS,
    SOURCE_HEATMAP,
    SOURCE_NONE,
    Cue,
    SubtitleTrack,
)


class FakeService:
    """Stands in for YouTubeService; records which requests were made."""

    def __init__(self, info, comments=None, subtitles=None, subtitle_error=None):
        self.info = info
        self.comments = comments or []
        self.subtitles = subtitles
        self.subtitle_error = subtitle_error
        self.calls = []

    def fetch_info(self, url):
        self.calls.append("info")
        return self.info

    def fetch_comments(self, url, limit):
        self.calls.append(("comments", limit))
        if isinstance(self.comments, Exception):
            raise self.comments
        return self.comments

    def fetch_subtitles(self, info, language):
        self.calls.append("subtitles")
        if self.subtitle_error is not None:
            raise self.subtitle_error
        if self.subtitles is None:
            return [], None
        return self.subtitles, SubtitleTrack("u", "en", False)


def video_info(**extra):
    return {"id": "abcdefghijk", "title": "Test", "duration": 300, **extra}


HEATMAP = make_heatmap([1.0] * 6 + [0.1] * 10 + [0.9, 0.95] + [0.1] * 12)
CUES = [Cue(150, 175, "build up"), Cue(160, 180, "punchline")]


def test_heatmap_video(reporter):
    service = FakeService(video_info(heatmap=HEATMAP), subtitles=CUES)
    analysis = analyze_video(service, "url", Settings(top_segments=2), reporter)
    assert analysis.source == SOURCE_HEATMAP
    assert [(m.start, m.end) for m in analysis.moments] == [(160, 180)]
    assert analysis.skip_intro == 60
    assert analysis.cues == CUES
    assert ("comments", 500) not in service.calls  # no fallback needed
    assert any("Most replayed" in m for m in reporter.messages("success"))


def test_missing_heatmap_falls_back_to_comments(reporter):
    comments = [
        {"text": "2:30 omg", "like_count": 50},
        {"text": "2:31 this part", "like_count": 5},
        {"text": "no timestamp", "like_count": 900},
    ]
    service = FakeService(video_info(heatmap=None), comments=comments)
    analysis = analyze_video(service, "url", Settings(), reporter)
    assert ("comments", 500) in service.calls
    assert analysis.source == SOURCE_COMMENTS
    assert analysis.moments[0].start == 150
    assert analysis.moments[0].mentions == 2
    assert any('no "Most replayed"' in m for m in reporter.messages("warning"))
    assert any("no English subtitles" in m for m in reporter.messages("warning"))


def test_no_heatmap_and_no_timestamps(reporter):
    service = FakeService(video_info(), comments=[{"text": "great video"}])
    analysis = analyze_video(service, "url", Settings(), reporter)
    assert analysis.source == SOURCE_NONE
    assert analysis.moments == []
    assert "subtitles" not in service.calls
    assert analysis.notes


def test_comments_turned_off(reporter):
    # yt-dlp returns an empty list, not an error, when comments are disabled.
    service = FakeService(video_info(), comments=[])
    analysis = analyze_video(service, "url", Settings(), reporter)
    assert analysis.source == SOURCE_NONE
    assert analysis.moments == []
    assert "subtitles" not in service.calls
    warning = " ".join(reporter.messages("warning"))
    assert "disabled" in warning and '"Cut"' in warning
    assert not any("Comments downloaded" in m for m in reporter.messages())
    assert any("disabled" in note for note in analysis.notes)


def test_comment_download_failure_does_not_crash(reporter):
    service = FakeService(video_info(), comments=Exception("Comments are turned off"))
    analysis = analyze_video(service, "url", Settings(), reporter)
    assert analysis.source == SOURCE_NONE
    warnings = reporter.messages("warning")
    assert any("Comments were not downloaded" in m for m in warnings)


def test_subtitle_429_after_retries_does_not_crash(reporter):
    service = FakeService(
        video_info(heatmap=HEATMAP),
        subtitle_error=Exception("HTTP Error 429: Too Many Requests"),
    )
    analysis = analyze_video(service, "url", Settings(), reporter)
    assert analysis.moments
    assert analysis.cues == []
    warning = [m for m in reporter.messages("warning") if "Subtitles" in m]
    assert warning and "429" in warning[0]


def test_invalid_subtitle_data_does_not_crash(reporter):
    service = FakeService(
        video_info(heatmap=HEATMAP),
        subtitle_error=ValueError("Prazan odgovor za titlove."),
    )
    analysis = analyze_video(service, "url", Settings(), reporter)
    assert analysis.cues == []
    assert any("Prazan odgovor" in m for m in reporter.messages("warning"))


def test_short_video_does_not_skip_intro(reporter):
    short = make_heatmap([0.2, 0.9, 0.3, 0.1], segment=10)  # 40 s video
    service = FakeService(video_info(duration=40, heatmap=short))
    analysis = analyze_video(service, "url", Settings(), reporter)
    assert analysis.skip_intro == 0
    assert analysis.moments


def test_upcoming_video_is_rejected(reporter):
    service = FakeService(video_info(live_status="is_upcoming"))
    with pytest.raises(UserFacingError):
        analyze_video(service, "url", Settings(), reporter)


def test_cancelled_before_start():
    reporter = FakeReporter()
    reporter.cancel_requested = True
    with pytest.raises(TaskCancelled):
        analyze_video(FakeService(video_info()), "url", Settings(), reporter)
