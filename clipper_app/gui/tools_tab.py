"""The "Tools & help" tab: yt-dlp, Deno and ffmpeg status and help."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Protocol

from ..config import LOG_FILE
from ..environment import (
    DENO_INSTALL_COMMAND,
    FFMPEG_INSTALL_COMMAND,
    YTDLP_MAX_AGE_DAYS,
    ToolStatus,
    ytdlp_age_days,
)

COLOR_OK = "#047857"
COLOR_BAD = "#b91c1c"
COLOR_WARN = "#b45309"

HELP_TEXT = (
    "How to use:\n"
    '  1. On the "Analysis" tab, paste a video or channel link and click "Load".\n'
    '  2. For a channel, select videos and click "Analyze selected".\n'
    "  3. Click a moment in the table (or an orange bar on the chart).\n"
    "  4. Optionally change the start/end, choose 16:9 or 9:16 and click "
    '"Cut".\n'
    'If YouTube reports "nsig extraction failed" or "Precondition check '
    'failed", click "Check/update yt-dlp" and make sure Deno is installed.'
)


class ToolsController(Protocol):
    """Actions the tab asks the application to perform."""

    def update_ytdlp(self) -> None:
        """Run the yt-dlp upgrade."""

    def recheck_tools(self) -> None:
        """Look for the tools again."""

    def install_tool(self, command: str) -> None:
        """Open a console that runs a winget install command."""

    def copy_to_clipboard(self, text: str) -> None:
        """Copy text to the clipboard."""

    def open_logs(self) -> None:
        """Open the logs folder."""


class ToolsTab(ttk.Frame):
    """Shows which tools are installed and how to install the missing ones."""

    def __init__(self, parent: tk.Misc, controller: ToolsController) -> None:
        """Build the tab.

        Args:
            parent: Parent widget (the notebook).
            controller: Receives user actions.
        """
        super().__init__(parent, padding=12)
        self._controller = controller
        self._buttons: list[ttk.Button] = []
        self._command_vars: list[tk.StringVar] = []
        self.columnconfigure(0, weight=1)

        ytdlp = ttk.LabelFrame(
            self, text="yt-dlp (downloading from YouTube)", padding=8
        )
        ytdlp.grid(row=0, column=0, sticky="ew")
        ytdlp.columnconfigure(0, weight=1)
        self._ytdlp_label = tk.Label(ytdlp, text="Checking...", anchor="w")
        self._ytdlp_label.grid(row=0, column=0, sticky="w")
        update = ttk.Button(
            ytdlp,
            text="Check/update yt-dlp",
            style="Accent.TButton",
            command=controller.update_ytdlp,
        )
        update.grid(row=0, column=1, sticky="e")
        self._buttons.append(update)
        ttk.Label(
            ytdlp,
            text=(
                "YouTube changes often, so old yt-dlp versions stop working "
                '(errors "nsig extraction failed", "Precondition check failed"). '
                'The button runs: pip install -U --pre "yt-dlp[default]". After '
                "updating, restart the app."
            ),
            style="Hint.TLabel",
            wraplength=900,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self._deno_label = self._tool_section(
            row=1,
            title="Deno (JavaScript runtime yt-dlp uses for YouTube)",
            command=DENO_INSTALL_COMMAND,
            hint=(
                "Without Deno, yt-dlp cannot solve YouTube's protection and errors "
                'appear. After installing, click "Recheck" (or restart the app).'
            ),
        )
        self._ffmpeg_label = self._tool_section(
            row=2,
            title="ffmpeg (cutting and making vertical clips)",
            command=FFMPEG_INSTALL_COMMAND,
            hint=(
                'Without ffmpeg the "Cut" button is disabled. After installing, '
                'click "Recheck".'
            ),
        )

        actions = ttk.Frame(self)
        actions.grid(row=3, column=0, sticky="w", pady=(10, 0))
        recheck = ttk.Button(actions, text="Recheck", command=controller.recheck_tools)
        recheck.pack(side="left")
        self._buttons.append(recheck)
        ttk.Button(actions, text="Open logs folder", command=controller.open_logs).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(
            self, text=f"Log file with error details: {LOG_FILE}", style="Hint.TLabel"
        ).grid(row=4, column=0, sticky="w", pady=(4, 0))
        ttk.Label(self, text=HELP_TEXT, justify="left").grid(
            row=5, column=0, sticky="w", pady=(12, 0)
        )

    def _tool_section(self, row: int, title: str, command: str, hint: str) -> tk.Label:
        frame = ttk.LabelFrame(self, text=title, padding=8)
        frame.grid(row=row, column=0, sticky="ew", pady=(10, 0))
        frame.columnconfigure(1, weight=1)
        status = tk.Label(frame, text="Checking...", anchor="w")
        status.grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(frame, text="Install (in Command Prompt):").grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        # Keep a reference: tkinter clears the Entry if the variable is
        # garbage collected.
        command_var = tk.StringVar(value=command)
        self._command_vars.append(command_var)
        ttk.Entry(frame, textvariable=command_var, state="readonly", width=36).grid(
            row=1, column=1, sticky="w", padx=6, pady=(6, 0)
        )
        ttk.Button(
            frame,
            text="Copy command",
            command=lambda: self._controller.copy_to_clipboard(command),
        ).grid(row=1, column=2, pady=(6, 0))
        install = ttk.Button(
            frame,
            text="Install now",
            command=lambda: self._controller.install_tool(command),
        )
        install.grid(row=1, column=3, padx=(6, 0), pady=(6, 0))
        self._buttons.append(install)
        ttk.Label(
            frame, text=hint, style="Hint.TLabel", wraplength=900, justify="left"
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))
        return status

    def show_status(self, tools: ToolStatus) -> None:
        """Display the detected tools.

        Args:
            tools: Result of the tool check.
        """
        if tools.ytdlp_version is None:
            self._ytdlp_label.configure(
                text='yt-dlp is not installed - click "Check/update yt-dlp".',
                foreground=COLOR_BAD,
            )
        else:
            age = ytdlp_age_days(tools.ytdlp_version)
            age_text = f", {age} days old" if age is not None else ""
            old = age is not None and age > YTDLP_MAX_AGE_DAYS
            ejs = (
                f" | yt-dlp-ejs {tools.ytdlp_ejs_version}"
                if tools.ytdlp_ejs_version
                else " | yt-dlp-ejs not installed (update yt-dlp)"
            )
            advice = " - updating is recommended" if old else ""
            version = tools.ytdlp_version
            self._ytdlp_label.configure(
                text=f"Installed version: {version}{age_text}{ejs}{advice}",
                foreground=(
                    COLOR_WARN if old or not tools.ytdlp_ejs_version else COLOR_OK
                ),
            )

        if tools.deno:
            version = tools.deno_version or "unknown version"
            too_old = (
                " - TOO OLD, version 2 or newer is required"
                if tools.deno_too_old
                else ""
            )
            self._deno_label.configure(
                text=f"Found: Deno {version} ({tools.deno}){too_old}",
                foreground=COLOR_WARN if tools.deno_too_old else COLOR_OK,
            )
        else:
            self._deno_label.configure(
                text=f"Not found. Install it with: {DENO_INSTALL_COMMAND}",
                foreground=COLOR_BAD,
            )

        if tools.ffmpeg:
            probe = "" if tools.ffprobe else " (ffprobe not found)"
            self._ffmpeg_label.configure(
                text=f"Found: {tools.ffmpeg}{probe}", foreground=COLOR_OK
            )
        else:
            self._ffmpeg_label.configure(
                text=(
                    "Not found - clip cutting is disabled. Install it "
                    f"with: {FFMPEG_INSTALL_COMMAND}"
                ),
                foreground=COLOR_BAD,
            )

    def set_busy(self, busy: bool) -> None:
        """Disable buttons that start background work while busy.

        Args:
            busy: ``True`` while a task is running.
        """
        for button in self._buttons:
            button.state(["disabled"] if busy else ["!disabled"])
