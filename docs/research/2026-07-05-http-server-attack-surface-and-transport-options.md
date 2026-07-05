# The out-of-process HTTP server as an attack surface — transport options for ppxai

**Date:** 2026-07-05
**Status:** Reference (session research; code-verified against `feature/v1.19.0` @ `6add04f6`)
**Related:**
- [2026-06-18-pi-coding-agent-comparison.md](2026-06-18-pi-coding-agent-comparison.md) — Pi's serverless in-process TS harness (the reference model)
- [2026-07-05-tauri-desktop-shell-analysis.md](2026-07-05-tauri-desktop-shell-analysis.md) — desktop-shell packaging (adjacent, not the same question)
- [2026-06-24-ppxai-sdk-mutation-tools-for-sre-agents.md](2026-06-24-ppxai-sdk-mutation-tools-for-sre-agents.md) — the SDK/embedded model for ppxai-sre
- [../decisions/0003-agent-platform-architecture.md](../decisions/0003-agent-platform-architecture.md)

## The question

ppxai runs its engine behind an **out-of-process HTTP server** (FastAPI/uvicorn).
This was an early decision to speed feature delivery — one server, many clients
(Rich TUI, Textual TUI, web, VSCode) over HTTP+SSE. Pi (the TS coding agent)
deliberately has **no server**: the whole harness is in-process TypeScript. The
out-of-process server carries its own security attack surface. What are ppxai's
options, and how does the sister repo `../ppxai-sre` (which consumes ppxai) constrain them?

## The attack surface (code-verified, default install)

On a default desktop install the server is an **unauthenticated loopback HTTP
service with wide-open CORS**:

1. **Auth is opt-in, default OFF.** `PPXAI_API_TOKEN` unset ⇒ every request is
   unauthenticated ([`server/auth.py:4-8`](../../ppxai/server/auth.py)). This is
   deliberate for the loopback desktop UX (TUIs/web/VSCode carry no bearer), but
   it means the default posture is "no auth."
2. **CORS is `allow_origins=["*"]` with `allow_credentials=True`**
   ([`server/http.py:193-201`](../../ppxai/server/http.py)). Any web origin the
   user visits can script requests to `127.0.0.1:54320` — the classic
   **localhost-service DNS-rebinding / CSRF** exposure. A malicious page can drive
   the local engine (send chats, spend the user's provider tokens/$, read
   sessions, and — with the tool tiers enabled — reach the tool surface).
3. **Bind is loopback by default** (`DEFAULT_HOST=127.0.0.1`) but `--host 0.0.0.0`
   is a documented one-flag exposure ([Pi-comparison doc / `http.py:10`](../../ppxai/server/http.py)),
   at which point "auth default-off" becomes a network-reachable unauthenticated
   engine.
4. **The port is a shared, discoverable rendezvous.** Any local process (any user
   account on a multi-user box; any malware) can find `:54320` and talk to it. In
   Pi's in-process model there is **no port, no listener, no local-RPC surface** —
   the attack surface simply doesn't exist because there's nothing to connect to.
5. **The v1.19.0 agent platform widens the blast radius of (1)–(4).** The tool-capable
   `/task` tier, `spawn_subagent`, egress allowlists, and secret sources all sit
   behind the same HTTP boundary. Mitigations exist (tier default-off, loopback
   auth carve-outs, SSRF guard, per-run authz) precisely *because* the HTTP
   surface is real — they are the tax the transport imposes.

**Summary:** the out-of-process server converts "run some Python" into "expose a
long-lived, discoverable, default-unauthenticated, permissive-CORS network
service on the user's machine." Every hardening item in debt Item 37 (loopback
spoofing, forwarded-header trust, SSRF, owner-scoping, token verification) is a
cost of *having a server*, not a cost of the engine.

## Why the server exists (the value it buys — don't discard lightly)

The server is not gratuitous. It is the **fan-out point for four clients + external
consumers**:

- One engine instance serves Rich TUI, Textual TUI, web, and VSCode simultaneously,
  with `AppState` sync + SSE push + the command envelope keeping them consistent.
- It is the **stable, semver-versioned external product**: `POST /v1/oneshot` and
  `/v1/agent/*` are how *other software* (ppxai-sre) consumes ppxai. That is a
  deliberate Stage-2 goal, not an accident.
