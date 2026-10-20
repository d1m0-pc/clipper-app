"""The "Settings" tab."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import filedialog, messagebox, ttk

from ..config import DEFAULT_OUTPUT_DIR, LIMITS, Settings, validate_cookies_file

COOKIES_WARNING = (
    "IMPORTANT: cookies.txt contains your Google account login. Anyone who gets "
    "this file can access your account. Never share it, send it, or upload it "
    "anywhere."
)
COOKIES_HELP = (
    "Cookies are optional. They help when YouTube asks you to sign in, to confirm "
    "you are not a bot, or returns error 429.\n"
    "How to create cookies.txt:\n"
    '  1. In the Brave browser, install the "Get cookies.txt LOCALLY" extension.\n'
    "  2. Open youtube.com and make sure you are signed in.\n"
    '  3. Click the extension icon and choose "Export" '
    "(save the file, e.g. in Documents).\n"
    '  4. Here, click "Browse..." and select that file.\n'
    "Reading cookies directly from Brave/Chrome does not work on Windows "
    '(error "Could not copy Chrome cookie database"), so only the file is used.'
)

_NUMBER_FIELDS = (
    (
        "channel_video_count",
        "Videos per channel:",
        "how many of the newest videos are shown",
    ),
    (
        "lead_in_seconds",
        "Seconds before segment:",
        "transcript and clip start this much earlier (default 15)",
    ),
    (
        "skip_intro_seconds",
        "Skip intro (seconds):",
        "the heatmap is always high at the start, so the intro is skipped "
        "(default 60)",
    ),
    (
        "top_segments",
        "Number of top segments:",
        "how many segments are picked (default 10)",
    ),
)


class SettingsTab(ttk.Frame):
    """Lets the user change and save settings."""

    def __init__(
        self,
        parent: tk.Misc,
        settings: Settings,
        on_save: Callable[[Settings], None],
    ) -> None:
        """Build the tab.

        Args:
            parent: Parent widget (the notebook).
            settings: Settings to show initially.
            on_save: Called with the new settings when the user saves.
        """
        super().__init__(parent, padding=12)
        self._on_save = on_save
        self.cookies_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.number_vars = {name: tk.StringVar() for name, _, _ in _NUMBER_FIELDS}
        self.columnconfigure(0, weight=1)
        self._build_cookies().grid(row=0, column=0, sticky="ew")
        self._build_analysis().grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self._build_output().grid(row=2, column=0, sticky="ew", pady=(10, 0))
        buttons = ttk.Frame(self)
        buttons.grid(row=3, column=0, sticky="w", pady=(12, 0))
        ttk.Button(
            buttons,
            text="Save settings",
            style="Accent.TButton",
            command=self._save,
        ).pack(side="left")
        ttk.Button(buttons, text="Reset to defaults", command=self._reset).pack(
            side="left", padx=(8, 0)
        )
        self.load(settings)

    def _build_cookies(self) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(self, text="Cookies (cookies.txt) - optional", padding=8)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Path to cookies.txt:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.cookies_var).grid(
            row=0, column=1, sticky="ew", padx=6
        )
        ttk.Button(frame, text="Browse...", command=self._browse_cookies).grid(
            row=0, column=2
        )
        ttk.Button(frame, text="Remove", command=lambda: self.cookies_var.set("")).grid(
            row=0, column=3, padx=(6, 0)
        )
        tk.Label(
            frame,
            text=COOKIES_WARNING,
            foreground="#b91c1c",
            anchor="w",
            justify="left",
            wraplength=900,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        ttk.Label(frame, text=COOKIES_HELP, justify="left").grid(
            row=2, column=0, columnspan=4, sticky="w"
        )
        return frame

    def _build_analysis(self) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(self, text="Analysis", padding=8)
        for row, (name, label, hint) in enumerate(_NUMBER_FIELDS):
            low, high = LIMITS[name]
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Spinbox(
                frame, from_=low, to=high, width=7, textvariable=self.number_vars[name]
            ).grid(row=row, column=1, sticky="w", padx=6)
            ttk.Label(
                frame, text=f"{hint}; allowed {low}-{high}", style="Hint.TLabel"
            ).grid(row=row, column=2, sticky="w")
        return frame

    def _build_output(self) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(self, text="Clips", padding=8)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Clips folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.output_var).grid(
            row=0, column=1, sticky="ew", padx=6
        )
        ttk.Button(frame, text="Browse...", command=self._browse_output).grid(
            row=0, column=2
        )
        ttk.Label(
            frame,
            text=f"If empty, clips are saved to: {DEFAULT_OUTPUT_DIR}",
            style="Hint.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        return frame

    def load(self, settings: Settings) -> None:
        """Show the given settings in the form.

        Args:
            settings: Settings to display.
        """
        self.cookies_var.set(settings.cookies_path)
        self.output_var.set(settings.output_dir or str(DEFAULT_OUTPUT_DIR))
        for name, var in self.number_vars.items():
            var.set(str(getattr(settings, name)))

    def collect(self) -> Settings:
        """Read the form into a :class:`Settings` object.

        Returns:
            The entered settings.

        Raises:
            ValueError: With a user-facing message if a number is invalid.
        """
        numbers: dict[str, int] = {}
        for name, label, _ in _NUMBER_FIELDS:
            low, high = LIMITS[name]
            text = self.number_vars[name].get().strip()
            try:
                value = int(text)
            except ValueError:
                raise ValueError(f'{label} "{text}" is not a whole number.') from None
            if not low <= value <= high:
                raise ValueError(f"{label} must be between {low} and {high}.")
            numbers[name] = value
        output = self.output_var.get().strip()
        if output == str(DEFAULT_OUTPUT_DIR):
            output = ""
        return Settings(
            cookies_path=self.cookies_var.get().strip(),
            output_dir=output,
            **numbers,
        )

    def _save(self) -> None:
        try:
            settings = self.collect()
        except ValueError as error:
            messagebox.showwarning("Invalid value", str(error), parent=self)
            return
        if settings.cookies_file:
            problem = validate_cookies_file(settings.cookies_file)
            if problem and not messagebox.askyesno(
                "cookies.txt",
                f"{problem}\n\nDo you still want to save this path?",
                parent=self,
            ):
                return
        self._on_save(settings)

    def _reset(self) -> None:
        self.load(Settings())

    def _browse_cookies(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Select cookies.txt",
            filetypes=[("cookies.txt", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self.cookies_var.set(path)

    def _browse_output(self) -> None:
        path = filedialog.askdirectory(
            parent=self, title="Select clips folder", mustexist=False
        )
        if path:
            self.output_var.set(path)
