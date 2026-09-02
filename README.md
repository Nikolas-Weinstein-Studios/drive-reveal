# drive-reveal

Google Drive has a "Manage in Google Drive web" button that goes from Drive for desktop
out to the browser. This is the missing direction: from a Drive web page to the same
folder in Explorer or Finder.

Click a bookmark (or press `Alt+Shift+R`) while looking at a folder in Drive, and a file
manager window opens on `G:\Shared drives\WORK\2. PROJECTS` — or wherever that folder
lives on this machine.

## How it works

Drive for desktop already keeps a full copy of the item tree in a local SQLite database.
Reading that means **no OAuth client, no API quota, no network, and no per-machine
credential setup** — which matters when the same checkout has to work on several
computers.

```
browser (bookmarklet or extension)
   │  extracts the Drive item ID from the page URL, or from the selected row
   ▼
gdrivereveal://reveal?id=<drive item id>
   │  OS protocol handler
   ▼
helper/drive-reveal.py
   │  1. find the mount point       ← DriveFS/root_preference_sqlite.db
   │  2. ID → stable_id → walk parents to a root
   │                                 ← DriveFS/<account>/metadata_sqlite_db
   │  3. join: G:\ + Shared drives\WORK\2. PROJECTS
   ▼
explorer.exe /select,<path>     or     open -R <path>
```

Nothing is written to either database; both are opened read-only.

## Install

Two halves: a local helper (once per machine) and a browser trigger (once per browser
profile).

### 1. Helper

**Windows**

```powershell
.\install\install_windows.ps1
.\install\install_windows.ps1 -Verify      # check it, change nothing
.\install\install_windows.ps1 -Uninstall
```

Writes `HKCU:\Software\Classes\gdrivereveal`. Per-user, so no administrator rights. It
uses `pythonw.exe` so no console window flashes on each click.

**macOS** — never run on a real Mac yet. Follow
**[install/MACOS.md](install/MACOS.md)**, which is a full bring-up checklist with the
expected output at each step and what to do when one fails.

```bash
./install/install_macos.sh
./install/install_macos.sh --verify      # check it, change nothing
./install/install_macos.sh --test        # live round trip through the URL scheme
./install/install_macos.sh --uninstall
```

macOS routes URL schemes to an app bundle rather than a command, and delivers the URL as
an Apple Event rather than as argv — so a plain shell script cannot receive it. This
compiles a small AppleScript applet into `~/Applications/DriveReveal.app` whose
`on open location` handler calls the same Python helper. `osacompile` ships with macOS; no
Xcode, no developer account, and nothing downloaded, so no Gatekeeper prompt.

Two things to know:

- **macOS has no usable `python3` out of the box.** `/usr/bin/python3` is a stub that pops
  a Command Line Tools installer instead of running. The installer probes each candidate
  by executing it and skips the stub, but you still need a real one:
  `brew install python`, or python.org.
- **The applet has absolute paths baked in** at install time, so moving the checkout or
  upgrading Python breaks it. `--verify` compares against a stamp recorded inside the
  bundle and tells you to re-run rather than failing mysteriously.

Both installers derive every path from their own location, so the repo can be cloned
anywhere. Nothing machine-specific is written into the repo.

### 2. Browser

**Bookmarklet** — open `bookmarklet/install.html` and drag the button to the bookmarks
bar. No extension, no signing, and it rides Firefox Sync to every machine along with the
rest of the bookmarks. This is the path that needs the least maintenance.

**Extension** — nicer: a toolbar button, a right-click item, and `Alt+Shift+R`.

- Temporarily: `about:debugging` → This Firefox → Load Temporary Add-on → pick
  `extension/manifest.json`. Gone on restart.
