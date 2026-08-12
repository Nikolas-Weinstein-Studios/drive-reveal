#!/usr/bin/env python3
"""Entry point for the gdrivereveal:// protocol handler and for running by hand.

A standalone script rather than `python -m drive_reveal`, because the OS launches this
with an unpredictable working directory and no PYTHONPATH. The repo location is derived
from this file, so the checkout can live anywhere on any machine.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from drive_reveal.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
