"""Detecting external tools (ffmpeg, Deno, yt-dlp) and updating yt-dlp."""

from __future__ import annotations

import glob
import importlib.metadata
import logging
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

FFMPEG_INSTALL_COMMAND = "winget install Gyan.FFmpeg"
DENO_INSTALL_COMMAND = "winget install DenoLand.Deno"
YTDLP_UPGRADE_COMMAND = 'pip install -U --pre "yt-dlp[default]"'
# Used by the "Install now" buttons; the extra flags avoid the
# agreement prompts that confuse beginners.
_WINGET_EXTRA = "--accept-source-agreements --accept-package-agreements"

YTDLP_MAX_AGE_DAYS = 30
MIN_DENO_MAJOR = 2

_VERSION_DATE_RE = re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})")
_DENO_VERSION_RE = re.compile(r"deno\s+(\d+)\.(\d+)\.(\d+)", re.IGNORECASE)


@dataclass
class ToolStatus:
    """What is installed on this computer.

    Attributes:
        ffmpeg: Path to ffmpeg, or ``None``.
        ffprobe: Path to ffprobe, or ``None``.
        deno: Path to Deno, or ``None``.
        deno_version: Deno version string, e.g. ``"2.5.4"``.
        ytdlp_version: Installed yt-dlp version, or ``None``.
        ytdlp_ejs_version: Installed yt-dlp-ejs version, or ``None``.
    """

    ffmpeg: str | None = None
    ffprobe: str | None = None
    deno: str | None = None
    deno_version: str | None = None
    ytdlp_version: str | None = None
    ytdlp_ejs_version: str | None = None

    @property
    def ffmpeg_dir(self) -> str | None:
        """Folder containing ffmpeg (what yt-dlp's ``ffmpeg_location`` wants)."""
        return str(Path(self.ffmpeg).parent) if self.ffmpeg else None

    @property
    def deno_too_old(self) -> bool:
        """``True`` if Deno is older than the version yt-dlp needs."""
        match = re.match(r"(\d+)", self.deno_version or "")
        return bool(match) and int(match.group(1)) < MIN_DENO_MAJOR


def no_window_flags() -> int:
    """Return ``creationflags`` that hide console windows on Windows.

    Returns:
        ``CREATE_NO_WINDOW`` on Windows, 0 elsewhere.
    """
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ytdlp_release_date(version: str | None) -> date | None:
    """Extract the release date from a yt-dlp version like ``2026.10.10``.

    Args:
        version: yt-dlp version string (nightly versions have extra parts).

    Returns:
        The release date, or ``None`` if it cannot be parsed.
    """
    match = _VERSION_DATE_RE.match(version or "")
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def ytdlp_age_days(version: str | None, today: date | None = None) -> int | None:
    """How many days old the installed yt-dlp version is.

    Args:
        version: yt-dlp version string.
        today: Reference date (defaults to today).

    Returns:
        Age in days, or ``None`` if the version is unknown.
    """
    released = ytdlp_release_date(version)
    if released is None:
        return None
    return max(0, ((today or date.today()) - released).days)


def package_version(name: str) -> str | None:
    """Return the installed version of a Python package without importing it.

    Args:
        name: Distribution name, e.g. ``"yt-dlp"``.

    Returns:
        The version or ``None`` if the package is not installed.
    """
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def find_tool(name: str) -> str | None:
    """Find an executable even if PATH was changed after the app started.

    ``winget`` updates PATH only for new programs, so besides the current
    PATH this also looks at the PATH stored in the Windows registry and at
    the usual winget / Deno install folders.

    Args:
        name: Executable name without extension, e.g. ``"ffmpeg"``.

    Returns:
        Full path to the executable or ``None``.
    """
    found = shutil.which(name)
    if found:
        return found
    extra = os.pathsep.join(_extra_search_dirs())
    return shutil.which(name, path=extra) if extra else None


