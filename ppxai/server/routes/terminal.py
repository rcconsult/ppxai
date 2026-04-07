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
import struct

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
        """Fork and exec the shell with a PTY."""
        child_pid, fd = pty.fork()
        if child_pid == 0:
            # Child process — exec the shell
            os.chdir(self.working_dir)
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            args = [self.shell]
            if self.login_shell:
                args.append("-l")
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
        """Kill the child process."""
        if self.child_pid is not None:
            try:
                os.kill(self.child_pid, signal.SIGTERM)
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
    shell_bin = shell_config.get("shell_bin") or os.environ.get("SHELL", "/bin/sh")
    login_shell = shell_config.get("login_shell", False)
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
        proc.kill()
        logger.info(f"Terminal: closed (session={session_id})")
