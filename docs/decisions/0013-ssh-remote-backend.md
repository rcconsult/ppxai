# ADR 0013 — SSH remote backend: a local hub reaching remote ppxai servers

**Date:** 2026-09-26 (revised 2026-09-26 — owner decided open questions 1, 2
and 5; 3 and 4 measured against a WSL2 sshd the same day)
**Status:** 🚧 **In progress.** Phase 1 (S3, the remote-side contract) was
implemented on 2026-09-27 (`78e34b8e`): `ppxai-server --uds/--announce/--detach/--list`,
the contract-1 registry, verified on Windows, macOS and Ubuntu 24.04. Phase 2
(S2, the transport) was implemented on 2026-09-28 on `feature/v1.19.4`:
`ppxai/remote/transport.py` + `openssh.py`. Phase 3 (S1 parsing + S4, the
session manager) the same day: `ppxai/remote/{inventory,contract,manager}.py`.
Phase 4 (S5, the hub proxy and `/hub/*` control API, wired to `remote.hosts`)
the same day: `ppxai/server/routes/remote_hub.py`. Phase 5 (S6, the web
client: `/h/` prefix recognition and the SSH Launcher in the split pane) the
same day, see S6 "As built". Phase 6 (owner trial) is not started. All of it
is unreleased, on `feature/v1.19.4`. Revise in place.
**Related:**
- [`../plan-ssh-remote-backend.md`](../plan-ssh-remote-backend.md) — the phased plan that implements this record
- [`../patterns/protocol-dependency-inversion.md`](../patterns/protocol-dependency-inversion.md) — the `Protocol`-in-leaf-module pattern the transport seam uses
- [`../patterns/state-sync-determinism.md`](../patterns/state-sync-determinism.md) — the reconnect/re-anchor rules a proxied client inherits
- [`0003-agent-platform-architecture.md`](0003-agent-platform-architecture.md) — the `/v1/agent/*` run registry a host view lists
- `deploy/k8s/` — the `/s/<user>/` ingress prefix, the precedent for path-prefix routing to a per-target backend

---

## Context

The owner has ppxai fully installed on several hosts they can reach with
key-based SSH. They want to keep the client (for now, the web app in a local
browser) on their own machine while the engine, the tools and the files stay
on the remote host.

**What this is not.** It is not remote *tool* execution from a local engine.
Because ppxai is installed on the target, the whole `ppxai-server` runs
there, and every tool — shell, file edit, preview, terminal, `/task` — already
executes on the right machine. Nothing below touches a tool. (A local engine
driving remote tools would need a filesystem/exec abstraction that does not
exist today: shell, filesystem, editor, container, terminal and preview each
call `subprocess`/`os`/`pathlib` directly. That is a different, much larger
design, deliberately out of scope.)

**What the problem therefore is:** getting a local browser to a server that
listens only on the remote host, safely, for more than one host at a time, and
being able to see what is already running there.

### What exists today (verified 2026-09-26 on `bugfix/v1.19.3` @ `41de6a1c`)

| Fact | Where |
|---|---|
| The web UI is served by `ppxai-server` and uses its page origin as the API base, plus an optional `/s/<user>` path prefix (the k8s ingress precedent) | `ppxai/web/app.js:71-74` |
| Only `/s/` is recognised as a prefix; `handleQuit()` special-cases it so "Leave" doesn't kill a shared pod | `ppxai/web/app.js:73`, `:1003-1007` |
| One `serverUrl` per page, threaded into `ApiClient`, `StreamHandler`, the terminal view; no multi-server concept | `ppxai/web/shared/api-client.js:26-38` |
| The terminal is a websocket at `/ws/terminal`, URL built from `serverUrl` (so it keeps a path prefix) | `ppxai/server/routes/terminal.py:202`, `ppxai/web/components/views/terminal-view.js:85-90` |
| Chat and agent-run streams are SSE (`StreamingResponse`) | `ppxai/server/routes/chat.py`, `routes/agent_v1.py` |
| Default bind is `127.0.0.1`; Host-header validation rejects non-loopback `Host` unless `PPXAI_TRUSTED_HOSTS` extends it | `ppxai/server/http.py:90`, `:199-280` |
| Bearer auth is opt-in via `PPXAI_API_TOKEN`; loopback peers without forwarding headers are exempt | `ppxai/server/auth.py:40`, `:116-140` |
| The server is started with `uvicorn.Config(host=..., port=...)`; no unix-socket option is wired | `ppxai/server/http.py:462-470` |
| `ppxai-desktop` finds and launches a **local** server binary only | `ppxai-desktop.py` |
| No SSH library in dependencies; no ADR or roadmap entry for remote hosts | `pyproject.toml`, `docs/decisions/`, `ROADMAP.md` |

