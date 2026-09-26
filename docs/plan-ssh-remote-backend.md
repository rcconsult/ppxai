# Plan — SSH remote backend (ADR 0013)

**Date:** 2026-09-26
**Status:** Draft, not started. Implements
[ADR 0013](decisions/0013-ssh-remote-backend.md) once the ADR's open questions
are resolved.
**Scope:** web client first. VSCode and the TUIs follow only after the web
path is proven.

Each phase is a gate: it lands with its tests, is tried by the owner, and the
next phase starts on instruction.

---

## Phase 0 — Resolve the ADR's open questions (no code)

| # | Question | How it is decided |
|---|---|---|
| Q1 | Where the hub runs | ✅ Owner: mounted in the local `ppxai-server` |
| Q2 | Config key for the host inventory | ✅ Owner: new top-level `remote.*` |
| Q3 | Windows OpenSSH → remote unix-socket forward | ✅ Measured 2026-09-26 against WSL2 sshd: works with the stock Windows client |
| Q4 | Connection reuse | ✅ Measured: one long-lived forward per server; the proxy must pool keep-alive connections. The 6-vs-61 ms spread is undiagnosed — re-measure against uvicorn in Phase 4 |
| Q5 | Hosts without the S3 contract | ✅ Owner: refuse |

Exit: ADR 0013 revised in place with the answers, still Proposed. **Phase 0 is complete.**

**Test rig for every later phase:** Ubuntu 24.04 on WSL2 with sshd on port 2222
(`ssh -p 2222 <user>@localhost`-style), which has `ppxai-server` installed. The live
opt-in tests read the destination from an env var; nothing host-specific goes
in the repo.

## Phase 1 — S3, the remote-side contract (`ppxai-server` only)

- `--uds <path>`: `uvicorn.Config(uds=...)`, socket dir 0700, socket 0600
  before the first accept.
- `--announce`: per-launch token into the process's `PPXAI_API_TOKEN`,
  registry entry written 0600, JSON echoed on stdout.
- `--detach`: daemonise (POSIX); refuse with a clear message on Windows.
- `--list --json`: live entries only; dead pid or dead socket → entry removed.
- Registry schema pinned by a JSON fixture and a test that fails on an
  unversioned change (`contract` must bump).

Tests: launch → list → `/health` over the socket with and without the token →
kill → list prunes. All local, POSIX-gated where the OS demands it.

## Phase 2 — S2, `RemoteTransport` + `OpenSSHTransport`

- `ppxai/remote/transport.py`: the Protocol, `RunResult`, `LocalEndpoint`,
  typed errors.
- `OpenSSHTransport`: `BatchMode=yes`, argv quoting in one function,
  `ssh -N -L` for forwards, stderr mapped to typed errors.
- `FakeTransport` for every later phase's tests.
- Layering fence: `ppxai/remote/` imports nothing from `engine/` or
  `commands/`.

Tests: argv quoting table (spaces, quotes, `$`, newlines); stderr → error-type
table from captured real OpenSSH messages; one opt-in live test against a host
named by an env var, skipped otherwise.

## Phase 3 — S4, `RemoteSessionManager`

- State machine exactly as drawn in the ADR; every transition an event the
  picker can render.
- `servers(host)` parses S3 `--list --json`; unknown `contract` → typed
  refusal naming both numbers.
- `detach` never stops a remote server; `stop` is explicit.

Tests: every transition driven through `FakeTransport`, including health
failure → degraded → recovery, and a transport dying mid-forward.

## Phase 4 — S5, the hub proxy

- `/h/<host>/<server-id>/…` → forwarded endpoint, prefix stripped.
- Streaming for SSE and chunked bodies; websocket upgrade for `/ws/terminal`.
- `Authorization` injected; `Host: localhost`; no `X-Forwarded-*`.
- Host id validated against the inventory before any lookup.

Tests: an in-process fake remote (a real `ppxai-server` app on a UDS or a
loopback port) behind `FakeTransport`: an SSE chat stream arrives unbuffered;
the terminal websocket round-trips; a request never carries the token back to
the browser; an unknown host id is a 404, never a forward.

## Phase 5 — S6, web client

- `app.js` prefix recognition: `/h/<host>/<id>` alongside `/s/<user>`.
- `handleQuit()`: under `/h/`, detach and return to the picker.
- Picker view: hosts + state, servers per host, sessions and runs per server
  via the remote's existing `/sessions` and `/v1/agent/runs`.
- Playwright: picker renders a fake inventory; attaching navigates into
  `/h/<host>/<id>/`; Leave returns to the picker without a stop call.

## Phase 6 — Owner trial

Real hosts, real keys: launch from the picker, chat with tools, open the
terminal, detach, re-attach from another tab, see the session still there,
stop. Findings feed back into the ADR before acceptance.

---

## Not in this plan

VSCode/TUI clients of the hub, remote tool execution from a local engine,
multi-user hubs, a hub reachable beyond loopback.
