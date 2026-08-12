"""Live checks against this machine's own Drive for desktop metadata.

These are not hermetic: they read the real local Drive database and assert that resolved
paths exist on disk. That is deliberate. The whole tool rests on undocumented Drive
internals, so the test that matters is "does this still produce a real path here", which
is also the fastest way to notice a Drive update changing the schema.

Run: python tests/test_live.py
"""

from __future__ import annotations

import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helper"))

from drive_reveal import ids                                    # noqa: E402
from drive_reveal.cli import main                               # noqa: E402
from drive_reveal.drivefs import (                              # noqa: E402
    ResolveError, _read_only, account_dirs, mount_point, resolve,
)

PASS, FAIL = "  ok  ", " FAIL "
failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"[{PASS if condition else FAIL}] {label}" + (f"  -- {detail}" if detail else ""))
    if not condition:
        failures.append(label)


# ------------------------------------------------------------------ url parsing (pure)

def test_id_extraction() -> None:
    print("\n== URL / payload parsing ==")
    cases = {
        "https://drive.google.com/drive/folders/1du8fpdeGzr3xLByCtz9UD5BDiudWK5bI":
            "1du8fpdeGzr3xLByCtz9UD5BDiudWK5bI",
        "https://drive.google.com/drive/u/0/folders/1du8fpdeGzr3xLByCtz9UD5BDiudWK5bI":
            "1du8fpdeGzr3xLByCtz9UD5BDiudWK5bI",
        "https://drive.google.com/drive/u/2/folders/0APqf2eu_M_LzUk9PVA?resourcekey=0-abc":
            "0APqf2eu_M_LzUk9PVA",
        "https://drive.google.com/file/d/1TKIylHD3-0Dt7gU6szxwSHH4MWzfLq6m/view?usp=sharing":
            "1TKIylHD3-0Dt7gU6szxwSHH4MWzfLq6m",
        "https://docs.google.com/document/d/1KlfSyff-hphr67x1qqPCgqgbiym8SBicarsn6VaZIXQ/edit":
            "1KlfSyff-hphr67x1qqPCgqgbiym8SBicarsn6VaZIXQ",
        "https://docs.google.com/spreadsheets/d/1MSVzjTK5bubSo7_pltKbWausKWoVUYynNdouj4GlIdE/edit#gid=0":
            "1MSVzjTK5bubSo7_pltKbWausKWoVUYynNdouj4GlIdE",
        "https://drive.google.com/open?id=1du8fpdeGzr3xLByCtz9UD5BDiudWK5bI":
            "1du8fpdeGzr3xLByCtz9UD5BDiudWK5bI",
        "1du8fpdeGzr3xLByCtz9UD5BDiudWK5bI": "1du8fpdeGzr3xLByCtz9UD5BDiudWK5bI",
        "gdrivereveal://1du8fpdeGzr3xLByCtz9UD5BDiudWK5bI":
            "1du8fpdeGzr3xLByCtz9UD5BDiudWK5bI",
        "gdrivereveal://reveal?id=1du8fpdeGzr3xLByCtz9UD5BDiudWK5bI":
            "1du8fpdeGzr3xLByCtz9UD5BDiudWK5bI",
        "gdrivereveal://reveal?url=https%3A%2F%2Fdrive.google.com%2Fdrive%2Fu%2F0%2Ffolders%2F"
        "1du8fpdeGzr3xLByCtz9UD5BDiudWK5bI": "1du8fpdeGzr3xLByCtz9UD5BDiudWK5bI",
        "https://drive.google.com/drive/my-drive": ids.MY_DRIVE,
        "https://drive.google.com/drive/u/0/my-drive": ids.MY_DRIVE,
        "https://drive.google.com/drive/u/0/shared-drives": ids.SHARED_DRIVES,
    }
    for payload, expected in cases.items():
        try:
            got = ids.extract(payload)
        except ids.NoIdFound as exc:
            got = f"<error: {exc}>"
        check(f"extract {payload[:64]}", got == expected, f"got {got!r}")

    for bad in ("", "   ", "https://drive.google.com/", "not a url at all"):
        try:
            ids.extract(bad)
            check(f"reject {bad!r}", False, "no exception raised")
        except ids.NoIdFound:
            check(f"reject {bad!r}", True)


# ---------------------------------------------------------------------- live resolving

def test_environment() -> None:
    print("\n== environment discovery ==")
    accounts = account_dirs()
    check("found a signed-in Drive account", bool(accounts), f"{len(accounts)} account(s)")
    mount = mount_point()
    check("mount point is a real Drive mount", mount.is_dir(), str(mount))
    check("mount exposes My Drive or Shared drives",
          any((mount / n).is_dir() for n in ("My Drive", "Shared drives")))


def _sample(sql: str, limit: int = 6) -> list[tuple]:
    with closing(_read_only(account_dirs()[0] / "metadata_sqlite_db")) as db:
        return list(db.execute(sql + f" LIMIT {limit}"))


