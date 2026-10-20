"""Clipper launcher (double-clicking start.bat runs this file).

Usage:
    python main.py               # normal start
    python main.py --smoke-test  # open the window, run checks, close
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info < (3, 10):  # noqa: UP036 - friendly message for old Python
    sys.exit("Clipper requires Python 3.10 or newer (recommended: 3.14).")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clipper_app.gui.app import run  # noqa: E402


def main() -> int:
    """Start the GUI.

    Returns:
        Process exit code.
    """
    return run(smoke_test="--smoke-test" in sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