- SSE streaming, background agent runs, and the durable run registry all assume a
  persistent process a client attaches to.

Pi has none of this because Pi is **one developer, one process, one context
window**. ppxai is **multi-client + an API-addressable governed backend**. The
Pi-comparison doc already pins this: *"which is precisely why it needs bearer
auth, egress firewalls, and owner-scoped runs that Pi explicitly does NOT want."*
So "just remove the server like Pi" is not a like-for-like move — it would delete
the multi-client fan-out and the external gateway that are core to what ppxai *is*.

## The key insight: there are TWO consumers with OPPOSITE needs

The transport decision is not one decision. Two distinct consumers pull opposite ways:

| Consumer | What it needs | Server verdict |
|---|---|---|
| **Interactive desktop user** (TUIs, web, VSCode, single machine) | Local engine + streaming; NO network service; no attack surface | Server is **pure liability** here — an in-process or local-IPC transport is strictly safer |
| **ppxai-sre** (uses ppxai as a dependency/SDK; per the [SDK model](2026-06-24-ppxai-sdk-mutation-tools-for-sre-agents.md)) | An **embedded** sandboxed run runtime it drives in-process — NOT a remote HTTP server it POSTs to | Server is **also unnecessary** here — the SDK model embeds `EngineClient` + the sandbox, no HTTP hop |
| **Cluster/gateway deployment** (ppxai-server in a pod, many agents call `/v1/*`) | The HTTP gateway, WITH auth mandatory + NetworkPolicy | Server is **required** — and here the attack surface is *managed* (bearer on, bound, behind NetworkPolicy) |

**This is the crux:** the two *local* consumers (desktop user, ppxai-sre-as-SDK)
do **not** need the HTTP server at all. Only the *remote-gateway* deployment does —
and there the surface is a managed, opt-in, authenticated one, which is the
defensible case. The indefensible case is the **default desktop install**, where a
network service with default-off auth exists solely to let a local browser tab
talk to a local engine.

## The options

### Option A — Harden the HTTP server in place (status quo++)

Keep the architecture; shrink the surface. Concrete, mostly-cheap moves:

