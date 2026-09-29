# Plan — SSH remote backend (ADR 0013)

**Date:** 2026-09-26
**Status:** ✅ **Complete.** Phases 0–6 implemented on `feature/v1.19.4`
(unreleased); the owner trial passed 2026-09-29 and the owner accepted ADR 0013
the same day, after the two items the trial left open were done (below). Implements [ADR 0013](decisions/0013-ssh-remote-backend.md).
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
| Q4 | Connection reuse | ✅ Measured: one long-lived forward per server; the proxy must pool keep-alive connections. The 6-vs-61 ms spread is undiagnosed; deferred at acceptance (ADR Q4) |
| Q5 | Hosts without the S3 contract | ✅ Owner: refuse |

Exit: ADR 0013 revised in place with the answers, still Proposed. **Phase 0 is complete.**

**Test rig for every later phase:** Ubuntu 24.04 on WSL2 with sshd on port 2222
(`ssh -p 2222 <user>@localhost`-style), which has `ppxai-server` installed. The live
opt-in tests read the destination from an env var; nothing host-specific goes
in the repo.

## Phase 1 — S3, the remote-side contract (`ppxai-server` only)

**Status (2026-09-27): implemented** — `ppxai/server/registry.py`, `ppxai-server --uds/--announce/--detach/--list`, `tests/test_server_registry.py`. Two findings shaped it: uvicorn makes a socket it binds itself 0666, so the server binds it and passes the fd; and `/health` is NOT exempt from auth (only from the Host check), so liveness probes and `--list` present the entry's token. The POSIX launch tests run on Ubuntu 24.04 (WSL2) and macOS before the owner trial.

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

**Status (2026-09-28): implemented** on `feature/v1.19.4` — `ppxai/remote/{transport,openssh}.py`, `tests/test_remote_transport.py`, `tests/remote_fakes.py` (`FakeTransport`), `tests/fake_ssh.py` (a stand-in ssh binary: runs the command through a real local `sh`, so the quoting table is end-to-end, and relays `-L` forwards to a unix socket), and Guard 3b in `tests/test_no_new_lazy_imports.py`. Decisions made while building it:

- **Local end of a forward:** a unix socket in a private 0700 `mkdtemp` dir on POSIX (`StreamLocalBindMask=0177`), loopback TCP on Windows. The hub is then the only local process that can reach a forward on POSIX.
- **CR/LF refused in argv**, not quoted: `sh` accepts them inside single quotes, csh-family login shells do not, and no ppxai command needs one.
- **Destination validation:** one `ssh` word, never starting with `-` (option injection such as `-oProxyCommand=…`).
- **A forward's readiness is "the local end accepts"**, not "the remote socket answers". Real ssh accepts locally and only fails the channel; liveness is S4's `/health` probe.
- **Exception names end in `Error`** (repo lint, N818); the ADR's S2 text is updated to match.

Verified against the real OpenSSH 8.6 client on macOS: unknown host → `HostUnreachableError`, closed port → the same. The opt-in live class runs with `PPXAI_TEST_SSH_DEST=<destination>` (and `PPXAI_TEST_SSH_COMMAND` for an ssh argv prefix, e.g. a scratch `UserKnownHostsFile`). **Linux (WSL2 Ubuntu 24.04, 706a60dd):** all 95 incl. the live class against a real sshd. **Windows (706a60dd):** a live `OpenSSHTransport` TCP forward from Windows OpenSSH to a WSL2 `ppxai-server --uds` reached the server (`/health` 401 without the token, as designed) and the port closed after `close()`; two test-only defects found by the peers were fixed (an echo server dying on EPIPE on Linux, `706a60dd`; the fake ssh writing stderr in text mode on Windows).

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

**Status (2026-09-28): implemented** on `feature/v1.19.4` — `ppxai/remote/inventory.py` (S1 `remote.hosts` validation; not yet read from config — Phase 4 wires it), `contract.py` (the hub's own contract record, pinned to the server's by a test), `manager.py`; `tests/test_remote_manager.py`. What the ADR did not say and the build decided is recorded under S4 "As built". Besides the fake-driven state-machine tests, the remote shell snippets (binary discovery, `cd` into the workdir) run through a real `sh`, and one slow test launches a real `ppxai-server --uds --announce --detach` through the fake ssh, attaches over a real forward, health-checks it and stops it with `POST /shutdown`.

- State machine exactly as drawn in the ADR; every transition an event the
  picker can render.
- `servers(host)` parses S3 `--list --json`; unknown `contract` → typed
  refusal naming both numbers.
- `detach` never stops a remote server; `stop` is explicit.

Tests: every transition driven through `FakeTransport`, including health
failure → degraded → recovery, and a transport dying mid-forward.

## Phase 4 — S5, the hub proxy

