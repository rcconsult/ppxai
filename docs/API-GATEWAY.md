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

**v1.18.3 status: optional.**

By default the server runs unauthenticated and listens on loopback
(`127.0.0.1`). For cluster-internal deployment behind a NetworkPolicy,
that is appropriate.

Bearer-token auth is on the roadmap (gated by `PPXAI_API_TOKEN` env
var; default off to preserve loopback UX). Until that lands, anything
exposing ppxai-server beyond a trusted network MUST gate it at the
ingress / service-mesh layer (mTLS, OAuth proxy, etc.).

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
- **Provider support.** v1 supports OpenAI-compatible providers, which
  covers `local`, `custom`, and any deployment routed through
  `OpenAICompatibleProvider` (NIM, vLLM, Ollama, OpenRouter, ...). Native
  OpenAI / Perplexity / Gemini providers grow oneshot support in
  subsequent releases; until then they return 400 with a clear message.
- **`response_format`.** Forwarded to the provider as-is. NVIDIA NIM,
  vLLM, and modern OpenAI-compat endpoints accept the OpenAI shape.
  Older endpoints may return 400 — that surfaces to the client as 502
  with the upstream message.
- **Per-model `extra_body` from `ppxai-config.json`** still applies.
  This means vendor knobs (NIM `chat_template_kwargs.enable_thinking`,
  Qwen3 `enable_thinking`, etc.) carry through without the caller
  having to know about them.

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
