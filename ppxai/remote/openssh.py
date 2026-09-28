"""`OpenSSHTransport` -- S2 implemented over the user's own `ssh` (ADR 0013).

Why the system client and not a library: the owner's `ssh` already knows
their config aliases, agent, `ProxyJump`, hardware keys and `known_hosts`.
ppxai stores none of that; a host is a destination string `ssh` understands.

Three rules hold everywhere in this module:

- **Never prompt.** Every invocation carries `BatchMode=yes`, so a missing
  key or an unknown host key fails fast instead of hanging the hub on a
  prompt nobody can see.
- **argv, never a shell string.** `run()` takes a list and quotes it for the
  remote login shell exactly once, in `quote_remote_argv`.
- **OpenSSH's stderr is kept verbatim** on every typed error, because its own
  message is what the user needs to fix their SSH setup.

Leaf-ish: stdlib plus `.transport`; nothing from `ppxai.engine`/`commands`.
"""

from __future__ import annotations

import asyncio
import collections
import re
import shlex
import shutil
import socket
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .transport import (
    AuthFailedError,
    ForwardFailedError,
    HostKeyRejectedError,
    HostUnreachableError,
    LocalEndpoint,
    RemoteTransportError,
    RunResult,
    TransportTimeoutError,
)

#: `ssh` exits 255 when IT fails; any other status is the remote command's.
SSH_FAILURE_RC = 255

_DEFAULT_CONNECT_TIMEOUT_S = 10
_DEFAULT_FORWARD_READY_TIMEOUT_S = 15.0
_READY_POLL_S = 0.05
_STOP_GRACE_S = 3.0
_STDERR_LINES_KEPT = 200

# Checked in this order; the first match wins. Host key before auth: a
# rejected host key ends the handshake before any credential is offered, and
# its message must never be read as a login problem. Patterns are OpenSSH's
# own wording (captured from OpenSSH 8.x/9.x on macOS, Linux and Windows).
_FAILURE_PATTERNS: tuple[tuple[type[RemoteTransportError], re.Pattern[str]], ...] = (
    (HostKeyRejectedError, re.compile(
        r"Host key verification failed"
        r"|REMOTE HOST IDENTIFICATION HAS CHANGED"
        r"|No \S+ host key is known for", re.IGNORECASE)),
    (AuthFailedError, re.compile(
        r"Permission denied \("
        r"|Too many authentication failures", re.IGNORECASE)),
    (ForwardFailedError, re.compile(
        r"Could not request local forwarding"
        r"|cannot listen to (port|path)"
        r"|unix_listener: cannot bind"
        r"|bind \[?[^\]]*\]?: Address already in use"
        r"|Bad local forwarding specification", re.IGNORECASE)),
    (HostUnreachableError, re.compile(
        r"Could not resolve hostname"
        r"|Connection refused"
        r"|Connection timed out|Operation timed out"
        r"|No route to host"
        r"|Network is unreachable"
        r"|Connection closed by"
        r"|Connection reset by"
        r"|kex_exchange_identification", re.IGNORECASE)),
)

_DESTINATION_RE = re.compile(r"^[^\s\-][^\s]*$")


def quote_remote_argv(argv: Sequence[str]) -> str:
    """Quote `argv` for a POSIX remote login shell. The ONE quoting site.

    `ssh` joins its command arguments with spaces and hands the result to the
    remote user's login shell, so an unquoted argv is a shell string in
    disguise. Each element is `shlex.quote`d. NUL cannot be passed at all,
    and CR/LF are refused rather than quoted: `sh` would accept them inside
    single quotes, but csh-family login shells do not, and no ppxai command
    needs one.
    """
    if not argv:
        raise ValueError("argv is empty")
    for arg in argv:
        if not isinstance(arg, str):
            raise TypeError(f"argv elements must be str, got {type(arg).__name__}")
        if "\x00" in arg or "\n" in arg or "\r" in arg:
            raise ValueError(f"argv element contains NUL or a line break: {arg!r}")
    return " ".join(shlex.quote(a) for a in argv)


def classify_ssh_failure(
    stderr: str, *, rc: int | None, forwarding: bool = False,
) -> RemoteTransportError | None:
    """Map OpenSSH's stderr to a typed error, or None if it names no ssh failure.

    `forwarding=True` makes an unrecognised failure a `ForwardFailedError` (the
    forward process exited, whatever the reason); otherwise None, and the
    caller decides.
    """
    for error_type, pattern in _FAILURE_PATTERNS:
        if pattern.search(stderr):
            return error_type(_summary(error_type, rc), stderr=stderr, rc=rc)
    if forwarding:
        return ForwardFailedError(_summary(ForwardFailedError, rc), stderr=stderr, rc=rc)
    return None


