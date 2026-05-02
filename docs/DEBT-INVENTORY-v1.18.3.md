# v1.18.3 Debt Inventory — Deferred Open Items

**Created:** 2026-05-02 (during `feature/v1.18.3` branch — pre-release).
**Status:** Tracking. Items here are explicitly deferred — not bugs blocking
release, but real follow-up work surfaced by the NVIDIA NIM Tier A
benchmark sweep (2026-05-01) and the engine work that closed Tier 1
items #1, #2, #3 + Tier 2 items #4, #5 from the post-sweep proposal.

This file is the canonical home for the remaining deferred items. Each
entry links back to its surfacing context, gives the trigger condition
for revisiting, and estimates effort so the next contributor can scope
a focused branch without re-discovering the context.

## How to use this file

- **Update on every release.** When an item lands, move it under
  "## Closed" with the commit hash + date. When new debt surfaces, add
  it to the appropriate section.
- **Don't merge debt items into release-note TODOs.** Those describe
  in-flight work for a specific version (`TODO-v1.18.3-*.md`); this
  describes work intentionally **not** in any version's plan yet.
- **Keep entries scannable.** One short paragraph + a "trigger to
  revisit" line + an effort estimate. Long context goes in linked docs.

---

## Open

### Item 16 — Surface throttle counters in `/usage` command output

**Affected files:** `ppxai/usage.py` (already has the data via
`get_provider_errors()`), `ppxai/commands/usage.py`, `ppxai/server/routes/usage.py`,
`ppxai/web/app.js` (web `/usage` panel), `vscode-extension/src/handlers/`
(VSCode `/usage`), `ppxai/rich/event_handler.py` (Rich-TUI `/usage`),
`ppxai/tui/app.py` (Textual `/usage`).

**What's already done:** v1.18.3 Tier 2 #5 plumbed
`UsageStorage.record_provider_error(provider, status_code, model)`
into the throttle path of `openai_compat.py`. Every NIM 403 / 429
(and any other openai-compat 403/429) now persists to
`~/.ppxai/usage/usage.json` under the `provider_errors` key with shape
`{count, last_seen, models[]}`.

**What's missing:** none of the four `/usage` rendering surfaces (Rich,
Textual, web, VSCode) read the new field. The data accumulates silently;
a user looking at "today's NVIDIA NIM activity" still only sees token
counts and cost, with no way to know whether 80% of calls were rate-limit
blocked. Surfacing it fulfils the original Tier 2 #5 design intent —
"NIM returned 12 quota errors today, last at 14:32" — and makes the
contamination pattern (see Item 18 below) visible without re-running
benchmarks.

**Why deferred:** the persistence layer is the load-bearing piece. UI
rendering is a clean follow-up that doesn't gate the v1.18.3 release —
shipping the persistence first means data starts accumulating from
v1.18.3 onward, so when the rendering lands, there's already history.

**Trigger to revisit:** next NVIDIA NIM session that hits a quota wall,
OR when `/usage` is touched for any other reason, OR a quiet rainy
afternoon (~30-45 min of work).

**Effort:**
- Minimum (~30 min): one new section in each of the four renderers
  reading `usage.get_provider_errors()` and emitting a "Provider errors"
  table with columns `provider | status | count | last_seen | models`.
  Skip the section when the dict is empty.
- Polish (~+15 min): optional `/usage --errors` flag to show only the
  error counters, hide them when zero, group by provider with sub-rows
  for status codes.

**Branch when ready:** `feat/usage-throttle-display`.

---

### Item 17 — Rerun qwen3-coder-480b benchmark on paid NVIDIA tier

**Affected files:** `benchmarks/llm-eval/results/index.json`,
`benchmarks/llm-eval/results/nvidia_qwen_qwen3-coder-480b-*.json`,
`ppxai-config.json` (`__comment_benchmark` block on `nvidia` provider),
`AGENTS.md` (`Qwen/Qwen3-Coder*` model_hint block).

