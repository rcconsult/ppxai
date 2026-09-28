"""Atomic file replacement with Windows retry semantics.

Extracted from ppxai.engine.tools.builtin.editor during the v1.18.0
stabilization pass (Phase 5g). The previous location (`_atomic_replace`
private helper in editor.py) was the only production caller, but tests
were importing it directly — violating the "go via interfaces" rule.

Keeping it as a single-function module with a documented contract
turns "this I/O primitive that editor.py happens to own" into an
explicit utility boundary. Future callers (session persistence,
checkpoint writes) can depend on the public contract without
reaching into the editor module.

Contract (see `atomic_replace` docstring): best-effort rename of a
prepared temp file onto a target path, with bounded retry for the
Windows file-lock race. Caller-supplied paths; no writes, no
encoding, no content sniffing. Cleanup of the orphaned temp file
is part of the contract on terminal failure — callers don't need
to wrap with their own try/finally for the happy or sad path.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Tuned for the common Windows antivirus / indexer / preview-server
# file-lock scenarios. 3 attempts with 100ms + 200ms backoffs covers
# the sub-second scans seen in practice; anything longer is a real
# lock we should surface to the user rather than hide with a retry.
_DEFAULT_MAX_RETRIES = 3


def atomic_replace(
    temp_path: Path,
    target_path: Path,
    max_retries: int = _DEFAULT_MAX_RETRIES,
) -> None:
    """Atomically replace `target_path` with `temp_path`.

    On POSIX this is a single `os.replace()` call — atomic by contract.
    On Windows `os.replace()` fails with `PermissionError` ([WinError
    5] Access is denied) when the target has an open handle, which
    happens routinely with antivirus scanners, file watchers, and
    preview servers. This helper retries with short backoff (100ms,
    200ms) up to `max_retries` attempts.

    On terminal failure, the orphaned temp file is unlinked before
    re-raising so the caller's directory doesn't accumulate detritus.

    Args:
        temp_path: Existing temp file containing the new content.
                   Should live on the same filesystem as `target_path`
                   so the rename is atomic rather than copy-then-delete.
        target_path: Path to replace. May or may not exist; POSIX
                   `os.replace` handles both cases.
        max_retries: Maximum attempts (default 3). Only has effect on
                   Windows — POSIX succeeds on the first call or
                   fails for a permission reason unrelated to locking.

    Raises:
        PermissionError: Windows lock contention persisted beyond
                         `max_retries`. The temp file has been
                         unlinked before this raises.
        OSError: Any other I/O failure (cross-filesystem rename,
                 target is a read-only directory, etc.). Temp file
                 cleanup is attempted but may itself fail silently
                 if the path has become inaccessible.
    """
    for attempt in range(max_retries):
        try:
            temp_path.replace(target_path)
            return
        except PermissionError:
            # Only Windows file-lock races are worth retrying; on
            # POSIX a PermissionError means the caller doesn't own
            # the destination, and more attempts won't change that.
            if sys.platform == "win32" and attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))  # 100ms, 200ms
                continue
            # Exhausted or non-Windows — clean up before re-raising so
            # the caller's directory doesn't accumulate .tmp carcasses.
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise


def write_json_atomic(
    target_path: Path | str,
    data: Any,
    *,
    indent: int | None = 2,
    ensure_ascii: bool = True,
    trailing_newline: bool = False,
    encoding: str = "utf-8",
) -> None:
    """Write `data` as JSON to `target_path` so a reader never sees a
    partial file.

    The JSON goes to a temp file in the target's directory, is flushed and
    fsynced, and then replaces the target via `atomic_replace` (so Windows
    lock races are retried). A concurrent reader opens either the old file
    or the new one, never an empty or half-written one. The previous
    `open(path, "w")` + `json.dump` truncated first, so a read that landed
    mid-save saw an empty file ("Expecting value: line 1 column 1").

    - A symlinked target is resolved first, so a config kept in a dotfiles
      repo stays a symlink and the file it points to is what changes.
    - An existing target keeps its permission bits. A new one is created
      owner-only (0600, from `mkstemp`) — stricter than `open(path, "w")`,
      which suits what goes through here (config, sessions, usage). Reading
      the umask to match it would briefly zero the process-wide umask, which
      is not thread-safe.
    - On any failure the temp file is removed and the target is untouched.
    """
    target = Path(os.path.realpath(target_path))
    text = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    if trailing_newline:
        text += "\n"
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, stat.S_IMODE(target.stat().st_mode))
        except FileNotFoundError:
            pass  # a new file keeps mkstemp's owner-only 0600
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    atomic_replace(tmp, target)