- Permanently, Firefox requires the add-on to be signed, even for private use. Sign it as
  an unlisted add-on at [addons.mozilla.org](https://addons.mozilla.org/developers/) and
  install the `.xpi` it returns. Free, and it stays private.

The extension is Manifest V2, which Firefox supports; it will need porting for Chrome.

### 3. First click

Firefox asks which application should open `gdrivereveal://`. Pick the helper and tick
**Remember my choice**, or it asks every time.

## What it picks

| In the browser | What opens |
| --- | --- |
| Viewing a folder, nothing selected | that folder |
| Exactly one file selected | that file, selected in its parent folder |
| Several files selected | the containing folder |
| A file open in preview, Docs, Sheets, or Slides | that file, selected in its folder |
| `My Drive` or `Shared drives` root | the corresponding top-level folder |

Selected-row detection reads Drive's HTML, which is obfuscated and changes without
notice. When it breaks, the tool falls back to the folder in the address bar rather than
guessing — so the worst case is less precision, never a wrong folder.

## Status

| | Helper | Protocol handler | Bookmarklet | Extension |
| --- | --- | --- | --- | --- |
| **Windows** | verified | verified | verified | loads temporarily; needs signing to persist |
| **macOS** | verified | verified | untested | untested |

The macOS half is now verified on a real Mac (2-account Drive setup): `tests/test_live.py`
resolves real items to real paths, `install_macos.sh` installs cleanly, and the AppleScript
applet correctly receives the `gdrivereveal://` Apple Event and opens Finder —
`install_macos.sh --test` opened a live Finder window end to end. `test_live.py` also had a
real bug surfaced by having two signed-in accounts: `test_multiple_mounts` assumed the
primary Drive mount always holds the sampled item, which isn't true once a second account's
mount can come first; fixed to find the mount that actually holds the item instead of
assuming index 0. The bookmarklet/extension browser side is unexercised — same code path as
Windows, just not yet clicked through in a Mac browser.

To bring up a Mac, in order:

```bash
python3 tests/test_live.py          # does the metadata resolve at all on this machine
./install/install_macos.sh
./install/install_macos.sh --verify
./install/install_macos.sh --test   # a Finder window should open on My Drive
```

`test_live.py` first: if Drive's schema or mount layout differs on macOS, that fails in
about a second and there is no point continuing to the installer.

**[install/MACOS.md](install/MACOS.md)** covers each of those steps in full — prerequisites,
expected output, how to diagnose a failure at each stage, and ranked fallbacks if the
AppleScript applet turns out to be a dead end.

## Limits

- **Shared with me** items have no local path at all until you add a shortcut to My
  Drive. The helper says so instead of inventing one.
- **Hidden or inaccessible shared drives** can remain in Drive for desktop's cached
  metadata after their Finder directory disappears. The helper reports that state and
  tells you to unhide the drive or reconnect the affected account instead of silently
  opening an empty `Shared drives` folder.
- **Not downloaded yet**: with selective sync an item can be in the metadata but absent
  from disk. The helper opens the nearest parent that does exist and notes it on stderr.
- **Multiple accounts** are handled by searching every signed-in account's metadata. The
  `/u/0/` index in Drive URLs is per-browser-profile ordering and does not map onto Drive
  for desktop's accounts, so it is ignored. Each account gets its own mount — a second
  drive letter on Windows, a second `~/Library/CloudStorage/GoogleDrive-<email>` on macOS —
  and the resolver picks the matching one. On macOS, the File Provider domain metadata
  maps each mount to DriveFS's account ID exactly; elsewhere, the resolver uses the mount
  that actually contains the path it built and refuses ambiguous shared-drive names.
  One exception: a bare `My Drive` or `Shared drives` root URL is genuinely ambiguous
  across accounts and resolves to the primary mount.
- **Trashed items** still resolve, to the path they had before being trashed. That path
  will not exist, so you get the parent folder.
- **The schema is undocumented.** A Drive for desktop update could change it. That is what
  `tests/test_live.py` is for — see below.

## Tests

```bash
python tests/test_live.py     # resolver, against this machine's real Drive metadata
node   tests/test_browser.mjs # browser-side target selection, with a stub DOM
```

`test_live.py` is deliberately not hermetic. It pulls real item IDs out of the local
database — folders, files, native Docs, shortcuts, shared drive roots, shared-with-me
orphans — resolves each one, and asserts the resulting path exists on disk. A fixture
would keep passing after Drive changed its schema; this fails, which is the point.

Run it first if anything stops working.

## Per-machine setup

Nothing here travels in the repo, so each machine needs:

1. Python 3.9+ on `PATH` (3.12+ preferred: `os.listdrives()` makes mount discovery faster).
   On macOS this means installing one — `/usr/bin/python3` is a stub, see
   [install/MACOS.md](install/MACOS.md).
2. Drive for desktop installed and signed in.
3. The helper installer run once (above).
4. The bookmarklet, or a signed `.xpi`, in that browser profile.

Verify with `-Verify` / `--verify`, which prints the resolved mount point and smoke-tests
the helper.

Bringing up a Mac for the first time: **[install/MACOS.md](install/MACOS.md)**.

## Layout

```
helper/
  drive-reveal.py          entry point; the protocol handler points here
  drive_reveal/
    drivefs.py             mount discovery, ID → local path
    ids.py                 Drive URL and gdrivereveal:// parsing
    reveal.py              explorer.exe / open -R
    cli.py                 argument handling, exit codes, error dialog
extension/                 Firefox MV2 add-on
bookmarklet/
  bookmarklet.js           readable source
  build.py                 regenerates install.html from it
  install.html             drag-to-install page
install/                   protocol handler registration, per platform
tests/
```

## Using the helper directly

It is a normal CLI, which is also the fastest way to debug it:

```bash
python helper/drive-reveal.py <url-or-id> --print   # print the path, open nothing
python helper/drive-reveal.py <url-or-id> --json    # full detail
python helper/drive-reveal.py <url-or-id> --select  # select in parent, don't open
python helper/drive-reveal.py <url-or-id>           # reveal it
```

Exit codes: `0` fine, `2` could not resolve, `1` resolved but the file manager failed.

`--gui` adds a dialog box on failure. The protocol handler passes it because it runs with
no console for the message to land in; it is off by default so an automated run can never
block on a modal.

Overrides, for testing against a copied profile:

- `DRIVE_REVEAL_DRIVEFS_DIR` — where to find the DriveFS data directory
- `DRIVE_REVEAL_MOUNT` — the Drive mount point
