"""The local hub's side of ADR 0013: reaching ppxai servers on remote hosts.

This package moves bytes between a local browser and a `ppxai-server`
running on another machine. It never interprets a chat, so it imports
nothing from `ppxai.engine` or `ppxai.commands` (fenced by
`tests/test_no_new_lazy_imports.py::TestRemoteImportsNoEngineOrCommands`).

- `transport` -- the `RemoteTransport` Protocol (S2), its value types and
  typed errors. A leaf: stdlib only.
- `openssh` -- `OpenSSHTransport`, the first implementation, a subprocess
  wrapper around the user's own `ssh`.
"""

from .openssh import OpenSSHTransport, classify_ssh_failure, quote_remote_argv
from .transport import (
    AuthFailedError,
    ForwardFailedError,
    HostKeyRejectedError,
    HostUnreachableError,
    LocalEndpoint,
    RemoteCommandFailedError,
    RemoteTransport,
    RemoteTransportError,
    RunResult,
    TransportTimeoutError,
)

__all__ = [
    "AuthFailedError",
    "ForwardFailedError",
    "HostKeyRejectedError",
    "HostUnreachableError",
    "LocalEndpoint",
    "OpenSSHTransport",
    "RemoteCommandFailedError",
    "RemoteTransport",
    "RemoteTransportError",
    "RunResult",
    "TransportTimeoutError",
    "classify_ssh_failure",
    "quote_remote_argv",
]
