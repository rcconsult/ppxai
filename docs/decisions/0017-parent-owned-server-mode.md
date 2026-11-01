# ADR 0017: A parent-owned server mode (`ppxai-server --owned`)

- **Status:** Implemented (2026-11-01, `feature/v1.19.5`). Accepted 2026-11-01 (owner).
- **Deciders:** owner (owns both ppxai and tai)
- **Target:** v1.19.5 (owner, 2026-11-01).
- **Related:** ADR 0013 (the SSH remote backend, whose `--uds --announce`
  contract this mirrors over TCP), `ppxai/server/auth.py` (the loopback
  exemptions this mode turns off), tai ADR 0001 and 0010 (tai launches
  ppxai-server as its own child).

## Context

tai, a native client, will start `ppxai-server` as its own child process
and talk to it over HTTP. On Linux and macOS it can use ADR 0013's
`--uds --announce`: a 0600 socket, a per-launch token, and one JSON entry
that tells the parent where the server is. On Windows that path is refused
(`_run_announced`: "--uds/--announce/--detach need a POSIX host"). Python
3.13 and 3.15 on Windows have no `socket.AF_UNIX` and no
`asyncio.start_unix_server`, so plain `--host/--port` is the only option.
A server owned by a parent process has three gaps there:

1. **The parent's token can be ignored.** `PPXAI_API_TOKEN` in the child's
   environment is read only by an `EnvSecretProvider` in the auth chain. A
   user config whose chain is a `file` store alone never consults it
   (`_provider_enforces_auth`), so the parent's bearer gets 401. Only
   `_run_announced` forces the env provider in.
2. **Loopback requests skip auth.** `check_request` exempts a token-less
   loopback request to everything outside `/v1/agent*` and `/v1/tokens`
   (`_is_loopback_ui_request`), plus the bootstrap mint. That covers
   `/chat` (with tools) and `/v1/oneshot`. It is deliberate, because the
   local browser UI sends no bearer. But it means any local process,
   including another Windows user's, can drive a server whatever token
   its parent set. ppxai-desktop on port 54320 has the same exposure
   today.
3. **The port races.** The parent must pick a free port and pass
   `--port`, and something else can take it first. Nothing reports a
   port-0 bind back.

Options weighed with the owner on 2026-11-01:
- (A) no change, the risk accepted;
- (B) an opt-in that forces the env token and drops the exemptions;
- (C) B plus a port-0 bind reported as JSON;
- (D) C plus exiting when the parent goes away;
- (E) TCP `--announce` on Windows, or a named pipe.

E contradicts ADR 0013's explicit "socket-only, never TCP" for the
announce contract, and uvicorn has no named-pipe transport. The owner
chose B and C as one mode, with D on POSIX only.

## Decision

Add one opt-in flag, `ppxai-server --owned`, for a server whose lifetime
and credentials belong to the process that started it. In this mode:

1. **The token comes from the parent, and it is required.**
   `PPXAI_API_TOKEN` must be set and non-empty; otherwise the server
   exits with status 2 before binding. An `EnvSecretProvider` is put
   first in the auth chain, exactly as `_run_announced` does. The server
   never generates or prints a token, so no secret crosses stdout.
2. **Every route needs the bearer.** Both loopback exemptions are off:
   the desktop/web UI one and the bootstrap mint. `/health` and
   `/status` need the bearer too, so a parent's bearer probe of
   `/health` proves in one request that the server is ready and that it
   enforces the parent's token (a probe without it gets 401). CORS
   preflight (`OPTIONS`) stays exempt, as everywhere. The web UI served
   by such a server cannot load, because a browser sends no bearer.
   That is intended for a headless child.
3. **Port 0, reported once.** `--port` defaults to 0 in this mode. The
   server binds `127.0.0.1` itself before it initializes, then prints
   exactly one JSON line as the first line on stdout:
   `{"host": "127.0.0.1", "port": <n>, "pid": <pid>, "version": "<x.y.z>"}`.
   Anything initialization would print goes to stderr until that line is
   out. The line means "bound"; readiness is the bearer `/health` probe,
   because connections queue in the listen backlog until uvicorn accepts.
   `--host` must be loopback: a wide bind would publish a server meant
   for one parent.
4. **It exits with its parent (POSIX only).** On Linux and macOS, when
   stdin is a pipe (not a TTY), EOF on stdin triggers the normal graceful
   shutdown, so a crashed parent does not leave an orphan holding a port.
   Windows is excluded because the parent's job object with
   kill-on-close already removes the orphan case there (tai's design).
5. **The things a parent does not want are off:** the idle-shutdown
   monitor (the parent decides when the server ends) and the SSH hub (a
   child is nobody's hub), as on an announced server. No registry entry
   is written: the parent already holds the address.

The flag cannot be combined with `--uds`, `--announce`, `--detach` or
`--reload` (usage error, status 2). Without `--owned`, nothing changes:
ppxai-desktop, the web UI and the VSCode extension keep today's
behaviour.

## Consequences

- tai, or any parent, gets a closed server on every OS with one launch
  shape and no port race.
- The loopback exposure stays for the desktop/web default. Closing that
  needs a bearer in the browser, which is a separate design.
- The JSON line is a new stable contract, one line with four keys. A
  key may be added later, but never removed or renamed without an ADR.
- The bound socket is handed to uvicorn (`Server.serve(sockets=[...])`)
  instead of being bound by uvicorn, so the port the parent reads is
  the port that serves.
