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

(All v1.18.3-introduced items closed in-branch — see "## Closed" below.
The remaining open work is in "## Carried over" below.)

---

## Carried over from DEBT-INVENTORY-v1.18.2.md (still open)

### Item 3 — k8s session-manager security tests

**Status:** trigger-deferred. See full entry in
[DEBT-INVENTORY-v1.18.2.md](DEBT-INVENTORY-v1.18.2.md#item-3--k8s-session-manager-security-tests-critique-8).
Not addressable until in a k8s context environment.

### Item 14 — Anthropic provider — moved to ROADMAP 2026-05-05

**Status:** moved from debt list to [ROADMAP.md §"v1.19.x - Anthropic
Provider (planned)"](../ROADMAP.md#v119x---anthropic-provider-planned).
Anthropic provider is feature work, not bug-fix-class debt — it belongs
on the roadmap, not the debt inventory. Original v1.18.2 entry preserved
at
[DEBT-INVENTORY-v1.18.2.md](DEBT-INVENTORY-v1.18.2.md#item-14--add-anthropic-provider-with-explicit-tos-aware-auth-fallback)
for the full design rationale (TOS warning text, OAuth fallback caveats).

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
remains valid even with the example present.

### Item 16 — Surface throttle counters in `/usage` — closed 2026-05-02 (commit `95b89115`)

v1.18.3 Tier 2 #5 plumbed `UsageStorage.record_provider_error` so
every NIM 403 / openai-compat 429 persists to
`~/.ppxai/usage/usage.json` under `provider_errors`. The data
accumulated silently — no `/usage` surface read it. This commit
makes the `/usage` command read it.

Single point of change feeds all 4 surfaces via the v1.18.1
envelope. New helpers `_build_provider_errors_table()` and
`_maybe_compose_with_errors()` in `ppxai/commands/tools.py` wrap
the existing usage TableResult in a CompositeResult ONLY when
provider_errors is non-empty. Empty-errors path returns the original
plain TableResult byte-identical to pre-v1.18.3 (backward-compatible).

CompositeResult was already supported by Rich and Textual via the
type-based dispatch; web (`web/shared/result-renderer.js`) and
VSCode (`vscode-extension/src/commandRenderer.ts`) had no handler —
added one in each that recurses the dispatcher into each sub-result.
Same pattern across all four renderers.

10 new tests in `tests/test_usage_provider_errors_command.py`:
empty → None, single → correct shape, multiple → sort order
(highest count first), comma-joined models, empty-models edge,
missing last_seen, session report empty path → plain TableResult
(backward compat), session report with errors → CompositeResult,
period report empty → plain TableResult, period report with errors
→ CompositeResult.

User-facing surface: when NIM has thrown 403s during the session,
`/usage` now shows a "Provider errors (throttle / quota / auth):
N total" table below the usage stats with provider | status | count
| last seen | models columns.

### Item 17 — qwen3-coder-480b excluded from curated NIM models — closed 2026-05-02 (commit `0f79549f`)

Re-ran the 36-test sweep against `qwen/qwen3-coder-480b-a35b-instruct`
on the NVIDIA NIM free tier on 2026-05-02 (commit `70882919` recorded
the result). Same 19.0% as the 2026-05-01 sweep, same low-tool-call/
short-duration contamination signature (11 calls in 86s on the rerun
vs 9 in 75s the day before; healthy peers do 74-89 in 197-1836s).
Conclusion: free tier throttles 480b sustained-load regardless of
how few explicit "operation not allowed" markers leak — the duration
and tool-call-volume signature is the diagnostic.

Decision (user direction 2026-05-02): exclude qwen3-coder-480b from
the curated NIM model set rather than continue listing a known-
broken-on-free-tier model. Removed entries from `models` and
`pricing` blocks in both `ppxai-config.json` and
`ppxai-config.example.json`. `coding_model` redirected from
qwen3-coder-480b to qwen3.5-122b-a10b (the Tier A champion at 77.4%
that already serves as default_model).

Engine `ModelProfile` entry (`*/qwen3-coder-480b*` glob in
`engine/model_profiles.py`) intentionally retained — users with paid
NIM access who re-add the model to their own config get the right
Tier S characteristics (parallel_tool_calls=True, max_tokens=4096).
Documented this in a new `__comment_coding_model` field in the main
config so the next reader doesn't mistake the exclusion for a code
oversight.

### Item 18 — NIM probe rerun: kimi-k2-thinking works, others still down — closed 2026-05-02 (commit `0f79549f`)

Re-probed the three "endpoint timeout" models from the 2026-05-01
NIM provider validation:

| Model | 2026-05-01 | 2026-05-02 |
|---|---|---|
| `moonshotai/kimi-k2-thinking` | timeout >90s | **200 OK** (reasoning_content emitted) |
| `deepseek-ai/deepseek-v3.2` | timeout >90s | timeout >60s (still down) |
| `qwen/qwen3.5-397b-a17b` | timeout >90s | timeout >60s (still down) |

`kimi-k2-thinking` is alive: returns 200 with reasoning_content (it's
a thinking model — emits the reasoning chain via `reasoning_content`
field; visible response in `content` once thinking concludes). The
short test exhausted `max_tokens` mid-thought (`finish_reason=length`)
because 10 tokens isn't enough for a reasoning model — set max_tokens
high (8K+) for real use. Description in the curated model entry now
records the probe success and the reasoning-mode caveat.

`deepseek-v3.2` and `qwen3.5-397b-a17b` description fields now record
both probe dates so future probes don't re-discover the same wall.

Not benchmarked: kimi-k2-thinking remains un-benchmarked because
running the 36-test reasoning-heavy sweep on the free tier carries
the same throttling risk that bit qwen3-coder-480b. Benchmark is a
separate decision when paid access lands or a user explicitly asks.

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
