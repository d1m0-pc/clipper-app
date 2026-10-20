"""Application paths and user settings (stored in ``settings.json``)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent.parent
SETTINGS_FILE = APP_DIR / "settings.json"
LOG_DIR = APP_DIR / "logs"
LOG_FILE = LOG_DIR / "clipper.log"
DEFAULT_OUTPUT_DIR = APP_DIR / "clips"

MAX_COOKIES_FILE_SIZE = 10 * 1024 * 1024

# (minimum, maximum) for every numeric setting.
LIMITS: dict[str, tuple[int, int]] = {
    "channel_video_count": (1, 500),
    "lead_in_seconds": (0, 120),
    "skip_intro_seconds": (0, 600),
    "top_segments": (1, 50),
}


@dataclass
class Settings:
    """User settings.

    Attributes:
        cookies_path: Optional path to a cookies.txt file (Netscape format).
        channel_video_count: How many latest videos to list for a channel.
        lead_in_seconds: Seconds of context before a moment (transcript/clip).
        output_dir: Folder for clips; empty means ``clips`` next to the app.
        skip_intro_seconds: Heatmap segments in the intro are ignored.
        top_segments: How many top heatmap segments to select.
    """

    cookies_path: str = ""
    channel_video_count: int = 20
    lead_in_seconds: int = 15
    output_dir: str = ""
    skip_intro_seconds: int = 60
    top_segments: int = 10

    @property
    def output_path(self) -> Path:
        """Folder where clips are saved."""
        return Path(self.output_dir) if self.output_dir.strip() else DEFAULT_OUTPUT_DIR

    @property
    def cookies_file(self) -> str | None:
        """The cookies.txt path, or ``None`` when not configured."""
        path = self.cookies_path.strip()
        return path or None


def normalized(settings: Settings) -> Settings:
    """Return a copy with every numeric value clamped to its allowed range.

    Args:
        settings: Settings that may contain out-of-range values.

    Returns:
        Corrected settings.
    """
    changes: dict[str, object] = {}
    for name, (low, high) in LIMITS.items():
        value = getattr(settings, name)
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = getattr(Settings(), name)
        changes[name] = min(max(number, low), high)
    for name in ("cookies_path", "output_dir"):
        changes[name] = str(getattr(settings, name) or "").strip()
    return replace(settings, **changes)


def load_settings(path: Path = SETTINGS_FILE) -> Settings:
    """Load settings, falling back to defaults for missing or broken values.

    Args:
        path: Location of ``settings.json``.

    Returns:
        The loaded (and normalized) settings.
    """
    if not path.exists():
        return Settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("Cannot read %s, using defaults.", path)
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    known = {f.name for f in fields(Settings)}
    values = {key: value for key, value in data.items() if key in known}
    try:
        return normalized(Settings(**values))
    except TypeError:
        return Settings()


def save_settings(settings: Settings, path: Path = SETTINGS_FILE) -> None:
    """Write settings to ``settings.json``.

    Args:
        settings: Settings to save.
        path: Destination file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(asdict(normalized(settings)), indent=2, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")


def validate_cookies_file(path: str) -> str | None:
    """Check that a file looks like a cookies.txt export for YouTube.

    Args:
        path: Path chosen by the user.

    Returns:
        ``None`` if the file looks fine, otherwise an error message for the user.
    """
    file = Path(path)
    if not file.is_file():
        return "The cookies.txt file does not exist at the selected path."
    try:
        if file.stat().st_size > MAX_COOKIES_FILE_SIZE:
            return "The file is too large to be a cookies.txt file."
        text = file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "The cookies.txt file cannot be read."
    lines = [line for line in text.splitlines() if line.strip()]
    header_ok = bool(lines) and lines[0].lstrip().startswith(
        ("# Netscape HTTP Cookie File", "# HTTP Cookie File")
    )
    cookie_lines = [
        line
        for line in lines
        if not line.startswith("#") or line.startswith("#HttpOnly_")
    ]
    tab_ok = any(len(line.split("\t")) == 7 for line in cookie_lines)
    if not (header_ok or tab_ok):
        return (
            "The file is not in cookies.txt (Netscape) format. Export it with "
            'the "Get cookies.txt LOCALLY" extension.'
        )
    if "youtube.com" not in text:
        return (
            "The file contains no cookies for youtube.com. Open youtube.com "
            "(signed in) and export cookies.txt again."
        )
    return None