**Status (2026-09-28): implemented** on `feature/v1.19.4` — `ppxai/server/routes/remote_hub.py` (the `/h/<host>/<id>/…` proxy plus a `/hub/*` control API the picker will use), `ppxai/config/remote.py` + the `remote` key in the loader's top-level whitelist, and the lifespan hook in `ppxai/server/http.py`. Built on top of the v1.19.4 websocket guard (`fix/v1.19.4`, merged in), which the investigation for this phase found. Decisions:

- **Off means absent.** Without `remote.hosts`, every hub path answers byte-for-byte like an unknown path, no manager exists and nothing is spawned. An announced (remote-side) server never runs a hub. A malformed `remote` block is logged and leaves the hub off; it never stops the server. The owner required that the k8s coder pods be unaffected: `tests/test_remote_hub_coder_fence.py` runs the real app with the coder pods' env and pins all of this, including that a pod which *had* `remote.hosts` still shows nothing to the ingress.
- **Loopback only, same-origin for writes.** The hub answers a direct loopback peer (no forwarding headers) only. A proxied non-GET, a websocket and every control POST must be same-origin (Origin equal to the hub's own, `Sec-Fetch-Site` not cross/same-site); control POSTs also need `application/json`, which forces a preflight.
- **Auto-attach on first proxied request**, so a reload after a hub restart works; a non-healthy attachment is a 503 with `Retry-After: 5`, a dead forward a 502.
- **Proxy details:** streamed both ways (SSE measured unbuffered), keep-alive client pooled per attachment (ADR Q4), `Host: localhost`, token injected, the browser's `Authorization`/`Cookie`/`Origin`/`Referer`/forwarding headers dropped; relative `Location` and cookie `Path` get the prefix; repeated `Set-Cookie` preserved. `trust_env=False` / `proxy=None` everywhere: an `HTTP(S)_PROXY` in the environment must never route a loopback or socket hop through a corporate proxy.
- **Control API:** `GET /hub/hosts`, `GET /hub/hosts/<host>/servers`, `POST /hub/hosts/<host>/servers` (launch), `POST /hub/hosts/<host>/servers/<id>/attach|detach|stop`. Errors are typed: 404 unknown host/server, 409 unsupported/old/unknown-contract, 502 transport, with OpenSSH's text in `detail`.

Tests: `tests/test_remote_hub.py` (two real uvicorn servers — the hub router and a fake remote on a unix socket and on TCP — 25 cases × 2 transports; mutation-checked: a buffering proxy and a missing loopback gate both fail it), the coder fence (22 cases; mutation-checked: dropping `remote` from the loader whitelist or the loopback gate fails it), and `tests/test_remote_hub_e2e.py` (slow): a real `ppxai-server` hub, configured by a real config file, launches a second real `ppxai-server` through the production `OpenSSHTransport` (its `ssh` a PATH shim around `tests/fake_ssh.py`), serves the remote's own web UI and terminal through `/h/lab/<id>/`, and stops it.

**Windows note:** "`ssh` from PATH" means `ssh.exe`. `CreateProcess` appends only `.exe` and ignores PATHEXT, so an `ssh.cmd`/`ssh.bat` wrapper earlier on PATH is never run (measured by win32-ppxai, 2026-09-28). Host-specific options belong in `~/.ssh/config`, as S1 says.

Live results recorded for Phases 2–3 (2026-09-28): a Windows hub (TCP local end) and a Linux hub (real OpenSSH, unix-socket local end: socket 0600 in a 0700 dir) each ran launch → attach (healthy) → stop (gone) against a real WSL2 sshd, with nothing left behind.

- `/h/<host>/<server-id>/…` → forwarded endpoint, prefix stripped.
- Streaming for SSE and chunked bodies; websocket upgrade for `/ws/terminal`.
- `Authorization` injected; `Host: localhost`; no `X-Forwarded-*`.
- Host id validated against the inventory before any lookup.

Tests: an in-process fake remote (a real `ppxai-server` app on a UDS or a
loopback port) behind `FakeTransport`: an SSE chat stream arrives unbuffered;
the terminal websocket round-trips; a request never carries the token back to
the browser; an unknown host id is a 404, never a forward.

## Phase 5 — S6, web client

**Status (2026-09-28): item 1 (prefix recognition) landed early**, because without it phase 4 was misleading, not merely incomplete. win32-ppxai's live hub run from Windows loaded `/h/wsl/<id>/`: HTML and assets came through the proxy, but every API call went to the LOCAL hub server, so the page showed and restored the Windows session. `app.js` now derives its prefix in one place (`servedPathPrefix()`: `/h/<host>/<id>` or `/s/<slug>`), and `handleQuit()` under `/h/` detaches and returns to `/`, never stopping anything; the coder `/s/` branch is unchanged (`tests/test_web_hub_prefix.py`, `tests/test_session_end_workflows.py`). The same run found that a FROZEN `ppxai-server` reports and runs in its binary's directory, because the entry script chdirs there; the launch directory is now recorded first and restored on the announce path (`tests/test_announced_workdir.py`). The picker (item 2) is still to do.

**Status (2026-09-28, later): items 2–4 implemented** as the owner's design, the **SSH Launcher** in the right split pane (ADR S6 "As built"): `ppxai/web/components/views/ssh-launcher-view.js`, the header button, host badge and `/#ssh` wiring in `app.js`, styles in `styles.css`. Tests: `tests/test_ssh_launcher_view.py` runs the renderer and the view under node with a fake `fetch` (escaping, no token rendered, counts only through healthy attachments and never attaching, Stop asks, Detach doesn't, one named tab per server, overlapping refreshes coalesce; mutation-checked), `tests/test_web_hub_prefix.py` pins Leave → `/#ssh`. A live Playwright run against a real hub and a real remote `ppxai-server` (fake ssh shim, as in the e2e test) walked button → launcher → New server → Open (new tab: badge `🖥 lab · <id8>`, title `ppxai — lab`, no SSH button) → Leave (back on `/`, launcher open, server "not attached") → Stop, with no console errors. That run found the one server change: the launcher's count reads re-attached a just-detached server through the proxy's auto-attach, so `X-Ppxai-Hub-Attach: no` now disables auto-attach per request (`tests/test_remote_hub.py::TestObserveOnly`). The scratch run became `tests/e2e/ssh-launcher.spec.ts` on 2026-09-29 (`npm run test:ssh`). The run on Windows against a real sshd is done: phase 6.

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

