"""GUI helpers, the background task bridge and a window smoke test."""

import threading
import time

import pytest

from clipper_app.gui.presenters import (
    analysis_status,
    clip_range,
    moment_details,
    moment_values,
    video_values,
)
from clipper_app.gui.tasks import WorkerReporter
from clipper_app.models import (
    SOURCE_COMMENTS,
    SOURCE_HEATMAP,
    SOURCE_NONE,
    CommentExample,
    Cue,
    HeatSegment,
    Moment,
    SubtitleTrack,
    VideoAnalysis,
    VideoEntry,
)

VIDEO = VideoEntry(
    "abcdefghijk", "https://www.youtube.com/watch?v=abcdefghijk", "Title", 600, 12345
)


def heat_analysis():
    moment = Moment(120, 150, 0.9, SOURCE_HEATMAP, avg_score=0.8, segment_count=3)
    return VideoAnalysis(
        VIDEO,
        SOURCE_HEATMAP,
        moments=[moment],
        heatmap=[HeatSegment(i * 10, i * 10 + 10, 0.5) for i in range(60)],
        cues=[Cue(108, 118, "context line"), Cue(120, 140, "the moment 😂")],
        subtitle_track=SubtitleTrack("u", "en", False),
        skip_intro=60,
    )


class TestPresenters:
    def test_video_values(self):
        assert video_values(VIDEO, "Not analyzed") == (
            "Title",
            "-",
            "12,345",
            "10:00",
            "Not analyzed",
        )

    def test_status(self):
        assert "heatmap" in analysis_status(heat_analysis())
        assert analysis_status(VideoAnalysis(VIDEO, SOURCE_NONE)) == "No data"

    def test_moment_values(self):
        values = moment_values(0, heat_analysis().moments[0])
        assert values[:5] == ("1", "2:00", "2:30", "30 s", "90/100")

    def test_details_with_transcript_from_lead_in(self):
        text = moment_details(heat_analysis(), 0, lead_in=15)
        assert "Moment #1: 2:00 - 2:30" in text
        assert "Transcript (from 1:45, 15 s before the moment):" in text
        assert "context line the moment" in text
        assert "&t=120s" in text

    def test_details_without_subtitles_and_with_comments(self):
        moment = Moment(
            300,
            360,
            12,
            SOURCE_COMMENTS,
            mentions=2,
            likes=10,
            examples=[CommentExample(9, "5:00 haha")],
        )
        analysis = VideoAnalysis(VIDEO, SOURCE_COMMENTS, moments=[moment])
        text = moment_details(analysis, 0, lead_in=15)
        assert "Transcript not available" in text
        assert "(9 likes) 5:00 haha" in text
        assert "mentions: 2" in text

    def test_clip_range_uses_lead_in(self):
        moment = Moment(120, 150, 0.9)
        assert clip_range(moment, 15, 600) == (105, 150)
        assert clip_range(Moment(5, 20, 0.5), 15, 600) == (0, 20)
        assert clip_range(Moment(590, 640, 0.5), 0, 600) == (590, 600)


class TestWorkerReporter:
    def test_messages_go_to_queue(self):
        posted = []
        reporter = WorkerReporter(posted.append, threading.Event())
        reporter.log("hello", "success")
        reporter.status("working", 0.5)
        assert ("log", "hello", "success") in posted
        assert ("status", "working", 0.5) in posted

    def test_wait_shows_countdown_and_can_be_cancelled(self):
        posted = []
        cancel = threading.Event()
        reporter = WorkerReporter(posted.append, cancel)
        timer = threading.Timer(0.3, cancel.set)
        timer.start()
        started = time.monotonic()
        assert reporter.wait(30, "Waiting because of 429.") is True
        assert time.monotonic() - started < 5
        assert any("Resuming in 30 s" in m[1] for m in posted if m[0] == "status")


