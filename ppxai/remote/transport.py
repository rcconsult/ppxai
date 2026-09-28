"""S2 -- the `RemoteTransport` Protocol (ADR 0013).

The hub reaches a remote host through exactly two operations: run a command
there, and forward a local endpoint to a unix socket there. Everything above
this seam -- the session manager (S4), the proxy (S5) -- is written against
the Protocol, so it is testable with a fake and the OpenSSH implementation
stays swappable (the ADR's `asyncssh` alternative).

Leaf module per docs/patterns/protocol-dependency-inversion.md: stdlib only,
no ppxai imports.

Errors are typed so S4's state machine can tell "the host is down" from
"the key was refused" from "the host key changed" without parsing text.
Each carries the transport's stderr verbatim, because OpenSSH's own message
is what the user needs to fix their SSH config.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class RunResult:
    """What a remote command did. `rc` is the remote command's exit status."""

    rc: int
    stdout: str
    stderr: str

    def check(self, argv: Sequence[str] = ()) -> RunResult:
        """Return self if `rc == 0`, else raise `RemoteCommandFailedError`."""
        if self.rc != 0:
            raise RemoteCommandFailedError(
                f"remote command exited {self.rc}"
                + (f": {' '.join(argv)}" if argv else ""),
                stderr=self.stderr,
                rc=self.rc,
            )
        return self


@dataclass(frozen=True)
class LocalEndpoint:
    """Where the hub connects to reach a forwarded remote socket.

    `address` is `"127.0.0.1:<port>"` for `tcp`, a filesystem path for `uds`.
    """

    kind: Literal["tcp", "uds"]
    address: str


class RemoteTransportError(Exception):
    """Base for every transport failure. `stderr` is the transport's own text."""

    def __init__(self, message: str, *, stderr: str = "", rc: int | None = None):
        super().__init__(message)
        self.stderr = stderr
        self.rc = rc

    def __str__(self) -> str:
        base = super().__str__()
        detail = self.stderr.strip()
        return f"{base}\n{detail}" if detail else base


class HostUnreachableError(RemoteTransportError):
    """Name did not resolve, connection refused or timed out, or dropped."""


class AuthFailedError(RemoteTransportError):
    """The host was reached but refused every offered credential."""


class HostKeyRejectedError(RemoteTransportError):
    """Unknown or changed host key. Never auto-accepted (BatchMode)."""


class RemoteCommandFailedError(RemoteTransportError):
    """The command ran on the remote and exited non-zero."""


class ForwardFailedError(RemoteTransportError):
    """The connection worked but the forward could not be set up or died."""


class TransportTimeoutError(RemoteTransportError):
    """The operation did not finish within its timeout; the process was killed."""


@runtime_checkable
class RemoteTransport(Protocol):
    """One remote host, reached however the implementation reaches it."""

    async def run(self, argv: Sequence[str], *, timeout: float) -> RunResult:
        """Run `argv` on the remote. A non-zero remote exit is a `RunResult`,
        not an error; transport-level failures raise a `RemoteTransportError`.
        """
        ...

    async def forward(self, remote_socket: str) -> LocalEndpoint:
        """Forward a local endpoint to `remote_socket` (an absolute path) and
        return once the local end accepts connections.
        """
        ...

    async def close(self) -> None:
        """Tear down every forward this transport opened. Idempotent."""
        ...