**Status (2026-09-29): PASSED**, run by the owner with win32-ppxai.

- **Setup.** Hub: the installed Windows `ppxai-server` 1.19.4 (built from
  `297f65d8`) with `remote.hosts = [{"id": "wsl", "ssh": "<alias>"}]`, the
  alias an `~/.ssh/config` entry for a WSL2 sshd on a local port. Remote:
  WSL2 Ubuntu 24.04 with a one-file `ppxai-server` (PyInstaller 6.17) built
  from `e3746f65`. Real OpenSSH, real keys; everything driven from the web
  SSH Launcher.
- **Launch.** "New server" started a detached server; its own unpack dir
  intact, no deleted mappings.
- **Open.** The remote UI in a new tab, its API under `/h/wsl/<id>/`.
- **Chat.** A plain turn answered in 2.0 s (`gemini-3.8-flash`); a tool turn
  (`get_weather`) in 7.5 s; three more turns, no errors in the logs.
- **Commands and terminal.** `/help`; `/terminal` opened a login shell in the
  remote home directory, used twice.
- **Detach and re-attach.** Leave, then Open again: the same session was
  restored with its new messages (68 → 82), so it persisted across the
  detach.
- **Stop.** `POST /shutdown` 200, a clean stop after about 6 minutes; the
  registry entry, the socket and the unpack dir were gone, with no new stale
  unpack dir.

**Findings, all fixed before the pass:**

1. A one-file `ppxai-server --detach` ran out of an unpack dir its launcher
   had deleted (the launcher forked, then exited, so the bootloader cleaned
   up under the daemon): every lazily loaded module failed, and chat with it
   (`…/_MEI…/base_library.zip: No such file`). Fixed in `e3746f65`: a frozen
   launcher re-spawns the binary with `PYINSTALLER_RESET_ENVIRONMENT=1`, so
   the daemon's bootloader owns its own unpack dir
   (`tests/test_detach_frozen.py`). Verified with real one-file builds on
   WSL and macOS Intel; Windows has no `--detach`.
2. `scripts/gateway-smoke.py` left a slow-starting server running after a
   startup timeout. Fixed in `cbd0d8e2` (60 s start wait on Windows; cleanup
   watches for a late listener).
3. The web client's API calls escaped the `/h/` prefix, and a frozen server
   reported its binary's directory as its workdir. Both fixed in `5c539936`
   (phase 5 above).

**Left open by the trial, done 2026-09-29** (the owner first deferred both,
then asked for them before accepting the ADR):

- A Playwright spec for the Launcher: `tests/e2e/ssh-launcher.spec.ts`,
  its own `ssh` project, run with `npm run test:ssh` in `tests/e2e/`
  (POSIX only; the remote is `tests/fake_ssh.py`, so no host or key).
- Remote builds without `e3746f65`: an older one-file build launched, then
  failed every chat, and the version number could not say so. The registry
  moved to contract 2 (same fields; the new meaning is "`--detach` works
  from a one-file build"), the hub retired contract 1, and before a launch
  the hub runs `ppxai-server --registry-contract` on the host and refuses a
  binary without it, or with a contract it does not read, before anything
  starts. `MIN_SERVER_VERSION` is gone. See ADR S3 "As built".

---

## Not in this plan

VSCode/TUI clients of the hub, remote tool execution from a local engine,
multi-user hubs, a hub reachable beyond loopback.
