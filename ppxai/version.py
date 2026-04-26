"""Version information for ppxai.

This module is intentionally minimal with no dependencies,
so it can be safely imported by the server without triggering
TUI dependencies like prompt_toolkit.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

__version__ = "1.18.2"


def _git_commit_hash() -> Optional[str]:
    """Return the short git commit hash if running from a git checkout.

    Returns None if not in a repo, git unavailable, or any subprocess
    failure. Used by the startup banner to make it obvious which code
    state is actually running — particularly important after editable
    installs where a stale Python process can outlive its source.
    """
    try:
        repo_root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _source_mtime() -> Optional[str]:
    """Return the most recent mtime across the engine + clients dirs.

    Catches the "edited source but stale Python process" gap: if you
    edit ppxai/rich/main.py at 20:54, restart at 21:07, and check the
    log banner, the banner shows source_mtime=20:54 confirming the
    process is running the post-edit code.
    """
    try:
        repo_root = Path(__file__).resolve().parent
        # Sample the high-traffic source files. Cheaper than scanning
        # the whole tree on every startup.
        candidates = [
            repo_root / "engine" / "session.py",
            repo_root / "engine" / "chat.py",
            repo_root / "rich" / "main.py",
            repo_root / "tui" / "stream_handler.py",
        ]
        mtimes = [c.stat().st_mtime for c in candidates if c.is_file()]
        if not mtimes:
            return None
        latest = max(mtimes)
        return datetime.fromtimestamp(latest).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError):
        return None


def get_runtime_version_info() -> Dict[str, str]:
    """Build a runtime-version snapshot for startup banners and log headers.

    Keys (all values are strings so the dict round-trips through
    string-only formatters cleanly):
      - version: __version__ (e.g. "1.18.1")
      - commit:  short git hash (e.g. "f73627a2") or "n/a"
      - source_mtime: latest source mtime (YYYY-MM-DD HH:MM:SS) or "n/a"
      - python:  Python version (e.g. "3.11.11")
      - platform: OS + arch (e.g. "darwin-x86_64")
    """
    return {
        "version": __version__,
        "commit": _git_commit_hash() or "n/a",
        "source_mtime": _source_mtime() or "n/a",
        "python": ".".join(str(x) for x in sys.version_info[:3]),
        "platform": f"{platform.system().lower()}-{platform.machine()}",
    }


def format_version_banner() -> str:
    """One-line, human-readable version banner.

    Used by Rich TUI startup print and Logger banner so users and
    log readers can instantly correlate behavior with the running
    code state.
    """
    info = get_runtime_version_info()
    return (
        f"ppxai v{info['version']} "
        f"(commit {info['commit']}, source {info['source_mtime']}, "
        f"python {info['python']}, {info['platform']})"
    )
