"""The "Analysis" tab: link input, video list, results and clip cutting."""

from __future__ import annotations

import tkinter as tk
import webbrowser
from collections.abc import Callable, Sequence
from tkinter import ttk
from typing import Protocol

from ..environment import FFMPEG_INSTALL_COMMAND
from ..formatting import format_time, parse_time
from ..models import VideoAnalysis, VideoEntry
from .presenters import (
    analysis_status,
    clip_range,
    moment_details,
    moment_values,
    results_header,
    video_values,
)
from .widgets import HeatmapChart, set_text, tree_with_scrollbar

VIDEO_COLUMNS = (
    ("title", "Title", 420, "w"),
    ("date", "Date", 100, "center"),
    ("views", "Views", 100, "e"),
    ("duration", "Duration", 80, "center"),
    ("status", "Status", 190, "w"),
)
MOMENT_COLUMNS = (
    ("index", "#", 40, "center"),
    ("start", "Start", 75, "center"),
    ("end", "End", 75, "center"),
    ("length", "Length", 70, "center"),
    ("score", "Score", 75, "center"),
    ("info", "Details", 170, "w"),
)

NOT_ANALYZED = "Not analyzed"


class AnalysisController(Protocol):
    """Actions the tab asks the application to perform."""

    def load_link(self, text: str) -> None:
        """Load a video or channel link."""

    def analyze_videos(self, video_ids: Sequence[str]) -> None:
        """Analyze the given videos."""

    def video_selected(self, video_id: str) -> None:
        """A video row was selected."""

    def cut_clip(self, start_text: str, end_text: str, vertical: bool) -> None:
        """Cut a clip of the current video."""

    def export_results(self, kind: str) -> None:
        """Export results (``"txt"`` or ``"csv"``)."""

    def open_clips_folder(self) -> None:
        """Open the clips folder."""


