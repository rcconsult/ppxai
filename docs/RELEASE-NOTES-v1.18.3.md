# Release Notes — v1.18.3

> **Scope:** NVIDIA NIM provider goes from "config-only support" to
> "first-class engine support." Five engine-level changes across two
> commits, plus a Tier A benchmark sweep that quantified the model lineup.
>
> **Tests:** 2883 passing, 15 skipped (was 2842 at v1.18.2 baseline → +41).
> 7 of the 15 skips are Unix-only `TestKillPreviewBackend` (Windows lacks
> the mock targets); fully covered on Linux CI.

## Summary

v1.18.3 takes NVIDIA NIM from "you can configure it as a custom provider
and it mostly works" to "the engine knows about NIM-style models, throttle
events, and reasoning-mode toggles." The work clusters into three themes:

1. **NVIDIA NIM provider + Tier A benchmark sweep** (2026-05-01,
   committed at `b37e6a01` — already on master pre-branch). Provider
   config with 12 curated models, NVIDIA-portal-recommended per-model
   params, native tool calling default. Benchmark winners:
   `qwen/qwen3.5-122b-a10b` 77.4% (best Tier A overall), Qwen3-Next-80B
   thinking variant 76.6%, Qwen3-Next-80B instruct 68.3%. The
   `qwen/qwen3-coder-480b` 19% result was rate-limit-contaminated on
   free tier — see Item 17 in the debt inventory for paid-tier rerun.

2. **Tier 1 engine support** (`0f986d36`). Three orthogonal additions:
   ModelProfile entries for namespaced NIM IDs, typed `PROVIDER_THROTTLED`
   event for HTTP 403/429 with structured payload, and `extra_body`
   config pass-through for vendor-specific runtime knobs.

3. **Tier 2 engine support** (`51c55d16`). Two follow-ups: per-model
   `reasoning_trigger` (in-prompt `/think` / `/no_think` for nemotron-style
   toggles), and provider-error telemetry persisted to
   `~/.ppxai/usage/usage.json` so quota-block patterns survive across
   sessions.

The user-visible change is most evident on three error paths: a NIM 403
"Operation not allowed" now produces a clear "Provider quota /
permission error... wait, switch model, or use paid tier" message
rather than a generic API-error wrapping the JSON body; the agent loop
tags the resulting `AGENT_RUN_ERROR` with `reason="provider_throttled"`
so post-mortems can distinguish quota blocks from genuine model
failures; and the throttle counters silently accumulate so a
follow-up `/usage` rendering pass (debt Item 16) can show "NVIDIA
returned 12 quota errors today" without re-running benchmarks.

## What's new

### NVIDIA NIM provider (already on master pre-branch)

`ppxai-config.json` and `ppxai-config.example.json` ship with a `nvidia`
provider entry pointing at `https://integrate.api.nvidia.com/v1`,
authed via `NVIDIA_API_KEY`, native tool calling default. 12 curated
models with NVIDIA-portal-recommended `generation_params` (temp varies
0.2–0.7, top_p varies 0.8–0.95). `qwen2.5-coder-32b-instruct` overrides
to `tool_calling.mode='prompt_based'` because NIM does not enable
native tools for that model.

Tier A benchmark sweep (2026-05-01, full 36-test suite):

| Model | Score | Tool calls | Status |
|---|---:|---:|---|
| `qwen/qwen3.5-122b-a10b` | **77.4%** | 74 | ✅ best Tier A overall |
| `qwen/qwen3-next-80b-a3b-thinking` | **76.6%** | 75 | ✅ thinking +8.3 vs instruct |
| `qwen/qwen3-next-80b-a3b-instruct` | **68.3%** | 89 | ✅ cheap fast tool-caller |
| `qwen/qwen3-coder-480b-a35b-instruct` | 19.0% | 9 | ⚠️ rate-limit-contaminated |
| `mistralai/mistral-large-3-675b-instruct-2512` | — | — | ✗ free-tier hang on agentic_tool_loops |
| `nvidia/llama-3.3-nemotron-super-49b-v1.5` | — | — | ✗ same hang pattern |
| `meta/llama-4-maverick-17b-128e-instruct` | — | — | ✗ regional unavailable in EU |

The 480B's 19% is **NOT** a quality measurement — only 9 tool calls
in 75s vs 74-89 calls in 197-1836s for healthy peers, with multiple
test results showing `{"message":"Operation not allowed"}` from NIM's
free-tier 403 quota-block. See `__comment_benchmark` in both repo
configs and Item 17 in [DEBT-INVENTORY-v1.18.3.md](DEBT-INVENTORY-v1.18.3.md)
for the paid-tier rerun plan.

### ModelProfile entries for namespaced NIM IDs (Tier 1 #3)