def test_resolves_real_items() -> None:
    print("\n== resolving real items to real paths ==")

    groups = {
        "My Drive folder": """
            SELECT i.id FROM items i JOIN stable_parents p ON p.item_stable_id = i.stable_id
            WHERE i.team_drive_stable_id IS NULL AND i.trashed=0 AND i.is_tombstone=0
              AND i.is_folder=1""",
        "My Drive file": """
            SELECT i.id FROM items i JOIN stable_parents p ON p.item_stable_id = i.stable_id
            WHERE i.team_drive_stable_id IS NULL AND i.trashed=0 AND i.is_tombstone=0
              AND i.is_folder=0""",
        "shared drive folder": """
            SELECT i.id FROM items i JOIN stable_parents p ON p.item_stable_id = i.stable_id
            WHERE i.team_drive_stable_id IS NOT NULL AND i.trashed=0 AND i.is_tombstone=0
              AND i.is_folder=1""",
        "shared drive file": """
            SELECT i.id FROM items i JOIN stable_parents p ON p.item_stable_id = i.stable_id
            WHERE i.team_drive_stable_id IS NOT NULL AND i.trashed=0 AND i.is_tombstone=0
              AND i.is_folder=0""",
        "google-native doc": """
            SELECT i.id FROM items i JOIN stable_parents p ON p.item_stable_id = i.stable_id
            WHERE i.mime_type LIKE 'application/vnd.google-apps.%'
              AND i.mime_type != 'application/vnd.google-apps.folder'
              AND i.trashed=0 AND i.is_tombstone=0""",
        "shared drive root": """
            SELECT id FROM items WHERE stable_id = team_drive_stable_id""",
        "shortcut": """
            SELECT i.id FROM shortcut_details s JOIN items i ON i.stable_id = s.shortcut_stable_id
            WHERE i.is_tombstone = 0""",
    }

    for label, sql in groups.items():
        rows = _sample(sql)
        if not rows:
            print(f"[ skip ] {label}: none present in this Drive")
            continue
        ok = missing = 0
        first_problem = ""
        for (cloud_id,) in rows:
            try:
                found = resolve(cloud_id)
            except ResolveError as exc:
                first_problem = first_problem or f"{cloud_id}: {exc}"
                missing += 1
                continue
            if found.path.exists():
                ok += 1
            else:
                missing += 1
                first_problem = first_problem or f"{found.path} does not exist on disk"
        check(f"{label} ({ok}/{len(rows)} exist on disk)", missing == 0, first_problem)


def test_orphans_fail_cleanly() -> None:
    print("\n== items with no local location ==")
    # NB: no `stable_id != team_drive_stable_id` here. That comparison is NULL, not true,
    # for every My Drive item, so it would silently match nothing. The IS NULL test
    # already excludes shared drive roots.
    rows = _sample("""
        SELECT id, local_title FROM items
        WHERE stable_id NOT IN (SELECT item_stable_id FROM stable_parents)
          AND is_tombstone = 0 AND team_drive_stable_id IS NULL
          AND stable_id > 200""", limit=4)
    if not rows:
        print("[ skip ] no shared-with-me orphans present")
        return
    for cloud_id, title in rows:
        try:
            found = resolve(cloud_id)
            # An orphan that resolves anyway means it really is reachable; only a
            # non-existent path is a bug.
            check(f"orphan {title!r}", found.path.exists(), f"claimed {found.path}")
        except ResolveError as exc:
            readable = "Shared with me" in str(exc) or "no local location" in str(exc)
            check(f"orphan {title!r} explained clearly", readable, str(exc)[:90])


def test_unknown_id() -> None:
    print("\n== unknown id ==")
    try:
        resolve("1ZZZnotarealdriveidZZZ00000000000")
        check("unknown ID rejected", False, "resolved something")
    except ResolveError as exc:
        check("unknown ID rejected", "not in the local metadata" in str(exc), str(exc)[:80])


def test_cli_contract() -> None:
    print("\n== CLI exit codes and output ==")
    rows = _sample("""
        SELECT i.id FROM items i JOIN stable_parents p ON p.item_stable_id = i.stable_id
        WHERE i.trashed=0 AND i.is_tombstone=0 AND i.is_folder=1""", limit=1)
    good = rows[0][0]

    check("--print on a real folder exits 0", main([good, "--print"]) == 0)
    check("--json on a real folder exits 0", main([good, "--json"]) == 0)
    check("unknown id exits 2", main(["1ZZZnotarealdriveidZZZ00000000000", "--print"]) == 2)
    check("unparseable target exits 2", main(["https://drive.google.com/", "--print"]) == 2)
    check("my-drive sentinel exits 0",
          main(["https://drive.google.com/drive/my-drive", "--print"]) == 0)


if __name__ == "__main__":
    test_id_extraction()
    test_environment()
    test_resolves_real_items()
    test_orphans_fail_cleanly()
    test_unknown_id()
    test_cli_contract()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed:")
        for name in failures:
            print(f"  - {name}")
        sys.exit(1)
    print("all checks passed")