---

## Decision

A **local hub** holds SSH connections to remote hosts and reverse-proxies each
one under a path prefix on a single local origin. The remote server listens on
a **private unix socket**, never a TCP port, and announces itself in a small
**registry** the hub reads over SSH. The transport is the **system OpenSSH
client**.

```
 local machine                                          remote host (ppxai installed)
┌───────────────────────────────────────────┐           ┌──────────────────────────────────┐
│ browser                                   │           │ ppxai-server --uds <sock>        │
│   /             host + session picker     │           │   socket 0600, owner-only        │
│   /h/<host>/…   remote's own web UI       │           │   PPXAI_API_TOKEN = per-launch   │
│      │                                    │           │                                  │
│      ▼                                    │   ssh     │ ~/.ppxai/run/servers/<id>.json   │
│ hub (ppxai/remote/)                       │──────────▶│   (S3 registry entry)            │
│   RemoteSessionManager  (S4)              │  -L fwd   │                                  │
│   reverse proxy HTTP/SSE/WS  (S5)         │◀─────────▶│                                  │
│   RemoteTransport = OpenSSH  (S2)         │           │                                  │
└───────────────────────────────────────────┘           └──────────────────────────────────┘
```

Seven seams, each defined before any code is written.

### S1 — Host inventory

A host is an **SSH destination string** as the user's own `ssh` understands it
— normally an alias from `~/.ssh/config`. ppxai stores no keys, users, ports,
jump hosts or identity files; those stay in SSH config, where the owner's
agent, `ProxyJump`, hardware keys and `known_hosts` already work.

```jsonc
// ppxai-config.json (new top-level key; name to be settled against ADR 0010's axes)
"remote": {
  "hosts": [
    { "id": "gpu01",  "ssh": "gpu01" },
    { "id": "lab-mac", "ssh": "lab-mac", "ppxai_server": "~/.local/bin/ppxai-server" }
  ]
}
```

`id` is the path segment (`/h/<id>/`), restricted to `[a-z0-9-]{1,32}` so it
is URL-safe and cannot smuggle a path. `ppxai_server` overrides binary
discovery on the remote (default: `ppxai-server` on the login `PATH`, then the
documented install locations). Nothing else is configurable in v1.

### S2 — `RemoteTransport` Protocol

Defined in a leaf module (`ppxai/remote/transport.py`), per the
protocol-dependency-inversion pattern:

```python
class RemoteTransport(Protocol):
    async def run(self, argv: Sequence[str], *, timeout: float) -> RunResult: ...
    async def forward(self, remote_socket: str) -> LocalEndpoint: ...
    async def close(self) -> None: ...

@dataclass(frozen=True)
class RunResult:  rc: int; stdout: str; stderr: str

@dataclass(frozen=True)
class LocalEndpoint:  kind: Literal["tcp", "uds"]; address: str  # "127.0.0.1:53811" | "/path/sock"
```

- `argv` is a list, never a shell string. The implementation quotes it for
  the remote login shell exactly once, in one place.
- `forward()` returns an endpoint the hub proxies to. On Windows the local end
  is a loopback TCP port (OpenSSH for Windows forwards TCP→remote-UDS); on
  POSIX it may be a local UDS.
- Errors are typed (`HostUnreachableError`, `AuthFailedError`,
  `HostKeyRejectedError`, `RemoteCommandFailedError`, `ForwardFailedError`,
  plus `TransportTimeoutError`; all subclass `RemoteTransportError`) and carry
  OpenSSH's stderr verbatim. `run()` returns a non-zero *remote* exit as a
  `RunResult` (`.check()` raises `RemoteCommandFailedError`); only ssh's own
  failures raise. ssh exits 255 for both its own failures and a remote command
  that exits 255, so a 255 is an ssh failure only when stderr carries a
  recognised OpenSSH message.
  The transport never prompts: it runs `ssh -o BatchMode=yes`, so a missing
  key or unknown host key fails fast instead of hanging the hub.

