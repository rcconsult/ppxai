"""The S3 server registry: what a remote host tells a hub (ADR 0013).

`ppxai-server --uds <path> --announce` writes one entry per running server
to `~/.ppxai/run/servers/<id>.json`; `ppxai-server --list --json` prints the
live ones. A hub on another machine reads them through the user's own SSH
session, so this file format is the one versioned cross-host wire in ADR
0013. Change a field and `CONTRACT` must bump: the hub refuses a contract
it does not know, naming both numbers. `tests/test_server_registry.py` pins
the field set per contract against a JSON fixture.

Trust boundary: an entry carries the server's bearer token, so entries are
written 0600 inside a 0700 directory -- the same boundary as
`~/.ppxai/.env`. The socket gets the same treatment (see `bind_uds`).

Paths are computed at call time, never at import: `Path.home()` read at
import pins the developer's real home into tests (docs/lessons/
module-level-home-paths-leak-into-user-state.md), and no module may read
config at import (tests/test_no_config_read_at_import.py).
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..common.process import pid_alive
from ..version import __version__

#: Bump on ANY change to the entry's fields or their meaning.
#: 2 (2026-09-29): same fields as 1; the meaning added is that a server
#: which writes it survives `--detach` from a PyInstaller one-file build
#: (`e3746f65`). A contract-1 server launched that way starts, then fails
#: every chat, and its version number cannot say so (the fix did not bump
#: it), so the hub retires contract 1 (`ppxai/remote/contract.py`).
CONTRACT = 2

#: Every key an entry carries at CONTRACT 2 (unchanged from 1), in write order.
ENTRY_FIELDS = (
    "contract", "id", "pid", "socket", "token", "version",
    "app_state_schema", "workdir", "started_at", "label",
)

_HEALTH_TIMEOUT_S = 2.0


def run_dir() -> Path:
    return Path.home() / ".ppxai" / "run"


def servers_dir() -> Path:
    return run_dir() / "servers"


def default_socket_path(server_id: str) -> Path:
    """`$XDG_RUNTIME_DIR/ppxai/<id>.sock`, else `~/.ppxai/run/sock/<id>.sock`.

    XDG_RUNTIME_DIR is a per-user 0700 tmpfs (`/run/user/<uid>`), measured
    as a working forward target from Windows OpenSSH (ADR 0013 Q3).
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) / "ppxai" if runtime else run_dir() / "sock"
    return base / f"{server_id}.sock"


def new_server_id() -> str:
    return secrets.token_hex(8)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def _app_state_schema_version() -> str | None:
    path = Path(__file__).resolve().parent.parent / "engine" / "app_state_schema.json"
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("version"))
    except (OSError, ValueError):
        return None


def build_entry(*, server_id: str, socket_path: Path, token: str, workdir: str,
                label: str | None = None, pid: int | None = None) -> dict[str, Any]:
    """The registry entry for THIS process (pid defaults to os.getpid()).

    The pid must be the serving process's own: a PyInstaller binary is a
    bootloader that forks the real server, and killing a launcher pid left
    the server running (ADR 0013, 2026-09-26 trial).
    """
    entry = {
        "contract": CONTRACT,
        "id": server_id,
        "pid": os.getpid() if pid is None else pid,
        "socket": str(socket_path),
        "token": token,
        "version": __version__,
        "app_state_schema": _app_state_schema_version(),
        "workdir": workdir,
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "label": label,
    }
    assert tuple(entry) == ENTRY_FIELDS
    return entry


def _private_dir(path: Path) -> None:
    """Create `path` (and parents) and make `path` itself 0700."""
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        os.chmod(path, 0o700)


def entry_path(server_id: str) -> Path:
    return servers_dir() / f"{server_id}.json"


def write_entry(entry: dict[str, Any]) -> Path:
    """Write atomically, 0600 from creation (never world-readable, even briefly)."""
    _private_dir(servers_dir())
    target = entry_path(entry["id"])
    tmp = target.with_suffix(".json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2)
        f.write("\n")
    os.replace(tmp, target)
    return target


def remove_entry(server_id: str) -> None:
    try:
        entry_path(server_id).unlink()
    except FileNotFoundError:
        pass


def read_entries() -> list[dict[str, Any]]:
    """Every parseable entry, newest first. Unparseable files are skipped."""
    folder = servers_dir()
    if not folder.is_dir():
        return []
    entries = []
    for path in folder.glob("*.json"):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(entry, dict) and "id" in entry:
            entries.append(entry)
    return sorted(entries, key=lambda e: str(e.get("started_at", "")), reverse=True)


def socket_answers(socket_path: str, token: str | None = None) -> bool:
    """True if `/health` answers 200 over the unix socket.

    An announced server has auth ON, and `/health` is not exempt from it
    (only from the Host check), so the entry's token must be presented --
    without it a live server answers 401 and would be pruned as dead.
    """
    if not hasattr(socket, "AF_UNIX") or not Path(socket_path).exists():
        return False
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with httpx.Client(transport=httpx.HTTPTransport(uds=socket_path),
                          timeout=_HEALTH_TIMEOUT_S) as client:
            return client.get("http://localhost/health", headers=headers).status_code == 200
    except (httpx.HTTPError, OSError):
        return False


def socket_accepts(socket_path: Path) -> bool:
    """True if something is listening on the socket (no HTTP, no auth)."""
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(_HEALTH_TIMEOUT_S)
    try:
        probe.connect(str(socket_path))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def is_live(entry: dict[str, Any]) -> bool:
    pid = entry.get("pid")
    return (isinstance(pid, int) and pid_alive(pid)
            and socket_answers(str(entry.get("socket", "")), entry.get("token")))


def list_live(prune: bool = True) -> list[dict[str, Any]]:
    """Entries whose pid is alive AND whose socket answers /health.

    With `prune`, every other entry is deleted (and its socket file, which
    a crashed server leaves behind).
    """
    live = []
    for entry in read_entries():
        if is_live(entry):
            live.append(entry)
        elif prune:
            remove_entry(str(entry["id"]))
            sock = entry.get("socket")
            if sock:
                try:
                    Path(sock).unlink()
                except OSError:
                    pass
    return live


def bind_uds(socket_path: Path) -> socket.socket:
    """Bind a listening unix socket that is 0600 before the first accept.

    uvicorn's own `uds=` path chmods the socket 0o666 after binding, so the
    server binds it here and hands uvicorn the file descriptor. The umask
    makes the socket 0600 from the instant it exists, and its directory is
    0700, so no other local user can connect even in the gap. A stale
    socket file (a crashed server) is replaced; a LIVE one is refused.
    """
    if not hasattr(socket, "AF_UNIX") or sys.platform == "win32":
        raise OSError("--uds needs a POSIX host (unix sockets); use --host/--port here")
    _private_dir(socket_path.parent)
    if socket_path.exists():
        if socket_accepts(socket_path):
            raise OSError(f"a server is already listening on {socket_path}")
        socket_path.unlink()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old_umask = os.umask(0o177)
    try:
        sock.bind(str(socket_path))
    finally:
        os.umask(old_umask)
    os.chmod(socket_path, 0o600)
    sock.listen(128)
    return sock
