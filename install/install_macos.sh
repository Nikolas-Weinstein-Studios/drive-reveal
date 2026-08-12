#!/usr/bin/env bash
#
# Register the gdrivereveal:// protocol handler on macOS for the current user.
#
# macOS routes custom URL schemes to an application bundle, not to a command line, and
# delivers the URL as an Apple Event rather than as argv. So this builds a tiny AppleScript
# applet whose `on open location` handler shells out to the Python helper. osacompile is
# part of the base system; no Xcode or developer account is involved.
#
# Usage:
#   ./install/install_macos.sh              install
#   ./install/install_macos.sh --verify     report what is registered
#   ./install/install_macos.sh --uninstall  remove it

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="$REPO_ROOT/helper/drive-reveal.py"
APP_DIR="$HOME/Applications"
APP="$APP_DIR/DriveReveal.app"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"

die() { printf 'error: %s\n' "$1" >&2; exit 1; }

find_python() {
    # Prefer a python3 that is actually on PATH; fall back to the system one. The Command
    # Line Tools stub at /usr/bin/python3 will prompt for an install if never used, so it
    # is the last resort rather than the first.
    for candidate in \
        "$(command -v python3 || true)" \
        /opt/homebrew/bin/python3 \
        /usr/local/bin/python3 \
        /usr/bin/python3
    do
        [ -n "$candidate" ] && [ -x "$candidate" ] && { printf '%s' "$candidate"; return 0; }
    done
    return 1
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
    echo "Repo:   $REPO_ROOT"
    echo "Helper: $HELPER $([ -f "$HELPER" ] && echo '(found)' || echo '(MISSING)')"
    echo "App:    $APP $([ -d "$APP" ] && echo '(installed)' || echo '(not installed)')"
    if python_bin="$(find_python)"; then
        echo "Python: $python_bin"
        echo
        echo "Resolving your My Drive root as a smoke test:"
        "$python_bin" "$HELPER" 'https://drive.google.com/drive/my-drive' --print \
            && echo "Helper works." \
            || echo "Helper failed."
    else
        echo "Python: NOT FOUND"
    fi
    [ -d "$APP" ] || exit 1
    exit 0
    ;;
"") ;;
*) die "unknown option: $1" ;;
esac

# ------------------------------------------------------------------------------ install

[ -f "$HELPER" ] || die "helper not found at $HELPER; run this from inside the checkout"
python_bin="$(find_python)" || die 'no python3 found; install Python 3.9+ and re-run'

mkdir -p "$APP_DIR"
rm -rf "$APP"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# The handler is written with the absolute paths baked in at install time. That is a
# machine-local artifact by design: it lives in ~/Applications, never in the repo.
cat > "$workdir/handler.applescript" <<APPLESCRIPT
on open location this_URL
	try
		do shell script quoted form of "$python_bin" & " " & quoted form of "$HELPER" & " --gui " & quoted form of this_URL
	on error errorMessage
		display alert "Reveal in Drive folder" message errorMessage as warning
	end try
end open location

on run
	display alert "Reveal in Drive folder" message "This app is launched by gdrivereveal:// links from your browser. There is nothing to do here." as informational
end run
APPLESCRIPT

osacompile -o "$APP" "$workdir/handler.applescript" || die 'osacompile failed'

PLIST="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleIdentifier string net.nikolas.drivereveal' "$PLIST" >/dev/null 2>&1 || \
    /usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier net.nikolas.drivereveal' "$PLIST"
/usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes array' "$PLIST" >/dev/null 2>&1 || true
/usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes:0:CFBundleURLName string Reveal in Drive folder' "$PLIST"
/usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes:0:CFBundleURLSchemes array' "$PLIST"
/usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string gdrivereveal' "$PLIST"
# Keeps the applet from appearing in the Dock while it runs.
/usr/libexec/PlistBuddy -c 'Add :LSUIElement bool true' "$PLIST" >/dev/null 2>&1 || true

# Force Launch Services to notice the new scheme now rather than at some later login.
[ -x "$LSREGISTER" ] && "$LSREGISTER" -f "$APP" >/dev/null 2>&1 || true

echo "Installed $APP"
echo "  python: $python_bin"
echo "  helper: $HELPER"
echo
echo 'Next:'
echo '  1. Install the browser side: drag the bookmarklet from bookmarklet/install.html,'
echo '     or load extension/ in Firefox via about:debugging.'
echo '  2. On the first click Firefox will ask which application to use. Pick DriveReveal'
echo '     and tick "Remember my choice".'
echo
echo "Check it with:  ./install/install_macos.sh --verify"