**What's wrong:** the 2026-05-01 free-tier sweep returned 19.0% for
`qwen/qwen3-coder-480b-a35b-instruct` — but that result is
**rate-limit-contaminated**, not a quality measurement. The model made
9 tool calls in 75s vs 74-89 calls in 197-1836s for healthy peers, and
multiple test results contain `{"message":"operation not allowed"}`
errors from NIM's 403 quota-block response.

**Free-tier rerun on 2026-05-02** (commit landing this entry): re-ran
the 36-test sweep — same 19.0% (7/36), same low-tool-call signature
(11 calls in 86s). Only **1 of 29 failures** explicitly leaked the
"operation not allowed" marker this time, vs many on the 2026-05-01
run. **Conclusion: the free tier still throttles the 480b, just less
explicitly.** The duration + tool-call-count signature is the
diagnostic, not the explicit error string. Fixed
`__comment_benchmark` in both configs to record both runs.

A single curl ping to the same endpoint at session start returned
200 OK in 679 ms — confirms the API itself works for this model on
free tier; it's the sustained 36-test load that hits the wall.

See [memory/feedback_benchmark_rate_limit_contamination.md] for the
broader diagnostic pattern.

**What's still open:** a clean (paid-tier) score for the 480b. The
provisional Tier S profile entry in `engine/model_profiles.py`
inherits family characteristics from the existing `qwen3-coder*`
glob, but `__comment_benchmark` in both repo configs continues to flag
the score as un-trustworthy until a clean rerun.

**Why deferred:** requires NVIDIA NIM paid-tier access. The 2026-05-02
rerun confirmed the free-tier diagnosis — no further free-tier reruns
will produce a clean number. The provisional Tier S placement is
reasonable given the family heritage; a paid-tier rerun would either
confirm or re-tier.

**Trigger to revisit:** when paid-tier access is provisioned, OR when
NVIDIA changes their free-tier policy, OR when a user reports the
480b underperforming in real use.

**Effort:**
- ~15 min: rerun the 36-test sweep against the paid-tier endpoint:
  `python benchmarks/llm-eval/benchmark.py --provider nvidia --model qwen/qwen3-coder-480b-a35b-instruct --timeout 120 --retries 1`
- ~5 min: update `__comment_benchmark` in `ppxai-config.json` and
  `ppxai-config.example.json` with the clean score; remove the
  "RATE-LIMIT-CONTAMINATED" qualifier.
- ~5 min: re-tier `*/qwen3-coder-480b*` profile if the score warrants
  a different placement.

**Branch when ready:** `bench/qwen3-coder-480b-rerun`.

---

### Item 18 — Probe kimi-k2-thinking, deepseek-v3.2, qwen3.5-397b once endpoints come back

**Affected files:** `ppxai-config.json` (currently has these as
"probe failed" model entries with no benchmark data),
`benchmarks/llm-eval/results/`.

**What's wrong:** during the 2026-05-01 NIM provider validation,
three models had endpoint timeouts (~90s) on the basic tool-calling
probe:
- `moonshotai/kimi-k2-thinking`
- `deepseek-ai/deepseek-v3.2`
- `qwen/qwen3.5-397b-a17b`

Cause unknown — could be cold-start latency, regional routing, or
free-tier credit exhaustion on those specific models. Their config
entries carry a `"probe failed"` description and no benchmark.

**Why deferred:** the three Tier A passing models (qwen3.5-122b-a10b,
qwen3-next-80b-{instruct,thinking}) are sufficient for daily use.
Filing this so the next NIM session checks whether the endpoints are
back rather than re-discovering "huh, those don't work" cold.

**Trigger to revisit:** any new NVIDIA NIM session, OR when an external
report confirms availability has changed.

**Effort:**
- ~5 min: rerun `/c/tmp/probe_nvidia_models.sh` — already exists,
  classifies HTTP 200 + tool_calls / 400 / timeout / etc.
- If any probe succeeds: ~10 min benchmark each via
  `c:/tmp/run_nvidia_tierA*.sh`.