def _summary(error_type: type[RemoteTransportError], rc: int | None) -> str:
    what = {
        HostKeyRejectedError: "ssh rejected the host key (check known_hosts)",
        AuthFailedError: "ssh authentication failed",
        ForwardFailedError: "ssh could not forward to the remote socket",
        HostUnreachableError: "ssh could not reach the host",
    }.get(error_type, "ssh failed")
    return f"{what} (exit {rc})" if rc is not None else what


def validate_destination(destination: str) -> str:
    """A destination is one `ssh` word: non-empty, no whitespace, and never
    starting with `-` (it would be read as an option)."""
    if not isinstance(destination, str) or not _DESTINATION_RE.match(destination):
        raise ValueError(f"invalid ssh destination: {destination!r}")
    return destination


def validate_remote_socket(path: str) -> str:
    """An absolute path with no `:` (the `-L` separator) and no whitespace."""
    if (not isinstance(path, str) or not path.startswith("/")
            or ":" in path or any(c.isspace() for c in path) or "\x00" in path):
        raise ValueError(f"invalid remote socket path: {path!r}")
    return path


@dataclass
class _Forward:
    endpoint: LocalEndpoint
    process: asyncio.subprocess.Process
    stderr_lines: collections.deque[str]
    drain: asyncio.Task[None]
    private_dir: Path | None = None
    closed: bool = field(default=False)


