"""S1 -- the host inventory (ADR 0013): `remote.hosts` in ppxai-config.json.

A host is an ssh destination string as the user's own `ssh` understands it,
normally an alias from `~/.ssh/config`. ppxai stores no keys, users, ports
or jump hosts; those stay in SSH config.

    "remote": {"hosts": [
        {"id": "gpu01", "ssh": "gpu01"},
        {"id": "lab-mac", "ssh": "lab-mac", "ppxai_server": "~/.local/bin/ppxai-server"}
    ]}

The caller passes the raw `remote` value in; this module never reads config
itself (no config reads at import, and the hub package stays a leaf).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .openssh import validate_destination

#: `id` is a URL path segment (`/h/<id>/`), so it is URL-safe by construction
#: and can never smuggle a path. It is looked up, never interpolated.
HOST_ID_RE = re.compile(r"^[a-z0-9-]{1,32}$")

#: The hub's own host in the picker (ADR 0013 Q1): never a remote.
RESERVED_HOST_IDS = frozenset({"local"})

_HOST_KEYS = frozenset({"id", "ssh", "ppxai_server"})


class InventoryError(ValueError):
    """`remote.hosts` is malformed. The message names the offending entry."""


@dataclass(frozen=True)
class RemoteHost:
    id: str
    ssh: str
    #: Remote path of `ppxai-server`; None = discover (login PATH, then
    #: `~/.local/bin/ppxai-server`). A leading `~/` means the remote $HOME.
    ppxai_server: str | None = None


def parse_hosts(remote: Any) -> list[RemoteHost]:
    """Validate the raw `remote` config value into hosts, in config order.

    A missing or empty `remote` is no hosts (the hub is off). Anything
    malformed raises `InventoryError`; nothing is silently dropped, because a
    host that vanished from the picker with no message is worse than a
    config error at startup.
    """
    if remote is None:
        return []
    if not isinstance(remote, dict):
        raise InventoryError(f"remote must be an object, got {type(remote).__name__}")
    raw_hosts = remote.get("hosts", [])
    if not isinstance(raw_hosts, list):
        raise InventoryError("remote.hosts must be a list")

    hosts: list[RemoteHost] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_hosts):
        where = f"remote.hosts[{index}]"
        if not isinstance(raw, dict):
            raise InventoryError(f"{where} must be an object")
        unknown = set(raw) - _HOST_KEYS
        if unknown:
            raise InventoryError(f"{where}: unknown key(s) {sorted(unknown)}; "
                                 f"allowed: {sorted(_HOST_KEYS)}")
        host_id = raw.get("id")
        if not isinstance(host_id, str) or not HOST_ID_RE.match(host_id):
            raise InventoryError(f"{where}: id {host_id!r} must match {HOST_ID_RE.pattern}")
        if host_id in RESERVED_HOST_IDS:
            raise InventoryError(f"{where}: id {host_id!r} is reserved")
        if host_id in seen:
            raise InventoryError(f"{where}: duplicate id {host_id!r}")
        seen.add(host_id)
        try:
            ssh = validate_destination(raw.get("ssh"))
        except ValueError:
            raise InventoryError(f"{where}: ssh {raw.get('ssh')!r} is not a single ssh "
                                 "destination (no spaces, must not start with '-')") from None
        binary = raw.get("ppxai_server")
        if binary is not None and (not isinstance(binary, str) or not binary.strip()
                                   or any(c in binary for c in "\n\r\x00")):
            raise InventoryError(f"{where}: ppxai_server must be a non-empty path")
        hosts.append(RemoteHost(host_id, ssh, binary))
    return hosts
