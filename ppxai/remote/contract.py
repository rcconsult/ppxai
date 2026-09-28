"""What the hub knows of the S3 registry contract (ADR 0013).

The remote side writes it (`ppxai/server/registry.py`); the hub reads it
through `ppxai-server --list --json` over SSH. The two ends are different
installs of possibly different versions, so the hub keeps its OWN record of
every contract it understands instead of importing the server's -- a hub
that imported `registry.CONTRACT` would "know" whatever it was built with,
which is exactly the skew the contract number exists to catch.
`tests/test_remote_manager.py` pins `KNOWN_CONTRACTS[registry.CONTRACT]`
to `registry.ENTRY_FIELDS`, so a server-side change fails a test here too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: Field set per contract number the hub can read.
KNOWN_CONTRACTS: dict[int, tuple[str, ...]] = {
    1: ("contract", "id", "pid", "socket", "token", "version",
        "app_state_schema", "workdir", "started_at", "label"),
}

#: The first release whose `ppxai-server` has `--uds/--announce/--list`.
MIN_SERVER_VERSION = "1.19.3"

#: A server id is a URL path segment (`/h/<host>/<id>/`).
SERVER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class RemoteHubError(Exception):
    """Base for hub-level refusals (above the transport)."""


class UnknownHostError(RemoteHubError):
    """The host id is not in `remote.hosts`."""


class UnknownServerError(RemoteHubError):
    """No live announced server with that id on the host."""


class ServerNotInstalledError(RemoteHubError):
    """No `ppxai-server` binary was found on the remote host."""


class UnsupportedServerError(RemoteHubError):
    """The remote `ppxai-server` predates the S3 contract (ADR 0013 Q5: refuse)."""


class UnknownContractError(RemoteHubError):
    """A registry entry carries a contract number this hub cannot read."""


class MalformedEntryError(RemoteHubError):
    """A registry entry is not what its contract promises."""


@dataclass(frozen=True)
class RemoteServer:
    """One announced server on a remote host (a contract-1 registry entry)."""

    host: str
    id: str
    pid: int
    socket: str
    token: str
    version: str
    app_state_schema: str | None
    workdir: str
    started_at: str
    label: str | None

    def public(self) -> dict[str, Any]:
        """Everything but the token -- the shape a browser may see."""
        return {k: v for k, v in self.__dict__.items() if k != "token"}

    def __repr__(self) -> str:  # never print a token into a log
        return f"RemoteServer(host={self.host!r}, id={self.id!r}, version={self.version!r})"


def parse_entry(host: str, raw: Any) -> RemoteServer:
    """One `--list --json` element -> `RemoteServer`, or a typed refusal."""
    if not isinstance(raw, dict):
        raise MalformedEntryError(f"{host}: registry entry is not an object")
    contract = raw.get("contract")
    if contract not in KNOWN_CONTRACTS:
        known = ", ".join(str(c) for c in sorted(KNOWN_CONTRACTS))
        raise UnknownContractError(
            f"{host}: server {raw.get('id', '?')!r} speaks registry contract "
            f"{contract!r}; this ppxai understands contract {known}. "
            "Upgrade the side that is older.")
    missing = [f for f in KNOWN_CONTRACTS[contract] if f not in raw]
    if missing:
        raise MalformedEntryError(f"{host}: contract-{contract} entry lacks {missing}")
    sid = raw["id"]
    if not isinstance(sid, str) or not SERVER_ID_RE.match(sid):
        raise MalformedEntryError(f"{host}: server id {sid!r} is not a safe path segment")
    for name, kind in (("pid", int), ("socket", str), ("token", str),
                       ("version", str), ("workdir", str), ("started_at", str)):
        if not isinstance(raw[name], kind) or isinstance(raw[name], bool):
            raise MalformedEntryError(f"{host}: {sid}: {name} must be {kind.__name__}")
    if not raw["socket"].startswith("/"):
        # `ppxai-server --uds` refuses to start on Windows, so only a POSIX
        # host can announce; anything else is a foreign or corrupt entry.
        raise MalformedEntryError(
            f"{host}: {sid}: socket {raw['socket']!r} is not an absolute POSIX path; "
            "remote hosts must be POSIX (ADR 0013 serves over a unix socket)")
    return RemoteServer(
        host=host, id=sid, pid=raw["pid"], socket=raw["socket"], token=raw["token"],
        version=raw["version"],
        app_state_schema=(None if raw["app_state_schema"] is None
                          else str(raw["app_state_schema"])),
        workdir=raw["workdir"], started_at=raw["started_at"],
        label=None if raw["label"] is None else str(raw["label"]),
    )


def version_tuple(version: str) -> tuple[int, ...]:
    """`"1.19.3"` -> `(1, 19, 3)`; non-numeric parts end the tuple."""
    parts = []
    for piece in version.strip().split("."):
        digits = re.match(r"\d+", piece)
        if not digits:
            break
        parts.append(int(digits.group()))
    return tuple(parts)