class OpenSSHTransport:
    """`RemoteTransport` over the system `ssh`, for one destination."""

    def __init__(
        self,
        destination: str,
        *,
        ssh_command: Sequence[str] = ("ssh",),
        connect_timeout_s: int = _DEFAULT_CONNECT_TIMEOUT_S,
        forward_ready_timeout_s: float = _DEFAULT_FORWARD_READY_TIMEOUT_S,
        local_forward_kind: str | None = None,
    ):
        """
        `ssh_command` is the argv prefix that runs ssh -- `("ssh",)` in
        production; tests pass `(sys.executable, "fake_ssh.py")`.

        `local_forward_kind` defaults to a unix socket on POSIX (in a private
        0700 directory, so only this user can reach the forward) and loopback
        TCP on Windows, where OpenSSH forwards TCP -> remote unix socket
        (measured in ADR 0013 question 3).
        """
        self.destination = validate_destination(destination)
        self._ssh = tuple(ssh_command)
        if not self._ssh:
            raise ValueError("ssh_command is empty")
        self._connect_timeout_s = int(connect_timeout_s)
        self._ready_timeout_s = float(forward_ready_timeout_s)
        kind = local_forward_kind or ("tcp" if sys.platform == "win32" else "uds")
        if kind not in ("tcp", "uds"):
            raise ValueError(f"local_forward_kind must be 'tcp' or 'uds', got {kind!r}")
        self._local_kind = kind
        self._forwards: list[_Forward] = []

    # -- argv -------------------------------------------------------------

    def _base_options(self) -> list[str]:
        return [
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={self._connect_timeout_s}",
        ]

    def run_argv(self, argv: Sequence[str]) -> list[str]:
        """The full local argv `run()` executes (exposed for tests)."""
        return [*self._ssh, *self._base_options(), "-T",
                self.destination, quote_remote_argv(argv)]

    def forward_argv(self, local: LocalEndpoint, remote_socket: str) -> list[str]:
        """The full local argv `forward()` executes (exposed for tests)."""
        validate_remote_socket(remote_socket)
        if local.kind == "uds":
            spec = f"{local.address}:{remote_socket}"
            extra = ["-o", "StreamLocalBindMask=0177",
                     "-o", "StreamLocalBindUnlink=yes"]
        else:
            spec = f"{local.address}:{remote_socket}"
            extra = []
        return [*self._ssh, *self._base_options(),
                "-o", "ExitOnForwardFailure=yes", *extra,
                "-N", "-L", spec, self.destination]

    # -- run --------------------------------------------------------------

    async def run(self, argv: Sequence[str], *, timeout: float) -> RunResult:
        full = self.run_argv(argv)
        proc = await asyncio.create_subprocess_exec(
            *full,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            await _kill(proc)
            raise TransportTimeoutError(
                f"ssh {self.destination}: no result within {timeout:g}s")
        stdout = out.decode("utf-8", errors="replace")
        stderr = err.decode("utf-8", errors="replace")
        rc = proc.returncode if proc.returncode is not None else -1
        if rc == SSH_FAILURE_RC:
            # 255 is ssh's own failure status -- unless the remote command
            # itself exited 255. OpenSSH always explains its own failures,
            # so an exit with no recognisable ssh message is the command's.
            error = classify_ssh_failure(stderr, rc=rc)
            if error is not None:
                raise error
        return RunResult(rc=rc, stdout=stdout, stderr=stderr)

    # -- forward ----------------------------------------------------------

    async def forward(self, remote_socket: str) -> LocalEndpoint:
        validate_remote_socket(remote_socket)
        private_dir: Path | None = None
        if self._local_kind == "uds":
            # mkdtemp is 0700: nobody else can reach the socket inside. Short
            # names keep the path under the 104-byte sun_path limit on macOS.
            private_dir = Path(tempfile.mkdtemp(prefix="ppxai-fwd-"))
            local = LocalEndpoint("uds", str(private_dir / "s.sock"))
        else:
            local = LocalEndpoint("tcp", f"127.0.0.1:{_free_loopback_port()}")

        proc = await asyncio.create_subprocess_exec(
            *self.forward_argv(local, remote_socket),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        # Drain stderr for the forward's whole life: every failed channel open
        # logs a line, and an undrained pipe would eventually block ssh.
        lines: collections.deque[str] = collections.deque(maxlen=_STDERR_LINES_KEPT)
        drain = asyncio.create_task(_drain(proc.stderr, lines))
        fwd = _Forward(local, proc, lines, drain, private_dir)

        try:
            await self._wait_ready(fwd)
        except BaseException:
            await _stop(fwd)
            raise
        self._forwards.append(fwd)
        return local

    async def _wait_ready(self, fwd: _Forward) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._ready_timeout_s
        while True:
            if fwd.process.returncode is not None:
                await asyncio.wait_for(fwd.drain, timeout=_STOP_GRACE_S)
                stderr = "\n".join(fwd.stderr_lines)
                error = classify_ssh_failure(
                    stderr, rc=fwd.process.returncode, forwarding=True)
                assert error is not None  # forwarding=True always classifies
                raise error
            if await _accepts(fwd.endpoint):
                return
            if loop.time() >= deadline:
                raise TransportTimeoutError(
                    f"ssh {self.destination}: forward to "
                    f"{fwd.endpoint.address} not accepting after "
                    f"{self._ready_timeout_s:g}s",
                    stderr="\n".join(fwd.stderr_lines))
            await asyncio.sleep(_READY_POLL_S)

    # -- close ------------------------------------------------------------

    async def close(self) -> None:
        forwards, self._forwards = self._forwards, []
        for fwd in forwards:
            await _stop(fwd)


async def _drain(stream: asyncio.StreamReader | None,
                 lines: collections.deque[str]) -> None:
    if stream is None:
        return
    while True:
        raw = await stream.readline()
        if not raw:
            return
        lines.append(raw.decode("utf-8", errors="replace").rstrip("\r\n"))


async def _accepts(endpoint: LocalEndpoint) -> bool:
    try:
        if endpoint.kind == "uds":
            if not Path(endpoint.address).exists():
                return False
            _, writer = await asyncio.open_unix_connection(endpoint.address)
        else:
            host, port = endpoint.address.rsplit(":", 1)
            _, writer = await asyncio.open_connection(host, int(port))
    except OSError:
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


async def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=_STOP_GRACE_S)
    except asyncio.TimeoutError:
        pass


async def _stop(fwd: _Forward) -> None:
    if fwd.closed:
        return
    fwd.closed = True
    if fwd.process.returncode is None:
        try:
            fwd.process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(fwd.process.wait(), timeout=_STOP_GRACE_S)
        except asyncio.TimeoutError:
            await _kill(fwd.process)
    if not fwd.drain.done():
        try:
            await asyncio.wait_for(fwd.drain, timeout=_STOP_GRACE_S)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            fwd.drain.cancel()
    if fwd.private_dir is not None:
        shutil.rmtree(fwd.private_dir, ignore_errors=True)


def _free_loopback_port() -> int:
    """A port free right now. ssh binds it moments later; if something takes
    it first, `ExitOnForwardFailure` makes that a prompt `ForwardFailedError`."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
