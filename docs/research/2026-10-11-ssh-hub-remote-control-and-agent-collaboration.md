# SSH hub for remote control and cross-host agent collaboration — reference notes

**Date:** 2026-10-11
**Status:** Reference (session research; nothing built, no ADR yet)
**Related:** [../decisions/0013-ssh-remote-backend.md](../decisions/0013-ssh-remote-backend.md),
[../decisions/0003-agent-platform-architecture.md](../decisions/0003-agent-platform-architecture.md),
[../plan-ssh-remote-backend.md](../plan-ssh-remote-backend.md)

Prompted by the question: can ADR 0013's SSH hub be used for remote control
of ppxai on other hosts, and for ppxai agents on different hosts working
together?

## Source basis

Code reading on `feature/v1.19.4` at `f966c009`:

- `ppxai/server/routes/remote_hub.py` (hub gate, proxy, `/hub/*` API)
- `ppxai/server/routes/agent_v1.py` (`/v1/agent/*` routes)
- `ppxai/server/auth.py` (loopback exemptions)
- ADR 0013 (scope, threat table, future work)

**Nothing here was live-tested.** The finding under "The hub is not
browser-only" comes from reading the code and has not been reproduced.

## Short answer

- **Remote control: yes, today.** It is what the hub was built for.
- **Agents working together across hosts: no.** The tunnel exists, but
  there is no cross-host run, delegation or messaging concept.

## What the hub does today

ADR 0013, all phases 0–6 done including the owner trial; unreleased.

- Off unless `remote.hosts` is configured. With no hosts, every hub path
  answers 404 exactly as an unknown path does.
- Transport: the system `ssh -N -L` per remote server, `BatchMode=yes`,
  the user's `known_hosts`. The remote server listens on a 0600 unix
  socket (`--uds`); the local end is a unix socket on POSIX and loopback
  TCP on Windows.
- `/hub/*` API (`remote_hub.py:256-310`): list hosts, list and launch
  servers on a host, attach, detach and stop a server.
- Proxy (`remote_hub.py:381-434`): `/h/<host>/<id>/<path>`, any HTTP
  method, streamed both ways (SSE unbuffered), websockets bridged. **There
  is no path allowlist**, so the remote's web UI, `/command/*`, `/task`,
  `/v1/agent/*` and `/ws/terminal` all pass through.
- The hub injects the remote server's bearer token from its registry entry
  and sets `Host: localhost`. It drops the caller's `Authorization`,
  `Cookie`, `Origin`, `Referer` and forwarding headers. The token never
  reaches the browser.
- Tools run on the remote host, under the remote's own config:
  `execution.task.enabled` (default off), sandbox, consent and egress
  ceiling.
- Hubs never chain: an announced server doesn't run a hub of its own.

**Limits:**

- Web UI only. VSCode and TUI clients of the hub are ADR 0013 future work.
- Single user. Multi-user hubs and a hub beyond loopback are out of scope
  for v1 (ADR 0013:322).
- A consent prompt from a remote `/task` run can be answered only in that
  remote server's own UI, opened through the hub.

"Remote control" here means driving ppxai servers on other hosts. Claude
Code's Remote Control feature is unrelated: it relays through Anthropic's
servers and gains nothing from this tunnel.

## The hub is not browser-only (finding)

ADR 0013 frames the hub as a local-browser surface. The gate is looser
than that framing:

- `_gate` (`remote_hub.py:225`) requires a direct loopback peer.
- `_cross_site` (`remote_hub.py:232`) blocks only when `Sec-Fetch-Site` is
  cross-site or same-site, or when an `Origin` header is present and
  differs from the server's own. **With no `Origin` header it returns
  False**, with the comment "not a browser request".
- `/h/...` is not under `_LOOPBACK_PROTECTED_PREFIXES` (`/v1/agent`,
  `/v1/tokens`, `auth.py:182`), so a loopback request to it needs no local
  bearer.

**Consequence (code reading, not reproduced):** any local process that can
reach the local `ppxai-server` can call
`POST /h/<host>/<id>/v1/agent/task`. The hub then injects the remote's
token, and the remote accepts the request as that token's owner. That
includes `curl` and a local agent run. Locally, `/v1/agent/task` stays
bearer-protected even from loopback (`auth.py:176-182`). Through the hub,
the same endpoint on a remote host does not.

Whether this matters depends on who can reach the local server:

- **Same OS user:** no new power. That user's processes can already run
  `ssh` with the same keys.
- **Another OS user on the same machine:** the `/h/...` routes are served on
  the local server's own port, usually loopback TCP. That's true on any OS;
  the unix socket is only the tunnel's local end. Any OS user who can
  connect to that port gets the owner's remote servers, including their
  terminal websocket. ADR 0013's threat table does not list this case.

Two follow-ups:

- **Decide if it's intended.** Either way, say so in ADR 0013's threat
  table.
- **Cover it with a test,** so the behaviour can't change silently in
  either direction.

## What cross-host agent collaboration would need

What already exists: an authenticated, multiplexed tunnel to a live remote
server, with token injection. What is missing:

| Gap | Today | Needed |
|---|---|---|
| Cross-host run concept | `/v1/agent/*` has no host. `spawn_subagent` (`engine/tools/agent_spawn.py`) creates children in one local registry. `/task` takes no host argument. | A "remote subagent": a local run that starts a run on a remote's `/v1/agent/task`, follows `/runs/{id}/events`, and collects the result into the local parent run. This fits the existing parent/child model. |
| Caller path | Only the hub's HTTP routes, built for a browser. | An engine-side client that uses the tunnel and the token directly. The proxy could be reused from the engine, but should not be reached by an engine calling its own server over HTTP. |
| Consent | A remote prompt is answerable only in that remote server's UI. | Relay `consent_required` events to the local UI, and send the answer back through the remote's `/runs/{id}/respond`. |
| Authorization | Hub requests act as the single owner of the remote's token. | An explicit task grant naming the hosts a run may delegate to, plus a cap on top of it, like `execution.egress_ceiling`. Delegation should be off by default, like `execution.task.enabled`. |
| Lifetime | — | Cancelling a local run cancels its remote children. Budgets and timeouts carry across hosts. A tunnel drop leaves the remote run in a defined state (`degraded`/`gone` mapped to run states). |
| Cost | `/cost` counts tiers per server. | Remote usage reported back into the local session's `/cost` (ADR 0008). |
| Threat model | ADR 0013 covers browser attacks and token leaks; nothing on agents. | An addendum: a prompt-injected local run delegating tool-capable work to other machines, delegation loops (hubs don't chain, but a remote run could call back), and the finding above. |

Not proposed: a local engine driving remote tools directly. ADR 0013:35-42
rules this out because shell, filesystem, editor, terminal and preview call
`subprocess`/`os`/`pathlib` directly, with no exec abstraction. Delegating
whole runs avoids that problem, since the remote ppxai runs its own tools.

## Order, if pursued

1. **Fleet view, read-only:** list each attached remote's
   `/v1/agent/runs` in the hub UI. No tool risk.
2. **Settle the no-`Origin` gate behaviour** and record it in ADR 0013's
   threat table.
3. **ADR for remote subagents,** covering the gap table above, before any
   code.
4. **Remote subagent, behind a default-off grant.** Start with
   `/task --host <id>` from the web client, then extend to the other
   clients.

## Open next steps (not started)

- Reproduce the no-`Origin` finding against a test hub.
- Decide whether to draft the remote-subagent ADR.