class AnalysisTab(ttk.Frame):
    """Main working tab."""

    def __init__(
        self,
        parent: tk.Misc,
        controller: AnalysisController,
        get_lead_in: Callable[[], float],
    ) -> None:
        """Build the tab.

        Args:
            parent: Parent widget (the notebook).
            controller: Receives user actions.
            get_lead_in: Returns the current lead-in setting in seconds.
        """
        super().__init__(parent, padding=8)
        self._controller = controller
        self._get_lead_in = get_lead_in
        self._analysis: VideoAnalysis | None = None
        self._current_video: VideoEntry | None = None
        self._busy = False
        self._ffmpeg_ok = False
        self._statuses: dict[str, str] = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self._build_link_bar()
        self._build_ffmpeg_banner()
        panes = ttk.PanedWindow(self, orient="vertical")
        panes.grid(row=3, column=0, sticky="nsew", pady=(6, 0))
        panes.add(self._build_video_list(panes), weight=1)
        panes.add(self._build_results(panes), weight=3)
        self._update_buttons()

    # ----------------------------------------------------------------- layout
    def _build_link_bar(self) -> None:
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        ttk.Label(bar, text="YouTube link (video or channel):").grid(
            row=0, column=0, padx=(0, 6)
        )
        self.link_var = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.link_var)
        entry.grid(row=0, column=1, sticky="ew")
        entry.bind("<Return>", lambda _: self._load())
        entry.focus_set()
        self._load_button = ttk.Button(
            bar, text="Load", style="Accent.TButton", command=self._load
        )
        self._load_button.grid(row=0, column=2, padx=(6, 0))
        ttk.Button(bar, text="Paste", command=self._paste).grid(
            row=0, column=3, padx=(6, 0)
        )
        ttk.Label(
            self,
            text=(
                "Example: https://www.youtube.com/watch?v=...  or a channel "
                "https://youtube.com/@waveform  (for a channel the newest "
                "videos are shown; change the count in Settings)"
            ),
            style="Hint.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

    def _build_ffmpeg_banner(self) -> None:
        self._ffmpeg_banner = tk.Label(
            self,
            text=(
                "ffmpeg is not installed, so clip cutting is disabled. "
                f"Install it with  {FFMPEG_INSTALL_COMMAND}  "
                '("Tools & help" tab), then click "Recheck".'
            ),
            background="#fef3c7",
            foreground="#92400e",
            anchor="w",
            justify="left",
            padx=8,
            pady=4,
        )

    def _build_video_list(self, parent: tk.Misc) -> ttk.Frame:
        frame = ttk.LabelFrame(parent, text="Videos", padding=6)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        self._list_header = ttk.Label(
            frame,
            text='Enter a link and click "Load". For a channel, select one or '
            'more videos (Ctrl/Shift + click), then click "Analyze selected".',
            style="Hint.TLabel",
        )
        self._list_header.grid(row=0, column=0, sticky="w")
        tree_frame, self.video_tree = tree_with_scrollbar(frame, VIDEO_COLUMNS, 5)
        tree_frame.grid(row=1, column=0, sticky="nsew", pady=4)
        self.video_tree.configure(selectmode="extended")
        self.video_tree.bind("<<TreeviewSelect>>", self._on_video_select)
        self.video_tree.bind("<Double-1>", self._on_video_double_click)

        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, sticky="w")
        self._analyze_button = ttk.Button(
            buttons,
            text="Analyze selected",
            style="Accent.TButton",
            command=self._analyze_selected,
        )
        self._analyze_button.pack(side="left")
        ttk.Button(buttons, text="Select all", command=self._select_all).pack(
            side="left", padx=(6, 0)
        )
        return frame

    def _build_results(self, parent: tk.Misc) -> ttk.Frame:
        frame = ttk.LabelFrame(parent, text="Results", padding=6)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(3, weight=1)
        self._title_label = ttk.Label(frame, text="", style="Title.TLabel")
        self._title_label.grid(row=0, column=0, sticky="w")
        self._source_label = ttk.Label(frame, text="", style="Hint.TLabel")
        self._source_label.grid(row=1, column=0, sticky="w")
        self.chart = HeatmapChart(frame, self._on_chart_select, height=125)
        self.chart.grid(row=2, column=0, sticky="ew", pady=(4, 6))

        split = ttk.PanedWindow(frame, orient="horizontal")
        split.grid(row=3, column=0, sticky="nsew")
        moments_frame, self.moment_tree = tree_with_scrollbar(split, MOMENT_COLUMNS, 7)
        self.moment_tree.configure(selectmode="browse")
        self.moment_tree.bind("<<TreeviewSelect>>", self._on_moment_select)
        split.add(moments_frame, weight=2)

        details_frame = ttk.Frame(split)
        details_frame.rowconfigure(0, weight=1)
        details_frame.columnconfigure(0, weight=1)
        self.details = tk.Text(
            details_frame,
            wrap="word",
            height=8,
            state="disabled",
            relief="flat",
            borderwidth=1,
            padx=8,
            pady=6,
            font=("Segoe UI", 10),
        )
        details_scroll = ttk.Scrollbar(
            details_frame, orient="vertical", command=self.details.yview
        )
        self.details.configure(yscrollcommand=details_scroll.set)
        self.details.grid(row=0, column=0, sticky="nsew")
        details_scroll.grid(row=0, column=1, sticky="ns")
        split.add(details_frame, weight=3)

        self._build_clip_bar(frame).grid(row=4, column=0, sticky="ew", pady=(6, 0))
        self.clear_results("The best moments of the selected video will appear here.")
        return frame

    def _build_clip_bar(self, parent: tk.Misc) -> ttk.Frame:
        bar = ttk.LabelFrame(parent, text="Cut a clip", padding=6)
        ttk.Label(bar, text="Start:").grid(row=0, column=0)
        self.start_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self.start_var, width=9).grid(
            row=0, column=1, padx=(4, 10)
        )
        ttk.Label(bar, text="End:").grid(row=0, column=2)
        self.end_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self.end_var, width=9).grid(
            row=0, column=3, padx=(4, 10)
        )
        self.vertical_var = tk.BooleanVar(value=False)
        ttk.Radiobutton(
            bar, text="Original 16:9", variable=self.vertical_var, value=False
        ).grid(row=0, column=4)
        ttk.Radiobutton(
            bar,
            text="Vertical 9:16 (Shorts/TikTok/Reels)",
            variable=self.vertical_var,
            value=True,
        ).grid(row=0, column=5, padx=(8, 10))
        self._cut_button = ttk.Button(
            bar, text="Cut", style="Accent.TButton", command=self._cut
        )
        self._cut_button.grid(row=0, column=6)
        self._preview_button = ttk.Button(
            bar, text="Preview on YouTube", command=self._preview
        )
        self._preview_button.grid(row=0, column=7, padx=(6, 0))

        ttk.Label(
            bar,
            text="Enter times as m:ss or h:mm:ss (e.g. 12:34). The clip is "
            "saved in the clips folder.",
            style="Hint.TLabel",
        ).grid(row=1, column=0, columnspan=8, sticky="w", pady=(4, 0))

        extra = ttk.Frame(bar)
        extra.grid(row=0, column=8, rowspan=2, sticky="e", padx=(12, 0))
        bar.columnconfigure(8, weight=1)
        ttk.Button(
            extra,
            text="Open clips folder",
            command=self._controller.open_clips_folder,
        ).pack(side="left")
        ttk.Button(
            extra,
            text="Export TXT",
            command=lambda: self._controller.export_results("txt"),
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            extra,
            text="Export CSV",
            command=lambda: self._controller.export_results("csv"),
        ).pack(side="left", padx=(6, 0))
        return bar

    # ------------------------------------------------------------ public API
    def set_videos(self, videos: Sequence[VideoEntry], header: str) -> None:
        """Replace the video list.

        Args:
            videos: Videos to show.
            header: Text above the list (e.g. channel name).
        """
        self.video_tree.delete(*self.video_tree.get_children())
        self._statuses.clear()
        for video in videos:
            self._statuses[video.video_id] = NOT_ANALYZED
            self.video_tree.insert(
                "",
                "end",
                iid=video.video_id,
                values=video_values(video, NOT_ANALYZED),
            )
        self._list_header.configure(text=header)
        self._update_buttons()

    def update_video(self, video: VideoEntry, status: str | None = None) -> None:
        """Update (or add) one row of the video list.

        Args:
            video: Video data.
            status: New status text; keeps the old one when ``None``.
        """
        if status is not None:
            self._statuses[video.video_id] = status
        current = self._statuses.get(video.video_id, NOT_ANALYZED)
        values = video_values(video, current)
        if self.video_tree.exists(video.video_id):
            self.video_tree.item(video.video_id, values=values)
        else:
            self.video_tree.insert("", "end", iid=video.video_id, values=values)

    def set_video_status(self, video_id: str, status: str) -> None:
        """Change only the status column of a video.

        Args:
            video_id: The video.
            status: New status text.
        """
        self._statuses[video_id] = status
        if self.video_tree.exists(video_id):
            self.video_tree.set(video_id, "status", status)

    def select_video(self, video_id: str) -> None:
        """Select a row in the video list without triggering analysis.

        Args:
            video_id: The video to select.
        """
        if self.video_tree.exists(video_id):
            self.video_tree.selection_set(video_id)
            self.video_tree.see(video_id)

    def show_analysis(self, analysis: VideoAnalysis) -> None:
        """Show the results of one video.

        Args:
            analysis: The analysis to display.
        """
        self._analysis = analysis
        self._current_video = analysis.video
        self.update_video(analysis.video, analysis_status(analysis))
        self._title_label.configure(text=analysis.video.title)
        self._source_label.configure(text=results_header(analysis))
        if analysis.heatmap:
            message = ""
        elif analysis.moments:
            message = (
                'This video has no "Most replayed" data - moments come from '
                "comments (height = mentions and likes)."
            )
        else:
            message = (
                'This video has no "Most replayed" data, and comments are '
                "disabled or contain no timestamps. Enter a start and end "
                'below and click "Cut".'
            )
        self.chart.show(
            analysis.heatmap,
            analysis.moments,
            analysis.video.duration,
            analysis.skip_intro,
            message,
        )
        self.moment_tree.delete(*self.moment_tree.get_children())
        for index, moment in enumerate(analysis.moments):
            self.moment_tree.insert(
                "", "end", iid=str(index), values=moment_values(index, moment)
            )
        if analysis.moments:
            self.moment_tree.selection_set("0")
            self.moment_tree.see("0")
        else:
            notes = "\n".join(analysis.notes) or "No moments found."
            set_text(self.details, notes)
            self.start_var.set("")
            self.end_var.set("")
        self._update_buttons()

    def show_video_without_results(self, video: VideoEntry) -> None:
        """Show a video that was not analyzed yet (cutting still works).

        Args:
            video: The selected video.
        """
        self._analysis = None
        self._current_video = video
        self._title_label.configure(text=video.title)
        self._source_label.configure(
            text='The video has not been analyzed yet. Click "Analyze selected" '
            "or double-click the video."
        )
        self.chart.clear("The video has not been analyzed yet.")
        self.moment_tree.delete(*self.moment_tree.get_children())
        set_text(
            self.details,
            "You can cut any part of this video right away: enter a start and "
            'end below and click "Cut".',
        )
        self._update_buttons()

    def clear_results(self, message: str) -> None:
        """Clear the results area.

        Args:
            message: Text shown in the chart.
        """
        self._analysis = None
        self._current_video = None
        self._title_label.configure(text="")
        self._source_label.configure(text="")
        self.chart.clear(message)
        self.moment_tree.delete(*self.moment_tree.get_children())
        set_text(self.details, "")

    def refresh_details(self) -> None:
        """Redraw the selected moment (e.g. after the lead-in changed)."""
        selection = self.moment_tree.selection()
        if self._analysis is not None and selection:
            self._select_moment(int(selection[0]))

    def set_busy(self, busy: bool) -> None:
        """Enable/disable buttons while a background task runs.

        Args:
            busy: ``True`` while a task is running.
        """
        self._busy = busy
        self._update_buttons()

    def set_ffmpeg_available(self, available: bool) -> None:
        """Show or hide the ffmpeg warning and enable/disable "Cut".

        Args:
            available: Whether ffmpeg was found.
        """
        self._ffmpeg_ok = available
        if available:
            self._ffmpeg_banner.grid_remove()
        else:
            self._ffmpeg_banner.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self._update_buttons()

    @property
    def cut_enabled(self) -> bool:
        """Whether the "Cut" button is currently enabled."""
        return "disabled" not in self._cut_button.state()

    # -------------------------------------------------------------- handlers
    def _update_buttons(self) -> None:
        idle = ["!disabled"] if not self._busy else ["disabled"]
        self._load_button.state(idle)
        has_videos = bool(self.video_tree.get_children())
        self._analyze_button.state(
            ["!disabled"] if has_videos and not self._busy else ["disabled"]
        )
        can_cut = self._ffmpeg_ok and not self._busy
        self._cut_button.state(["!disabled"] if can_cut else ["disabled"])

    def _load(self) -> None:
        if not self._busy:
            self._controller.load_link(self.link_var.get())

    def _paste(self) -> None:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return
        self.link_var.set(text.strip())

    def _select_all(self) -> None:
        self.video_tree.selection_set(self.video_tree.get_children())

    def _analyze_selected(self) -> None:
        selected = list(self.video_tree.selection())
        if not selected:
            children = self.video_tree.get_children()
            if len(children) == 1:
                selected = list(children)
        self._controller.analyze_videos(selected)

    def _on_video_select(self, _: tk.Event) -> None:
        selection = self.video_tree.selection()
        if len(selection) == 1:
            self._controller.video_selected(selection[0])

    def _on_video_double_click(self, event: tk.Event) -> None:
        row = self.video_tree.identify_row(event.y)
        if row and not self._busy:
            self._controller.analyze_videos([row])

    def _on_chart_select(self, index: int) -> None:
        if self.moment_tree.exists(str(index)):
            self.moment_tree.selection_set(str(index))
            self.moment_tree.see(str(index))

    def _on_moment_select(self, _: tk.Event) -> None:
        selection = self.moment_tree.selection()
        if selection:
            self._select_moment(int(selection[0]))

    def _select_moment(self, index: int) -> None:
        analysis = self._analysis
        if analysis is None or index >= len(analysis.moments):
            return
        lead_in = self._get_lead_in()
        self.chart.select(index)
        set_text(self.details, moment_details(analysis, index, lead_in))
        start, end = clip_range(
            analysis.moments[index], lead_in, analysis.video.duration
        )
        self.start_var.set(format_time(start))
        self.end_var.set(format_time(end))

    def _cut(self) -> None:
        self._controller.cut_clip(
            self.start_var.get(), self.end_var.get(), self.vertical_var.get()
        )

    def _preview(self) -> None:
        """Open the current video in the browser at the "Start" time."""
        video = self._current_video
        if video is None:
            return
        try:
            seconds = parse_time(self.start_var.get())
        except ValueError:
            seconds = 0.0
        webbrowser.open(video.moment_url(seconds))
