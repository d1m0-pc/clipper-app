"""Reusable widgets: heatmap bar chart, log panel and small helpers."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Sequence
from datetime import datetime
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from ..formatting import format_time
from ..models import HeatSegment, Moment

COLOR_BAR = "#7aa6d8"
COLOR_INTRO = "#cfd5dd"
COLOR_MOMENT = "#f59e0b"
COLOR_SELECTED = "#dc2626"
COLOR_AXIS = "#6b7280"
COLOR_TEXT = "#374151"
COLOR_BACKGROUND = "#ffffff"

LOG_COLORS = {
    "info": "#1f2937",
    "success": "#047857",
    "warning": "#b45309",
    "error": "#b91c1c",
}

_TICK_STEPS = (10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200)


def tree_with_scrollbar(
    parent: tk.Misc, columns: Sequence[tuple[str, str, int, str]], height: int
) -> tuple[ttk.Frame, ttk.Treeview]:
    """Create a Treeview table with a vertical scrollbar.

    Args:
        parent: Parent widget.
        columns: ``(id, heading, width, anchor)`` for each column.
        height: Visible rows.

    Returns:
        Tuple of (frame to place, tree widget).
    """
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(
        frame, columns=[c[0] for c in columns], show="headings", height=height
    )
    for column_id, heading, width, anchor in columns:
        tree.heading(column_id, text=heading, anchor=anchor)
        stretch = column_id == columns[0][0] or anchor == "w"
        tree.column(column_id, width=width, minwidth=40, anchor=anchor, stretch=stretch)
    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.grid(row=0, column=0, sticky="nsew")
    scrollbar.grid(row=0, column=1, sticky="ns")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    return frame, tree


def set_text(widget: tk.Text, text: str) -> None:
    """Replace the content of a read-only Text widget.

    Args:
        widget: The text widget.
        text: New content.
    """
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", text)
    widget.configure(state="disabled")


class LogPanel(ttk.Frame):
    """Read-only, colored log of messages for the user."""

    MAX_LINES = 3000

    def __init__(self, parent: tk.Misc, height: int = 7) -> None:
        """Create the panel.

        Args:
            parent: Parent widget.
            height: Visible lines.
        """
        super().__init__(parent)
        self._text = ScrolledText(
            self,
            height=height,
            wrap="word",
            state="disabled",
            relief="flat",
            borderwidth=1,
            font=("Segoe UI", 9),
        )
        self._text.pack(fill="both", expand=True)
        for level, color in LOG_COLORS.items():
            self._text.tag_configure(level, foreground=color)
        self._text.tag_configure("time", foreground="#9ca3af")

    def append(self, message: str, level: str = "info") -> None:
        """Add a message with the current time.

        Args:
            message: Text to show.
            level: ``info``, ``success``, ``warning`` or ``error``.
        """
        text = self._text
        text.configure(state="normal")
        text.insert("end", f"[{datetime.now():%H:%M:%S}] ", ("time",))
        text.insert("end", f"{message}\n", (level if level in LOG_COLORS else "info",))
        lines = int(text.index("end-1c").split(".")[0])
        if lines > self.MAX_LINES:
            text.delete("1.0", f"{lines - self.MAX_LINES}.0")
        text.configure(state="disabled")
        text.see("end")

    def clear(self) -> None:
        """Remove all messages."""
        set_text(self._text, "")


class HeatmapChart(tk.Canvas):
    """Bar chart of the "Most replayed" heatmap with highlighted moments."""

    def __init__(
        self,
        parent: tk.Misc,
        on_select: Callable[[int], None],
        height: int = 140,
    ) -> None:
        """Create the chart.

        Args:
            parent: Parent widget.
            on_select: Called with the moment index when a moment is clicked.
            height: Height in pixels.
        """
        super().__init__(
            parent,
            height=height,
            background=COLOR_BACKGROUND,
            highlightthickness=1,
            highlightbackground="#d0d7de",
        )
        self._on_select = on_select
        self._segments: list[HeatSegment] = []
        self._moments: list[Moment] = []
        self._duration = 0.0
        self._skip_intro = 0.0
        self._selected: int | None = None
        self._message = 'The "Most replayed" chart will appear here.'
        self._plot = (0.0, 0.0, 1.0, 1.0)  # left, top, right, bottom
        self.bind("<Configure>", lambda _: self._redraw())
        self.bind("<Button-1>", self._on_click)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda _: self.delete("hover"))

    def show(
        self,
        segments: Sequence[HeatSegment],
        moments: Sequence[Moment],
        duration: float | None,
        skip_intro: float,
        message: str = "",
    ) -> None:
        """Display a heatmap and its moments.

        Args:
            segments: Heatmap segments (may be empty).
            moments: Moments to highlight.
            duration: Video length in seconds.
            skip_intro: Intro length that was ignored (drawn in gray).
            message: Text shown when there is no heatmap.
        """
        self._segments = list(segments)
        self._moments = list(moments)
        ends = [s.end for s in self._segments] + [m.end for m in self._moments]
        self._duration = float(duration or max(ends, default=0.0))
        self._skip_intro = skip_intro
        self._selected = None
        self._message = message
        self._redraw()

    def clear(self, message: str) -> None:
        """Remove the chart and show a message instead.

        Args:
            message: Text to show.
        """
        self.show([], [], None, 0.0, message)

    def select(self, index: int | None) -> None:
        """Highlight one moment.

        Args:
            index: Moment index or ``None``.
        """
        self._selected = index
        self._redraw()

    def _x(self, seconds: float) -> float:
        left, _, right, _ = self._plot
        return left + (right - left) * seconds / max(self._duration, 1.0)

    def _time_at(self, x: float) -> float:
        left, _, right, _ = self._plot
        ratio = (x - left) / max(right - left, 1.0)
        return min(max(ratio, 0.0), 1.0) * self._duration

    def _moment_index_at(self, seconds: float) -> int | None:
        for index, moment in enumerate(self._moments):
            if moment.start <= seconds <= moment.end:
                return index
        return None

    def _redraw(self) -> None:
        self.delete("all")
        width = max(self.winfo_width(), 50)
        height = max(self.winfo_height(), 50)
        self._plot = (8.0, 24.0, width - 8.0, height - 22.0)
        left, top, right, bottom = self._plot
        if not self._segments and not self._moments:
            self.create_text(
                width / 2,
                height / 2,
                text=self._message,
                fill=COLOR_TEXT,
                width=width - 40,
                justify="center",
                font=("Segoe UI", 10),
            )
            return

        selected = (
            self._moments[self._selected]
            if self._selected is not None and self._selected < len(self._moments)
            else None
        )
        plot_height = bottom - top
        for seg in self._segments:
            middle = (seg.start + seg.end) / 2
            index = self._moment_index_at(middle)
            if selected is not None and selected.start <= middle <= selected.end:
                color = COLOR_SELECTED
            elif index is not None:
                color = COLOR_MOMENT
            elif seg.start < self._skip_intro:
                color = COLOR_INTRO
            else:
                color = COLOR_BAR
            x0, x1 = self._x(seg.start), self._x(seg.end)
            y0 = bottom - max(seg.value * plot_height, 1.0)
            self.create_rectangle(
                x0, y0, max(x1 - 1, x0 + 1), bottom, fill=color, width=0
            )

        if not self._segments:
            # Comment-based moments: draw one bar per moment, height = score.
            top_score = max((m.score for m in self._moments), default=1.0) or 1.0
            for index, moment in enumerate(self._moments):
                color = COLOR_SELECTED if index == self._selected else COLOR_MOMENT
                x0, x1 = self._x(moment.start), self._x(moment.end)
                y0 = bottom - max(moment.score / top_score * plot_height, 3.0)
                self.create_rectangle(
                    x0, y0, max(x1, x0 + 3), bottom, fill=color, width=0
                )
            self.create_text(
                left,
                6,
                anchor="nw",
                fill=COLOR_TEXT,
                font=("Segoe UI", 9),
                text=self._message
                or 'No "Most replayed" data - showing moments ' "from comments.",
            )
        else:
            self._draw_legend(left)
        self._draw_axis(left, right, bottom)

    def _draw_legend(self, left: float) -> None:
        items = (
            (COLOR_BAR, "Most replayed"),
            (COLOR_MOMENT, "Top moments"),
            (COLOR_SELECTED, "Selected moment"),
            (COLOR_INTRO, "Skipped intro"),
        )
        x = left
        for color, label in items:
            self.create_rectangle(x, 7, x + 10, 17, fill=color, width=0)
            text_id = self.create_text(
                x + 14,
                12,
                anchor="w",
                text=label,
                fill=COLOR_TEXT,
                font=("Segoe UI", 9),
            )
            bbox = self.bbox(text_id)
            x = (bbox[2] if bbox else x + 100) + 14

    def _draw_axis(self, left: float, right: float, bottom: float) -> None:
        self.create_line(left, bottom, right, bottom, fill=COLOR_AXIS)
        max_ticks = max(2, int((right - left) / 70))
        step = next(
            (s for s in _TICK_STEPS if self._duration / s <= max_ticks),
            _TICK_STEPS[-1],
        )
        tick = 0.0
        while tick <= self._duration + 0.01:
            x = self._x(tick)
            # Keep the first/last label inside the canvas.
            anchor = "n"
            if x - left < 15:
                anchor = "nw"
            elif right - x < 15:
                anchor = "ne"
            self.create_line(x, bottom, x, bottom + 4, fill=COLOR_AXIS)
            self.create_text(
                x,
                bottom + 5,
                anchor=anchor,
                text=format_time(tick),
                fill=COLOR_AXIS,
                font=("Segoe UI", 8),
            )
            tick += step

    def _on_click(self, event: tk.Event) -> None:
        if not self._moments:
            return
        seconds = self._time_at(event.x)
        index = self._moment_index_at(seconds)
        if index is None:
            nearest = min(
                range(len(self._moments)),
                key=lambda i: min(
                    abs(self._moments[i].start - seconds),
                    abs(self._moments[i].end - seconds),
                ),
            )
            moment = self._moments[nearest]
            distance = min(abs(moment.start - seconds), abs(moment.end - seconds))
            if distance <= self._duration * 0.03:
                index = nearest
        if index is not None:
            self._on_select(index)

    def _on_motion(self, event: tk.Event) -> None:
        self.delete("hover")
        if not (self._segments or self._moments):
            return
        left, top, right, bottom = self._plot
        if not (left <= event.x <= right and top - 20 <= event.y <= bottom):
            return
        seconds = self._time_at(event.x)
        label = format_time(seconds)
        for seg in self._segments:
            if seg.start <= seconds < seg.end:
                label = f"{label}  -  {seg.value * 100:.0f}/100"
                break
        self.create_line(
            event.x, top, event.x, bottom, fill="#9ca3af", dash=(2, 2), tags="hover"
        )
        self.create_text(
            right,
            6,
            anchor="ne",
            text=label,
            fill=COLOR_TEXT,
            font=("Segoe UI", 9, "bold"),
            tags="hover",
        )
