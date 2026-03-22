"""
PTY I/O for ppxai-native — spawn ppxai Rich TUI in a pseudo-terminal.

macOS/Linux only. Windows does not support pty.fork().
"""

import fcntl
import os
import pty
import signal
import struct
import sys
import termios
from typing import Tuple


def spawn_ppxai(cols: int, rows: int) -> Tuple[int, int]:
    """Fork a PTY and exec ppxai Rich TUI in the child process.

    Returns (child_pid, master_fd).
    The child runs ppxai.rich.main:main() via `python -m ppxai.rich.main`.
    """
    pid, master_fd = pty.fork()

    if pid == 0:
        # Child process — exec ppxai Rich TUI
        # Set TERM so Rich knows it can use colors/unicode
        os.environ["TERM"] = "xterm-256color"
        os.environ["COLORTERM"] = "truecolor"
        # Tell ppxai it's running inside ppxai-native (for future use)
        os.environ["PPXAI_NATIVE"] = "1"
        os.execve(
            sys.executable,
            [sys.executable, "-m", "ppxai.rich.main"],
            os.environ,
        )
        # execve never returns on success; if it does, exit
        os._exit(1)

    # Parent process — configure master_fd
    # Set non-blocking I/O
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    # Set terminal size
    pty_resize(master_fd, cols, rows)

    return pid, master_fd


def pty_read(master_fd: int) -> bytes:
    """Non-blocking read all available data from PTY master.

    Returns empty bytes if nothing available or on error.
    """
    chunks = []
    while True:
        try:
            chunk = os.read(master_fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        except BlockingIOError:
            break
        except OSError:
            break
    return b"".join(chunks)


def pty_write(master_fd: int, data: bytes) -> None:
    """Write data to PTY master (sends to child's stdin)."""
    if not data:
        return
    try:
        os.write(master_fd, data)
    except OSError:
        pass


def pty_resize(master_fd: int, cols: int, rows: int) -> None:
    """Update PTY window size. Sends SIGWINCH to child process group."""
    try:
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
    except OSError:
        pass


def is_child_alive(pid: int) -> bool:
    """Check if child process is still running (non-blocking waitpid)."""
    try:
        result, status = os.waitpid(pid, os.WNOHANG)
        return result == 0  # 0 means still running
    except ChildProcessError:
        return False


def kill_child(pid: int) -> None:
    """Send SIGTERM to child process."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def close_master(master_fd: int) -> None:
    """Close the PTY master file descriptor."""
    try:
        os.close(master_fd)
    except OSError:
        pass
