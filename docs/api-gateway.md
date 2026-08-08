# ppxai-server API gateway

ppxai-server exposes two tiers of HTTP endpoints. This document defines
the **stable v1 gateway** tier — the surface external agents and tools
can build against with semver-style guarantees.

The other tier is **internal endpoints** consumed by ppxai's own
clients (Rich TUI, Textual TUI, web app, VSCode extension). Those
endpoints evolve with the clients and offer no stability guarantees;
external consumers should not depend on them.

---

## Stability tiers

| Tier | URL prefix | Stability | Consumers |
|---|---|---|---|
| **v1 gateway** | `/v1/<endpoint>` | Stable; semver-style guarantees | External agents (outlook-monitor, classifiers, integrations) |
| **Internal** | `/<endpoint>` (no prefix) | Unstable; may break with any release | ppxai's own clients |

### v1 gateway guarantees

For every endpoint under `/v1/`:

- **Request shape** — fields documented as required will not be removed.
  New optional fields may be added (non-breaking).
- **Response shape** — fields documented as guaranteed will not be removed
  or repurposed. New fields may be added (non-breaking).
- **Status codes** — documented codes for documented conditions are stable.
  We may add new codes for new conditions.
- **Path** — the `/v1/<endpoint>` URL is stable for the v1 lifetime.
  Breaking changes ship as `/v2/<endpoint>` and the two run in parallel
  through a deprecation window (minimum: one minor release).

What we explicitly do *not* guarantee:

- **Latency / throughput** — vary by provider, model, and host load.
- **Provider availability** — providers can be added, removed, or
  renamed in `ppxai-config.json`; the gateway only exposes what the
  server is configured for.
- **Error message text** — the structured fields (`detail`) are stable
  in shape; the prose inside may change for clarity.

### `/v1/agent/*` — in development, NOT yet sealed (v1.19.0)

> ⚠️ **Exception to the guarantees above.** The agent platform endpoints —
> `POST /v1/agent/run`, `POST /v1/agent/task`, `GET /v1/agent/runs[/<id>]`,
> `/v1/agent/runs/<id>/{events,cancel,respond,ack,resume}`, the run-event / monitor-SSE
> event schema, and `POST /v1/tokens` — are **in development and NOT covered
> by the v1 stability contract**, despite living under `/v1/`. Their request,
> response, and event shapes WILL change.
>
> They become the agent consumer contract only once the agents API is
> **designed, tested, validated, and explicitly sealed** — at which point this
> exemption is removed and the guarantees above apply. Until then, do not build
> against them as stable. (The blanket "every `/v1/` endpoint is stable" rule
> above does **not** apply to this set while this notice stands.)
>
> The tool-capable `POST /v1/agent/task` tier additionally ships **default-off**
> (`execution.task.enabled`) and is sandboxed in-process only — safe for
> **trusted operators** (the task/grant is operator-authored), not for untrusted
> input. See [decisions/0003-agent-platform-architecture.md](decisions/0003-agent-platform-architecture.md).

#### Run working directory (v1.19.x workdir-alignment)

A `/v1/agent/task` run's relative tool paths resolve deterministically —
never against the server process launch dir:

1. `workdir` in the request body — per-run intent like `provider`/`model`.
   The ppxai clients thread their **session working dir** automatically
   (`--work-dir` on a `/task` launch overrides), so "summarize README.md" means
   the same thing in chat and in a task run. Must exist (400 otherwise).
2. Absent: the **server default** — `server.working_dir` config, else the
   user's home (the same default every new UI session gets).
3. Filesystem seal ON (`execution.task.sandbox.enforcement: "in_process"`):
   the per-run jail **always wins**; a requested `workdir` is ignored and
   the launch response carries `workdir_ignored: true` (clients render a
   warning). Warn-don't-fail keeps the same invocation portable across
   sealed and unsealed hosts.

The effective workdir is recorded on the run meta (`workdir`, `null` =
default/jail), returned by `GET /v1/agent/runs/<id>`, reused verbatim by
`POST .../resume`, and inherited by `spawn_subagent` children. The
tool-free `/v1/agent/run` tier has no `workdir` — it executes no tools,
so there is nothing to resolve paths against.

