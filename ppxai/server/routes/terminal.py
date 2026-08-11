"""
WebSocket terminal endpoint — PTY-backed shell in the browser (v1.17.1).

Local mode: spawns a shell via pty.fork()
K8s mode: kubectl exec into pod (future)

NOTE: PTY is Unix-only. On Windows, the router registers but the endpoint
returns an error explaining that the terminal feature requires a Unix host.
"""

import asyncio
import os
import platform
import shutil
import struct
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ...common.logger import get_logger
from ...config import get_shell_config
from ..state import get_or_create_session

logger = get_logger("server")

router = APIRouter()

# Unix-only modules — guarded so the server can still start on Windows
_PTY_AVAILABLE = False
if platform.system() != "Windows":
    try:
        import fcntl
        import pty
        import signal
        import termios

        _PTY_AVAILABLE = True
    except ImportError:
        pass


class PtyProcess:
    """Manages a PTY child process for a terminal session."""

    def __init__(self, shell: str, working_dir: str, login_shell: bool = False):
        self.shell = shell
        self.working_dir = working_dir
        self.login_shell = login_shell
        self.child_pid = None
        self.fd = None

    def spawn(self) -> None:
        """Fork and exec the shell with a PTY.

        The shell is launched **interactive** (`-i`) so readline is active —
        command history (up/down), line editing (Ctrl-A/E, word motion),
        tab-completion and a prompt all depend on the shell running in
        interactive mode, which a bare `execvpe([shell])` on a PTY does NOT
        reliably enable (bash only auto-goes-interactive when *both* stdin and
        stderr are TTYs AND no non-option args force otherwise; being explicit
        removes the ambiguity, and dash/sh never edit lines without it). It is
        also launched **login** (`-l`) by default so the user's profile
        (`.bash_profile`/`.profile` → PATH, aliases) is sourced — a browser
        terminal is a full session, not a subshell. See _resolve_shell for why
        we prefer bash over the /bin/sh→dash fallback (dash has no history and
        no line editing regardless of flags).
        """
        child_pid, fd = pty.fork()
        if child_pid == 0:
            # Child process — exec the shell
            os.chdir(self.working_dir)
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            # Make readline behave even when no rc file exists (fresh container
            # HOME with no .bashrc): a writable HISTFILE so history persists
            # across reconnects, and SHELL set so subshells/tools agree on it.
            env.setdefault("SHELL", self.shell)
            if not env.get("HISTFILE"):
                env["HISTFILE"] = os.path.join(
                    env.get("HOME", self.working_dir), ".bash_history"
                )
            env.setdefault("HISTSIZE", "10000")
            env.setdefault("HISTFILESIZE", "20000")
            args = [self.shell]
            if self.login_shell:
                args.append("-l")
            # Interactive — the flag that turns on history + line editing.
            args.append("-i")
            os.execvpe(self.shell, args, env)
        else:
            # Parent process
            self.child_pid = child_pid
            self.fd = fd
            # Set non-blocking for async reads
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def resize(self, cols: int, rows: int) -> None:
        """Resize the PTY."""
        if self.fd is not None:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)

    def write(self, data: bytes) -> None:
        """Write input to the PTY."""
        if self.fd is not None:
            os.write(self.fd, data)

    def read(self, size: int = 4096) -> bytes:
        """Read output from the PTY (non-blocking)."""
        if self.fd is None:
            return b""
        try:
            return os.read(self.fd, size)
        except (OSError, IOError):
            return b""

    def is_alive(self) -> bool:
        """Check if child process is still running."""
        if self.child_pid is None:
            return False
        try:
            pid, status = os.waitpid(self.child_pid, os.WNOHANG)
            return pid == 0
        except ChildProcessError:
            return False

    def kill(self) -> None:
        """Kill the child process and reap it with a bounded wait.

        Interactive shells ignore SIGTERM (POSIX job control), so SIGTERM +
        a blocking ``waitpid(pid, 0)`` can hang forever once the shell has
        finished initializing. SIGHUP is what a closing terminal sends and
        interactive shells DO exit on it; SIGKILL is the backstop after a
        short WNOHANG grace loop.
        """
        if self.child_pid is not None:
            try:
                os.kill(self.child_pid, signal.SIGHUP)
                os.kill(self.child_pid, signal.SIGTERM)
                reaped = False
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    pid, _ = os.waitpid(self.child_pid, os.WNOHANG)
                    if pid != 0:
                        reaped = True
                        break
                    time.sleep(0.05)
                if not reaped:
                    os.kill(self.child_pid, signal.SIGKILL)
                    os.waitpid(self.child_pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
            self.child_pid = None
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None


def _resolve_terminal_shell(configured: "str | None") -> str:
    """Pick the shell binary for the browser terminal.

    Order: explicit config (`tools.shell.shell_bin`) → `$SHELL` → **bash** if
    on PATH → `/bin/sh`. The bash preference matters: the previous fallback was
    `os.environ.get("SHELL", "/bin/sh")`, and in a fresh container `$SHELL` is
    usually empty, so it landed on `/bin/sh` — which on Debian/Ubuntu is
    **dash**. dash has NO command history and NO readline line-editing, so the
    browser terminal felt broken (no up-arrow recall, no Ctrl-A/E, no
    tab-complete) even though the PTY itself worked. bash gives all of those.
    An explicit config value or a real `$SHELL` always wins, so this only
    changes the unconfigured fallback.
    """
    if configured:
        return configured
    env_shell = os.environ.get("SHELL")
    if env_shell:
        return env_shell
    bash = shutil.which("bash")
    if bash:
        return bash
    return "/bin/sh"


@router.websocket("/ws/terminal")
async def websocket_terminal(websocket: WebSocket):
    """WebSocket endpoint for interactive terminal.

    Protocol (JSON messages):
        Client → Server:
            {"type": "input", "data": "..."}     — keyboard input
            {"type": "resize", "cols": N, "rows": N} — terminal resize
        Server → Client:
            {"type": "output", "data": "..."}     — terminal output
            {"type": "exit", "code": N}           — shell exited
    """
    await websocket.accept()

    if not _PTY_AVAILABLE:
        await websocket.send_json({
            "type": "error",
            "data": "Terminal requires a Unix host (PTY not available on Windows).",
        })
        await websocket.close()
        return

    # Resolve session from query params
    session_id = websocket.query_params.get("session")
    try:
        _, engine, _ = await get_or_create_session(session_id)
    except Exception as e:
        await websocket.send_json({"type": "error", "data": str(e)})
        await websocket.close()
        return

    # Get shell config
    shell_config = get_shell_config()
    shell_bin = _resolve_terminal_shell(shell_config.get("shell_bin"))
    # A browser terminal is a full interactive session: default to a login
    # shell so the user's profile/PATH loads. Config can force it off.
    login_shell = shell_config.get("login_shell")
    if login_shell is None:
        login_shell = True
    working_dir = engine.get_working_dir() or os.getcwd()

    logger.info(f"Terminal: opening {shell_bin} in {working_dir} (session={session_id})")

    # Spawn PTY
    proc = PtyProcess(shell_bin, working_dir, login_shell)
    try:
        proc.spawn()
    except Exception as e:
        await websocket.send_json({"type": "error", "data": f"Failed to spawn shell: {e}"})
        await websocket.close()
        return

    async def read_pty():
        """Read PTY output and send to WebSocket using event loop fd monitoring."""
        loop = asyncio.get_event_loop()
        try:
            while proc.is_alive():
                # Wait until the PTY fd is readable
                readable = asyncio.Event()
                loop.add_reader(proc.fd, readable.set)
                try:
                    await readable.wait()
                finally:
                    loop.remove_reader(proc.fd)

                data = proc.read()
                if data:
                    await websocket.send_json({
                        "type": "output",
                        "data": data.decode("utf-8", errors="replace"),
                    })
        except (WebSocketDisconnect, RuntimeError):
            pass
        except Exception as e:
            logger.debug(f"Terminal read error: {e}")

    # Start background reader
    reader_task = asyncio.create_task(read_pty())

    try:
        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("type")

            if msg_type == "input":
                proc.write(msg["data"].encode("utf-8"))
            elif msg_type == "resize":
                proc.resize(msg.get("cols", 80), msg.get("rows", 24))
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        logger.info(f"Terminal: client disconnected (session={session_id})")
    except Exception as e:
        logger.debug(f"Terminal WebSocket error: {e}")
    finally:
        reader_task.cancel()
        # kill() waits up to ~2s for the shell to die — off the event loop,
        # so a stubborn child can never freeze the whole server again.
        await asyncio.to_thread(proc.kill)
        logger.info(f"Terminal: closed (session={session_id})")
