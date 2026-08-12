"""Regenerate install.html from bookmarklet.js.

Crude but dependency-free: strips comments and collapses whitespace, which is all a
70-line script needs. Keeps the readable source and the draggable link from drifting
apart.

Run: python bookmarklet/build.py
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
MARKER_START = "<!-- BOOKMARKLET:START -->"
MARKER_END = "<!-- BOOKMARKLET:END -->"


def minify(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    source = re.sub(r"(?m)^\s*//.*$", "", source)
    source = re.sub(r"\s*\n\s*", " ", source)
    source = re.sub(r"\s{2,}", " ", source)
    source = re.sub(r"\s*([{};:,()=<>+!&|\[\]])\s*", r"\1", source)
    return source.strip()


def main() -> None:
    minified = minify((HERE / "bookmarklet.js").read_text(encoding="utf-8"))
    # quote() rather than raw text: an unescaped % or # in a href breaks the URL, and
    # html.escape() alone would leave those intact.
    href = "javascript:" + quote(minified, safe="")

    page = (HERE / "install.html").read_text(encoding="utf-8")
    link = (
        f'<a class="bookmarklet" href="{html.escape(href, quote=True)}">'
        "Reveal in Drive folder</a>"
    )
    start, end = page.index(MARKER_START), page.index(MARKER_END)
    page = page[: start + len(MARKER_START)] + "\n      " + link + "\n      " + page[end:]

    (HERE / "install.html").write_text(page, encoding="utf-8")
    print(f"install.html updated ({len(href)} chars in the href)")


if __name__ == "__main__":
    main()
