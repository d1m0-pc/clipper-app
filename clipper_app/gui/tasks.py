"""Running work in a background thread so the window never freezes.

Worker threads never touch tkinter. They put messages into a queue, and the
main thread reads the queue every 100 ms.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from typing import Any

from ..errors import TaskCancelled, friendly_error
from ..reporting import LEVEL_INFO, log_to_file

logger = logging.getLogger(__name__)

_POLL_MS = 100
_MAX_MESSAGES_PER_POLL = 300


class WorkerReporter:
    """Reporter used inside a worker thread (thread-safe)."""

    def __init__(self, post: Callable[[tuple], None], cancel_event: threading.Event):
        """Create a reporter.

        Args:
            post: Puts a message into the GUI queue.
            cancel_event: Set when the user presses "Cancel".
        """
        self._post = post
        self._cancel = cancel_event

    def log(self, message: str, level: str = LEVEL_INFO) -> None:
        """Show a message in the log panel (and write it to the log file)."""
        log_to_file(message, level)
        self._post(("log", message, level))

    def status(self, message: str, progress: float | None = None) -> None:
        """Update the status line and progress bar."""
        self._post(("status", message, progress))

    def cancelled(self) -> bool:
        """Return ``True`` once the user asked to cancel."""
        return self._cancel.is_set()

    def wait(self, seconds: float, reason: str = "") -> bool:
        """Sleep with a visible countdown.

        Args:
            seconds: How long to wait.
            reason: Text shown before the countdown.

        Returns:
            ``True`` if the user cancelled while waiting.
        """
        remaining = int(math.ceil(seconds))
        while remaining > 0:
            self.status(f"{reason} Resuming in {remaining} s...".strip(), None)
            if self._cancel.wait(1.0):
                return True
            remaining -= 1
        return self._cancel.is_set()

    def call_in_gui(self, func: Callable[..., Any], *args: Any) -> None:
        """Run ``func(*args)`` on the main (GUI) thread.

        Args:
            func: Function that updates the GUI.
            *args: Arguments for ``func``.
        """
        self._post(("call", func, args))


class TaskRunner:
    """Runs one background task at a time and delivers results to the GUI."""

    def __init__(
        self,
        root: tk.Misc,
        on_log: Callable[[str, str], None],
        on_status: Callable[[str, float | None], None],
        on_busy: Callable[[bool], None],
    ) -> None:
        """Create the runner and start polling the message queue.

        Args:
            root: Any tkinter widget (used for ``after``).
            on_log: Shows a log message ``(message, level)``.
            on_status: Shows status text and progress.
            on_busy: Called with ``True`` when a task starts, ``False`` at end.
        """
        self._root = root
        self._on_log = on_log
        self._on_status = on_status
        self._on_busy = on_busy
        self._queue: queue.Queue[tuple] = queue.Queue()
        self._cancel = threading.Event()
        # Cleared only when the "finished" message reaches the GUI thread, so
        # a new task can never overlap with the end of the previous one.
        self._running = False
        self._root.after(_POLL_MS, self._poll)

    @property
    def busy(self) -> bool:
        """``True`` while a task is running."""
        return self._running

    def run(
        self,
        name: str,
        work: Callable[[WorkerReporter], Any],
        on_success: Callable[[Any], None] | None = None,
        on_error: Callable[[BaseException, str], None] | None = None,
    ) -> bool:
        """Start ``work`` in a background thread.

        Args:
            name: Short description, used for the thread and the log.
            work: The function to run; it receives a :class:`WorkerReporter`.
            on_success: Called on the GUI thread with the result.
            on_error: Called on the GUI thread with ``(error, message)``.

        Returns:
            ``False`` if another task is still running.
        """
        if self.busy:
            self._on_log("Please wait for the current task to finish.", "warning")
            return False
        self._cancel = threading.Event()
        reporter = WorkerReporter(self._queue.put, self._cancel)
        thread = threading.Thread(
            target=self._work,
            args=(name, work, reporter, on_success, on_error),
            name=f"task-{name}",
            daemon=True,
        )
        self._running = True
        self._on_busy(True)
        thread.start()
        return True

    def cancel(self) -> None:
        """Ask the running task to stop as soon as possible."""
        if self.busy and not self._cancel.is_set():
            self._cancel.set()
            self._on_log("Cancelling... (the current step finishes first)", "warning")

    def _work(
        self,
        name: str,
        work: Callable[[WorkerReporter], Any],
        reporter: WorkerReporter,
        on_success: Callable[[Any], None] | None,
        on_error: Callable[[BaseException, str], None] | None,
    ) -> None:
        logger.info("Task started: %s", name)
        try:
            result = work(reporter)
        except BaseException as error:  # noqa: BLE001 - report everything
            if isinstance(error, TaskCancelled) or self._cancel.is_set():
                logger.info("Task cancelled: %s", name)
                self._queue.put(("cancelled", name))
            else:
                logger.exception("Task failed: %s", name)
                self._queue.put(("error", on_error, error, friendly_error(error)))
        else:
            logger.info("Task finished: %s", name)
            self._queue.put(("done", on_success, result))
        finally:
            self._queue.put(("finished",))

    def _poll(self) -> None:
        try:
            for _ in range(_MAX_MESSAGES_PER_POLL):
                try:
                    message = self._queue.get_nowait()
                except queue.Empty:
                    break
                self._dispatch(message)
        finally:
            try:
                self._root.after(_POLL_MS, self._poll)
            except tk.TclError:
                pass  # window was closed

    def _dispatch(self, message: tuple) -> None:
        kind = message[0]
        try:
            if kind == "log":
                self._on_log(message[1], message[2])
            elif kind == "status":
                self._on_status(message[1], message[2])
            elif kind == "call":
                message[1](*message[2])
            elif kind == "done":
                if message[1] is not None:
                    message[1](message[2])
            elif kind == "error":
                _, callback, error, text = message
                self._on_log(text, "error")
                if callback is not None:
                    callback(error, text)
            elif kind == "cancelled":
                self._on_log("The task was cancelled.", "warning")
            elif kind == "finished":
                self._running = False
                self._on_busy(False)
        except Exception:
            logger.exception("Error while handling message %s", kind)
            self._on_log(friendly_error(RuntimeError("gui")), "error")
