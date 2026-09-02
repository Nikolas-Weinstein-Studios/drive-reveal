#!/usr/bin/env bash
#
# Register the gdrivereveal:// protocol handler on macOS for the current user.
#
# macOS routes custom URL schemes to an application bundle, not to a command line, and
# delivers the URL as an Apple Event rather than as argv. So this builds a tiny AppleScript
# applet whose `on open location` handler shells out to the Python helper. osacompile is
# part of the base system; no Xcode or developer account is involved.
#
# The absolute paths to python and to the helper are baked into the applet at install
# time. That makes the bundle a machine-local artifact, which is why it lives in
# ~/Applications and never in the repo -- and why moving the checkout means re-running
# this script. `--verify` detects that case.
#
# Usage:
#   ./install/install_macos.sh              install
#   ./install/install_macos.sh --verify     report what is registered, change nothing
#   ./install/install_macos.sh --test       live round trip through the URL scheme
#   ./install/install_macos.sh --uninstall  remove it

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="$REPO_ROOT/helper/drive-reveal.py"
APP_DIR="$HOME/Applications"
APP="$APP_DIR/DriveReveal.app"
STAMP="$APP/Contents/Resources/install-stamp"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"

die() { printf 'error: %s\n' "$1" >&2; exit 1; }

find_python() {
    # Order matters. /usr/bin/python3 is last because on a Mac that has never installed
    # the Command Line Tools it is a stub: running it pops a GUI installer prompt rather
    # than executing anything. Each candidate is actually run before being accepted, so a
    # stub or a broken install is skipped instead of being baked into the bundle.
    local candidate
    for candidate in \
        "$(command -v python3 2>/dev/null || true)" \
        /opt/homebrew/bin/python3 \
        /usr/local/bin/python3 \
        "$HOME/.pyenv/shims/python3" \
        /usr/bin/python3
    do
        [ -n "$candidate" ] || continue
        [ -x "$candidate" ] || continue
        # -S skips site customisation, so this stays a cheap "does it run" probe. -E
        # ignores PYTHON* variables, so a terminal that exports PYTHONHOME (an app like
        # FreeCAD leaves one behind) cannot make every candidate look broken.
        if "$candidate" -E -S -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
            >/dev/null 2>&1; then
            printf '%s' "$candidate"
            return 0
        fi
    done
    return 1
}

report_env() {
    echo "Repo:   $REPO_ROOT"
    echo "Helper: $HELPER $([ -f "$HELPER" ] && echo '(found)' || echo '(MISSING)')"
    echo "App:    $APP $([ -d "$APP" ] && echo '(installed)' || echo '(not installed)')"
}

check_stamp() {
    # The stamp records what was baked into the applet, so a moved checkout or an
    # upgraded python shows up as a specific, fixable complaint.
    [ -f "$STAMP" ] || { echo 'Stamp: missing (installed by an older version?)'; return 1; }
    local stamped_python stamped_helper rc=0
    stamped_python="$(sed -n 's/^python=//p' "$STAMP")"
    stamped_helper="$(sed -n 's/^helper=//p' "$STAMP")"
    echo "Baked python: $stamped_python"
    echo "Baked helper: $stamped_helper"
    if [ ! -x "$stamped_python" ]; then
        echo '  -> that python no longer exists; re-run this script' >&2
        rc=1
    fi
    if [ "$stamped_helper" != "$HELPER" ]; then
        echo "  -> the checkout moved (now $HELPER); re-run this script" >&2
        rc=1
    elif [ ! -f "$stamped_helper" ]; then
        echo '  -> that helper no longer exists; re-run this script' >&2
        rc=1
    fi
    return $rc
}

check_scheme() {
    local plist="$APP/Contents/Info.plist"
    [ -f "$plist" ] || { echo 'Info.plist: missing'; return 1; }
    if /usr/libexec/PlistBuddy -c 'Print :CFBundleURLTypes:0:CFBundleURLSchemes:0' "$plist" \
        2>/dev/null | grep -qx 'gdrivereveal'; then
        echo 'URL scheme: gdrivereveal declared in Info.plist'
        return 0
    fi
    echo 'URL scheme: NOT declared in Info.plist' >&2
    return 1
}

check_signature() {
    if codesign --verify --deep --strict "$APP" >/dev/null 2>&1; then
        echo 'Code signature: valid'
        return 0
    fi
    echo 'Code signature: INVALID; re-run this script' >&2
    return 1
}

