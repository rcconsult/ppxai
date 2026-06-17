# Plan: Option A — config-driven native web search for oneshot

**Status:** Proposed (awaiting go)
**Branch:** `feature/v1.19.0`
**Scope:** additive, capability-gated; the egress security perimeter is held
**constant** by design (this is the whole point of Option A).

---

## Problem

The tool-free `/v1/oneshot` and `/v1/agent/run` tiers answer from model weights
only — no retrieval. For search-native providers (Perplexity, Gemini) that's the
worst tier: you pay for a search model with search switched off. The user wants
oneshot to "augment its context with web search and answer more advanced
queries" — **without** importing the tool-loop exfiltration threat model.

## Decision (settled)

**Option A: native, provider-side web search.** Retrieval happens inside the
provider's own API call (Perplexity Sonar, Gemini Google Search grounding). The
model is **never** given a `web_search`/`fetch_url` tool, so there is no
prompt-injection exfiltration vector and `NetworkPolicy` (the `/task`-only
egress firewall) is **not** involved.

Rejected: Option B (giving oneshot the actual web tools) — that turns oneshot
into a tool loop and pulls in the SSRF/exfil surface without the allowlist that
contains it on `/task`.

## Security perimeter (UNCHANGED — the contract of this change)

| Property | Before | After |
|---|---|---|
| Egress hosts from a oneshot call | provider API only | provider API only (`api.perplexity.ai`, `generativelanguage.googleapis.com`) |
| `web_search`/`fetch_url` tool exposed to model | no | **no** (locked by test) |
| Model can name an arbitrary URL to fetch | no | **no** |
| `NetworkPolicy` involvement | none (oneshot bypasses `ScopedToolManager`) | none |
| Prompt-injection exfil vector | none | none |

Trust boundary = "I already trust Perplexity/Google to fetch on my behalf" —
the same boundary every existing oneshot call already crosses.

## What the code ALREADY does (verified 2026-06-17)

This is the key finding: for the two search-capable providers, Option A is
**already live as configured** — the increment is a control surface + guardrails,
not new plumbing.

- **Gemini** — `oneshot()` calls `_build_config(use_grounding=self.enable_grounding)`
  (gemini.py:496); with no ppxai tools passed, `GoogleSearch()` is added
  (gemini.py:663). `_build_provider` forwards `provider.gemini.options.enable_grounding`
  (config: `true`) via `**options`. **Gemini oneshot grounds today.**
- **Perplexity** — default model `sonar-pro` searches natively ("always on for
  sonar models", perplexity.py:51). `oneshot()` uses the model as-is.
  **Perplexity oneshot searches today.**
- **OpenAI / NVIDIA** — `capabilities.web_search = false`. No native search;
  correctly a no-op for Option A.

So the user's "impractical endpoint" experience was either on a non-search
provider, or grounding working silently-but-unrecognized. Either way the gap is
**control + discoverability**, not capability.

## The increment

A single global switch, capability-gated, default-off, plus guardrails.

1. **Config flag** `tools.web_search.oneshot_grounding` (bool, default `false`).
   - When **off** (default): current behavior, byte-identical. ppxai-sre's
     `/v1/oneshot` consumers see no change.
   - When **on**: for *search-capable* providers, ensure native search is
     active at provider-construction time — Gemini `enable_grounding=True`;
     Perplexity selects/keeps a sonar search model if the requested model
     isn't search-capable. For non-search providers it is a **no-op** (never
     silently mistaken for Option B).
   - Read in `routes/oneshot.py::_build_provider` and the agent-run
     `_v1_provider_or_400` path (the two oneshot construction sites).
2. **Capability gate** — apply only when `capabilities.web_search` is true for
   the provider. Keeps the flag honest: it can never reach for a tool.
3. **Tests**
   - Gemini oneshot adds `GoogleSearch` when grounding on; absent when off.
   - Perplexity oneshot uses a search (sonar) model.
   - OpenAI/NVIDIA oneshot unaffected by the flag.
   - **Perimeter lock:** assert NO `web_search`/`fetch_url`/`get_weather` tool is
     ever registered on the oneshot path (guards against future drift into B).
4. **Docs** — `docs/api-gateway.md`: oneshot grounding is opt-in + provider-gated;
   security rationale (no exfil tool exposed); note that Gemini/Perplexity
   already ground by config and the flag is the explicit override.

## Non-goals

- No change to `/v1/agent/task` or `NetworkPolicy`.
- No `web_search`/`fetch_url` tool on the oneshot path (that's Option B).
- No new egress destinations.

## Files (anticipated)

- `ppxai/server/routes/oneshot.py` — read flag in `_build_provider`, set native
  search on search-capable providers.
- `ppxai/server/routes/agent_v1.py` — same gate in `_v1_provider_or_400`.
- `ppxai/config/loader.py` (or wherever `tools.web_search` is read) — surface
  the new key with a default.
- `tests/test_oneshot_grounding.py` (new) — the four assertions above.
- `docs/api-gateway.md` — opt-in note + rationale.
- `docs/debt-inventory.md` — increment entry.

## Trial recipe (after build)

```powershell
# flag OFF (default): non-search-flavored answer, no citations
irm http://127.0.0.1:54320/v1/oneshot -Method Post -ContentType application/json `
  -Body (@{prompt="what shipped in the latest ppxai release this week?"; provider="perplexity"; model="sonar-pro"} | ConvertTo-Json)

# flag ON in config → same call returns grounded + cited answer
# (Gemini: same prompt, provider="gemini" → grounded today even with flag off)
```

## Verify-don't-assume checklist

- [ ] Confirm `_build_provider` actually forwards the new flag to provider ctor
      (read, don't assume — `**options` path).
- [ ] Confirm Perplexity model-substitution only triggers for non-sonar models
      (don't downgrade a deliberately-chosen reasoning model).
- [ ] Run the perimeter-lock test and watch it FAIL if a web tool is added to
      the oneshot path (negative test must actually bite).