- ~2 min: update config descriptions / add `__comment_best_for` for
  newly-passing models.

**Branch when ready:** `bench/nvidia-tier-a-followups`.

---

## Carried over from DEBT-INVENTORY-v1.18.2.md (still open)

### Item 3 — k8s session-manager security tests

**Status:** trigger-deferred. See full entry in
[DEBT-INVENTORY-v1.18.2.md](DEBT-INVENTORY-v1.18.2.md#item-3--k8s-session-manager-security-tests-critique-8).
Not addressable until in a k8s context environment.

### Item 14 — Anthropic provider

**Status:** carried over. Pre-work + ADR done; Phase 1 (API key)
implementation pending. ~half day with TOS-aware OAuth fallback in
Phase 2. [DEBT-INVENTORY-v1.18.2.md](DEBT-INVENTORY-v1.18.2.md#item-14--add-anthropic-provider-with-explicit-tos-aware-auth-fallback).

---

## Closed

### Tier 1 #1 — `extra_body` config pass-through — closed 2026-05-02 (commit `0f986d36`)

`ppxai/config/providers.py::get_extra_body()` resolves a per-provider /
per-model `extra_body` dict (provider defaults, model overrides win).
`ppxai/engine/providers/base.py::_get_extra_body()` is a thin instance
wrapper. `openai_compat.py` includes the resolved dict via
`client.chat.completions.create(extra_body=...)` only when non-empty
(empty dict skipped to avoid breaking strict endpoints). Comment keys
(`__comment_*`) stripped before sending. 7 tests in
`tests/test_extra_body.py` covering: no config → empty, provider-only,
model-overrides-provider, comment stripping, helper returns configured
payload, helper returns empty when not configured, AttributeError
fallback.

Unblocks Qwen3.5 / GLM `chat_template_kwargs.enable_thinking` toggle
without forking the engine. Future-proofs for other vendor-specific
runtime knobs (vLLM-only parameters, NIM-specific extras).

### Tier 1 #2 — `EventType.PROVIDER_THROTTLED` — closed 2026-05-02 (commit `0f986d36`)

New event type distinguishes provider-side rate-limit / quota errors
from generic model failures. `BaseProvider._classify_throttle()`
detects `RateLimitError` (HTTP 429) and `APIStatusError` with status
403, returning structured `{status_code, provider, model, message,
retry_after}` payload. `openai_compat.py` emits `PROVIDER_THROTTLED`
in place of `ERROR` when classification matches; `chat.py` treats both
events identically on the abort path but tags `reason="provider_throttled"`
in the `AGENT_RUN_ERROR` payload so post-mortems can distinguish quota
blocks from genuine failures.

ppxaide TUI `stream_handler.py` maps the new event onto `ENGINE_ERROR`
with a dict-aware unwrap so the user sees the recovery hint
(`message` field) rather than the raw payload dict.

`base.py::_format_error()` refines the 403 message: when body contains
"operation not allowed" (NIM's quota-block signature), the user sees
"Provider quota / permission error (403): endpoint refused the call.
On NVIDIA NIM free tier this typically means the per-model rate limit
was exhausted — wait, switch model, or use paid tier" instead of a
generic `API error (403)`.

9 tests in `tests/test_provider_throttle.py` covering classification
(403/429 → throttle, 400/500/generic-Exception → not), retry-after
header parsing, provider_id propagation, message formatting for NIM
403, generic 403, 429.

### Tier 1 #3 — ModelProfile entries for Tier A NVIDIA NIM models — closed 2026-05-02 (commit `0f986d36`)

`ppxai/engine/model_profiles.py` gains seven `*/<model>*` patterns
covering namespaced NIM IDs:
- `*/qwen3-coder-480b*` (Tier S, parallel_tool_calls=True, max_tokens=4096)
- `*/qwen3.5-122b*` (Tier A — NIM benchmark 77.4%, NVIDIA portal params)
- `*/qwen3.5-397b*` (Tier B provisional — probe failed, family-inherited)
- `*/llama-3.3-nemotron*` (Tier B provisional — supports_reasoning,
  in-prompt /think convention)
- `*/mistral-large-3*` (Tier B provisional — free-tier hung on
  agentic_tool_loops)
- `*/devstral-2*` (Tier B provisional — coding family)

Pre-fix, the existing `qwen3-coder*` pattern (no leading `*/`) only
matched non-namespaced IDs, so NIM-routed
`qwen/qwen3-coder-480b-a35b-instruct` fell back to the default profile.

8 tests in `tests/test_model_profiles.py::TestNvidiaNimProfiles`
pinning each pattern + an unknown-NIM-model fall-through sanity check.

### Tier 2 #4 — `reasoning_trigger` per-model in-prompt marker — closed 2026-05-02 (commit `51c55d16`)

NVIDIA's `nvidia/llama-3.3-nemotron-super-49b-v1.5` toggles reasoning
via an in-prompt convention: `/think` enables, `/no_think` disables.
This is distinct from `chat_template_kwargs.enable_thinking` (Qwen3.5 /
GLM go via `extra_body`) — nemotron has no extra-body knob.

`ppxai/config/providers.py::get_reasoning_trigger()` resolves a
per-provider / per-model `reasoning_trigger` string (provider defaults,
model overrides win). `BaseProvider._apply_reasoning_trigger()`
appends the configured marker on its own line to the FIRST `role ==
"system"` message. Idempotent: skipped when already present.
When no system message exists, one is prepended carrying just the
trigger. `openai_compat.py` calls the helper after `_convert_messages`
in both streaming and `chat_sync_simple` paths.

`ppxai-config.json` nemotron entry has `"reasoning_trigger": "/think"`
so reasoning fires by default. Users override to `/no_think` to disable
for cost / latency reasons.

9 tests in `tests/test_reasoning_trigger.py` covering: config layer
(no config / provider-only / model-overrides / empty-string-as-none)
and provider layer (no-trigger no-op / append to existing system /
idempotent / prepend when no system / first-system-only when multiple).

### Tier 2 #5 — Provider-error telemetry in usage_stats — closed 2026-05-02 (commit `51c55d16`)

`UsageStorage.record_provider_error(provider, status_code, model)`
persists a counter to `~/.ppxai/usage/usage.json` under the new
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
`_classify_throttle` path after emitting `EventType.PROVIDER_THROTTLED`.
Best-effort persistence: failures are logged at DEBUG and ignored —
telemetry must not break chat. Backward-compatible with pre-v1.18.3
files (`provider_errors` key absent → defaults to empty dict on load).

8 tests in `tests/test_usage_provider_errors.py` covering: first
record creates entry, repeated records increment count, distinct
models tracked (deduped), distinct status codes tracked separately,
record persists across instances, record without model works,
module-level convenience functions, pre-v1.18.3 backward compat.

The data accumulates from v1.18.3 onward but is not yet rendered in
any `/usage` surface — see Item 16 (Open) for the rendering follow-up.

### Item 12 — GitHub Actions Node 20 deprecation — closed 2026-05-02 (commit `c1bc765b`)

Carried from v1.18.2. Bumped `actions/checkout`, `actions/setup-node`,
`actions/upload-artifact`, `actions/download-artifact` from v4 → v5
across `build.yml` (8 + 2 + 7 + 5 = 22 occurrences) and `docs.yml`
(1 occurrence). v5 versions ship Node 24 manifests natively, so the
`FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: 'true'` env-var override is no
longer needed and dropped from both workflows. Untouched:
`astral-sh/setup-uv@v4` (different vendor), `softprops/action-gh-release@v2`
(separate version track), `actions/setup-python@v5` (already current).
Beats GitHub's hard cutoff of 2026-09-16 by ~4 months.

### Item 13 — `release.py` step 14 silent-failure fix — closed 2026-05-02 (commit `4d756c1a`)

Carried from v1.18.2. `verify_release()` now `sys.exit(1)` on four
critical conditions: release missing, JSON unparseable, required
asset(s) missing, body shorter than `MIN_RELEASE_BODY_CHARS=500`.
Asset list expanded from 11 → 15 to include the 3 ppxaide binaries
(build-tui-textual job) and the macOS DMG (build-dmg job) — both
were silently un-checked before, which is why the v1.18.2 build-dmg
flake passed verification. Body cross-check warns (not exits) on
prefix mismatch with `docs/RELEASE-NOTES-v*.md`. Verified against
live v1.18.2 (success) + simulated v1.18.2-style failures
(missing-DMG, 80-char body) — all four `sys.exit(1)` paths trigger
correctly with actionable recovery hints.

Lands on `feature/v1.18.3` so the fix runs for the v1.18.3 release
itself — first opportunity to confirm it catches the silent-failure
modes that bit v1.18.1 (4 retag cycles) and v1.18.2 (twice).

### Item 15 — `deploy/shared/AGENTS.md` deletion — closed 2026-05-02 (commit `c7f3a3d7`)

Carried from v1.18.2. `deploy/shared/AGENTS.md` (369 lines) and
`deploy/shared/AGENTS-local.md` (82 lines) deleted entirely (option
(b) from the v1.18.2 entry's listed remediations). Confirmed nothing
in the deploy stack reads them: `deploy/images/server/Dockerfile:53`
copies `AGENTS.md` from the project root, not `deploy/shared/`. No
helm template, kaniko job, session-manager deployment, or
`values.yaml` referenced the path. The parallel copies had drifted
across 13 model_hint blocks since 2026-03-27. git history preserves
both files if anyone needs to consult them; the empty
`deploy/shared/` directory disappears with them.

### Item 19 — Qwen3.5 `enable_thinking` config example — closed 2026-05-02 (commit `7db7d665`)

Added an `__example_extra_body` block to the
`qwen/qwen3.5-122b-a10b` entry in both bundled configs
(`ppxai-config.json` and `ppxai-config.example.json`) showing the
`chat_template_kwargs.enable_thinking` shape, plus an
`__comment_extra_body` explaining why it's commented out by default
(~2x latency). Also added a hint line to the `Qwen/Qwen3.5*`
model_hint block in `AGENTS.md` pointing at the config example.

The `__example_*` prefix follows the existing `__comment_*`
convention and is stripped before sending to the provider — config
remains valid even with the example present. Closes the only
v1.18.3 Open item that didn't gate on external triggers (paid NIM
tier, kubernetes context, etc.).

---

## Bug fixes from in-branch validation on 2026-05-02

### Sentinel-test regression caught
`tests/test_stream_handler_dispatch.py::test_every_event_type_is_covered`
flagged the new `EventType.PROVIDER_THROTTLED` as missing from
`stream_handler.py::EVENT_MAP`. Fixed by mapping it to `ENGINE_ERROR`
(chat.py treats them identically) + dict-aware unwrap in
`on_engine_error` so users see the recovery hint instead of the raw
payload dict. The drift test did its job — added without it, the
ppxaide TUI would have silently logged "Unhandled event type" warnings
on every NIM 403.

---

## Related documents

- [docs/RELEASE-NOTES-v1.18.3.md](RELEASE-NOTES-v1.18.3.md) — user-facing summary of the release
- [docs/DEBT-INVENTORY-v1.18.2.md](DEBT-INVENTORY-v1.18.2.md) — prior version's tracking
- [memory/feedback_benchmark_rate_limit_contamination.md] — diagnostic pattern for the Item 17 contamination signal
- [AGENTS.md] `nvidia:` provider_hint block — runtime guidance for models on NIM endpoint
- [ppxai-config.json] `nvidia` provider entry — 12 curated NIM models with portal-recommended params

The `TODO-v1.18.3-*.md` family (none yet at branch creation) describes
in-flight planning for v1.18.3. This doc tracks debt **not** in any
version's plan yet — items needing their own future branch.