check_applet() {
    # A bundle built before the environment fix invokes python directly, so it still dies
    # on a browser launched from a PYTHONHOME-exporting app. That is invisible from the
    # outside -- the scheme, stamp and signature all look right -- so read the script back.
    local scpt="$APP/Contents/Resources/Scripts/main.scpt"
    [ -f "$scpt" ] || { echo 'Applet script: missing' >&2; return 1; }
    if osadecompile "$scpt" 2>/dev/null | grep -q -- '/usr/bin/env -i'; then
        echo 'Applet: runs python in a scrubbed environment'
        return 0
    fi
    echo 'Applet: built before the PYTHONHOME fix; re-run this script' >&2
    return 1
}

check_registration() {
    [ -x "$LSREGISTER" ] || {
        echo 'Launch Services: lsregister not found' >&2
        return 1
    }
    # Consume the complete dump: with pipefail enabled, an early-exiting filter would
    # SIGPIPE lsregister and turn a successful lookup into a false failure. Require the
    # scheme claim inside this app's own record, not merely a stale mention of its path.
    if "$LSREGISTER" -dump 2>/dev/null | awk -v app="$APP" '
        /^path:/ { in_app = index($0, app) > 0 }
        in_app && /^claimed schemes:/ && /gdrivereveal:/ { found = 1 }
        END { exit(found ? 0 : 1) }
    '; then
        echo 'Launch Services: gdrivereveal is registered to this app'
        return 0
    fi
    echo 'Launch Services: gdrivereveal is NOT registered to this app; re-run this script' >&2
    return 1
}

smoke_test_helper() {
    local python_bin
    python_bin="$(find_python)" || { echo 'Python: NOT FOUND (need 3.9+)' >&2; return 1; }
    echo "Python: $python_bin"
    echo
    echo 'Resolving your My Drive root as a smoke test:'
    if "$python_bin" -E "$HELPER" 'https://drive.google.com/drive/my-drive' --print; then
        echo 'Helper works.'
    else
        echo 'Helper failed.' >&2
        return 1
    fi
}

case "${1:-}" in
--uninstall)
    if [ -d "$APP" ]; then
        [ -x "$LSREGISTER" ] && "$LSREGISTER" -u "$APP" >/dev/null 2>&1 || true
        rm -rf "$APP"
        echo "Removed $APP"
    else
        echo "Nothing to remove; $APP does not exist."
    fi
    exit 0
    ;;
--verify)
    rc=0
    report_env
    echo
    [ -d "$APP" ] && {
        check_scheme || rc=1
        check_stamp || rc=1
        check_applet || rc=1
        check_signature || rc=1
        check_registration || rc=1
    } || rc=1
    echo
    smoke_test_helper || rc=1
    exit $rc
    ;;
--test)
    [ -d "$APP" ] || die "not installed; run this script with no arguments first"
    check_signature >/dev/null || die "invalid app signature; re-run this script"
    check_registration >/dev/null || die "app is not registered; re-run this script"
    echo 'Dispatching gdrivereveal:// through Launch Services, exactly as the browser does.'
    echo 'A Finder window should open on your My Drive.'
    open 'gdrivereveal://reveal?url=https%3A%2F%2Fdrive.google.com%2Fdrive%2Fmy-drive'
    echo
    echo 'If nothing opened, the applet did not receive the URL. Check Console.app for'
    echo 'DriveReveal, and confirm with:  ./install/install_macos.sh --verify'
    exit 0
    ;;
"") ;;
*) die "unknown option: $1" ;;
esac

# ------------------------------------------------------------------------------ install

[ -f "$HELPER" ] || die "helper not found at $HELPER; run this from inside the checkout"
command -v osacompile >/dev/null 2>&1 || die 'osacompile not found; it ships with macOS'
command -v codesign >/dev/null 2>&1 || die 'codesign not found; it ships with macOS'
[ -x /usr/libexec/PlistBuddy ] || die 'PlistBuddy not found; it ships with macOS'
python_bin="$(find_python)" || die 'no working python3 3.9+ found. Install it with `brew install python` or from python.org, then re-run.'