`ppxai/engine/model_profiles.py` gains seven `*/<model>*` patterns
covering NIM-namespaced IDs. Pre-fix, the existing `qwen3-coder*`
pattern (no leading `*/`) only matched non-namespaced IDs, so
`qwen/qwen3-coder-480b-a35b-instruct` fell back to the default profile.

```python
"*/qwen3-coder-480b*": ModelProfile(  # Tier S, parallel_tool_calls
    tool_calling=ToolCallingProfile(mode="native", parallel_tool_calls=True),
    max_tokens=4_096, max_tool_iterations=20, tier="S",
),
"*/qwen3.5-122b*": ModelProfile(tool_calling=..., max_tokens=4_096, tier="A"),
"*/qwen3.5-397b*": ModelProfile(tool_calling=..., max_tokens=4_096, tier="B"),
"*/llama-3.3-nemotron*": ModelProfile(
    tool_calling=..., max_tokens=8_192,
    supports_reasoning=True,  # in-prompt /think convention
    tier="B",
),
"*/mistral-large-3*": ModelProfile(tool_calling=..., max_tokens=4_096, tier="B"),
"*/devstral-2*": ModelProfile(tool_calling=..., max_tokens=4_096, tier="B"),
```

Sentinel test class `TestNvidiaNimProfiles` in
`tests/test_model_profiles.py` pins each pattern.

### `EventType.PROVIDER_THROTTLED` typed event (Tier 1 #2)

```python
class EventType(Enum):
    ...
    PROVIDER_THROTTLED = "provider_throttled"
    # Payload: {"status_code": int, "provider": str, "model": str,
    #           "message": str, "retry_after": Optional[float]}
```

`BaseProvider._classify_throttle()` in `engine/providers/base.py`
detects `RateLimitError` (HTTP 429) and `APIStatusError` with status
403, returning the structured payload. `openai_compat.py` emits
`PROVIDER_THROTTLED` instead of `ERROR` when classification matches;
`chat.py` treats both events identically on the abort path but tags
`reason="provider_throttled"` in `AGENT_RUN_ERROR` so post-mortems
can distinguish quota blocks from genuine failures.

