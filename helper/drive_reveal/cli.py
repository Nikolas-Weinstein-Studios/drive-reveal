"""Command line entry point, and the target of the gdrivereveal:// protocol handler.

When launched by the protocol handler there is no console attached, so failures are
reported in a dialog box. Run it from a terminal and it behaves like a normal CLI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import ids
from .drivefs import ResolveError, Resolved, mount_point, resolve
from .reveal import RevealError, reveal

EXIT_OK, EXIT_NOT_FOUND, EXIT_ERROR = 0, 2, 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drive-reveal",
        description="Open the local Drive for desktop folder for a Google Drive web link.",
    )
    parser.add_argument(
        "target",
        help="A Drive item ID, a drive.google.com or docs.google.com URL, "
        "or a gdrivereveal:// payload.",
    )
    parser.add_argument(
        "--print", dest="print_only", action="store_true",
        help="Print the resolved local path instead of opening a file manager.",
    )
    parser.add_argument(
        "--json", dest="as_json", action="store_true",
        help="Print the full resolution result as JSON. Implies --print.",
    )
    parser.add_argument(
        "--select", action="store_true",
        help="Select the item inside its parent folder rather than opening it.",
    )
    parser.add_argument(
        "--gui", action="store_true",
        help="Report failures in a dialog box as well as on stderr. The protocol handler "
        "passes this, since it runs with no console for the message to land in.",
    )
    return parser


def _resolve_target(target: str) -> Resolved:
    item = ids.extract(target)

    if item in (ids.MY_DRIVE, ids.SHARED_DRIVES):
        name = "My Drive" if item == ids.MY_DRIVE else "Shared drives"
        path = Path(mount_point()) / name
        if not path.is_dir():
            raise ResolveError(f"{name} is not present in the local Drive mount")
        return Resolved(
            path=path, relative=Path(name), name=name,
            is_folder=True, account_id="-",
        )

    return resolve(item)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)

    try:
        found = _resolve_target(args.target)
    except (ids.NoIdFound, ResolveError) as exc:
        _fail(str(exc), args.gui)
        return EXIT_NOT_FOUND

    if args.as_json:
        print(json.dumps({
            "path": str(found.path),
            "relative": str(found.relative),
            "name": found.name,
            "is_folder": found.is_folder,
            "exists": found.exists,
            "account_id": found.account_id,
            "via_shortcut": found.via_shortcut,
            "reveal_target": str(found.reveal_target),
        }, indent=2))
        return EXIT_OK

    if args.print_only:
        print(found.path)
        return EXIT_OK

    target = found.reveal_target
    # Selecting only makes sense when the item itself is on disk.
    select = args.select and target == found.path
    try:
        reveal(target, select=select)
    except RevealError as exc:
        _fail(str(exc), args.gui)
        return EXIT_ERROR

    if target != found.path:
        note = f"{found.name} is not downloaded yet; opened {target} instead."
        print(note, file=sys.stderr)
    return EXIT_OK


def _fail(message: str, gui: bool) -> None:
    print(f"drive-reveal: {message}", file=sys.stderr)
    if gui:
        _dialog("Reveal in Drive folder", message)


def _dialog(title: str, message: str) -> None:
    """Show a modal error box. Only ever called under --gui: it blocks until dismissed."""
    try:
        if sys.platform == "win32":
            import ctypes

            MB_ICONWARNING = 0x30
            ctypes.windll.user32.MessageBoxW(None, message, title, MB_ICONWARNING)
        elif sys.platform == "darwin":
            import subprocess

            script = (
                f'display dialog {json.dumps(message)} with title {json.dumps(title)} '
                'buttons {"OK"} default button "OK" with icon caution'
            )
            subprocess.run(["osascript", "-e", script], capture_output=True)
    except Exception:
        pass  # a failed error dialog must not mask the original error


if __name__ == "__main__":
    sys.exit(main())
