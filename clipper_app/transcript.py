"""Subtitle track selection and json3 transcript parsing."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Cue, SubtitleTrack


def pick_subtitle_track(info: Mapping, language: str = "en") -> SubtitleTrack | None:
    """Choose the best subtitle track: manual first, then automatic.

    For automatic captions ``en-orig`` (the original speech recognition) is
    preferred over ``en`` (which may be a machine translation).

    Args:
        info: yt-dlp info dict with ``subtitles`` / ``automatic_captions``.
        language: Base language code.

    Returns:
        The selected track with a json3 URL, or ``None`` if there is none.
    """
    groups = (
        (info.get("subtitles") or {}, [language], False),
        (info.get("automatic_captions") or {}, [f"{language}-orig", language], True),
    )
    for container, preferred, automatic in groups:
        if not isinstance(container, Mapping):
            continue
        variants = sorted(
            code
            for code in container
            if _is_variant(code, language) and code not in preferred
        )
        for code in [*preferred, *variants]:
            fmt = _pick_json3_format(container.get(code))
            if fmt is not None:
                return SubtitleTrack(
                    url=fmt["url"],
                    language=code,
                    automatic=automatic,
                    impersonate=fmt.get("impersonate"),
                )
    return None


def parse_json3(data: str | bytes | Mapping) -> list[Cue]:
    """Parse YouTube's json3 subtitle format into cues.

    Args:
        data: Raw json3 text/bytes or an already decoded dict.

    Returns:
        Cues sorted by start time. Empty lines are dropped.

    Raises:
        ValueError: If the data is not valid json3.
    """
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    if isinstance(data, str):
        if not data.strip():
            raise ValueError("Empty subtitle response.")
        try:
            data = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ValueError("Subtitles are not in the expected json3 format.") from exc
    if not isinstance(data, Mapping):
        raise ValueError("Subtitles are not in the expected json3 format.")

    cues: list[Cue] = []
    for event in data.get("events") or []:
        if not isinstance(event, Mapping):
            continue
        segs = event.get("segs")
        if not segs:
            continue
        text = "".join(
            str(seg.get("utf8", "")) for seg in segs if isinstance(seg, Mapping)
        )
        text = " ".join(text.split())
        if not text:
            continue
        try:
            start = float(event.get("tStartMs", 0)) / 1000
            length = float(event.get("dDurationMs", 0) or 0) / 1000
        except (TypeError, ValueError):
            continue
        cues.append(Cue(start, start + max(length, 0.0), text))
    cues.sort(key=lambda cue: cue.start)
    return cues


def transcript_for_range(cues: Sequence[Cue], start: float, end: float) -> str:
    """Join the subtitle text that overlaps a time range.

    Args:
        cues: Parsed subtitle cues.
        start: Range start in seconds (lead-in already applied).
        end: Range end in seconds.

    Returns:
        The transcript text, or an empty string.
    """
    parts: list[str] = []
    for cue in cues:
        overlaps = cue.start < end and (cue.end > start or cue.start >= start)
        if not overlaps:
            continue
        if parts and parts[-1] == cue.text:
            continue
        parts.append(cue.text)
    return " ".join(parts)


def moment_transcript(
    cues: Sequence[Cue], start: float, end: float, lead_in: float
) -> tuple[float, str]:
    """Transcript for a moment, starting ``lead_in`` seconds earlier.

    Args:
        cues: Parsed subtitle cues.
        start: Moment start in seconds.
        end: Moment end in seconds.
        lead_in: Seconds of context before the moment.

    Returns:
        Tuple of (actual transcript start, transcript text).
    """
    from_time = max(0.0, start - max(0.0, lead_in))
    return from_time, transcript_for_range(cues, from_time, end)


def _is_variant(code: str, language: str) -> bool:
    return code == language or code.startswith(f"{language}-")


def _pick_json3_format(formats: Iterable[Mapping] | None) -> Mapping | None:
    candidates = [f for f in formats or [] if isinstance(f, Mapping) and f.get("url")]
    for fmt in candidates:
        if fmt.get("ext") == "json3":
            return fmt
    if candidates:
        # No json3 entry listed: YouTube's timedtext API still serves json3
        # when asked with fmt=json3.
        fmt = dict(candidates[0])
        fmt["url"] = _with_query(fmt["url"], fmt="json3")
        fmt["ext"] = "json3"
        return fmt
    return None


def _with_query(url: str, **params: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(params)
    return urlunsplit(parts._replace(query=urlencode(query)))