@pytest.fixture
def tk_root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("No graphical environment")
    root.withdraw()
    yield root
    root.destroy()


def pump(root, condition, timeout=20.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)
    root.update()
    return condition()


class TestTaskRunner:
    def make_runner(self, root):
        from clipper_app.gui.tasks import TaskRunner

        events = {"logs": [], "status": [], "busy": []}
        runner = TaskRunner(
            root,
            lambda message, level: events["logs"].append((level, message)),
            lambda message, progress: events["status"].append(message),
            events["busy"].append,
        )
        return runner, events

    def test_success(self, tk_root):
        runner, events = self.make_runner(tk_root)
        results = []

        def work(reporter):
            reporter.log("working", "info")
            reporter.status("half", 0.5)
            return 42

        assert runner.run("test", work, results.append)
        assert runner.busy
        assert not runner.run("second", work)  # only one task at a time
        assert pump(tk_root, lambda: not runner.busy)
        assert results == [42]
        assert ("info", "working") in events["logs"]
        assert "half" in events["status"]
        assert events["busy"] == [True, False]

    def test_error_is_translated_not_raw_traceback(self, tk_root):
        runner, events = self.make_runner(tk_root)
        errors = []

        def work(reporter):
            raise RuntimeError("ERROR: [youtube] x: nsig extraction failed")

        runner.run("test", work, on_error=lambda e, message: errors.append(message))
        assert pump(tk_root, lambda: not runner.busy)
        assert errors and "Check/update yt-dlp" in errors[0]
        assert all("Traceback" not in m for _, m in events["logs"])

    def test_cancel(self, tk_root):
        runner, events = self.make_runner(tk_root)

        def work(reporter):
            if reporter.wait(30, "Waiting."):
                from clipper_app.errors import TaskCancelled

                raise TaskCancelled()
            return "not cancelled"

        results = []
        runner.run("test", work, results.append)
        tk_root.after(200, runner.cancel)
        assert pump(tk_root, lambda: not runner.busy, timeout=10)
        assert results == []
        assert any("cancelled" in m for _, m in events["logs"])


def test_video_ids_starting_with_dash_work_in_tables(tk_root):
    from clipper_app.gui.analysis_tab import AnalysisTab

    class Controller:
        def __getattr__(self, name):
            return lambda *args: None

    tab = AnalysisTab(tk_root, Controller(), lambda: 15.0)
    video = VideoEntry("-IoE0Tz2XQc", "u", "Dash video", 100)
    tab.set_videos([video], "x")
    tab.set_video_status("-IoE0Tz2XQc", "Analyzing...")
    tab.update_video(video, "Done")
    tab.select_video("-IoE0Tz2XQc")
    tk_root.update()
    assert tab.video_tree.selection() == ("-IoE0Tz2XQc",)
    assert tab.video_tree.set("-IoE0Tz2XQc", "status") == "Done"


def test_main_window_starts_and_shows_results(tmp_path, tk_root):
    from clipper_app.gui.app import ClipperApp

    app = ClipperApp(
        tk_root, settings_path=tmp_path / "settings.json", startup_dialogs=False
    )
    assert pump(tk_root, lambda: app.tools_checked and not app.runner.busy)
    # The cut button follows the ffmpeg check.
    assert app.analysis_tab.cut_enabled == bool(app.tools.ffmpeg)

    analysis = heat_analysis()
    app._entries = {VIDEO.video_id: VIDEO}
    app.analysis_tab.set_videos([VIDEO], "Test")
    app._on_video_analyzed(analysis)
    tk_root.update()
    assert app.analysis_tab.moment_tree.get_children() == ("0",)
    assert app.analysis_tab.start_var.get() == "1:45"
    assert app.analysis_tab.end_var.get() == "2:30"
    assert "the moment" in app.analysis_tab.details.get("1.0", "end")
    app.analysis_tab.chart.event_generate("<Configure>")
    tk_root.update()
