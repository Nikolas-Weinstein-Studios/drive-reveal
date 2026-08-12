"""Extract a Drive item ID from whatever the browser hands over.

The browser side sends either a bare ID or the page URL, and Drive has accumulated a
lot of URL shapes over the years. Parsing them here rather than in JavaScript keeps the
bookmarklet and the extension small and means only one place needs updating.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

# Drive IDs are base64url-ish. Folder/shared-drive IDs start with 0A; file IDs with 1.
# Length varies by vintage (legacy 28, current 33+), so match on charset and a floor.
_ID = r"[A-Za-z0-9_-]{15,}"

_PATTERNS = (
    re.compile(rf"/(?:folders|d)/({_ID})"),          # /drive/folders/X, /file/d/X, /document/d/X
    re.compile(rf"[?&](?:id|ids)=({_ID})"),          # /open?id=X, legacy ?ids=X
    re.compile(rf"/drive/(?:u/\d+/)?search\?.*?({_ID})"),
)

# Sentinel targets that are locations rather than items.
MY_DRIVE = "@my-drive"
SHARED_DRIVES = "@shared-drives"

_LOCATIONS = {
    "my-drive": MY_DRIVE,
    "home": MY_DRIVE,
    "shared-drives": SHARED_DRIVES,
    "priority": MY_DRIVE,
}


class NoIdFound(Exception):
    """Raised when the input contains nothing that looks like a Drive item."""


def extract(payload: str) -> str:
    """Return a Drive item ID, or a MY_DRIVE / SHARED_DRIVES sentinel.

    Accepts a bare ID, a Drive/Docs URL, or a gdrivereveal:// protocol payload.
    """
    if not payload or not payload.strip():
        raise NoIdFound("Nothing to look up")

    payload = payload.strip().strip('"').strip("'")

    # gdrivereveal://reveal?id=X or gdrivereveal://reveal?url=<encoded page url>
    if payload.lower().startswith("gdrivereveal:"):
        payload = _unwrap_protocol(payload)

    # A bare ID with no URL syntax around it.
    if re.fullmatch(_ID, payload):
        return payload

    parsed = urlparse(payload)

    for pattern in _PATTERNS:
        match = pattern.search(payload)
        if match:
            return match.group(1)

    # No item ID: fall back to recognising a Drive location view.
    segments = [s for s in parsed.path.split("/") if s and not re.fullmatch(r"u|\d+", s)]
    for segment in reversed(segments):
        if segment in _LOCATIONS:
            return _LOCATIONS[segment]

    raise NoIdFound(
        f"No Drive item ID found in {payload[:120]!r}. Open the file or folder in Drive "
        "so its ID appears in the address bar."
    )


def _unwrap_protocol(payload: str) -> str:
    """Pull the real target out of a gdrivereveal:// URL."""
    # Normalise gdrivereveal:X and gdrivereveal://X alike.
    rest = payload.split(":", 1)[1].lstrip("/")
    parsed = urlparse("//" + rest, scheme="")
    query = parse_qs(parsed.query)

    for key in ("url", "u", "href"):
        if query.get(key):
            return unquote(query[key][0])
    for key in ("id", "item"):
        if query.get(key):
            return unquote(query[key][0])

    # gdrivereveal://<id> with no query string.
    return unquote((parsed.netloc + parsed.path).strip("/"))
