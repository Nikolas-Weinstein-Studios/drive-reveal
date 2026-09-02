# macOS bring-up

The macOS half of drive-reveal has been verified on a real two-account setup. This is the
checklist to verify it, what each step should print, and what to do when one does not.

Everything here is self-contained — no need to have read anything else in the repo first.

## Why macOS needs its own path at all

The Python helper is nearly platform-generic. Only two things differ: how it reveals a path
(`open -R` instead of `explorer.exe /select,`) and where it looks for the Drive mount
(`~/Library/CloudStorage/GoogleDrive-<email>` instead of a drive letter). Both are already
written.

The real difference is registration. Windows lets you point a URL scheme straight at a
command line in the registry. **macOS routes URL schemes to an application bundle and
delivers the URL as an Apple Event, not as argv** — so a shell script cannot receive it at
all. `install_macos.sh` therefore compiles a small AppleScript applet whose
`on open location` handler shells out to the helper. The installer re-signs the finished
bundle after adding its URL-scheme metadata so Launch Services can safely register it.

## Prerequisites

1. **Drive for desktop** installed, signed in, and running. Check that
   `~/Library/CloudStorage/` contains a `GoogleDrive-<your-email>` directory with
   `My Drive` inside it.
2. **A real `python3`, 3.9 or newer.** macOS does not ship one. `/usr/bin/python3` is a
   stub that opens a Command Line Tools installer prompt instead of running. Get one with
   `brew install python`, or from python.org.

   ```bash
   python3 -c 'import sys; print(sys.version); print(sys.executable)'
   ```

   If that prompts you to install developer tools, you are on the stub. The installer
   detects this and skips it, but it needs some real interpreter to find.
3. **Firefox** (or any browser — the bookmarklet is not Firefox-specific).

## Step 1 — does the metadata resolve at all

```bash
python3 tests/test_live.py
```

Do this before touching the installer. It reads this machine's real Drive metadata,
resolves a sample of every item type, and asserts the resulting paths exist on disk. It
takes about a second. If Drive's schema or mount layout differs on macOS, this fails here
and the installer is moot.

Expect `all checks passed`, and a mount point under `~/Library/CloudStorage/`.

**If the mount point line is wrong or missing** — Drive is not running, or it mounts
somewhere unexpected on this machine. Find the real location and confirm the resolver can
use it:

```bash
ls ~/Library/CloudStorage/
DRIVE_REVEAL_MOUNT="$HOME/Library/CloudStorage/GoogleDrive-you@example.com" \
  python3 tests/test_live.py
```

If the override makes it pass, mount discovery needs a case added for this machine's
layout — that is in `mount_points()` in `helper/drive_reveal/drivefs.py`.

**If it fails to find the DriveFS data directory** — it looks in
`~/Library/Application Support/Google/DriveFS`. Confirm that exists. `DRIVE_REVEAL_DRIVEFS_DIR`
overrides it.

**If path walking fails but the database is found** — Drive changed its schema. The tests
are non-hermetic precisely so this surfaces as a failure rather than passing silently.
Capture the output; the tables involved are `items`, `stable_parents`, `shortcut_details`
and `properties`.

## Step 2 — helper on its own, no protocol involved

```bash
python3 helper/drive-reveal.py 'https://drive.google.com/drive/my-drive' --print
python3 helper/drive-reveal.py '<paste any Drive folder URL>' --json
python3 helper/drive-reveal.py '<paste any Drive folder URL>'
```

The first prints a path. The second prints full detail including whether it exists on disk.
The third should open a Finder window.

If `--print` works but the third does nothing, the problem is `open -R` in
`helper/drive_reveal/reveal.py`, not resolution — a much smaller thing to fix.

## Step 3 — install the protocol handler

```bash
./install/install_macos.sh
./install/install_macos.sh --verify
```

`--verify` should report the app installed, `gdrivereveal` declared in `Info.plist`, the
baked python and helper paths still valid, and a working smoke test.

The install itself fails loudly if it cannot declare the URL scheme, rather than leaving a
bundle that looks installed and never fires.

## Step 4 — the live round trip

```bash
./install/install_macos.sh --test
```

This dispatches `gdrivereveal://` through Launch Services exactly as the browser will. **A
Finder window should open on My Drive.**

**If nothing opens**, the applet is not receiving the Apple Event. Diagnose in this order:

1. Confirm the scheme is registered to this bundle:
   ```bash
   /usr/libexec/PlistBuddy -c 'Print :CFBundleURLTypes' \
     ~/Applications/DriveReveal.app/Contents/Info.plist
   ```
2. Check whether the applet ran and failed, versus never launched at all — open
   Console.app and filter for `DriveReveal` while re-running `--test`.
3. Run the applet directly. It should show an informational alert, which proves the bundle
   itself is sound and isolates the problem to event delivery:
   ```bash
   open ~/Applications/DriveReveal.app
   ```
4. Force a Launch Services re-scan, which is occasionally all it needs:
   ```bash
   /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
     -f ~/Applications/DriveReveal.app
   ```

### If an alert says "Failed to import encodings module"

```
Fatal Python error: Failed to import encodings module
ModuleNotFoundError: No module named 'encodings'
```

The applet reached python; python could not find its own standard library. That is
`PYTHONHOME` pointing somewhere else, and it is inherited rather than yours: the applet
inherits the browser's environment, and the browser inherits the environment of whatever
launched it. Apps that ship their own interpreter export it — **FreeCAD** sets
`PYTHONHOME=/Applications/FreeCAD.app/Contents/Resources`, and a browser opened from
FreeCAD's help menu carries that into every URL handler it launches. Confirm it on the
running browser:

```bash
ps -E -p "$(pgrep -x firefox | head -1)" -ww -o command= | tr ' ' '\n' | grep '^PYTHON'
```

Installers from 2026-09-02 onwards build the applet so it scrubs the environment
(`env -i`) and runs python with `-E`, so nothing inherited can reach it. Re-run
`./install/install_macos.sh`; `--verify` reports `Applet: runs python in a scrubbed
environment` once the bundle has the fix. Quitting and reopening the browser from the Dock
also clears it, but only until the next time it is opened from another app.

### If the applet approach is a dead end

Ranked fallbacks, none of which change the helper or the browser side:

1. **A tiny Swift app** in place of the AppleScript applet, implementing
   `application(_:open:)`. Needs Xcode Command Line Tools for `swiftc`; more code, but the
   most reliable way to handle a URL scheme on current macOS.
2. **An Automator "Application"** with a Run Shell Script action, plus the same
   `CFBundleURLTypes` patch. Roughly the same shape as the applet, so if the applet failed
   on event delivery this may fail the same way — cheap to try, though.
3. **Skip the protocol entirely** and drive it from a hotkey instead: a Shortcuts or
   Keyboard Maestro action that reads Firefox's frontmost tab URL via AppleScript and pipes
   it to `helper/drive-reveal.py`. Loses the in-page button, keeps the functionality, and
   needs no bundle at all.

A local HTTP server is *not* on this list, and it is the obvious idea: the bookmarklet
would `fetch('http://127.0.0.1:PORT/...')` and no registration would be needed on either
platform. It does not work, because Drive sends a strict Content-Security-Policy and
`connect-src` blocks the request. Firefox exempts bookmarklet *script execution* from CSP,
not the network requests that script then makes.

## Step 5 — browser side

Identical to Windows; nothing here is OS-specific.

Open `bookmarklet/install.html` and drag the button to the bookmarks bar. On the first
click Firefox asks which application to use — pick DriveReveal and tick **Remember my
choice**.

For the toolbar button and `Alt+Shift+R` instead, load `extension/manifest.json` via
`about:debugging` → This Firefox → Load Temporary Add-on. That version disappears on
restart; making it permanent needs a free unlisted signing round-trip at
addons.mozilla.org.

## Known gotcha after it works

The applet has absolute paths to python and to this checkout baked in at install time. Move
the checkout, or upgrade python, and it breaks. `--verify` compares against a stamp
recorded inside the bundle and tells you to re-run rather than failing mysteriously.

The other one is environmental rather than structural, and it bites long after a clean
install: a browser launched from an app that exports `PYTHONHOME` passes it down to the
applet. See ["Failed to import encodings module"](#if-an-alert-says-failed-to-import-encodings-module)
above.

## What to report back

If something fails, the useful payload is:

```bash
sw_vers
python3 -c 'import sys; print(sys.executable, sys.version)'
ls ~/Library/CloudStorage/
python3 tests/test_live.py 2>&1 | tail -30
./install/install_macos.sh --verify 2>&1
```