First implementation: **`OpenSSHTransport`**, a subprocess wrapper around the
system `ssh`. A test double (`FakeTransport`) implements the same Protocol so
S3–S6 are testable with no network.

### S3 — Remote-side contract (the only change on remote hosts)

This is the one versioned, cross-host wire. Two additions to `ppxai-server`:

**Launch.** `ppxai-server --uds <path> --detach --announce`

- binds a unix socket instead of TCP (`uvicorn.Config(uds=...)`), `chmod 0600`
  before accepting;
- generates a per-launch token into `PPXAI_API_TOKEN` for its own process, so
  auth is ON even though every request arrives through the socket;
- writes a registry entry, then prints the same JSON on stdout and detaches.

**List.** `ppxai-server --list --json` prints every registry entry whose pid
is alive and whose socket answers `/health`, and deletes dead entries.

Registry entry, `~/.ppxai/run/servers/<id>.json`, mode 0600:

```json
{
  "contract": 1,
  "id": "9f2c…",
  "pid": 41233,
  "socket": "/home/u/.ppxai/run/sock/9f2c.sock",
  "token": "…",
  "version": "1.19.3",
  "app_state_schema": "1.1",
  "workdir": "/home/u/src/project",
  "started_at": "2026-09-26T10:14:03Z",
  "label": "optional human label"
}
```

`contract` is an integer; the hub refuses an entry whose `contract` it does not
know, with a message naming both numbers. The token lives in a 0600 file inside
the owner's home — the same trust boundary as `~/.ppxai/.env`, and the hub reads
it only through the user's own SSH session.

### S4 — `RemoteSessionManager` (local service)

Owns one connection per host and a small state machine:

```
disconnected ──connect──▶ connecting ──forward ok──▶ tunneled ──/health ok──▶ healthy
      ▲                        │                          │                      │
      │                 transport error              health fails          health fails
      └──────────── close ◀────┴──────────────────────────┴─────▶ degraded ─────┘
                                                                   (retry with backoff)
```

Verbs: `hosts()`, `servers(host)` (runs S3 `--list`), `launch(host, workdir,
label)`, `attach(host, server_id)`, `detach(host, server_id)` (drop the
forward, leave the server running), `stop(host, server_id)` (ask the server to
shut down). **Detach is the default** when the browser leaves; stopping a
remote server is always an explicit act.

**As built (2026-09-28):**

- A sixth, terminal state, **`gone`**: the server is no longer in the host's
  registry (stopped, crashed, host rebooted). The 2026-09-26 trial asked for
  it: a server that ends is a normal outcome, not `degraded`. `degraded`
  retries re-list the host first; a server missing from the list is `gone`.
- `degraded` also covers a forward that works but whose `/health` fails
  (e.g. 401). Retries back off exponentially (1 s doubling, capped at 30 s)
  and emit no event while nothing changes.
- `stop()` sends `POST /shutdown` through the server's own forward (attaching
  first if needed); it never signals a pid.
- `route(host, id)` gives S5 the endpoint and token, and only for a
  `healthy` attachment. Every public view omits the token, and so does
  `RemoteServer`'s `repr`.
- The hub keeps its own record of each contract it can read
  (`ppxai/remote/contract.py`) instead of importing the server's, and a test
  pins it to `ppxai/server/registry.py`. A listing with one unreadable entry
  returns the rest plus a refusal message; it does not fail whole.
- The remote binary is the configured `ppxai_server`, else `ppxai-server` on
  the login PATH, else `~/.local/bin/ppxai-server` (non-interactive SSH login
  PATHs often lack `~/.local/bin`). An old server (argparse rejects `--list`
  or `--uds`) is refused with its `--version` and the minimum, 1.19.3.

The manager lives in a new package `ppxai/remote/` that imports nothing from
`ppxai/engine/` or `ppxai/commands/` — it moves bytes and never interprets a
chat. A fence joins `tests/test_no_new_lazy_imports.py`'s layering checks.

### S5 — Hub routing

`/h/<host>/<server-id>/…` is reverse-proxied to that server's forwarded
endpoint with the prefix stripped, as the k8s ingress does for `/s/<user>/`.
The proxy must:

- stream: no buffering of SSE (`text/event-stream`) or chunked responses;
- upgrade websockets (`/ws/terminal`);
- inject `Authorization: Bearer <token>` from the registry entry — the token
  never reaches the browser;
