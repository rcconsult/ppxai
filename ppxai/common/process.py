"""Process helpers shared across the engine and the server.

Leaf module: stdlib only, no ppxai imports.
"""

from __future__ import annotations

import ctypes
import os
import sys

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5


def _pid_alive_windows(pid: int) -> bool:
    """Query the process instead of signalling it.

    `os.kill(pid, 0)` is NOT a probe on Windows: signal 0 is
    `signal.CTRL_C_EVENT`, so it sends Ctrl+C to `pid`'s console process
    group. Handed a pid in our own console (the test suite passes
    `os.getpid()`), it interrupts this process and every sibling sharing
    the console -- it killed whole pytest runs silently at ~62%.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # ERROR_ACCESS_DENIED: the process exists but belongs to someone else.
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def pid_alive(pid: int) -> bool:
    """True if a process with this pid exists (any owner)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by another user — treat as alive.
        return True
    except OSError:
        return False
