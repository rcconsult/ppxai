"""The local hub's side of ADR 0013: reaching ppxai servers on remote hosts.

This package moves bytes between a local browser and a `ppxai-server`
running on another machine. It never interprets a chat, so it imports
nothing from `ppxai.engine` or `ppxai.commands` (fenced by
`tests/test_no_new_lazy_imports.py::TestRemoteImportsNoEngineOrCommands`).

- `transport` -- the `RemoteTransport` Protocol (S2), its value types and
  typed errors. A leaf: stdlib only.
- `openssh` -- `OpenSSHTransport`, the first implementation, a subprocess
  wrapper around the user's own `ssh`.
- `inventory` -- `remote.hosts` (S1), validated from the raw config value.
- `contract` -- the registry contracts this hub can read, and the hub-level
  refusals (unknown host, old server, unknown contract).
- `manager` -- `RemoteSessionManager` (S4): list, launch, attach, detach,
  stop, and the per-attachment state machine.
"""

from .contract import (
    KNOWN_CONTRACTS,
    MIN_SERVER_VERSION,
    MalformedEntryError,
    RemoteHubError,
    RemoteServer,
    ServerNotInstalledError,
    UnknownContractError,
    UnknownHostError,
    UnknownServerError,
    UnsupportedServerError,
)
from .inventory import InventoryError, RemoteHost, parse_hosts
from .manager import RemoteSessionManager, ServerListing, State, StateChange
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
    "KNOWN_CONTRACTS",
    "MIN_SERVER_VERSION",
    "InventoryError",
    "MalformedEntryError",
    "RemoteHost",
    "RemoteHubError",
    "RemoteServer",
    "RemoteSessionManager",
    "ServerListing",
    "ServerNotInstalledError",
    "State",
    "StateChange",
    "UnknownContractError",
    "UnknownHostError",
    "UnknownServerError",
    "UnsupportedServerError",
    "parse_hosts",
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