- send `Host: localhost` and **no** `X-Forwarded-*` headers, so the remote's
  Host validation passes with default settings;
- rewrite nothing in bodies. The remote UI already builds every URL from its
  page prefix (verified for `ApiClient` and the terminal view); prefix
  recognition is S6's job.

`/` on the hub is the host/session picker. `/h/<host>/` with no server id
lists that host's servers.

### S6 — Web client

Two small changes, both generalising what `/s/<user>/` already does:

1. **Prefix recognition.** `app.js:73` recognises `/h/<host>/<id>` as well as
   `/s/<user>`; `handleQuit()` treats it as *detach* (return to the picker),
   never as shutting the server down.
2. **Picker page.** A new view served by the hub: hosts with connection state
   (S4), each host's servers (S3 entries), and per server the sessions and
   agent runs read from the remote's **existing** `/sessions` and
   `/v1/agent/runs` endpoints through the proxy. No new remote endpoint is
   needed to "see what is running".

The UI inside `/h/<host>/<id>/` is **served by the remote server itself**, so
UI and server versions always match. The AppState schema guard that landed
2026-09-21 remains the backstop, not the mechanism.

**As built (2026-09-28), owner design:** the picker is not a page but the
**SSH Launcher**, a view in the web UI's right split pane (the
`RightPanelFrame` that already hosts files and task runs), opened by a header
"SSH" button with its own icon (the brand bubble with a `>_` prompt). The button appears only on the local page, and only when
`GET /hub/hosts` answers 200 (a hub is configured); `/` stays the ordinary
chat UI. **Open** puts the remote's UI in a new browser tab, one named tab
per server. **Leave** on a remote page detaches and lands on `/#ssh`, which
reopens the launcher. A remote page names its host in a header badge and the
tab title. Stop is only offered in the launcher, and asks first. Session and
run counts are read only through a *healthy* attachment and with
`X-Ppxai-Hub-Attach: no`, which makes the hub answer 503 instead of
auto-attaching: without it, a refresh whose host list predated a Detach
re-attached the server (found in a live browser run).

All hosts share one browser origin, so `localStorage` is shared across hosts.
Today's keys are viewer preferences (theme, layout) where sharing is fine; any
future host-specific key must be namespaced by prefix.

### S7 — Security model

| Threat | Control |
|---|---|
| Another user on the remote host connects to the server | Unix socket 0600 in a 0700 dir; no TCP listener at all |
| Something on the remote reaches the socket anyway (same uid) | Per-launch bearer token, required — same uid is the owner's own trust boundary |
| A web page in the local browser drives the hub (CSRF, DNS rebinding) | The hub inherits `http.py`'s loopback-origin CORS and Host validation unchanged |
| Token disclosure to the browser | Hub injects the header; the token is never in a page, URL or `localStorage` |
| Unknown or changed host key | `BatchMode=yes` + the user's `known_hosts`; fail, never auto-accept |
| Path smuggling via host id | `id` pattern `[a-z0-9-]{1,32}`, looked up in the inventory, never interpolated into a command |

Out of scope for v1: multi-user hubs, exposing the hub beyond loopback, and
running the hub on a machine other than the browser's.

---

## Why this and not the alternatives

**Tunnels only (a port per host, browser switches origin).** Less code, but one
browser origin per host: per-origin `localStorage`, a CORS allowance per port,
the token in the browser, and no single place to show every host. Each of
those is a problem the hub removes by construction.

**`asyncssh` instead of system OpenSSH.** Finer-grained control and errors, but
a new dependency that must re-implement what the owner's `ssh` already does
(config aliases, agent, `ProxyJump`, hardware keys, `known_hosts`) and a new
PyInstaller hidden-import surface. The S2 Protocol keeps this swappable if
OpenSSH's error detail proves too coarse.

**Remote TCP port with a token.** Works, but any local user on the remote can
reach the port and only the token stands between them and a shell. A 0600
socket removes the listener other users could reach.

**Local UI against the remote API.** Would put local web assets against a
remote server of possibly another version — exactly the skew the schema guard
exists to detect. Serving the remote's own UI removes the skew.

## Open questions — owner answers 2026-09-26

1. **Where the hub runs — DECIDED: mounted in the local `ppxai-server`**,
   gated by `remote.hosts` being non-empty. Local and remote sessions share
   one origin and one picker; local is just host `local`. (Rejected: a
   `ppxai-desktop --hub` mode; a separate engine-less `ppxai-hub` entry point.)