The `_format_error()` 403 branch is refined: when the body contains
"operation not allowed" (NIM's quota-block signature), the user sees:

> Provider quota / permission error (403): endpoint refused the call.
> On NVIDIA NIM free tier this typically means the per-model rate limit
> was exhausted — wait, switch model, or use paid tier.

ppxaide TUI's `stream_handler.py` maps `PROVIDER_THROTTLED` onto
`ENGINE_ERROR` with a dict-aware unwrap in `on_engine_error` so the
user sees the recovery hint (`message` field) rather than the raw
payload dict.

### `extra_body` config pass-through (Tier 1 #1)

New `ppxai/config/providers.py::get_extra_body()` resolves a
per-provider / per-model `extra_body` dict (provider defaults, model
overrides win on conflict; comment keys stripped). `BaseProvider.
_get_extra_body()` is a thin instance wrapper. `openai_compat.py`
forwards the resolved dict via `client.chat.completions.create(
extra_body=...)` only when non-empty (empty dict skipped to avoid
breaking strict endpoints).

Config example:

```json
"providers": {
  "nvidia": {
    "extra_body": {
      "chat_template_kwargs": {"enable_thinking": false}
    },
    "models": {
      "qwen/qwen3.5-122b-a10b": {
        "extra_body": {
          "chat_template_kwargs": {"enable_thinking": true}
        }
      }
    }
  }
}
```

Unblocks Qwen3.5 / GLM `chat_template_kwargs.enable_thinking` toggle
without forking the engine. Future-proofs for vLLM-only parameters,
NIM-specific extras, GLM thinking-mode, etc.

### `reasoning_trigger` in-prompt marker (Tier 2 #4)

NVIDIA's `nvidia/llama-3.3-nemotron-super-49b-v1.5` toggles reasoning
via an in-prompt convention: `/think` enables, `/no_think` disables.
This is distinct from `chat_template_kwargs.enable_thinking` (Qwen3.5
/ GLM go via `extra_body`) — nemotron has no extra-body knob.

`ppxai/config/providers.py::get_reasoning_trigger()` resolves a
per-provider / per-model `reasoning_trigger` string. `BaseProvider.
_apply_reasoning_trigger()` appends the configured marker on its own
line to the FIRST `role == "system"` message. Idempotent: skipped
when already present at the end. When no system message exists, one
is prepended carrying just the trigger.

The bundled `ppxai-config.json` nemotron entry has
`"reasoning_trigger": "/think"` so reasoning fires by default.
Override to `/no_think` per-model to disable for cost / latency.

### Provider-error telemetry (Tier 2 #5)

`UsageStorage.record_provider_error(provider, status_code, model)`
persists a counter to `~/.ppxai/usage/usage.json` under a new
`provider_errors` key. Shape:

```json
{
  "provider_errors": {
    "nvidia:403": {
      "count": 12,
      "last_seen": "2026-05-02T14:32:00",
      "models": ["qwen/qwen3-coder-480b-a35b-instruct"]
    }
  }
}
```

`openai_compat.py` fires `record_provider_error` from the
`_classify_throttle` path after emitting `PROVIDER_THROTTLED`.
Best-effort persistence — failures logged at DEBUG and ignored.
Backward-compatible with pre-v1.18.3 usage files.

The data accumulates from v1.18.3 onward; a follow-up rendering pass
(debt Item 16) will surface it in the `/usage` command across all
four clients (Rich, Textual, web, VSCode).

### `nvidia:` provider_hint block in `AGENTS.md`

New runtime guidance for models served via NIM:

```yaml
nvidia:
  - "You are running on NVIDIA NIM (build.nvidia.com) with native tool calling."
  - "Call tools directly via the API - do NOT output tool-call JSON in response text."
  - "If a tool returns 'Operation not allowed' or 'NIM unavailable', that is a NIM-side rate limit / quota block, NOT a model failure. Acknowledge the error and STOP retrying - do not loop."
  - "After 2 consecutive identical NIM errors, report the persistent error to the user and wait - do not escalate to alternative tools."
  - "For long agentic chains, prefer fewer steps with focused tool calls over many small ones - free-tier quotas favour batched work."
  ...
```

The existing `Qwen/Qwen3.5*` and `*Qwen3-Next*` model_hint blocks
already covered the three benchmark-passing models — no model_hint
changes needed for v1.18.3.

## Internal

- **2883 tests passing** (was 2842 → +41 across the v1.18.3 branch).
  Distribution: 8 NIM profile sentinels + 9 throttle classification
  + 7 extra_body + 9 reasoning_trigger + 8 provider-error telemetry
  = 41 new tests. All run in <1s on the .venv interpreter.
- **`docs/DEBT-INVENTORY-v1.18.3.md`** filed with 4 new items (16:
  /usage rendering, 17: 480b paid-tier rerun, 18: kimi/deepseek/397b
  probes, 19: extra_body wiring example) plus 5 carried-over from
  v1.18.2 (Items 3, 12, 13, 14, 15).
- **Sentinel test caught a missing dispatcher entry.**
  `tests/test_stream_handler_dispatch.py::test_every_event_type_is_covered`
  flagged the new `EventType.PROVIDER_THROTTLED` as missing from
  `EVENT_MAP`. Fixed by mapping to `ENGINE_ERROR` (chat.py treats them
  identically). Without the drift test, ppxaide TUI would have silently
  logged "Unhandled event type" warnings on every NIM 403.

## Discipline pinned

### Verify before dismissing benchmark scores

The `qwen/qwen3-coder-480b` 19% Tier A free-tier result almost ended up
recorded as a quality finding. It was 80% of calls returning HTTP 403
from NIM's quota wall — diagnosable in 30 seconds by comparing
`metadata.total_tool_calls` (9 vs 74-89 for healthy peers) and
`duration_seconds` (75s vs 197-1836s) plus reading
`test_results[].details.error` for the "Operation not allowed" pattern.
Memory entry [feedback_benchmark_rate_limit_contamination.md] pins the
diagnostic ladder so the next surprisingly-low free-tier score gets the
same treatment.

### Follow user requests, don't second-guess them

Mid-branch, the user asked "bump version numbers and tier 2 items"
and I cited CLAUDE.md's `/release` rule, suggested deferring the bump,
and skipped it in favor of doing only the Tier 2 work. The user
corrected: "I said bump up version numbers, remember to follow user
requests, do not take decisions before asking user." Memory entry
[feedback_follow_user_requests.md] captures the lesson — policy docs
describe defaults, user instructions override defaults, and pre-deciding
"I'll do X *instead* because policy says Y" is a decision masquerading
as compliance.

## Resume context

If picking this up on a different machine, see
[DEBT-INVENTORY-v1.18.3.md](DEBT-INVENTORY-v1.18.3.md) for the open
follow-ups. The branch is `feature/v1.18.3` (pushed to origin at
`51c55d16`). Three commits over master:

```
51c55d16 feat(engine): NVIDIA NIM Tier 2 — reasoning_trigger + throttle telemetry
b3aad2f6 chore: bump version 1.18.2 → 1.18.3
0f986d36 feat(engine): NVIDIA NIM Tier 1 — profiles, throttle event, extra_body
```

`/release v1.18.3` is the next step — script will detect the version
bumps already in place and proceed to changelog/release-notes
verification + tag + push. Item 16 (`/usage` throttle display) and
Item 17 (480b paid-tier rerun) can roll into v1.18.4 or land first
depending on appetite.
