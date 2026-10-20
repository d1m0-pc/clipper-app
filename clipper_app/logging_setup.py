"""Writing full error details to ``logs/clipper.log``."""

from __future__ import annotations

import logging
import platform
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__
from .config import LOG_FILE

_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"


def setup_logging(log_file: Path = LOG_FILE) -> Path:
    """Send all log records (with tracebacks) to a rotating log file.

    Uncaught exceptions from the main thread and worker threads are logged
    too, so the user never needs to see a raw traceback.

    Args:
        log_file: Where to write the log.

    Returns:
        The log file path.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(_FORMAT))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for old in list(root.handlers):
        if isinstance(old, RotatingFileHandler):
            root.removeHandler(old)
    root.addHandler(handler)

    def log_uncaught(exc_type, exc_value, exc_traceback) -> None:  # noqa: ANN001
        logging.getLogger("clipper").critical(
            "Uncaught error", exc_info=(exc_type, exc_value, exc_traceback)
        )

    def log_thread_exception(args: threading.ExceptHookArgs) -> None:
        logging.getLogger("clipper").critical(
            "Uncaught error in thread %s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = log_uncaught
    threading.excepthook = log_thread_exception
    logging.getLogger("clipper").info(
        "Clipper %s started (Python %s, %s)",
        __version__,
        platform.python_version(),
        platform.platform(),
    )
    return log_file