2. **Config key — DECIDED: `remote.*`, a new top-level key** (a fourth axis
   beside ADR 0010's three), shaped as in S1.
3. **Windows OpenSSH forwarding to a remote unix socket — ✅ WORKS
   (measured 2026-09-26).** `OpenSSH_for_Windows_9.5p2` →
   Ubuntu 24.04 on WSL2 (sshd on port 2222):
   `ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes -L 127.0.0.1:<port>:/run/user/<uid>/<dir>/s.sock`
   forwarded HTTP to a Python listener on a 0600 socket in a 0700 directory
   under `$XDG_RUNTIME_DIR`. No TCP fallback is needed for this client.
   `$XDG_RUNTIME_DIR` (a per-user tmpfs, `/run/user/<uid>`) is the natural home
   for S3's socket; `~/.ppxai/run/sock/` stays the fallback where it is unset.
4. **Connection reuse — MEASURED 2026-09-26, optimisation deferred.** Same
   hosts. The WSL2 hop is loopback, so these numbers are tunnel overhead, not
   network latency:

   | Measurement | Result |
   |---|---|
   | `ssh -N -L` start → local port accepting | 652 ms |
   | Fresh `ssh … true` (new connection + auth) | 336–492 ms |
   | Server alone, in-host over the socket | 0.74 ms avg |
   | New SSH channel per request (HTTP/1.0) | 120 ms avg (78–139) |
   | One reused channel (HTTP/1.1 keep-alive) | 61 ms avg, **6 ms min**, 83 max |

   Conclusions: (a) one long-lived `ssh -N -L` per attached server is fine —
   connection cost is paid once; (b) the hub's proxy MUST pool keep-alive
   connections to the forward, since every new channel costs ~120 ms;
   (c) the 6 ms minimum vs 61 ms mean looks like a write-coalescing /
   delayed-ACK effect, not a floor — **not yet diagnosed**; measure against
   a real `ppxai-server` (uvicorn, not `http.server`) before tuning anything.
   **Real-server re-measure (2026-09-26, `ppxai-server` 1.19.3 on WSL2 over a
   loopback-TCP forward):** `/health` keep-alive ×50 = 64 ms avg, 31 min, 80
   max — the same shape as the `http.server` numbers, so the spread is the
   tunnel, not the test server. Still undiagnosed.

   **Real-server perimeter test, same run — 10/10 through the forward:**
   `/health`; `/` (web UI served, `APP_STATE_SCHEMA` injected);
   `/schema/app-state`; `/commands?client=web`; `/state`; `/v1/agent/runs`
   401 without a token, 401 with a wrong one, 200 with the right one;
   `Host: evil.example` → 400 on `/` and `/state` (`/health` is exempt by
   design, `http.py:403`); `/ws/terminal` round-trips a command through a PTY
   on the remote. Three findings for the design:

   - **Over a TCP forward the remote server sees `sshd` as a loopback peer**,
     so the loopback UI exemption applies and the UI works with no token —
     for the owner, and equally for every other local user on that host.
     This is the concrete case for S7's unix socket, and why a TCP fallback
     must never be the default.
   - **The PID a launcher records is not the server's.** The PyInstaller
     binary is a bootloader that forks the real server; killing the recorded
     PID left the server running (reparented to init, still listening). S3's
     `--announce` must record `os.getpid()` from inside the server, and
     `stop` must go through the server (a shutdown request), not a signal to
     a launcher PID.
   - **The server shuts itself down after 5 idle minutes** ("Auto-shutdown: 5
     minutes of inactivity"). A detached remote server will therefore
     disappear on its own. S3/S4 must either disable the idle timer for
     `--detach` launches or treat "gone after idle" as a normal state, not
     `degraded`.
5. **Remote hosts without the S3 contract — DECIDED: refuse** with a message
   naming the remote's version and the minimum that has the contract. No TCP
   fallback launch.

## Future / proper solution

- A VSCode and TUI client of the same hub (they already take one server URL).
- Remote tool execution from a local engine, if a host without ppxai installed
  ever matters — needs the exec/filesystem abstraction this record avoids.
- Reusing S2 for the deferred k8s terminal mode (`routes/terminal.py:5`).

## Triggers to revisit

- A remote host where ppxai cannot be installed.
- OpenSSH error detail proves too coarse for S4's state machine.
- A second user needs to share one hub.
