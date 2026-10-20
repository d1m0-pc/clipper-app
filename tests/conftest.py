"""Shared test helpers. No test needs network access."""

from __future__ import annotations

import pytest


class FakeReporter:
    """Collects messages instead of showing them in the GUI."""

    def __init__(self, cancel_after_waits: int | None = None) -> None:
        self.logs: list[tuple[str, str]] = []
        self.statuses: list[tuple[str, float | None]] = []
        self.waits: list[float] = []
        self._cancel_after_waits = cancel_after_waits
        self.cancel_requested = False

    def log(self, message: str, level: str = "info") -> None:
        self.logs.append((level, message))

    def status(self, message: str, progress: float | None = None) -> None:
        self.statuses.append((message, progress))

    def cancelled(self) -> bool:
        return self.cancel_requested

    def wait(self, seconds: float, reason: str = "") -> bool:
        self.waits.append(seconds)
        if (
            self._cancel_after_waits is not None
            and len(self.waits) >= self._cancel_after_waits
        ):
            self.cancel_requested = True
            return True
        return False

    def messages(self, level: str | None = None) -> list[str]:
        return [m for lvl, m in self.logs if level is None or lvl == level]


@pytest.fixture
def reporter() -> FakeReporter:
    return FakeReporter()


def make_heatmap(values: list[float], segment: float = 10.0) -> list[dict]:
    """Build a yt-dlp style heatmap with equally long segments."""
    return [
        {"start_time": i * segment, "end_time": (i + 1) * segment, "value": v}
        for i, v in enumerate(values)
    ]
