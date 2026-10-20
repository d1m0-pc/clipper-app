"""Main window: connects the tabs with the background tasks."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tkinter as tk
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from .. import APP_NAME, __version__
from ..analyzer import analyze_video
from ..clipping import ClipCutter, ClipRequest, validate_range
from ..config import (
    APP_DIR,
    LOG_DIR,
    SETTINGS_FILE,
    Settings,
    load_settings,
    save_settings,
)
from ..environment import (
    DENO_INSTALL_COMMAND,
    FFMPEG_INSTALL_COMMAND,
    YTDLP_MAX_AGE_DAYS,
    YTDLP_UPGRADE_COMMAND,
    ToolStatus,
    check_tools,
    installed_version_in_subprocess,
    list_separator,
    open_install_console,
    open_path,
    upgrade_ytdlp,
    winget_command_for_button,
    ytdlp_age_days,
)
from ..errors import TaskCancelled, UserFacingError, friendly_error
from ..exporter import export_results
from ..formatting import format_time, parse_time
from ..logging_setup import setup_logging
from ..models import VideoAnalysis, VideoEntry
from ..reporting import LEVEL_ERROR, LEVEL_SUCCESS, LEVEL_WARNING, log_to_file
from ..urls import parse_youtube_link
from ..youtube import YouTubeService
from .analysis_tab import AnalysisTab
from .presenters import analysis_status
from .settings_tab import SettingsTab
from .tasks import TaskRunner, WorkerReporter
from .tools_tab import ToolsTab
from .widgets import LogPanel

logger = logging.getLogger(__name__)

# Short pause between videos so YouTube is less likely to answer with 429.
PAUSE_BETWEEN_VIDEOS = 3.0
LONG_CLIP_SECONDS = 600


class ClipperApp:
    """The application window and its actions."""

    def __init__(
        self,
        root: tk.Tk,
        settings_path: Path = SETTINGS_FILE,
        startup_dialogs: bool = True,
    ) -> None:
        """Build the window and start the tool check.

        Args:
            root: The Tk root window.
            settings_path: Where settings are loaded from and saved to.
            startup_dialogs: Show pop-ups about missing tools at startup
                (disabled in automated tests).
        """
        self.root = root
        self._settings_path = settings_path
        self._startup_dialogs = startup_dialogs
        self.settings = load_settings(settings_path)
        self.tools = ToolStatus()
        self.tools_checked = False
        self._entries: dict[str, VideoEntry] = {}
        self._analyses: dict[str, VideoAnalysis] = {}
        self._current_id: str | None = None

        root.title(f"{APP_NAME} {__version__} - viral moments from YouTube")
        _configure_style(root)
        _set_initial_geometry(root)
        root.report_callback_exception = self._on_tk_error
        self._build()
        self.runner = TaskRunner(root, self.log, self.set_status, self._set_busy)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.log('Welcome! Paste a YouTube video or channel link and click "Load".')
        root.after(100, lambda: self._check_tools(startup=True))

    # ----------------------------------------------------------------- layout
    def _build(self) -> None:
        container = ttk.Frame(self.root)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(container)
        self.notebook.grid(row=0, column=0, sticky="nsew", padx=6, pady=(6, 0))
        self.analysis_tab = AnalysisTab(
            self.notebook, self, lambda: float(self.settings.lead_in_seconds)
        )
        self.settings_tab = SettingsTab(
            self.notebook, self.settings, self._save_settings
        )
        self.tools_tab = ToolsTab(self.notebook, self)
        self.notebook.add(self.analysis_tab, text="  Analysis  ")
        self.notebook.add(self.settings_tab, text="  Settings  ")
        self.notebook.add(self.tools_tab, text="  Tools & help  ")

        status = ttk.Frame(container, padding=(6, 4))
        status.grid(row=1, column=0, sticky="ew")
        status.columnconfigure(1, weight=1)
        self.progress = ttk.Progressbar(
            status, length=220, mode="determinate", maximum=100
        )
        self.progress.grid(row=0, column=0)
        self.status_label = ttk.Label(status, text="Ready.")
        self.status_label.grid(row=0, column=1, sticky="ew", padx=8)
        self.cancel_button = ttk.Button(status, text="Cancel", command=self._cancel)
        self.cancel_button.grid(row=0, column=2)
        self.cancel_button.state(["disabled"])

        self.log_panel = LogPanel(container, height=5)
        self.log_panel.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self._progress_running = False

    # ------------------------------------------------------- status and log
    def log(self, message: str, level: str = "info") -> None:
        """Show a message in the log panel.

        Args:
            message: Text for the user.
            level: ``info``, ``success``, ``warning`` or ``error``.
        """
        self.log_panel.append(message, level)

    def _log_and_file(self, message: str, level: str = "info") -> None:
        log_to_file(message, level)
        self.log(message, level)

    def set_status(self, message: str, progress: float | None = None) -> None:
        """Update the status line and progress bar.

        Args:
            message: Status text.
            progress: 0-1, or ``None`` for an animated "working" bar.
        """
        self.status_label.configure(text=message)
        if progress is None:
            if not self._progress_running:
                self.progress.configure(mode="indeterminate")
                self.progress.start(15)
                self._progress_running = True
        else:
            if self._progress_running:
                self.progress.stop()
                self._progress_running = False
            self.progress.configure(mode="determinate", value=progress * 100)

    def _set_busy(self, busy: bool) -> None:
        self.analysis_tab.set_busy(busy)
        self.tools_tab.set_busy(busy)
        self.cancel_button.state(["!disabled"] if busy else ["disabled"])
        if not busy:
            if self._progress_running:
                self.progress.stop()
                self._progress_running = False
            self.progress.configure(mode="determinate", value=0)
            self.status_label.configure(text="Ready.")

    def _cancel(self) -> None:
        self.runner.cancel()

    # ------------------------------------------------------------ tool check
    def _check_tools(self, startup: bool = False) -> None:
        def work(reporter: WorkerReporter) -> ToolStatus:
            reporter.status("Checking tools (yt-dlp, Deno, ffmpeg)...", None)
            return check_tools()

        self.runner.run(
            "tool-check", work, lambda tools: self._apply_tools(tools, startup)
        )

    def _apply_tools(self, tools: ToolStatus, startup: bool) -> None:
        self.tools = tools
        self.tools_checked = True
        self.tools_tab.show_status(tools)
        self.analysis_tab.set_ffmpeg_available(bool(tools.ffmpeg))
        if tools.ytdlp_version is None:
            self._log_and_file(
                "yt-dlp is not installed. Run setup.bat or click "
                '"Check/update yt-dlp" ("Tools & help" tab).',
                LEVEL_ERROR,
            )
        else:
            age = ytdlp_age_days(tools.ytdlp_version)
            self.log(f"yt-dlp version: {tools.ytdlp_version}")
            if age is not None and age > YTDLP_MAX_AGE_DAYS:
                self._log_and_file(
                    f"yt-dlp is {age} days old. If errors appear, click "
                    '"Check/update yt-dlp".',
                    LEVEL_WARNING,
                )
        if not tools.deno:
            self._log_and_file(
                f"Deno not found. Install it with: {DENO_INSTALL_COMMAND}",
                LEVEL_WARNING,
            )
        elif tools.deno_too_old:
            self._log_and_file(
                f"Deno {tools.deno_version} is too old. Update it: "
                "winget upgrade DenoLand.Deno",
                LEVEL_WARNING,
            )
        else:
            self.log(f"Deno: {tools.deno_version or 'found'}")
        if tools.ffmpeg:
            self.log("ffmpeg found, clip cutting is enabled.")
        else:
            self._log_and_file(
                'ffmpeg not found, so the "Cut" button is disabled. '
                f"Install it with: {FFMPEG_INSTALL_COMMAND}",
                LEVEL_WARNING,
            )
        if not startup:
            self.log("Tools rechecked.", LEVEL_SUCCESS)
        elif self._startup_dialogs and (not tools.ffmpeg or not tools.deno):
            self._show_missing_tools_dialog(tools)

    def _show_missing_tools_dialog(self, tools: ToolStatus) -> None:
        parts = ["Some tools the app needs are missing:\n"]
        if not tools.ffmpeg:
            parts.append(
                '• ffmpeg - needed to cut clips (the "Cut" button stays '
                "disabled until you install it).\n"
                f"   Command: {FFMPEG_INSTALL_COMMAND}\n"
            )
        if not tools.deno:
            parts.append(
                "• Deno - needed for yt-dlp to work with YouTube.\n"
                f"   Command: {DENO_INSTALL_COMMAND}\n"
            )
        parts.append(
            "Type the commands into Command Prompt (Start → cmd) or click "
            '"Install now" on the "Tools & help" tab. Then click '
            '"Recheck".\n\nOpen the "Tools & help" tab now?'
        )
        if messagebox.askyesno("Missing tools", "\n".join(parts), parent=self.root):
            self.notebook.select(self.tools_tab)

    # ------------------------------------------------- AnalysisController API
    def load_link(self, text: str) -> None:
        """Load a video (analyze it) or a channel/playlist (list its videos).

        Args:
            text: The link typed by the user.
        """
        try:
            link = parse_youtube_link(text)
        except ValueError as error:
            messagebox.showwarning("Invalid link", str(error), parent=self.root)
            return
        if not link.is_list:
            assert link.video_id is not None
            entry = VideoEntry(video_id=link.video_id, url=link.url, title=link.url)
            self._entries = {entry.video_id: entry}
            self.analysis_tab.set_videos([entry], "Single video")
            self.analysis_tab.select_video(entry.video_id)
            self._analyze([entry])
            return

        settings, tools = self.settings, self.tools
        count = settings.channel_video_count

        def work(reporter: WorkerReporter) -> tuple[str, list[VideoEntry]]:
            reporter.status(f"Loading video list (up to {count})...", None)
            reporter.log(f"Loading the newest {count} videos: {link.url}")
            return YouTubeService(settings, tools, reporter).list_videos(
                link.url, count
            )

        def done(result: tuple[str, list[VideoEntry]]) -> None:
            title, videos = result
            self._entries = {video.video_id: video for video in videos}
            self._current_id = None
            self.analysis_tab.clear_results(
                'Select one or more videos and click "Analyze selected".'
            )
            self.analysis_tab.set_videos(
                videos,
                f"{title}: {len(videos)} newest videos. Select videos "
                '(Ctrl/Shift + click) and click "Analyze selected".',
            )
            if videos:
                self.log(f'Loaded {len(videos)} videos from "{title}".', LEVEL_SUCCESS)
            else:
                self.log("There are no public videos at this address.", LEVEL_WARNING)

        def failed(_: BaseException, message: str) -> None:
            messagebox.showerror("Loading failed", message, parent=self.root)

        self.runner.run("video-list", work, done, failed)

    def analyze_videos(self, video_ids: Sequence[str]) -> None:
        """Analyze the selected videos one after another.

        Args:
            video_ids: Ids of videos from the list.
        """
        entries = [self._entries[i] for i in video_ids if i in self._entries]
        if not entries:
            messagebox.showinfo(
                "Select a video",
                "First select at least one video in the list "
                "(Ctrl/Shift + click for more).",
                parent=self.root,
            )
            return
        self._analyze(entries)

    def _analyze(self, entries: list[VideoEntry]) -> None:
        settings, tools = self.settings, self.tools
        total = len(entries)
        if self._current_id not in {e.video_id for e in entries}:
            self._current_id = entries[0].video_id

        def work(reporter: WorkerReporter) -> tuple[int, list[str]]:
            service = YouTubeService(settings, tools, reporter)
            done_count = 0
            errors: list[str] = []
            for number, entry in enumerate(entries, start=1):
                if number > 1 and reporter.wait(
                    PAUSE_BETWEEN_VIDEOS, "Short pause between videos."
                ):
                    raise TaskCancelled()
                reporter.call_in_gui(
                    self.analysis_tab.set_video_status, entry.video_id, "Analyzing..."
                )
                reporter.log(f"[{number}/{total}] Analyzing: {entry.title}")
                try:
                    analysis = analyze_video(service, entry.url, settings, reporter)
                except TaskCancelled:
                    reporter.call_in_gui(
                        self.analysis_tab.set_video_status, entry.video_id, "Cancelled"
                    )
                    raise
                except Exception as error:
                    logger.exception("Analysis failed: %s", entry.url)
                    message = friendly_error(error)
                    errors.append(message)
                    reporter.log(f"Analysis failed: {message}", LEVEL_ERROR)
                    reporter.call_in_gui(
                        self.analysis_tab.set_video_status, entry.video_id, "Error"
                    )
                    continue
                done_count += 1
                reporter.call_in_gui(self._on_video_analyzed, analysis)
            return done_count, errors

        def done(result: tuple[int, list[str]]) -> None:
            done_count, errors = result
            if done_count:
                self.log(
                    f"Analysis finished: {done_count} of {total} videos.",
                    LEVEL_SUCCESS,
                )
            if errors and not done_count:
                messagebox.showerror("Analysis failed", errors[-1], parent=self.root)

        self.runner.run("analysis", work, done)

    def _on_video_analyzed(self, analysis: VideoAnalysis) -> None:
        video_id = analysis.video.video_id
        self._analyses[video_id] = analysis
        self._entries[video_id] = analysis.video
        if self._current_id in (None, video_id):
            self._current_id = video_id
            self.analysis_tab.show_analysis(analysis)
        else:
            self.analysis_tab.update_video(analysis.video, analysis_status(analysis))

    def video_selected(self, video_id: str) -> None:
        """Show results (or an empty view) for the selected video.

        Args:
            video_id: The selected video.
        """
        if video_id == self._current_id and video_id in self._analyses:
            return
        self._current_id = video_id
        if video_id in self._analyses:
            self.analysis_tab.show_analysis(self._analyses[video_id])
        elif video_id in self._entries:
            self.analysis_tab.show_video_without_results(self._entries[video_id])

    def cut_clip(self, start_text: str, end_text: str, vertical: bool) -> None:
        """Validate the input and cut a clip in the background.

        Args:
            start_text: Start time as typed.
            end_text: End time as typed.
            vertical: ``True`` for 9:16.
        """
        if not self.tools.ffmpeg:
            messagebox.showwarning(
                "ffmpeg is not installed",
                f"Cutting requires ffmpeg.\n\nCommand: {FFMPEG_INSTALL_COMMAND}",
                parent=self.root,
            )
            return
        video = self._entries.get(self._current_id or "")
        if video is None:
            messagebox.showinfo(
                "Select a video",
                "First select or analyze a video.",
                parent=self.root,
            )
            return
        try:
            start = parse_time(start_text)
            end = parse_time(end_text)
            start, end = validate_range(start, end, video.duration)
        except (ValueError, UserFacingError) as error:
            messagebox.showwarning("Invalid time", str(error), parent=self.root)
            return
        if end - start > LONG_CLIP_SECONDS and not messagebox.askyesno(
            "Long clip",
            f"The clip is {format_time(end - start)} long. Are you sure?",
            parent=self.root,
        ):
            return

        request = ClipRequest(video, start, end, vertical, self.settings.output_path)
        settings, tools = self.settings, self.tools
        shape = "9:16" if vertical else "16:9"

        def work(reporter: WorkerReporter) -> Path:
            reporter.log(
                f"Cutting {format_time(start)} - {format_time(end)} ({shape}) from "
                f'"{video.title}"...'
            )
            return ClipCutter(settings, tools, reporter).cut(request)

        def done(path: Path) -> None:
            self.log(f"Clip saved: {path}", LEVEL_SUCCESS)
            if messagebox.askyesno(
                "Clip is ready",
                f"Clip saved:\n{path}\n\nOpen the folder with the clip?",
                parent=self.root,
            ):
                self._open(path, select=True)

        def failed(_: BaseException, message: str) -> None:
            messagebox.showerror("Cutting failed", message, parent=self.root)

        self.runner.run("cutting", work, done, failed)

    def export_results(self, kind: str) -> None:
        """Export all analyzed videos to a .txt or .csv file.

        Args:
            kind: ``"txt"`` or ``"csv"``.
        """
        analyses = list(self._analyses.values())
        if not analyses:
            messagebox.showinfo(
                "No results", "First analyze at least one video.", parent=self.root
            )
            return
        filetypes = (
            [("CSV for Excel", "*.csv")] if kind == "csv" else [("Text", "*.txt")]
        )
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save results",
            defaultextension=f".{kind}",
            filetypes=filetypes,
            initialdir=str(APP_DIR),
            initialfile=f"clipper_results_{datetime.now():%Y-%m-%d_%H%M}.{kind}",
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != f".{kind}":
            target = target.with_name(f"{target.name}.{kind}")
        try:
            count = export_results(
                analyses, target, float(self.settings.lead_in_seconds), list_separator()
            )
        except OSError as error:
            logger.exception("Export failed")
            messagebox.showerror(
                "Export failed", friendly_error(error), parent=self.root
            )
            return
        self._log_and_file(
            f"Exported {count} moments ({len(analyses)} videos) to {target}",
            LEVEL_SUCCESS,
        )

    def open_clips_folder(self) -> None:
        """Open the folder with clips (creates it if needed)."""
        folder = self.settings.output_path
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            messagebox.showerror("Error", friendly_error(error), parent=self.root)
            return
        self._open(folder)

    # ---------------------------------------------------- ToolsController API
    def update_ytdlp(self) -> None:
        """Upgrade yt-dlp with pip and check for Deno afterwards."""
        before = self.tools.ytdlp_version

        def work(reporter: WorkerReporter) -> tuple[int, str | None, ToolStatus]:
            reporter.log(f"Running: {YTDLP_UPGRADE_COMMAND}")
            reporter.status("Updating yt-dlp (this can take a minute)...", None)
            code = upgrade_ytdlp(
                lambda line: reporter.status(f"pip: {line[:110]}", None),
                reporter.cancelled,
            )
            if reporter.cancelled():
                raise TaskCancelled()
            after = installed_version_in_subprocess("yt-dlp")
            tools = check_tools()
            tools.ytdlp_version = after or tools.ytdlp_version
            return code, after, tools

        def done(result: tuple[int, str | None, ToolStatus]) -> None:
            code, after, tools = result
            self._apply_tools(tools, startup=False)
            if code != 0:
                message = (
                    "Updating yt-dlp failed. Check your internet connection and "
                    "try again (details are in the log file)."
                )
                self._log_and_file(message, LEVEL_ERROR)
                messagebox.showerror("Update failed", message, parent=self.root)
            elif after and after != before:
                self._log_and_file(
                    f"yt-dlp updated: {before or 'not installed'} → {after}.",
                    LEVEL_SUCCESS,
                )
                if messagebox.askyesno(
                    "yt-dlp updated",
                    f"New version: {after}\n\nThe new version is used only after "
                    "the app restarts. Restart now?",
                    parent=self.root,
                ):
                    self._restart()
                    return
            else:
                self._log_and_file(
                    f"You already have the latest yt-dlp ({after or before}).",
                    LEVEL_SUCCESS,
                )
            if not tools.deno:
                messagebox.showwarning(
                    "Deno not found",
                    "yt-dlp needs a JavaScript runtime (Deno) for YouTube.\n\n"
                    "Open Command Prompt (Start → cmd) and type:\n\n"
                    f"    {DENO_INSTALL_COMMAND}\n\n"
                    'Then restart the app (or click "Recheck").',
                    parent=self.root,
                )

        self.runner.run("update-yt-dlp", work, done)

    def recheck_tools(self) -> None:
        """Search for the tools again (e.g. after installing ffmpeg)."""
        self._check_tools(startup=False)

    def install_tool(self, command: str) -> None:
        """Open a Command Prompt window that runs a winget install command.

        Args:
            command: The ``winget install ...`` command.
        """
        try:
            open_install_console(winget_command_for_button(command))
        except OSError as error:
            logger.exception("winget did not start")
            messagebox.showerror(
                "Install did not start",
                f"{error}\n\nOpen Command Prompt and type:\n{command}",
                parent=self.root,
            )
            return
        self.log(
            f"An install window was opened ({command}). When it finishes, "
            'close it and click "Recheck".',
        )

    def copy_to_clipboard(self, text: str) -> None:
        """Copy text to the clipboard.

        Args:
            text: Text to copy.
        """
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.log(f"Copied: {text}")

    def open_logs(self) -> None:
        """Open the folder with log files."""
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._open(LOG_DIR)

    # --------------------------------------------------------------- helpers
    def _save_settings(self, settings: Settings) -> None:
        try:
            save_settings(settings, self._settings_path)
        except OSError as error:
            logger.exception("Settings were not saved")
            messagebox.showerror("Error", friendly_error(error), parent=self.root)
            return
        self.settings = load_settings(self._settings_path)
        self.settings_tab.load(self.settings)
        self.analysis_tab.refresh_details()
        self._log_and_file(
            "Settings saved. The segment count and intro skip apply from the "
            "next analysis.",
            LEVEL_SUCCESS,
        )

    def _open(self, path: Path, select: bool = False) -> None:
        try:
            open_path(path, select=select)
        except OSError as error:
            logger.exception("Cannot open %s", path)
            messagebox.showerror("Error", friendly_error(error), parent=self.root)

    def _restart(self) -> None:
        main = APP_DIR / "main.py"
        try:
            subprocess.Popen([sys.executable, str(main)], cwd=str(APP_DIR))
        except OSError as error:
            logger.exception("Restart failed")
            messagebox.showerror("Error", friendly_error(error), parent=self.root)
            return
        self.root.destroy()

    def _on_close(self) -> None:
        if self.runner.busy and not messagebox.askyesno(
            "Task in progress",
            "A task is still running. Do you really want to close the app?",
            parent=self.root,
        ):
            return
        self.runner.cancel()
        self.root.destroy()

    def _on_tk_error(self, exc_type, exc_value, exc_traceback) -> None:  # noqa: ANN001
        logger.error(
            "Error in the user interface",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        self.log(friendly_error(exc_value), LEVEL_ERROR)


def _configure_style(root: tk.Tk) -> None:
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(name).configure(family="Segoe UI", size=10)
        except tk.TclError:
            pass
    default = tkfont.nametofont("TkDefaultFont")
    row_height = int(default.metrics("linespace") * 1.45)
    style.configure("Treeview", rowheight=row_height)
    style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
    style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
    style.configure("Hint.TLabel", foreground="#6b7280")
    style.configure("Title.TLabel", font=("Segoe UI", 12, "bold"))


def _set_initial_geometry(root: tk.Tk) -> None:
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    width = min(int(screen_w * 0.9), 1400)
    height = min(int(screen_h * 0.88), 950)
    root.geometry(
        f"{width}x{height}+{(screen_w - width) // 2}+{max((screen_h - height) // 3, 0)}"
    )
    root.minsize(min(1000, screen_w), min(680, screen_h))


def _enable_dpi_awareness() -> None:
    """Make text sharp on high-DPI Windows screens."""
    if os.name != "nt":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def run(smoke_test: bool = False) -> int:
    """Start the application.

    Args:
        smoke_test: Build the window, run the startup checks for a few
            seconds and close automatically (used to verify the install).

    Returns:
        Process exit code.
    """
    log_file = setup_logging()
    _enable_dpi_awareness()
    try:
        root = tk.Tk()
    except tk.TclError:
        logger.exception("Tk could not start")
        print("The graphical window cannot be opened (tkinter). Details:", log_file)
        return 1
    try:
        app = ClipperApp(root, startup_dialogs=not smoke_test)
        if smoke_test:

            def finish() -> None:
                if app.runner.busy:
                    root.after(250, finish)
                    return
                logger.info("Smoke test: window created successfully.")
                root.destroy()

            root.after(1500, finish)
        root.mainloop()
    except Exception as error:
        logger.exception("The app crashed")
        try:
            messagebox.showerror(
                APP_NAME,
                "The app hit an error and has to close.\n\n"
                f"{friendly_error(error)}\n\nLog file: {log_file}",
            )
        except tk.TclError:
            pass
        return 1
    return 0
