"""Locate the LibreOffice executable across platforms.

The office-preview pipeline (PPTX→PNG, DOCX→PDF) shells out to LibreOffice
headless. Historically the code looked for the command name ``libreoffice``
only — which works on Linux (the distro package puts ``libreoffice`` on
PATH) but **fails on macOS**, where LibreOffice ships its binary as
``soffice`` inside ``/Applications/LibreOffice.app`` and never adds anything
to PATH. The result: a plain ``brew install --cask libreoffice`` left office
raster preview silently dead, and users had to hand-create a symlink.

This module resolves the executable the way a user expects a simple system
install to "just work":

1. ``PPXAI_LIBREOFFICE`` env override (explicit path — wins over everything).
2. ``libreoffice`` then ``soffice`` on PATH (Linux package / user symlink).
3. Well-known absolute install locations per OS (macOS .app bundle,
   Windows Program Files, common Linux opt paths).

Resolution is intentionally **not cached** — a LibreOffice install made
while the server is running is picked up on the next request, no restart.

Leaf module: stdlib only, no ppxai imports.
"""

import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional

# Executable names to probe on PATH, in preference order. Linux ships
# `libreoffice` (and usually a `soffice` alias); a user symlink may use
# either name.
_PATH_NAMES = ("libreoffice", "soffice")

# Env var for an explicit override (unusual install dirs, portable builds).
_ENV_OVERRIDE = "PPXAI_LIBREOFFICE"


def _well_known_paths() -> List[Path]:
    """Absolute locations LibreOffice installs to but doesn't put on PATH."""
    paths: List[Path] = []
    if sys.platform == "darwin":
        paths += [
            Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
            Path.home() / "Applications/LibreOffice.app/Contents/MacOS/soffice",
        ]
    elif os.name == "nt":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432"):
            base = os.environ.get(env)
            if base:
                paths.append(Path(base) / "LibreOffice" / "program" / "soffice.exe")
    else:  # Linux / other Unix — PATH usually covers it; cover opt installs.
        paths += [
            Path("/usr/bin/soffice"),
            Path("/usr/local/bin/soffice"),
            Path("/opt/libreoffice/program/soffice"),
            Path("/snap/bin/libreoffice"),
        ]
    return paths


def find_libreoffice() -> Optional[str]:
    """Return the absolute path to a runnable LibreOffice executable, or None.

    Order: ``PPXAI_LIBREOFFICE`` env override → ``libreoffice``/``soffice`` on
    PATH → well-known per-OS install locations. Returns a string suitable for
    use as ``argv[0]`` in ``subprocess``.
    """
    override = os.environ.get(_ENV_OVERRIDE)
    if override:
        p = Path(override).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
        # An explicit override that doesn't resolve is a user error worth
        # not silently masking — fall through to auto-detection anyway so a
        # stale env var doesn't break a working install.

    for name in _PATH_NAMES:
        found = shutil.which(name)
        if found:
            return found

    for p in _well_known_paths():
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)

    return None


def libreoffice_available() -> bool:
    """True iff a LibreOffice executable can be located (see find_libreoffice)."""
    return find_libreoffice() is not None
