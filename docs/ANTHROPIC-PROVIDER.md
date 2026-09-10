# Anthropic provider (Claude)

> ## ⚠️ Status: UNTESTED against the live API
>
> This provider has **never made a real API call.** Its tests shape requests
> and read response objects; the Anthropic SDK is never invoked, and no
> `ANTHROPIC_API_KEY` existed on the machine it was written on. It is
> verified against the SDK surface and the published docs, not against
> observed behaviour.
>
> **Unproven, not broken.** It is inert unless you install the `[anthropic]`
> extra and configure the provider, so it cannot affect an existing install.
> If you are the first to point it at a real key, expect bugs — and the three
> most likely are named under [Limits of Phase 1](#limits-of-phase-1).
>
> Remove this banner once a live smoke test passes.

Native support for Claude over Anthropic's Messages API. Optional — install
the extra to enable it:

```bash
uv sync --extra anthropic     # or: pip install 'ppxai[anthropic]'
export ANTHROPIC_API_KEY=sk-ant-...
```

Without the extra the provider does not register, and `create_provider("anthropic")`
returns `None` — the same "provider unavailable" path every caller already
handles.

## Why this is not an OpenAI-compatible endpoint

Anthropic publishes an OpenAI-compatible shim, and pointing
`OpenAICompatibleProvider` at it would have been a config entry rather than a
module. That shim flattens the request into the chat-completions shape, which
costs every Claude-specific capability this provider exists to reach:

| Capability | Through this provider | Through the compat shim |
|---|---|---|
| Adaptive thinking + `effort` | yes | no |
| Prompt caching (and its 3 input billing classes) | yes | no |
| `stop_reason: "refusal"` + `stop_details` | yes | flattened |
| Native parallel tool calls | yes | partial |

ppxai models this as a **wire**, not a dialect: `ModelFacts.wire_protocol`
has reserved `"messages"` since ADR 0012, and
`ppxai/engine/providers/wire/messages.py` is the handler that fills the slot.
The provider owns the *account* (key, models, prices, error classification);
the handler owns the *format*.

## Configuration

```jsonc
"anthropic": {
  "name": "Anthropic",
  "base_url": "https://api.anthropic.com",   // recorded; the SDK client is built directly
  "api_key_env": "ANTHROPIC_API_KEY",
  "default_model": "claude-opus-5",
  "coding_model": "claude-opus-5",
  "options": {
    "enable_thinking": true,
    "enable_prompt_caching": true
    // "effort": "low" | "medium" | "high" | "xhigh" | "max"
  }
}
```

### Thinking is configured, never prompted

`budget_tokens` is **rejected with a 400** on Claude Opus 5, Sonnet 5 and the
4.7/4.8 family — the fixed-thinking-budget concept is gone, replaced by
adaptive thinking plus `output_config.effort`. Do not add "think step by
step" to a system prompt for these models either: the incantation is
redundant at best on a thinking model, and depth is a request parameter.

ppxai sends `display: "summarized"` so the reasoning pane has something to
show. The API default is `"omitted"`, which streams **empty** thinking
blocks — the pane would look like a long pause before the answer.

### Effort is a cost lever, not a quality dial

`effort` trades thoroughness against token spend within one model. It is the
first quality-trading lever *after* the free wins, and higher is not
automatically better — the top of the range earns its cost only on hard
problems. Sweep it against `benchmarks/llm-eval/` on your own traffic before
changing the default; the curve is per-workload and per-model.

### Sampling parameters are dropped, deliberately

`temperature`, `top_p` and `top_k` are rejected on this wire. An operator
config carrying them (written for another provider) would otherwise make
**every** Claude request fail, so the provider filters them and logs at debug
rather than forwarding them.

## Cost accounting

Anthropic bills input in **three** classes, not one:

| Class | Rate |
|---|---|
| uncached input | the model's `input` rate |
| cache **write** | 1.25x input (5-minute cache) |
| cache **read** | 0.1x input |

`UsageStats` carries `cache_creation_input_tokens` / `cache_read_input_tokens`
and `calculate_cost` prices them separately. This matters in the expensive
direction: folding cache reads into `prompt_tokens` would over-report by up
to 10x on the cached portion. Rates come from the model's pricing row when it
states `cache_write` / `cache_read`, and otherwise from those multipliers.

**The shipped prices are a snapshot** (Anthropic's published table, cached
2026-06-24) and carry a `__comment` saying so. Verify them against current
published pricing before trusting `/cost` — prices change, and a stale rate
is a silently wrong number.

## Refusals are a 200, not an error

Claude may decline a request: HTTP 200, `stop_reason: "refusal"`, with a
`stop_details` category. ppxai surfaces this as an `ERROR` event in chat and
as a `refusal` key on the `/v1/oneshot` result, so a caller reading only
`content` cannot mistake a decline for an empty completion.

`stop_details` is populated **only** for a refusal and is `None` for every
other stop reason — read it guarded.

**Server-side refusal fallbacks are NOT enabled.** Anthropic offers a
`fallbacks` parameter that silently re-runs a declined request on a different
model inside the same call. It is deliberately off here: it changes which
model answered and what the operator is billed for, which is the operator's
decision rather than ppxai's default. Enable it in your own fork if you want
it, and note it requires the beta Messages endpoint.

## Auth

Phase 1 is API-key only (`ANTHROPIC_API_KEY`). The mainline path, and the
recommended one.

⚠️ **OAuth credential reuse is NOT implemented** (ROADMAP Phase 2). Reusing
Claude Code subscription credentials from a non-Claude-Code client may
violate Anthropic's Terms of Service. ppxai will not read
`~/.claude/.credentials.json` and does not take that decision on your behalf.
If Phase 2 lands it will be opt-in behind an explicit config flag, with a
runtime warning — the project does not endorse, guarantee, or take legal
responsibility for that path.

## Limits of Phase 1

**Where a live call is most likely to disagree with this code**, in order —
these are the assumptions a smoke test would settle first:

1. **Stream event shapes.** `wire`-side streaming matches
   `content_block_delta` with `text_delta` / `thinking_delta` deltas. Wrong
   type names mean text and reasoning stream as nothing — a silent empty
   response, not an error.
2. **Cache token reporting.** Top-level `cache_control` is assumed to yield
   `cache_creation_input_tokens` / `cache_read_input_tokens` in `usage`. If
   it does not, `/cost` under-reports the cached portion and the whole
   cache-aware pricing path is decorative.
3. **Structured outputs placement.** `response_format` goes inside
   `output_config.format` on `oneshot`. If the API expects it elsewhere,
   schema-pinned oneshot calls return 400.

Implemented (subject to the above): streaming chat, `oneshot`, native tool
calling, vision, prompt caching, adaptive thinking, effort, refusal handling,
throttle classification, cache-aware usage.

Not implemented: server-side tools (`web_search`, `web_fetch`, code
execution), the Batches API, the Files API, extended context beta headers,
and OAuth (above). None are blocked — they are simply not Phase 1.
