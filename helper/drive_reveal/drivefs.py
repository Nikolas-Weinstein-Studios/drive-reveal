"""Resolve a Google Drive item ID to its path inside the local Drive for desktop mount.

Everything here reads Drive for desktop's own local metadata, so resolution needs no
OAuth client, no API quota, and no network. The two files that matter:

  <DriveFS>/root_preference_sqlite.db        mount points (which drive letter / volume)
  <DriveFS>/<account_id>/metadata_sqlite_db  the item tree (id, name, parent)

Both are private to Drive for desktop and are opened strictly read-only. Neither is
documented by Google, so every assumption about them is validated at runtime and a
failure downgrades to a clear error rather than a wrong path.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path, PurePath


class ResolveError(Exception):
    """Raised when an item ID cannot be turned into a local path."""


# --------------------------------------------------------------------------- layout


def drivefs_dir() -> Path:
    """Locate Drive for desktop's data directory for this machine and user.

    Never hardcoded to a particular home directory or drive letter: derived from the
    OS-appropriate environment variable so the same checkout works on every machine.
    """
    override = os.environ.get("DRIVE_REVEAL_DRIVEFS_DIR")
    if override:
        d = Path(override)
        if not d.is_dir():
            raise ResolveError(f"DRIVE_REVEAL_DRIVEFS_DIR is set but not a directory: {d}")
        return d

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise ResolveError("LOCALAPPDATA is not set; cannot locate Drive for desktop data")
        d = Path(base) / "Google" / "DriveFS"
    elif sys.platform == "darwin":
        d = Path.home() / "Library" / "Application Support" / "Google" / "DriveFS"
    else:
        raise ResolveError(
            f"Drive for desktop does not run on {sys.platform}; "
            "set DRIVE_REVEAL_DRIVEFS_DIR to test against a copied profile"
        )

    if not d.is_dir():
        raise ResolveError(f"Drive for desktop data directory not found at {d}. Is it installed?")
    return d


def account_dirs(base: Path | None = None) -> list[Path]:
    """Account subdirectories, newest-signed-in first. Named by numeric obfuscated ID."""
    base = base or drivefs_dir()
    accounts = [
        p for p in base.iterdir()
        if p.is_dir() and p.name.isdigit() and (p / "metadata_sqlite_db").is_file()
    ]
    if not accounts:
        raise ResolveError(f"No signed-in Drive accounts with metadata found under {base}")
    return sorted(accounts, key=lambda p: p.stat().st_mtime, reverse=True)


def mount_point(base: Path | None = None) -> Path:
    """Find where Drive for desktop is mounted (a drive letter, or a CloudStorage dir).

    Drive records this itself in root_preference_sqlite.db, which is authoritative and
    survives the user relocating or remapping the mount. Falls back to probing the
    conventional locations if that table cannot be read.
    """
    override = os.environ.get("DRIVE_REVEAL_MOUNT")
    if override:
        return Path(override)

    base = base or drivefs_dir()
    try:
        with closing(_read_only(base / "root_preference_sqlite.db")) as db:
            for (mount,) in db.execute(
                "SELECT last_mount_point FROM media WHERE name = 'Google Drive' AND ignored = 0"
            ):
                if mount and _looks_like_mount(Path(mount)):
                    return Path(mount)
    except (sqlite3.Error, OSError, ResolveError):
        pass  # fall through to probing

    for candidate in _candidate_mounts():
        if _looks_like_mount(candidate):
            return candidate

    raise ResolveError(
        "Could not find the Google Drive mount point. Is Drive for desktop running? "
        "Set DRIVE_REVEAL_MOUNT to override."
    )


def _candidate_mounts() -> list[Path]:
    if sys.platform == "win32":
        # Only ask about drives that are actually present. Probing every letter blind
        # stalls for seconds per disconnected network mapping.
        try:
            letters = os.listdrives()  # Python 3.12+
        except (AttributeError, OSError):
            letters = [f"{chr(c)}:\\" for c in range(ord("D"), ord("Z") + 1)]
        return [Path(d) for d in reversed(letters)]
    home = Path.home()
    found = sorted((home / "Library" / "CloudStorage").glob("GoogleDrive-*"))
    return [*found, Path("/Volumes/GoogleDrive")]


def _looks_like_mount(path: Path) -> bool:
    """A Drive mount always exposes 'My Drive' and/or 'Shared drives' at its top level."""
    try:
        return path.is_dir() and any(
            (path / name).is_dir() for name in ("My Drive", "Shared drives")
        )
    except OSError:
        return False


# ------------------------------------------------------------------------ db access


def _read_only(path: Path) -> sqlite3.Connection:
    """Open a live Drive database read-only, snapshotting it if Drive holds it locked.

    Drive keeps these in WAL mode while running. A WAL reader normally needs to write
    the -shm file, which a read-only open cannot do, so this falls back to copying the
    database plus its sidecars to a temp file. The copy is what makes the WAL readable,
    so recent changes are not lost.
    """
    if not path.is_file():
        raise ResolveError(f"Expected Drive database not found: {path}")

    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        db = sqlite3.connect(uri, uri=True, timeout=5)
        db.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        return db
    except sqlite3.Error:
        pass

    tmp = Path(tempfile.mkdtemp(prefix="drive-reveal-")) / path.name
    for suffix in ("", "-wal", "-shm"):
        side = path.with_name(path.name + suffix)
        if side.is_file():
            shutil.copy2(side, tmp.with_name(tmp.name + suffix))
    return sqlite3.connect(f"file:{tmp.as_posix()}?mode=ro", uri=True, timeout=5)


# ------------------------------------------------------------------------- resolving


@dataclass(frozen=True)
class Resolved:
    """A successful lookup: where the item lives, and what it is."""

    path: Path
    relative: PurePath
    name: str
    is_folder: bool
    account_id: str
    via_shortcut: bool = False

    @property
    def exists(self) -> bool:
        return self.path.exists()

    @property
    def reveal_target(self) -> Path:
        """What to hand the file manager: the item if present, else its nearest parent.

        Selective sync and Shared-with-me items can be known to the metadata but absent
        from disk. Opening the parent is more useful than failing outright.
        """
        target = self.path
        while not target.exists() and target != target.parent:
            target = target.parent
        return target


def _tree(db: sqlite3.Connection) -> tuple[dict, dict, dict, set]:
    """Load the id/parent tree. One pass beats 20 round trips up a deep path."""
    items = {}
    by_cloud_id = {}
    for stable_id, cloud_id, title, is_folder, team_drive in db.execute(
        "SELECT stable_id, id, local_title, is_folder, team_drive_stable_id "
        "FROM items WHERE is_tombstone = 0"
    ):
        items[stable_id] = (cloud_id, title, bool(is_folder), team_drive)
        by_cloud_id[cloud_id] = stable_id

    parents = {
        item: parent
        for item, parent in db.execute(
            "SELECT item_stable_id, parent_stable_id FROM stable_parents"
        )
    }
    # A shared drive's root is the one item that is its own team drive.
    shared_roots = {sid for sid, (_, _, _, td) in items.items() if td == sid}
    return items, by_cloud_id, parents, shared_roots


def _my_drive_root(db: sqlite3.Connection, by_cloud_id: dict) -> int | None:
    row = db.execute("SELECT value FROM properties WHERE property = 'root_id'").fetchone()
    if not row or not row[0]:
        return None
    root_id = row[0].decode() if isinstance(row[0], bytes) else str(row[0])
    return by_cloud_id.get(root_id)


def _shortcut_target(db: sqlite3.Connection, stable_id: int) -> int | None:
    row = db.execute(
        "SELECT target_stable_id FROM shortcut_details WHERE shortcut_stable_id = ?",
        (stable_id,),
    ).fetchone()
    return row[0] if row else None


def _walk_up(stable_id: int, items: dict, parents: dict, my_root, shared_roots) -> PurePath:
    """Climb to a known root, collecting names. Raises if the chain leaves local Drive."""
    parts: list[str] = []
    seen: set[int] = set()
    sid = stable_id

    while True:
        if sid in seen:
            raise ResolveError("Drive metadata contains a parent cycle; cannot build a path")
        seen.add(sid)

        entry = items.get(sid)
        if entry is None:
            raise ResolveError("Path walk left the known item tree; metadata may be mid-sync")
        _, title, _, _ = entry

        if sid == my_root:
            return PurePath("My Drive", *reversed(parts))
        if sid in shared_roots:
            return PurePath("Shared drives", title, *reversed(parts))

        parts.append(title)
        parent = parents.get(sid)
        if parent is None:
            raise ResolveError(
                f"{title!r} has no local location. Items under 'Shared with me' are not "
                "in your Drive folder until you add a shortcut to My Drive."
            )
        sid = parent


def resolve(item_id: str) -> Resolved:
    """Turn a Drive item ID into a local path, searching every signed-in account.

    Accounts are searched rather than inferred from the URL's /u/N/ index, because that
    index is per-browser-profile ordering and does not map reliably onto Drive for
    desktop's accounts.
    """
    if not item_id:
        raise ResolveError("No Drive item ID given")

    base = drivefs_dir()
    mount = mount_point(base)
    problems = []

    for account in account_dirs(base):
        try:
            with closing(_read_only(account / "metadata_sqlite_db")) as db:
                items, by_cloud_id, parents, shared_roots = _tree(db)
                stable_id = by_cloud_id.get(item_id)
                if stable_id is None:
                    continue

                my_root = _my_drive_root(db, by_cloud_id)
                via_shortcut = False
                try:
                    relative = _walk_up(stable_id, items, parents, my_root, shared_roots)
                except ResolveError:
                    # A shortcut may be unreachable itself while its target is fine.
                    target = _shortcut_target(db, stable_id)
                    if target is None:
                        raise
                    relative = _walk_up(target, items, parents, my_root, shared_roots)
                    stable_id, via_shortcut = target, True

                _, title, is_folder, _ = items[stable_id]
                return Resolved(
                    path=Path(mount) / relative,
                    relative=relative,
                    name=title,
                    is_folder=is_folder,
                    account_id=account.name,
                    via_shortcut=via_shortcut,
                )
        except ResolveError as exc:
            problems.append(f"{account.name}: {exc}")

    if problems:
        raise ResolveError("; ".join(problems))
    raise ResolveError(
        f"Drive item {item_id} is not in the local metadata for any signed-in account. "
        "It may belong to another account, or Drive may not have synced it yet."
    )