mkdir -p "$APP_DIR"
rm -rf "$APP"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# The applet inherits the environment of whatever launched the browser, and the browser
# hands that on to us. FreeCAD, Blender, Houdini and friends export PYTHONHOME pointing at
# their own bundled interpreter; a Homebrew python started with that set dies at
# "Failed to import encodings module" before it runs a line of the helper. So the command
# is built from a scrubbed environment (env -i, plus the two variables the helper genuinely
# needs) and python is given -E so it ignores any PYTHON* variable that survives.
cat > "$workdir/handler.applescript" <<APPLESCRIPT
on open location this_URL
	try
		do shell script "/usr/bin/env -i HOME=" & quoted form of "$HOME" & " PATH=/usr/bin:/bin:/usr/sbin:/sbin " & quoted form of "$python_bin" & " -E " & quoted form of "$HELPER" & " --gui " & quoted form of this_URL
	on error errorMessage
		display alert "Reveal in Drive folder" message errorMessage as warning
	end try
end open location

on run
	display alert "Reveal in Drive folder" message "This app is launched by gdrivereveal:// links from your browser. There is nothing to open here." as informational
end run
APPLESCRIPT

osacompile -o "$APP" "$workdir/handler.applescript" || die 'osacompile failed'

PLIST="$APP/Contents/Info.plist"

# Each container is created explicitly. PlistBuddy will not reliably conjure the
# intermediate array and dict from a single deep Add, and a half-written CFBundleURLTypes
# means Launch Services silently ignores the scheme.
/usr/libexec/PlistBuddy -c 'Delete :CFBundleURLTypes' "$PLIST" >/dev/null 2>&1 || true
/usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes array' "$PLIST" >/dev/null
/usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes:0 dict' "$PLIST" >/dev/null
/usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes:0:CFBundleURLName string Reveal in Drive folder' "$PLIST" >/dev/null
/usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes:0:CFBundleURLSchemes array' "$PLIST" >/dev/null
/usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string gdrivereveal' "$PLIST" >/dev/null

if /usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$PLIST" >/dev/null 2>&1; then
    /usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier net.nikolas.drivereveal' "$PLIST" >/dev/null
else
    /usr/libexec/PlistBuddy -c 'Add :CFBundleIdentifier string net.nikolas.drivereveal' "$PLIST" >/dev/null
fi

# Keeps the applet out of the Dock while it handles a link. Alerts still display.
/usr/libexec/PlistBuddy -c 'Add :LSUIElement bool true' "$PLIST" >/dev/null 2>&1 \
    || /usr/libexec/PlistBuddy -c 'Set :LSUIElement true' "$PLIST" >/dev/null

# Fail loudly if the scheme did not take, rather than leaving a bundle that looks
# installed and never fires.
/usr/libexec/PlistBuddy -c 'Print :CFBundleURLTypes:0:CFBundleURLSchemes:0' "$PLIST" \
    2>/dev/null | grep -qx 'gdrivereveal' \
    || die "failed to declare the URL scheme in $PLIST"

mkdir -p "$(dirname "$STAMP")"
cat > "$STAMP" <<STAMP
python=$python_bin
helper=$HELPER
repo=$REPO_ROOT
STAMP

# osacompile ad-hoc signs the applet, but the Info.plist and install stamp above are
# deliberately added afterward. Re-sign the finished bundle so Launch Services accepts
# it instead of silently dropping the URL-scheme registration as an invalid app.
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 \
    || die "could not sign $APP"
codesign --verify --deep --strict "$APP" >/dev/null 2>&1 \
    || die "signature verification failed for $APP"

# Force Launch Services to notice the new scheme now rather than at some later login.
[ -x "$LSREGISTER" ] || die 'lsregister not found; cannot register gdrivereveal'
"$LSREGISTER" -f "$APP" >/dev/null 2>&1 \
    || die 'Launch Services rejected DriveReveal.app'
check_registration >/dev/null \
    || die 'DriveReveal.app is still absent from Launch Services after registration'

echo "Installed $APP"
echo "  python: $python_bin"
echo "  helper: $HELPER"
echo
echo 'Next:'
echo '  1. Check it:   ./install/install_macos.sh --verify'
echo '  2. Live test:  ./install/install_macos.sh --test'
echo '  3. Browser:    drag the bookmarklet from bookmarklet/install.html, or load'
echo '                 extension/ in Firefox via about:debugging.'
echo '  4. On the first click Firefox asks which application to use. Pick DriveReveal'
echo '     and tick "Remember my choice".'
