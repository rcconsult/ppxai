# ADR 0004 — LLM gateway features (v1.18.3)

**Date:** 2026-05-03
**Status:** Accepted — implemented (`server/routes/oneshot.py`, `server/routes/auth.py`; §4 of ADR 0009 revises the "no tool loop in oneshot" property for enriched requests, perimeter preserved)
**Related:**
- [`docs/api-gateway.md`](../api-gateway.md) — user-facing spec for the v1 gateway
- `ppxai/server/routes/oneshot.py` — first gateway endpoint
- `ppxai/server/auth.py` — bearer-token middleware
- ADR 0003 — Agent platform architecture (server-driven agents; orthogonal concern)

## Context

ppxai-server started as the API for ppxai's own clients (Rich TUI,
Textual TUI, web app, VSCode extension). Endpoints like `/chat`
(SSE-streaming, session-scoped, history mutation, multimodal
attachments) were designed for those clients and evolve with them.

In May 2026, the SRE-agent stack (`ppxai-sre-repo`) cross-checked
ppxai against its outlook-monitor agent's needs. The investigation
showed:

1. The agent (a stateless email classifier) doesn't want sessions,
   doesn't want SSE, doesn't want history. It wants
   "given this prompt, return the JSON answer."
2. Workarounds existed: ship a fresh `X-Session-Id: <uuid>` per call
   (creates a session lazily); parse JSON out of free-text responses
   with retry on parse failure; rely on cluster NetworkPolicy for
   trust.
3. Each workaround was a small tax that all external agents would pay.
4. ppxai's clients meanwhile keep evolving `/chat` and friends —
   binding external agents to those endpoints would couple them to
   internal-client churn.

The choice: continue with implicit two-tier (anyone can call any
endpoint, no stability promises), or make the boundary explicit.

## Decision

**Make the boundary explicit. Add a `/v1/...` URL prefix as the
stable external surface; everything else is internal.**

Three sub-decisions, all accepted in v1.18.3:

### 1. Path-versioned gateway tier (`/v1/<endpoint>`)

External agents, integrations, and any caller outside ppxai's own
clients consume `/v1/...` endpoints with semver-style guarantees:
- Required fields don't disappear; new optional fields can be added.
- Documented status codes are stable.
- Breaking changes ship as `/v2/<endpoint>` with a deprecation window
  (minimum: one minor release).

Internal endpoints (`/chat`, `/command/*`, `/files/*`, `/state`, etc.)
keep evolving with ppxai's own clients and offer no stability promise.
External callers reaching for them is a signal that either the
gateway needs to grow or the use case is internal-shaped (file an issue).

### 2. Stateless `POST /v1/oneshot` as the first endpoint

Single-turn LLM call, no session, no history, no streaming. Pure
prompt → response. Fields:

- Required: `prompt`
- Optional: `provider`, `model`, `system`, `response_format`,
  `max_tokens`, `temperature`
- Response: `{content, finish_reason, model, provider, usage}`

Implementation: bypass `EngineClient` entirely. `_build_provider`
constructs a provider directly from `ppxai-config.json` config and
calls `provider.oneshot()`. No session-state mutation, no AppState
side effects, no SSE. Per-model `extra_body` from config still
applies (so vendor knobs like NIM `chat_template_kwargs.enable_thinking`
carry through transparently).

### 3. Bearer-token auth, opt-in, default off

`PPXAI_API_TOKEN` env var enables auth. When set, every non-OPTIONS
request needs `Authorization: Bearer <token>` matching the value, or
gets `401` with `WWW-Authenticate: Bearer realm="ppxai"`. When unset,
server runs unauthenticated (preserves localhost desktop UX).

Single shared token in v1. Per-agent identity, scoped tokens,
rotation, OIDC/JWT — all explicitly NOT in v1 (see
[`docs/api-gateway.md`](../api-gateway.md) "Future directions").

## Why these and not the alternatives

### Why a separate `/v1/...` prefix instead of versioning `/chat`?

`/chat` is **session-scoped, SSE-streaming, history-mutating, multimodal**.
None of those properties match a stateless gateway. Making `/chat`
backwards-compatible across both shapes is real cognitive overhead
on every change to either; documenting two stability tiers on one
URL invites confusion. Separate URL = separate contract.

### Why path-versioning (`/v1/oneshot`) over response-versioning (`{"version": 1, ...}`)?

Both work. Path-versioning is the industry norm
(`/v1/chat/completions`, `api.github.com/v3`, etc.) and supports the
"two versions in parallel during deprecation" use case more cleanly:
breaking changes ship as `/v2/oneshot`, both run side by side, the
old shape is removed after the deprecation window. Response-versioning
forces all clients to inspect the field on every response and branch
on it.