**Sandbox posture profiles.** The seal is *operator posture per
deployment*, never a wire flag — there is deliberately no per-run
"unseal" (any bearer holder could otherwise escape the operator's
config):

| Profile | Seal | Why |
|---|---|---|
| Desktop / IDE assistant | OFF (default) | The user is the trust boundary; runs work on the user's own project via the session workdir; T5 consent gates risky actions. |
| Coder pod (k8s) | OFF | The pod + NetworkPolicies + app-layer bearer are the real walls; the in-process seal would add friction, not protection. Per-run egress allowlists (AC-2) still apply. |
| Embedded agents (e.g. ppxai-sre) | ON | Unattended runs over untrusted input (prompt-injection surface) get least-privilege reads: the jail plus skill-mounted read roots. Relaxation = mount more roots via `--skill`, not unsealing. |

For genuinely hostile workloads the answer is OS isolation (ADR 0003
tier-d container), not a stronger in-process jail.

### What's not in the gateway tier

These endpoints are **internal** and may change at any time:

- `POST /chat` — SSE streaming chat (session-scoped, history mutation,
  multimodal attachments). Designed for ppxai's clients.
- `POST /command/<name>` — slash-command dispatcher with the
  `{ok, result, side_effects, events, version}` envelope. The envelope
  contract is versioned (`version: 1`) but the endpoint itself is for
  ppxai's clients.
- `GET /sessions`, `POST /sessions/...` — session lifecycle.
- `GET /files/...`, `POST /files/...` — file tree, upload, serve.
- `GET /state`, `GET /providers`, `GET /completion`, etc.

If you're building an external agent and find yourself reaching for one
of these, file an issue: either the `/v1/` surface needs to grow, or
your use case is internal-client-shaped and we should talk about it.

---

## Authentication

**v1.19.0 status: optional bearer-token auth, backed by a pluggable
provider chain (opt-in; default is still unauthenticated on an unset
`PPXAI_API_TOKEN`).** A `file` provider can additionally be configured
to enforce auth unconditionally and to unlock a self-service token
registry at `/v1/tokens`. See "What changed" below for the delta from
the v1.18.3 single-token model.

### Threat model

ppxai-server is an LLM proxy with API-key-spending power. Any client
that reaches its HTTP port can spend tokens on your provider accounts,
read provider responses, and (against `/chat`) trigger ppxai's tools.
"Auth" here is really "who is allowed to spend money and trigger code
on your behalf."

| Deployment | Trust boundary | Auth required? |
|---|---|---|
| Loopback only (TUI / web app / VSCode on localhost) | Same machine — anything on the box already has your `~/.ppxai/.env` | No — adds friction without value |
| Cluster-internal behind a NetworkPolicy | The cluster | Optional. Defense-in-depth if NetworkPolicy is misconfigured or another pod gets compromised |
| Exposed beyond cluster (Ingress, NodePort, port-forward, public DNS) | The network | **Mandatory.** Without it, anyone reachable can drain your provider account |

### Enabling auth

Auth enforcement is decided by a **provider chain**, configured under
`server.secrets.providers` in `ppxai-config.json`. Each entry is
`{"type": "env", "var": "..."}` or `{"type": "file", "path": "..."}`.
Omit the whole `server.secrets` block (or leave `providers` empty) and
the server falls back to a single `env` provider on `PPXAI_API_TOKEN` —
byte-identical to the v1.18.3 behavior.

```json
"server": {
  "secrets": {
    "providers": [
      { "type": "file", "path": "~/.ppxai/tokens.json" },
      { "type": "env", "var": "PPXAI_API_TOKEN" }
    ]
  }
}
```

The simplest opt-in — no config file changes — is still the env var:

```bash
export PPXAI_API_TOKEN="$(openssl rand -hex 32)"
ppxai-server
```

Empty / whitespace-only values of `PPXAI_API_TOKEN` are treated as
"this provider doesn't enforce" so a stray empty config entry doesn't
lock everyone out.

Clients send the token via the standard `Authorization: Bearer …`
header (case-insensitive scheme per RFC 7235):

```http
POST /v1/oneshot
Authorization: Bearer <token>
Content-Type: application/json
```

### Behavior

Whether auth is enforced is a per-provider decision, evaluated across
the whole chain (`ppxai/server/auth.py::_provider_enforces_auth`):

