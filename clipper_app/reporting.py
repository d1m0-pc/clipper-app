"""The interface background tasks use to talk to the user."""

from __future__ import annotations

import logging
import time
from typing import Protocol

from .errors import TaskCancelled

LEVEL_INFO = "info"
LEVEL_SUCCESS = "success"
LEVEL_WARNING = "warning"
LEVEL_ERROR = "error"

_LOG_LEVELS = {
    LEVEL_INFO: logging.INFO,
    LEVEL_SUCCESS: logging.INFO,
    LEVEL_WARNING: logging.WARNING,
    LEVEL_ERROR: logging.ERROR,
}

logger = logging.getLogger("clipper.user")


class Reporter(Protocol):
    """Progress/log channel from a background task to the GUI."""

    def log(self, message: str, level: str = LEVEL_INFO) -> None:
        """Show a message in the log panel."""

    def status(self, message: str, progress: float | None = None) -> None:
        """Update the status line; ``progress`` is 0-1 or ``None`` (unknown)."""

    def cancelled(self) -> bool:
        """Return ``True`` once the user pressed "Cancel"."""

    def wait(self, seconds: float, reason: str = "") -> bool:
        """Sleep, showing a countdown; return ``True`` if cancelled."""


def check_cancelled(reporter: Reporter) -> None:
    """Raise :class:`TaskCancelled` if the user cancelled the task.

    Args:
        reporter: The task's reporter.

    Raises:
        TaskCancelled: When cancellation was requested.
    """
    if reporter.cancelled():
        raise TaskCancelled()


def log_to_file(message: str, level: str) -> None:
    """Write a user-visible message to the log file as well.

    Args:
        message: The message.
        level: One of the ``LEVEL_*`` constants.
    """
    logger.log(_LOG_LEVELS.get(level, logging.INFO), message)


class ConsoleReporter:
    """Reporter that prints to the console (for scripts and debugging)."""

    def __init__(self) -> None:
        """Create a reporter that is never cancelled."""
        self.messages: list[tuple[str, str]] = []

    def log(self, message: str, level: str = LEVEL_INFO) -> None:
        """Print and remember a message."""
        self.messages.append((level, message))
        print(f"[{level}] {message}")

    def status(self, message: str, progress: float | None = None) -> None:
        """Print a status update."""
        suffix = f" ({progress:.0%})" if progress is not None else ""
        print(f"[status] {message}{suffix}")

    def cancelled(self) -> bool:
        """Console tasks are never cancelled."""
        return False

    def wait(self, seconds: float, reason: str = "") -> bool:
        """Sleep without a countdown."""
        print(f"[wait] {reason} {seconds:.0f} s")
        time.sleep(seconds)
        return False