def deno_version(deno_path: str) -> str | None:
    """Ask Deno for its version.

    Args:
        deno_path: Path to the Deno executable.

    Returns:
        Version like ``"2.5.4"`` or ``None`` if it could not be determined.
    """
    try:
        result = subprocess.run(
            [deno_path, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=no_window_flags(),
        )
    except (OSError, subprocess.SubprocessError):
        logger.exception("Deno --version failed")
        return None
    match = _DENO_VERSION_RE.search(result.stdout or "")
    return ".".join(match.groups()) if match else None


def prepend_to_path(folder: str | None) -> None:
    """Put a folder at the front of this process's PATH if it is missing.

    Some yt-dlp checks (e.g. "can ffmpeg download a section?") only look at
    PATH and ignore ``ffmpeg_location``, so tools found elsewhere (winget
    folder, PATH changed after the app started) must be added here.

    Args:
        folder: Folder to add; ``None`` does nothing.
    """
    if not folder:
        return
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    known = {os.path.normcase(os.path.normpath(p)) for p in parts}
    if os.path.normcase(os.path.normpath(folder)) not in known:
        os.environ["PATH"] = os.pathsep.join([folder, *parts])
        logger.info("Added to PATH: %s", folder)


def check_tools() -> ToolStatus:
    """Look for ffmpeg, ffprobe, Deno and yt-dlp.

    Folders of the tools that were found are added to this process's PATH
    (see :func:`prepend_to_path`).

    Returns:
        The current tool status.
    """
    status = ToolStatus(
        ffmpeg=find_tool("ffmpeg"),
        ffprobe=find_tool("ffprobe"),
        deno=find_tool("deno"),
        ytdlp_version=package_version("yt-dlp"),
        ytdlp_ejs_version=package_version("yt-dlp-ejs"),
    )
    prepend_to_path(status.ffmpeg_dir)
    if status.deno:
        prepend_to_path(str(Path(status.deno).parent))
        status.deno_version = deno_version(status.deno)
    logger.info("Tools: %s", status)
    return status


def python_executable() -> str:
    """Console Python to run pip with (``python.exe`` instead of ``pythonw``).

    Returns:
        Path to the Python interpreter.
    """
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        console = exe.with_name("python.exe")
        if console.exists():
            return str(console)
    return str(exe)


def upgrade_ytdlp(
    on_line: Callable[[str], None],
    should_stop: Callable[[], bool] = lambda: False,
) -> int:
    """Run ``pip install -U --pre "yt-dlp[default]"`` and stream its output.

    Args:
        on_line: Receives every output line from pip.
        should_stop: Polled between lines; returning ``True`` stops pip.

    Returns:
        pip's exit code (0 means success).
    """
    command = [
        python_executable(),
        "-m",
        "pip",
        "install",
        "-U",
        "--pre",
        "yt-dlp[default]",
    ]
    env = dict(
        os.environ,
        PYTHONIOENCODING="utf-8",
        PIP_DISABLE_PIP_VERSION_CHECK="1",
        PIP_NO_INPUT="1",
    )
    logger.info("Running: %s", command)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=no_window_flags(),
    )
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip()
        if line:
            logger.info("pip: %s", line)
            on_line(line)
        if should_stop():
            process.terminate()
            break
    return process.wait()


def installed_version_in_subprocess(name: str) -> str | None:
    """Read a package version in a fresh Python process (after an upgrade).

    Args:
        name: Distribution name.

    Returns:
        The version, or ``None``.
    """
    code = (
        "import importlib.metadata as m, sys\n"
        "try:\n"
        f"    print(m.version({name!r}))\n"
        "except m.PackageNotFoundError:\n"
        "    sys.exit(1)\n"
    )
    try:
        result = subprocess.run(
            [python_executable(), "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=no_window_flags(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def winget_command_for_button(command: str) -> str:
    """Add flags that skip winget's agreement prompts.

    Args:
        command: A ``winget install <id>`` command.

    Returns:
        The command with the accept flags appended.
    """
    return f"{command} {_WINGET_EXTRA}"


def open_install_console(command: str) -> None:
    """Open a visible Command Prompt window that runs ``command``.

    The window stays open (``cmd /k``) so the user can read the result.

    Args:
        command: The command to run, e.g. a winget install command.

    Raises:
        OSError: If the console cannot be started.
    """
    if os.name != "nt":
        raise OSError("Installing via winget works only on Windows.")
    subprocess.Popen(
        ["cmd.exe", "/k", command],
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )


def open_path(path: Path, select: bool = False) -> None:
    """Open a folder (or show a file) in Windows Explorer.

    Args:
        path: Folder or file to open.
        select: For files, open the containing folder and highlight the file.
    """
    if os.name == "nt":
        if select and path.is_file():
            subprocess.Popen(["explorer", f"/select,{path}"])
        else:
            os.startfile(str(path))  # noqa: S606 - opening a local folder
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    target = path.parent if select and path.is_file() else path
    subprocess.Popen([opener, str(target)])


def list_separator() -> str:
    """CSV column separator that Excel expects on this computer.

    Most European Windows settings use ``;`` because the comma
    is the decimal separator.

    Returns:
        ``","`` or ``";"`` (the default).
    """
    if os.name != "nt":
        return ";"
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Control Panel\International"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "sList")
    except OSError:
        return ";"
    return value if value in (",", ";") else ";"


def _extra_search_dirs() -> list[str]:
    dirs: list[str] = []
    dirs.extend(_registry_path_dirs())
    local = os.environ.get("LOCALAPPDATA", "")
    home = Path.home()
    if local:
        winget = Path(local) / "Microsoft" / "WinGet"
        dirs.append(str(winget / "Links"))
        patterns = [
            winget / "Packages" / "Gyan.FFmpeg*" / "*" / "bin",
            winget / "Packages" / "Gyan.FFmpeg*" / "bin",
            winget / "Packages" / "DenoLand.Deno*",
            winget / "Packages" / "DenoLand.Deno*" / "*",
        ]
        for pattern in patterns:
            dirs.extend(sorted(glob.glob(str(pattern)), reverse=True))
    dirs.append(str(home / ".deno" / "bin"))
    system_drive = os.environ.get("SystemDrive", "C:") + os.sep
    dirs.append(str(Path(system_drive) / "ffmpeg" / "bin"))
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        dirs.append(str(Path(program_files) / "ffmpeg" / "bin"))
    unique: list[str] = []
    for folder in dirs:
        if folder and folder not in unique:
            unique.append(folder)
    return unique


def _registry_path_dirs() -> list[str]:
    if os.name != "nt":
        return []
    import winreg

    keys = (
        (winreg.HKEY_CURRENT_USER, "Environment"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
    )
    dirs: list[str] = []
    for root, sub_key in keys:
        try:
            with winreg.OpenKey(root, sub_key) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        for part in str(value).split(";"):
            if part.strip():
                dirs.append(os.path.expandvars(part.strip()))
    return dirs