1. **Fix CORS** — replace `allow_origins=["*"]` + credentials with an explicit
   allowlist (the app's own origin) or drop credentialed CORS entirely for the
   local case. Add **Origin/Host header validation** (anti-DNS-rebinding: reject
   requests whose `Host` isn't `127.0.0.1:<port>`/`localhost`). *This is the single
   highest-value, lowest-cost change and should happen regardless of any larger
   decision.*
2. **Bind to a random high port + write it to a `0600` file** the trusted clients
   read (removes the fixed-`:54320` rendezvous).
3. **Per-launch loopback token** — desktop launcher mints an ephemeral token,
   passes it to the clients it spawns; auth becomes default-*on* for loopback too
   (the machinery already exists — `ProviderChain`, `/v1/tokens`, Inc 8b authz).
4. **Unix domain socket instead of TCP** (macOS/Linux) — filesystem-permission
   gated, no port, no network stack, no rebinding. Windows: named pipe or the
   random-port+token fallback. This removes most of the surface while keeping the
   multi-client fan-out.

**Buys:** keeps every client + the external gateway working unchanged; closes the
worst holes (CORS, fixed port, default-off auth) in days, not weeks. **Costs:**
the server still exists; UDS/named-pipe adds a platform branch; doesn't help the
"why is there a listener at all" objection for the pure-desktop case.

### Option B — In-process transport for local clients (the Pi-shaped move, scoped)

Give the **in-process-capable** clients a direct, no-socket path to the engine,
and keep the HTTP server only for what genuinely needs it.

- **Rich/Textual TUIs** already import Python — they can hold an `EngineClient`
  directly and skip HTTP entirely (today they talk to the server; they need not).
- **Desktop web UI** is the hard case — a browser *must* speak some wire protocol.
  Options: a Tauri shell with Rust↔JS IPC (no localhost server — see the
  [Tauri analysis](2026-07-05-tauri-desktop-shell-analysis.md)), or a
  same-process embedded webview with a custom protocol handler.
- **VSCode extension** talks to its own extension host; it could consume an
  in-process Node/py bridge, but today HTTP is simplest.
- **HTTP server becomes opt-in**, started only for the **remote-gateway** deployment
  (cluster, ppxai-sre-over-network if ever needed) — auth mandatory there.

**Buys:** the pure-desktop install has **no network listener** — the entire class
of localhost-service attacks disappears for the common case. Matches Pi's "no
server" security posture where it applies. **Costs:** significant — it splits the
transport into two code paths (in-process vs HTTP), the web client still needs
*a* transport (so Tauri or embedded-webview becomes coupled to this), and the
`AppState`/command-envelope/SSE machinery must work over both. This is a
multi-increment architectural change, not a patch.

### Option C — ppxai-sre uses ppxai as an embedded SDK (no HTTP at all for it)

This is **already the recommended direction** for ppxai-sre (see the
[SDK-mutation-tools note](2026-06-24-ppxai-sdk-mutation-tools-for-sre-agents.md)).
ppxai-sre embeds `EngineClient` + the sandbox primitives and drives sandboxed
sub-agent runs **in-process**, rather than POSTing to `/v1/agent/task` over HTTP.

**For the transport question this means:** the sister repo does **not** depend on
the HTTP server for the mutation-tool path — it depends on an **embeddable engine
API** (debt Item **(t)**: lift `build_task_runner` out of the server route into the
engine). So hardening/removing the HTTP server for local use does **not** break
ppxai-sre's intended integration — provided the embeddable runner exists. The HTTP
`/v1/*` surface remains only for the deployments that genuinely want a remote
gateway (and those run auth-on, behind a NetworkPolicy).

**This is the load-bearing reconciliation:** Options A/B for the desktop client and
Option C for ppxai-sre are **compatible** — both point at "the HTTP server is for
remote-gateway deployments only; local consumers (desktop + SDK) go in-process."

### Option D — Full Pi-style rewrite (rejected)

Rebuild the harness in-process in one language with no server, like Pi. **Not
viable.** ppxai is ~64k LoC Python engine + ~60k LoC tests + 4 clients + a
mid-flight v1.19.0 agent platform + the external `/v1/*` product. Pi is a
single-developer tool with none of ppxai's multi-client or gateway obligations.
This throws away the fan-out and the external product to solve a surface that
Options A+C already close. Recorded only to close it explicitly.

## Recommendation

**Do A now; make C real next; treat B as the long-horizon desktop endgame; reject D.**

1. **Immediately (days, do regardless):** the CORS + Host/Origin-validation fix
   (Option A.1). `allow_origins=["*"] + allow_credentials=True` on a
   default-unauthenticated loopback service is the sharpest edge and is cheap to
   blunt. Add anti-rebinding Host checks. This is a security fix independent of any
   architecture decision — file it, don't wait for the big call.
2. **Near term (A.2–A.4):** random port + `0600` port file + per-launch loopback
   token, so the desktop default becomes auth-*on* and un-discoverable. Consider
   UDS/named-pipe to remove the TCP surface on macOS/Linux.
3. **Structural (Option C):** land the embeddable-runner API (debt **(t)**) so
   ppxai-sre consumes ppxai as an in-process SDK and never depends on the local
   HTTP server. This is already on the roadmap for the mutation-tool work; it
   *also* happens to remove the sister repo from the "needs the server" column.
4. **Long horizon (Option B):** if/when the desktop shell moves to Tauri (separate
   analysis), fold the web client onto Rust↔JS IPC and make the HTTP server
   **opt-in for remote-gateway deployments only**. At that point the pure-desktop
   install has no network listener — the Pi security posture, achieved without a
   rewrite, and without losing the multi-client fan-out or the external gateway.

**The framing that resolves the tension:** ppxai should not choose "server vs no
server" globally. It should make the HTTP server **the remote-gateway transport,
not the default-local transport.** Local desktop use and ppxai-sre-as-SDK both go
in-process; the server exists, authenticated and bounded, for the deployments that
actually want a network-addressable governed backend. That keeps the value the
server was introduced for while removing the attack surface from the 90% case
where it was never needed.

## Follow-up artifacts

- File the **CORS/Host-validation** fix as a security debt item (Item 37 or a new
  entry) — it is actionable today and independent of the larger decision.
- The embeddable-runner (debt **(t)**) already carries the Option-C weight; annotate
  it that it *also* removes ppxai-sre from the HTTP-dependency set.
- If B is pursued, it composes with the Tauri desktop-shell analysis (Rust↔JS IPC
  is the web client's in-process transport).