Internal command-dispatcher (`POST /command/<name>`) uses
response-versioning (`{ok, result, side_effects, events, version: 1}`)
because there's only one client surface (ppxai's own) and the version
field is a tripwire, not a deprecation enabler. Different problem,
different shape.

### Why bypass `EngineClient` for `/v1/oneshot`?

`EngineClient` is a session abstraction with substantial setup cost
(provider creation, tool registration, AppState wiring, session
manager bookkeeping). For stateless single-turn calls, all of that
is wasted — and worse, accidental session reuse via `X-Session-Id`
collisions becomes a footgun. Provider construction is the only
thing oneshot needs; `_build_provider` does just that, ~30 LoC,
zero side effects.

### Why OpenAI-compat only in v1, not native Gemini / native OpenAI / Perplexity?

OpenAI-compat (`OpenAICompatibleProvider`) covers `local`, `custom`,
NIM, vLLM, Ollama, OpenRouter — the cases external agents actually
target today (outlook-monitor's NIM deployment specifically).
Native OpenAI, native Perplexity, and native Gemini providers each
need their own `oneshot()` with provider-specific quirks
(google-genai SDK shape, Perplexity citation handling, OpenAI's
Responses API). Each is independently small but together they're a
pre-emptive scope expansion. Defer until a user actually asks.
The 400 message names this explicitly so the gap is visible:
`"Provider X doesn't support /v1/oneshot yet. Use POST /chat with
X-Session-Id for now."`

### Why single shared token for v1 auth, not multi-token?

Multi-token requires a registry, persistence, rotation mechanism,
revocation API — see ADR 0004's complement in
[`docs/api-gateway.md`](../api-gateway.md) "Future directions" for
the `/v1/tokens` design. That's ~500 LoC + storage migration policy
+ a separate stability commitment. Single token is ~50 LoC and
unblocks the loopback-leaving deployments today. We'd need to ship
multi-token before opening ppxai-server to multiple tenants from
different teams; we don't have that need yet.

### Why opt-in (default off) rather than always-on?

Localhost desktop is the dominant use case. The Rich TUI / Textual
TUI / web app / VSCode extension all hit ppxai-server on loopback
without any Authorization header. Forcing auth there means every
desktop user has to set an env var on first run — friction without
value, since anything on the box already has the user's
`~/.ppxai/.env`. Making auth opt-in keeps the desktop UX zero-config
while making it trivial to enable for cluster deployment.

## Triggers to revisit

This ADR should be re-opened when any of these fire:

| Trigger | Likely change |
|---|---|
| A second native provider (Gemini, Perplexity, OpenAI-native) gains `oneshot()` | Promote v1 scope from "OpenAI-compat only" to "all providers"; remove the 400 carve-out |
| Multiple agents need per-call attribution | Build the `/v1/tokens` registry; env-var token becomes bootstrap |
| Corporate-IdP integration request lands | Add OIDC/JWT validation under `/v1/auth/...` (separate ADR) |
| Streaming output requested for `/v1/oneshot` | Either add a `?stream=1` mode or a separate `/v1/oneshot/stream` endpoint with SSE |
| Tool calls requested for `/v1/oneshot` | Probably belongs at `/v1/agent/run` instead — see ADR 0003 stage 2 |
| Rate limiting requested | Per-token (multi-token first) or per-IP (middleware); separate ADR |

## Consequences

### What this enables

- External agents (outlook-monitor first; SRE agents next) can build
  against ppxai-server with semver-style stability guarantees on the
  request/response shape.
- ppxai's own clients keep evolving `/chat` and `/command/*` without
  worrying about external consumers.
- The two-tier model gives a clean answer to "should this be a new
  endpoint or evolve an existing one?" — depends on consumer profile.
- Bearer auth opt-in is the floor for non-loopback deployments; the
  documented `/v1/tokens` direction is the ceiling for the next round.

### What this requires

- Discipline on the `/v1/` boundary: every breaking change to a
  documented field is a `/v2/<endpoint>`. Cheap if we don't
  accumulate technical debt; expensive if we do.
- Test coverage on the v1 surface (`tests/test_oneshot_route.py`,
  `tests/test_auth_middleware.py`) is part of the stability promise;
  shape-pinning tests are cheap insurance.
- The "OpenAI-compat only" scope must be lifted before claiming
  parity with `/chat` — until then external agents working with
  Perplexity / native Gemini / native OpenAI hit the 400 wall.

### Migration notes

Existing consumers (ppxai's own clients) are unaffected — none of
them use `/v1/...` paths or set `PPXAI_API_TOKEN`. The change is
strictly additive in v1.18.3.
