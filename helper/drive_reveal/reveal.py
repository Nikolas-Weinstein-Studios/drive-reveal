"""Hand a path to the platform file manager."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class RevealError(Exception):
    """Raised when the file manager could not be launched."""


def reveal(path: Path, select: bool = False) -> str:
    """Show `path` in Explorer or Finder. Returns a one-line description of what ran.

    A folder is opened so its contents are visible; a file is selected inside its parent.
    `select` forces the select-in-parent behaviour even for a folder.
    """
    path = Path(path)
    as_file = select or not path.is_dir()

    if sys.platform == "win32":
        return _reveal_windows(path, as_file)
    if sys.platform == "darwin":
        return _reveal_macos(path, as_file)
    return _reveal_freedesktop(path)


def _reveal_windows(path: Path, as_file: bool) -> str:
    # Explorer wants a native backslash path and no trailing separator.
    target = str(path).rstrip("\\/")
    args = ["explorer.exe"]
    if as_file:
        # /select, must stay glued to the path in one argument, and Explorer rejects
        # a quoted path here, so this is passed through as a single argv entry.
        args.append(f"/select,{target}")
    else:
        args.append(target)

    # Explorer exits 1 on success often enough that its return code is meaningless.
    try:
        subprocess.Popen(args, close_fds=True)
    except OSError as exc:
        raise RevealError(f"Could not launch Explorer: {exc}") from exc
    return " ".join(args)


def _reveal_macos(path: Path, as_file: bool) -> str:
    args = ["open"] + (["-R"] if as_file else []) + [str(path)]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RevealError(f"open failed: {result.stderr.strip() or result.returncode}")
    return " ".join(args)


def _reveal_freedesktop(path: Path) -> str:
    """Best effort for a Linux box holding a copied Drive profile (tests, mostly)."""
    for launcher in (["xdg-open"], ["gio", "open"]):
        try:
            subprocess.Popen(launcher + [str(path)], close_fds=True)
            return " ".join(launcher + [str(path)])
        except OSError:
            continue
    raise RevealError(f"No file manager launcher found for {path}")