- **`env` provider** enforces only while its var is set and non-empty
  — unset means "this provider is inactive," matching the v1.18.3
  loopback desktop UX.
- **A mint-capable provider (`file`) enforces by mere presence**, even
  with zero tokens minted. An empty token store means "no one gets in"
  (401), not "everyone gets in" — this closes the footgun where
  revoking the last token would otherwise silently open the server.
- **A read-only provider whose capabilities can't be introspected**
  (a future non-`env` backend) fails closed and is assumed to enforce.
- **No providers configured at all** → auth disabled, all routes serve
  as before.

When auth is enforced:

- Every request needs a valid `Authorization: Bearer <token>` header,
  or it gets `401 Unauthorized` with `WWW-Authenticate: Bearer
  realm="ppxai"`. **A presented bearer is always validated** — even on
  a route that would otherwise be loopback-exempt (see below) — so an
  invalid or expired token on an exempt route still 401s instead of
  being silently ignored.
- **CORS preflight (OPTIONS) is exempted** — browsers don't send
  `Authorization` on preflight by spec; the actual request that
  follows is auth-checked normally.
- **Loopback exemptions** apply only when the caller presents **no**
  bearer at all (a genuine local browser has none to send). "Loopback"
  means the peer IP is `127.0.0.1` / `::1` / `localhost` **and** the
  request carries no proxy-forwarding header (`X-Forwarded-For` etc.)
  — a request that passed through a reverse proxy is never treated as
  loopback, even if the rewritten IP looks local. The exemptions:
  - Unauthenticated loopback `POST /v1/tokens`, whenever a mint-capable
    (`file`) provider is configured — not gated on the store being
    empty; repeat local mints are deliberate (this is how an operator
    bootstraps and re-provisions a file-backed deployment).
  - The loopback UI/static/`/chat` surface — the local desktop/web
    client carries no bearer by default.
  - The exact path `POST /v1/agent/run` (the tool-free oneshot run
    tier) — behaviorally identical to `/v1/oneshot`, so it's exempted
    the same way; the tool-capable `/v1/agent/task` tier and
    `/runs/{id}/cancel` stay protected.
  - Loopback `GET` of an **unowned** run's metadata or event stream
    (`/v1/agent/runs/{id}` and `/v1/agent/runs/{id}/events`) — i.e. a
    run the token-less local browser itself created via the exempt
    `POST /v1/agent/run`. A run created with a bearer (any `/task` run,
    or any run minted by an authenticated caller) is **not** exempt.
  - CORS preflight (`OPTIONS`).
- **Everything else under `/v1/agent` and `/v1/tokens` stays
  bearer-protected even from loopback** — a local browser being
  trusted to load the UI does not extend to reading another owner's
  run transcripts or administering tokens.
- **The env provider's var is read live on every request.** Operators
  can rotate / disable / re-enable that provider by updating the
  variable without a server restart (e.g. via k8s ConfigMap reload,
  though the pod still needs to see the new value — env-var reload
  depends on your deployment mechanism). A `file` provider's store is
  likewise re-read per request (no server restart needed to mint,
  revoke, or pick up a manually edited `tokens.json`).

### Transport perimeter: CORS + Host validation (v1.19.x)

Independent of bearer auth, the server hardens its **local transport** against
a malicious website (or a DNS-rebinding attacker) driving the engine over
loopback. Two controls, both **bind-conditional** and secure-by-default for the
desktop, overridable for a gateway/coder deployment:

- **CORS** defaults to the app's own **loopback origins** (regex
  `^https?://(127\.0\.0\.1|localhost)(:\d+)?$`), not `*`. The old
  `allow_origins=["*"] + allow_credentials=True` made Starlette *reflect* any
  Origin (it can't legally send `*` with credentials), i.e. trust every website
  the user visited. The desktop web UI is same-origin with the server, so CORS
  never blocks it; a third-party site is refused. A gateway with a genuinely
  cross-origin browser client sets **`PPXAI_ALLOWED_ORIGINS`** (comma-separated).
- **Host-header validation** rejects a request whose `Host` isn't a loopback
  name with `400 {"error":"invalid_host"}` — anti-DNS-rebinding. Exempts
  `/health`+`/healthz` (kubelet probes send `Host=<pod IP>`) and CORS preflight
  (`OPTIONS`).

**Bind-conditional behavior** (the server knows its bind host):

| Bind | `PPXAI_TRUSTED_HOSTS` | Host validation |
|---|---|---|
| loopback (`127.0.0.1`, desktop default) | unset | strict — loopback only |
| wide (`0.0.0.0`, gateway/coder) | set to your host(s) | loopback + those hosts |
| wide (`0.0.0.0`) | unset | **permissive + one-time warn** (non-breaking fallback) |
| any | `*` | disabled |

The wide-bind-permissive fallback means upgrading the server image alone never
starts 400ing an existing gateway before its env is set — but you **should** set
`PPXAI_TRUSTED_HOSTS` to your ingress host to actually enable the protection.
The k8s coder deployment does this automatically: the session-manager threads
`PPXAI_TRUSTED_HOSTS` + `PPXAI_ALLOWED_ORIGINS` from `INGRESS_HOST` into every
per-user pod (see `deploy/`). This is defense-in-depth atop the ingress
NetworkPolicy — not a replacement for it.

### What auth doesn't replace

- **NetworkPolicy / mTLS / firewall rules** are still your floor.
  Tokens can leak (`exec` into a pod, `cat` a mounted secret, `env |
  grep PPXAI`). Network controls don't.
- **Provider-side auth** is unaffected. Your NIM / OpenAI / Perplexity
  API keys are still spent through ppxai; the bearer token only gates
  who's allowed to invoke the proxy.
- **Prompt-injection defenses** are not auth's job. A malicious prompt
  body still works regardless of the caller's identity.

### Limitations of the env-only (`env`) provider

The **single-shared-token** model — an `env` provider with no `file`
provider alongside it — is still the default and is deliberately
minimal. It does NOT give you:

- Multiple per-agent tokens (everyone uses the same secret).
- Per-token attribution (the audit trail says "authenticated caller,"
  not "outlook-monitor").
- Token rotation / expiry (you rotate by changing the env var; no
  graceful handover window).
- Scoped tokens (a token that can call `/v1/oneshot` but not `/chat`).
- Rate-limiting per token.
- OAuth/OIDC integration (no JWT validation; no corporate IdP).

Everything except OAuth/OIDC and per-token rate-limiting is available
today by adding a `file` provider to the chain — see below.

### The token registry (`file` provider, `/v1/tokens`) — shipped v1.19.0

Configuring a `file` provider (`{"type": "file", "path":
"~/.ppxai/tokens.json"}`) under `server.secrets.providers` turns on a
multi-token registry, managed via three gateway endpoints
(`ppxai/server/routes/tokens_v1.py`). **Shipped ≠ sealed:** these
endpoints work as documented here, but their request/response shapes
remain under the `/v1/agent/*` in-development exemption above — don't
build against them as a frozen contract until that notice is removed.

- `POST /v1/tokens` — mint a token. Body: `{"owner": "<principal>",
  "roles": ["..."], "ttl_s": <optional seconds>}`. Returns
  `{"token": "<raw material>", "meta": {token_id, owner, roles,
  expires_at, revoked, source}}`. **The raw `token` value is returned
  exactly once** (GitHub-PAT style) — it is never persisted and never
  logged; only a salted SHA-256 hash (`sha256:<salt>:<digest>`) is
  written to `~/.ppxai/tokens.json`, one random salt per token, so a
  stolen store file can't be replayed into a working token.
- `GET /v1/tokens` — list token **metadata only**, never material:
  `[{token_id, owner, roles, expires_at, revoked, source}]`.
- `DELETE /v1/tokens/{token_id}` — revoke a token. Revocation is
  one-way; a second revoke of the same id 404s (indistinguishable from
  an unknown id, see owner-scoping below).

There is no rotate endpoint — rotation is mint-a-new-token +
revoke-the-old-one.

**Owner-scoping.** An authenticated remote caller may only list its own
`owner`'s tokens (others are filtered out of the `GET` response) and
mint only under its own `owner` (minting for a different owner is
`403`). Revoking a token owned by someone else 404s — the same status
as revoking an unknown id — so ownership can't be probed via status
code. The **unscoped operator** — no bearer presented, either because
auth is disabled or because the request qualifies for a loopback
exemption — may administer tokens for any owner; this is how an
operator bootstraps or re-provisions a deployment from the local
machine.

**Mixed chains.** A chain can run `file` alongside `env` (see the
config example above) so an existing `PPXAI_API_TOKEN` deployment keeps
working unchanged while individual per-agent tokens are minted
incrementally. Mutating operations always route to the first
capable provider in the chain; against an `env`-only (read-only) chain,
`POST`/`DELETE /v1/tokens` return `405` — configure a `file` provider
to unlock them.

**Roles.** The `roles` field is accepted and stored today for future
routing/authz use; the current auth/authz gate does not yet branch on
role content — it's a forward-compatible label, not yet an enforcement
axis.

### What's still not in v1.19.0

- Scoped/least-privilege tokens (a `roles` label exists, but no gate
  currently restricts a token to a subset of endpoints).
- Rate-limiting per token.
- OAuth/OIDC integration (no JWT validation; no corporate IdP). If your
  use case needs this, file an issue or write an ADR — the design
  space (validate JWTs from a configured issuer, e.g. Auth0/Okta/Azure
  AD/k8s ServiceAccount tokens, with identity from `sub`/`aud`/custom
  claims) is still open and unclaimed by any code; a future OIDC surface
  would live under `/v1/auth/...` precisely because `/v1/tokens` is
  already spoken for by the shipped PAT-style registry above.

### What changed: v1.18.3 → v1.19.0

- **v1.18.3:** a single optional bearer via `PPXAI_API_TOKEN`, checked
  directly in `server/auth.py`. No `/v1/tokens`. No loopback carve-outs
  beyond CORS preflight.
- **v1.19.0 (Inc 8a/8b):** auth delegates to a pluggable
  `ProviderChain` (`ppxai/server/secrets/`). With no `server.secrets`
  config, behavior is byte-identical to v1.18.3 (a single `env`
  provider is synthesized as the default). Adding a `file` provider
  unlocks the `/v1/tokens` registry, owner-scoped multi-token
  management, and per-run authorization (a run created with a bearer
  is owned by that bearer's principal; loopback reads of *unowned* runs
  stay exempt, owned runs do not). This is additive and non-breaking:
  the env-var bootstrap keeps working standalone or alongside a `file`
  provider.
- **Client consequence.** Because a presented bearer is always
  validated — including on loopback-exempt routes — ppxai's own web and
  VSCode clients (v1.19.0) attach the stored bearer **only to `/v1/*`
  paths**, never globally: a stale or wrong token would otherwise 401
  the whole desktop UI instead of just the `/v1/agent` and `/v1/tokens`
  calls. Both clients expose the same in-chat `/token
  status|set|mint|clear` family (mint uses the loopback bootstrap
  exemption above; a 401 from `/task` points at it). Storage differs
  per client: web keeps the token in `localStorage` (mint owner
  `web-local`); VSCode keeps it in `SecretStorage` (mint owner
  `vscode-local`), shared with the **"ppxai: Set API Token"** command
  palette entry — which is also what a bare `/token set` opens there,
  so the raw value never transits the webview transcript.

---

## Endpoints

### `POST /v1/oneshot` — stateless completion

**Added:** v1.18.3.

Single-turn LLM call with no session, no history, no streaming.
Designed for classifiers, routers, and any "given this prompt, return
one response" workload.

> **Since v1.19.1 (FU):** every oneshot executes as a `kind=oneshot`
> registry run under the hood — the wire contract is unchanged, but each
> call leaves an auditable record in `~/.ppxai/runs/<id>/` (visible to
> `/run ls`, reaped by the standard retention policy). "Stateless" keeps
> its meaning: no *session* side effects, the response is the collect.

#### Request

```http
POST /v1/oneshot
Content-Type: application/json

{
  "prompt": "Classify this email...",          // required, non-empty
  "provider": "nvidia",                         // optional; default = server's default_provider
  "model": "qwen/qwen3.5-122b-a10b",            // optional; default = provider's default_model
  "system": "You are a classifier...",          // optional system message
  "response_format": {                          // optional OpenAI-shape
    "type": "json_object"                       //   or "json_schema" with json_schema field
  },
  "max_tokens": 512,                            // optional, > 0
  "temperature": 0.0                            // optional, 0.0–2.0
}
```

#### Response

```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "content": "...",                  // model's response text (always present, may be "")
  "finish_reason": "stop",           // "stop" | "length" | "content_filter" | "tool_calls" | null
  "model": "qwen/qwen3.5-122b-a10b", // resolved model (provider may echo a different ID)
  "provider": "nvidia",              // resolved provider
  "usage": {                         // null if the provider didn't return usage
    "prompt_tokens": 423,
    "completion_tokens": 87,
    "total_tokens": 510
  },
  "grounding": {                     // v1.19.1, ADDITIVE: present ONLY when the
    "searched": true,                //   search-loop enrichment served the request
    "run_id": "run_c02a3cbac2f0",    //   (absent — not null — otherwise, so existing
    "queries": ["..."],              //   consumers see a byte-identical envelope)
    "backend": "perplexity",         // premium backend, or "duckduckgo" (free)
    "search_cost": 0.0000568         // premium-search USD cost of THIS request
  }
}
```

`grounding.run_id` is the debug handle: the enriched request executed as a
real `kind=oneshot` run, so `~/.ppxai/runs/<run_id>/` holds its meta + event
log (queries, egress allow/deny audit, usage) and the run-inspection
surfaces work on it. All grounding fields derive from that run's own audit
trail — concurrent requests cannot cross-attribute cost.

#### Errors

| Status | Condition |
|---|---|
| 400 | Unknown provider, missing model with no default, no API key for provider, provider doesn't support oneshot in v1 |
| 422 | Request body fails validation (empty prompt, negative max_tokens, temperature out of range, etc.) |
| 502 | Provider call raised — wraps the upstream error as `{"detail": "Provider call failed: <message>"}`; on the enrichment path, a failed/cancelled run — the detail carries the `run_id` for post-mortem |
| 504 | Enrichment-path run exceeded the request timeout — the run is cooperatively cancelled and the detail carries its `run_id` (the record stays inspectable) |

#### Notes

- **Stateless.** No session is created or mutated. Safe for high-frequency
  short-lived calls (rate-limited by the upstream provider, not by ppxai).
- **Provider support.** v1.19.x: **all configured providers** are
  supported. `oneshot()` is part of the `BaseProvider` contract, so
  `local`/`custom`/NIM/vLLM/Ollama/OpenRouter **and** native
  OpenAI/Perplexity/Gemini all work. The only 400 is an *unbuildable*
  provider (unknown name / missing API key). (Pre-1.19.x this endpoint
  rejected native providers by class — that restriction is removed.)
- **`response_format`.** Reaches the model on every provider, but the
  gateway **delivers it — it does not enforce it**. Read that as a hard
  contract boundary, not a caveat:

  > A `200` does **not** guarantee the response matches your schema.
  > **Validate the returned JSON against your expected shape.** A 200 with
  > the wrong keys is a handled failure, not a parse.

  Enforcement belongs to the provider and varies by endpoint. NVIDIA NIM,
  vLLM and modern OpenAI-compat endpoints accept the OpenAI shape and are
  forwarded verbatim; older endpoints may return 400, surfacing as 502
  with the upstream message. Gemini takes a different route — it has no
  `response_format` field, so ppxai maps it onto `response_mime_type` /
  `response_schema` (`providers/gemini.py::response_format_to_gemini`),
  which additionally strips `additionalProperties` (the SDK's `Schema`
  model accepts it, the REST API 400s on it) and suppresses Google Search
  grounding for that call, since Gemini refuses the combination.

  This boundary is not theoretical. Before v1.19.1 the Gemini path
  accepted `response_format` and silently dropped it: callers pinning a
  JSON schema got `200` with well-formed JSON whose keys the model chose,
  and no error anywhere. That is fixed — but a client that *trusts*
  enforcement rather than checking it would have shipped mis-typed
  results on any provider that behaves the same way.
- **Per-model `extra_body` from `ppxai-config.json`** still applies.
  This means vendor knobs (NIM `chat_template_kwargs.enable_thinking`,
  Qwen3 `enable_thinking`, etc.) carry through without the caller
  having to know about them.
- **Grounding (opt-in, v1.19.1 — two independent switches under
  `execution.run.*`).** Both default **off**; with both off the endpoint is
  a **pure closed-book LLM call** — no context enrichment, no egress beyond
  the provider API itself (with a local provider this is fully
  air-gap-safe). The decision is made **per request** per the ADR 0009 §4
  gating table, logged to the server debug log, and reported per configured
  model by `/doctor`:

  | `execution.run.web_search` | `execution.run.grounding` | Behavior |
  |---|---|---|
  | off | off | **Closed-book** (default): training-data answer only. |
  | off | on | **Native**: the provider's own search (Gemini grounding, Perplexity Sonar) retrieves *inside the provider's API call*. No new egress, no tool exposed, no run record. Non-search providers degrade gracefully to closed-book. |
  | on | off | **Search-loop**: the model gets exactly one tool, `web_search`, and the request executes as an auditable `kind=oneshot` run (the `grounding` response field appears). Exists so **local models get context enrichment** they otherwise never have. Non-tool-capable models degrade to closed-book; a failed search degrades to answering with what the model has. |
  | on | on | **Best available per provider**: native wins when the provider has it (never both — retrieval is never done or billed twice); the search loop is the fallback for providers without native search. |

  - **No combination errors out** — the switches only change where the
    answer's knowledge comes from, and every unmet precondition degrades
    gracefully toward closed-book.
  - **Search-loop perimeter.** The run's grant is hardwired to
    `{web_search}` (nothing can widen it); `NetworkPolicy` clamps egress to
    the search-backend hosts; a small iteration budget bounds the loop.
    Host/filesystem-safe, not injection-proof: retrieved text can influence
    the answer — inherent to grounding, including the native path.
  - **ADR 0004 revision.** v1 originally promised "no tool loop in
    oneshot". That purity claim is revised (ADR 0009 §4 / ADR 0011): the
    search-loop path drives the *same* sandboxed run tier as
    `/v1/agent/task` — a facade, not a second tool-execution path — and it
    is opt-in, default-off, with the wire byte-identical when off.
  - **Legacy key.** `tools.web_search.oneshot_grounding` (v1.19.0) is
    dual-read as `execution.run.grounding`; an explicit `execution.run.*`
    value wins. New configs should use the `execution.run` block.
  - For general tool-using agent work (custom grants, egress allowlists,
    specs/skills), use `POST /v1/agent/task` — oneshot's search-loop is the
    single-tool special case of that tier.

#### Example: classification with structured output

```python
import httpx

resp = httpx.post(
    "http://ppxai-server.internal:54320/v1/oneshot",
    json={
        "prompt": (
            "Classify this email's intent. Reply with JSON: "
            "{intent, confidence, reasoning}.\n\n"
            f"Email:\n{email_body}"
        ),
        "system": "You are a classifier. Reply only with JSON.",
        "response_format": {"type": "json_object"},
        "max_tokens": 256,
        "temperature": 0.0,
    },
    timeout=30.0,
)
resp.raise_for_status()
result = resp.json()["content"]  # JSON string per response_format

# Validate the SHAPE, don't assume it. `response_format` is delivered to the
# provider, not enforced by the gateway — a 200 can carry well-formed JSON
# with keys the model chose. Treat that as a handled failure, not a parse.
EXPECTED = {"intent", "confidence", "reasoning"}
try:
    parsed = json.loads(result)
except json.JSONDecodeError as exc:
    raise ClassifierError(f"non-JSON response: {result[:200]}") from exc
if not isinstance(parsed, dict) or not EXPECTED <= parsed.keys():
    # Retrying rarely helps: an unenforced schema fails the same way twice.
    raise ClassifierError(
        f"schema not honoured — expected {sorted(EXPECTED)}, "
        f"got {sorted(parsed) if isinstance(parsed, dict) else type(parsed).__name__}"
    )
```

---

## Adding new gateway endpoints

When proposing a new `/v1/<endpoint>`, write an ADR first
(`docs/decisions/NNNN-<slug>.md`) covering:

1. The use case and why it can't ride on existing `/v1/` endpoints.
2. The request/response shape, with field-level stability notes.
3. Error conditions and status codes.
4. Provider-support scope (which providers in v1, which deferred).

The ADR pins the design decisions for future reviewers; the route
implementation lands in `ppxai/server/routes/<endpoint>.py` and is
registered in `ppxai/server/routes/__init__.py`.

Once shipped, the endpoint enters the v1 stability contract — breaking
changes require `/v2/<endpoint>` with a deprecation window.
