"""Retrying requests that YouTube rate-limits (HTTP 429)."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import TypeVar

from .errors import TaskCancelled

T = TypeVar("T")

DEFAULT_BACKOFF: tuple[float, ...] = (30.0, 60.0, 120.0)


def is_rate_limited(error: BaseException) -> bool:
    """Check whether an error is YouTube's "429 Too Many Requests".

    Works with yt-dlp's ``HTTPError`` (``status`` attribute) and with
    ``DownloadError`` / ``ExtractorError`` that only carry the message.

    Args:
        error: The exception to inspect.

    Returns:
        ``True`` if the request should be retried later.
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "status", None) == 429:
            return True
        text = str(current).lower()
        if "too many requests" in text or "http error 429" in text:
            return True
        # yt-dlp's DownloadError keeps the original error in ``exc_info``.
        exc_info = getattr(current, "exc_info", None)
        nested = None
        if isinstance(exc_info, tuple) and len(exc_info) > 1:
            nested = exc_info[1]
        current = nested or current.__cause__ or current.__context__
    return False


def call_with_backoff(
    func: Callable[[], T],
    *,
    delays: Sequence[float] = DEFAULT_BACKOFF,
    should_retry: Callable[[BaseException], bool] = is_rate_limited,
    on_retry: Callable[[int, int, float, BaseException], None] | None = None,
    wait: Callable[[float], bool | None] = time.sleep,
) -> T:
    """Call ``func`` and retry with growing pauses when it is rate-limited.

    Args:
        func: The operation to run.
        delays: Pause before each retry, e.g. 30 s, 60 s, 120 s.
        should_retry: Decides whether an error is worth retrying.
        on_retry: Called before each pause with
            ``(next_attempt, total_attempts, delay, error)``.
        wait: Sleeps for the given seconds; returning ``True`` means the user
            cancelled and stops the retries.

    Returns:
        Whatever ``func`` returns.

    Raises:
        TaskCancelled: If ``wait`` reports a cancellation.
        Exception: The last error if it is not retryable or retries ran out.
    """
    total = len(delays) + 1
    for attempt in range(1, total + 1):
        try:
            return func()
        except TaskCancelled:
            raise
        except Exception as error:
            if attempt >= total or not should_retry(error):
                raise
            delay = delays[attempt - 1]
            if on_retry is not None:
                on_retry(attempt + 1, total, delay, error)
            if wait(delay):
                raise TaskCancelled() from error
    raise AssertionError("unreachable")
