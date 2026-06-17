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

**v1.18.3 status: optional bearer-token auth (opt-in, default off).**

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

Set the `PPXAI_API_TOKEN` environment variable to the token clients
must present. Empty / whitespace-only values are treated as "auth
disabled" so a stray empty config entry doesn't lock everyone out.

```bash
export PPXAI_API_TOKEN="$(openssl rand -hex 32)"
ppxai-server
```

Clients send the token via the standard `Authorization: Bearer …`
header (case-insensitive scheme per RFC 7235):

```http
POST /v1/oneshot
Authorization: Bearer <token>
Content-Type: application/json
```

### Behavior

- **Auth disabled (default):** all routes serve as before. Localhost
  desktop UX unchanged.
- **Auth enabled:** every request needs the right `Authorization`
  header or it gets `401 Unauthorized` with `WWW-Authenticate: Bearer
  realm="ppxai"`.
- **CORS preflight (OPTIONS) is exempted** — browsers don't send
  `Authorization` on preflight by spec; the actual request that
  follows is auth-checked normally.
- **The token is read from the env var on every request.** Operators
  can rotate / disable / re-enable by updating the variable without a
  server restart (e.g. via k8s ConfigMap reload, though the pod still
  needs to see the new value — env-var reload depends on your
  deployment mechanism).

### What auth doesn't replace

- **NetworkPolicy / mTLS / firewall rules** are still your floor.
  Tokens can leak (`exec` into a pod, `cat` a mounted secret, `env |
  grep PPXAI`). Network controls don't.
- **Provider-side auth** is unaffected. Your NIM / OpenAI / Perplexity
  API keys are still spent through ppxai; the bearer token only gates
  who's allowed to invoke the proxy.
- **Prompt-injection defenses** are not auth's job. A malicious prompt
  body still works regardless of the caller's identity.

### Limitations of v1

The v1.18.3 model is **single shared token**. Deliberately scoped to
unblock the loopback-leaving deployments without committing to a
larger design. Specifically NOT in v1:

- Multiple per-agent tokens (everyone uses the same secret).
- Per-token attribution in logs (the audit trail says "authenticated
  caller," not "outlook-monitor").
- Token rotation / expiry (you rotate by changing the env var; no
  graceful handover window).
- Scoped tokens (a token that can call `/v1/oneshot` but not `/chat`).
- Rate-limiting per token.
- OAuth/OIDC integration (no JWT validation; no corporate IdP).

If your use case needs any of these, see "Future directions" below
and either file an issue or write the ADR.

### Future directions

The natural next step is a **token registry** managed via gateway
endpoints — closer to GitHub PATs than to a login flow:

- `POST /v1/tokens` — create a new token with a name and optional
  scopes. Returns `{token_id, token_value}`. The full value is shown
  exactly once (like GitHub).
- `GET /v1/tokens` — list tokens (without values) — `[{id, name,
  scopes, created_at, last_used_at}]`.
- `DELETE /v1/tokens/{id}` — revoke a token.
- `POST /v1/tokens/{id}/rotate` — generate a new value, invalidate
  the old, return the new value.

This would supersede the env-var token (kept as a bootstrap mechanism
for the first token). Each token can carry:

- **`name`** for audit attribution ("outlook-monitor", "incident-responder").
- **`scopes`** like `["oneshot:invoke", "chat:read"]` so a classifier
  agent can call `/v1/oneshot` but can't `/chat` with tools.
- **`expires_at`** for time-bounded rotation.
- **`last_used_at`** for stale-token detection.

For corporate environments, a third direction is **OIDC / JWT
validation**: drop the local token registry, validate JWTs from a
configured issuer (Auth0, Okta, Azure AD, k8s ServiceAccount tokens).
Each call's identity comes from the JWT's `sub` / `aud` / custom
claims; ppxai-server doesn't store any secrets. This is the
production-grade option and ships as `/v1/auth/jwt` config plus an
optional path-based verification policy. Defer until there's actual
demand.

**Naming note:** the future endpoints are named `/v1/tokens` (CRUD on
API tokens, modeled after GitHub PATs) rather than `/v1/auth` (which
typically means OAuth-style login flows). `/v1/auth/...` is reserved
for the OIDC/JWT direction if that lands.

These are speculative — no commitment until an ADR pins the design.
The v1.18.3 single-token model intentionally has no migration cost
to the registry version (env-var bootstrap stays valid; registry
becomes the production path).

---

## Endpoints

### `POST /v1/oneshot` — stateless completion

**Added:** v1.18.3.

Single-turn LLM call with no session, no history, no streaming.
Designed for classifiers, routers, and any "given this prompt, return
one response" workload.

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
  }
}
```

#### Errors

| Status | Condition |
|---|---|
| 400 | Unknown provider, missing model with no default, no API key for provider, provider doesn't support oneshot in v1 |
| 422 | Request body fails validation (empty prompt, negative max_tokens, temperature out of range, etc.) |
| 502 | Provider call raised — wraps the upstream error as `{"detail": "Provider call failed: <message>"}` |

#### Notes

- **Stateless.** No session is created or mutated. Safe for high-frequency
  short-lived calls (rate-limited by the upstream provider, not by ppxai).
- **Provider support.** v1.19.x: **all configured providers** are
  supported. `oneshot()` is part of the `BaseProvider` contract, so
  `local`/`custom`/NIM/vLLM/Ollama/OpenRouter **and** native
  OpenAI/Perplexity/Gemini all work. The only 400 is an *unbuildable*
  provider (unknown name / missing API key). (Pre-1.19.x this endpoint
  rejected native providers by class — that restriction is removed.)
- **`response_format`.** Forwarded to the provider as-is. NVIDIA NIM,
  vLLM, and modern OpenAI-compat endpoints accept the OpenAI shape.
  Older endpoints may return 400 — that surfaces to the client as 502
  with the upstream message.
- **Per-model `extra_body` from `ppxai-config.json`** still applies.
  This means vendor knobs (NIM `chat_template_kwargs.enable_thinking`,
  Qwen3 `enable_thinking`, etc.) carry through without the caller
  having to know about them.
- **Native web search (opt-in, provider-side).** Set
  `tools.web_search.oneshot_grounding: true` in `ppxai-config.json` to let
  oneshot augment a completion with the **provider's own** web search —
  Gemini Google-Search grounding, Perplexity Sonar. This is **Option A**:
  retrieval happens *inside the provider's API call*, so the egress
  perimeter is unchanged (same provider host the call already reaches) and
  **no `web_search`/`fetch_url` tool is ever exposed to the model** — there
  is no prompt-injection exfiltration vector and no `NetworkPolicy`
  involvement (that stays the `/v1/agent/task`-only egress firewall).
  - **Default off.** When off, behavior is byte-identical to pre-1.19.x —
    existing consumers see no change.
  - **Capability-gated.** Only providers with `capabilities.web_search:
    true` are affected (Gemini, Perplexity). For OpenAI / NVIDIA it's a
    no-op — the flag can never reach for a tool a provider doesn't have.
  - Gemini already grounds when `provider.gemini.options.enable_grounding`
    is set; Perplexity sonar* models search intrinsically. This flag is the
    single, explicit, deterministic switch so a gateway consumer can opt in
    without depending on per-provider config.
  - For tool-*using* agent work (granted `web_search`/`fetch_url` with an
    egress allowlist), use `POST /v1/agent/task`, not oneshot — that's the
    sandboxed tier where `NetworkPolicy` applies.

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
parsed = json.loads(result)
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
