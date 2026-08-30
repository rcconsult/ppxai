# Plan: ADR 0012 implementation — protocol handlers, under the Sonar deadline

**Status: DRAFT — awaiting owner review. Nothing below is started.**
**Owner decision 2026-08-30:** capabilities + profiles **unify first** (new
W1); wire protocol then lives in the unified model-facts system, not in a
third parallel resolver. ADR 0012 §2 will be amended accordingly; the
unification itself gets its own short ADR (0013) drafted at W1 start and
signed off before code.
**Drives:** [ADR 0012](decisions/0012-wire-protocol-as-per-model-capability.md)
(Proposed) · closes debt **Item 61** (W2) and **Item 62** (W4) · absorbs
**I4b** from [plan-per-model-capabilities.md](plan-per-model-capabilities.md)
as W3.

## Why (the stated goal, not a side effect)

Per-provider/per-model capability resolution exists to **simplify the code
and raise reuse** — one protocol implementation serving every provider that
speaks it, routing as data, no per-provider special cases. Every iteration
below must move those metrics, measured at its gate:

- **Reuse:** the Responses handler ends up consumed by 2 providers (W3);
  `convert_messages` exists once per protocol, not once per provider (W4).
- **Simplification:** `openai_native.py` shrinks by the ~350 extracted
  lines; Gemini's incompatible `_convert_messages` override is deleted;
  `RESPONSES_API_PREFIXES` routing branch ×3 collapses to one resolver.
  Target: **net-negative LoC in `providers/*.py` outside the new `wire/`
  package**, reported per iteration.
- **No new carve-outs:** if an iteration wants a helper, wrapper, or
  special case to get green, that is a design smell — stop and raise the
  question instead (see Working rules).

## Working rules (owner directives, binding for every iteration)

1. **Iterative, like the I1–I4 arc:** each iteration ends **testable and
   runnable** — full suite green, app launches, live trial where the
   iteration touched a wire. No iteration leaves a half-moved seam.
2. **Call graphs per iteration:** run `graphify update .` and refresh
   **`docs/provider-wire-call-graphs.md`** (new, created in W1) showing the
   provider→handler→SDK call paths before/after that iteration — the
   [agent-platform-call-graphs.md](agent-platform-call-graphs.md)
   precedent, scoped to the wire layer.
3. **Structural changes only.** No patchwork, no spaghetti, no
   helper/surface carving to route around a design problem. When the clean
   shape is uncertain, **stop and put the question to the owner** with
   options — confirm/reject/adjust before code. Known questions are listed
   in "Open questions" below; new ones get raised the moment they appear.
4. **Nothing left failing or unfinished.** Anything that breaks outside
   this plan's edits gets root-caused and fixed (or explicitly
   owner-deferred with a debt entry), never dismissed as pre-existing —
   [CLAUDE.md "Verify, don't assume"] and the no-preexisting-dismissal
   rule apply. Zero new technical debt is the default; any debt taken is
   filed in the inventory the same day.
5. **Owner gates every iteration** ("go W1", …), per the standing rule.

## The clock

**Perplexity retires the Sonar chat-completions endpoint 2026-09-27**
(web-verified 2026-08-30: Perplexity forum "Sonar is moving to the Agent
API" + changelog; endpoint labelled *legacy*). It is the only wire
`PerplexityProvider` speaks. Forum precedent (Gemini 2.5-flash died
*early* for some users) → **target W3 complete by 2026-09-20.**

---

## W0 — file the deadline + probe the unknowns (~0.5d) — ✅ DONE 2026-08-30

Shipped: `07deb278` (filing) + `f440dbc3` (probe). Suite 5188 passed /
32 skipped / 0 failed. Probe gained `--api-path responses` (drift check on
the other wire) and `--survey-responses` (this battery); +12 offline tests.

**Measured live — five findings, four of which widen W3:**

| # | Question | **Measured answer** |
|---|---|---|
| (a) | bare vs namespaced IDs | ⚠️ **bare IDs DO NOT EXIST on the Responses wire.** `sonar`, `sonar-pro`, `sonar-reasoning-pro` → 400 `validation failed: model "..." is not supported`; only `perplexity/sonar` answers |
| (b) | native tools | ✅ `perplexity/sonar` + `anthropic/claude-sonnet-5` both accepted the array **and emitted a real `function_call`** |
| (c) | citations | ⚠️ **mechanism changes.** Search is an explicit **tool** here, not implicit: a plain request runs no search and returns no citations. With `tools=[{"type":"web_search"}]` they arrive as a **`search_results` output item** (15 results: id/snippet/date/url) while the text block's `annotations` stay **empty** |
| (d) | streaming | ✅ works via stock SDK (19–24 events) |
| (e) | `max_output_tokens` | required for `anthropic/*`, **not** for `perplexity/sonar` → **per-model table data**, as ADR 0012 assumed |
| (f) | base URL | `https://api.perplexity.ai/v1` serves Responses; the bare host 404s. `constants.py:271` holds the bare host today |

**Consequence for W3 (scope grew):** the 09-27 retirement is **not a
transport swap — it renames every user-facing Perplexity model ID**, so W3
must ship `/doctor` deprecation rows and update example config, install
scripts, vscode config and the four pricing tables. And the citation change
is **behavioural**, not a parse-site move: `web_premium.py` must request
the `web_search` tool explicitly and read `search_results` items.

**Also verified (auditor session, no action needed):** slash-bearing model
IDs are safe on provider `perplexity` — every production provider-key split
is `split("/")[0]` / `split("/", 1)` (`usage.py:243`, `session.py:1326`,
`tools.py:569`/`647`, `search_backends.py:148`).

## W1 — unify per-model fact resolution (NEW · ADR 0013 · ~2.5–3d)

Today two parallel systems answer overlapping per-model questions:
`ProviderCapabilities` (6 booleans; I2 ladder in `config/capabilities.py`;
2 `shipped_capabilities_for_model` overrides) and `ModelProfile` /
`ToolCallingProfile` (65 globs; own layered merge in `chat.py`; carries the
inert `api_path`). `native_tool_calling` (boolean) vs `tool_calling.mode`
(native/prompt_based/auto) is the visible redundancy — I3's Layer-2 bug
lived exactly in their seam (`chat.py:693` checks mode FIRST and
short-circuits capabilities).

- **ADR 0013 first** (short): the unified model-facts shape, which field
  wins the boolean-vs-mode pair, the config key surface (both systems have
  config overrides today — a merge is an ADR-0010-style clean break and
  needs the `/doctor` config-shape scan shipped WITH it), migration of the
  65 profiles. Owner signs off before code.
- One resolution ladder, one accessor family on `BaseProvider`, one guard.
  `wire_protocol` is a field of the unified facts from day one —
  **declared here, consumed in W2**.

**Fences:** every existing capability + profile test passes against the
unified accessor; the I2 real-config cross-pair test extended to profile
fields; mode-vs-capability seam test (the I3 regression). **Runnable
after:** behaviour byte-identical — this iteration only moves where facts
are resolved, not what they say. Call graphs + graphify refresh.

## W2 — extract the Responses handler + make routing consume the facts (ADR 0012 steps 1–2 · closes Item 61 · ~1.5d)

- Leaf package `ppxai/engine/providers/wire/`: `ProtocolHandler` +
  `WireContext` + `responses.py` (the six moved members).
- `openai_native` delegates, and routing reads
  `facts.wire_protocol` from W1's resolver — `RESPONSES_API_PREFIXES`
  becomes seed data; the 3 drift rows each decided from measurement.
- ADR 0006 `assert_wire_blocks_clean` added to the Responses converter
  (Item 62 fix (a)).
- **Probe de-duplication:** `scripts/probe-perplexity-capabilities.py`
  currently carries its own `to_responses_tool` copy of
  `_convert_tools_for_responses`. Once `wire/responses.py` exists the probe
  imports the real converter — otherwise it stops testing the shape the
  provider actually sends (raised by the auditor session, W0 review).
- Call graphs + graphify refresh.

**Fences:** request-kwargs spy byte-identical for unchanged models;
declared-vs-routed across all 65 profiles; operator `wire_protocol`
override provably changes the outgoing request. **Runnable after:** OpenAI
routes from data; only deliberately-fixed drift rows differ (named in the
commit message).

## W3 — Perplexity speaks Responses (I4b · **DEADLINE 09-20** · ~2d + live trial)

- Responses handler registered on `PerplexityProvider`; routing table
  from W0 data. Agent-fleet rows (`anthropic/*` +
  `requires_max_output_tokens` per W0 (e)). Configured set = owner's pick
  (suggestion: 3 Sonar + `anthropic/claude-sonnet-5`).
- **web_search backend migration**: `web_premium.py`'s own Perplexity
  client moves onto the same wire resolution as the provider (no second
  patched client — structural rule 3).
- Capability table + `task_authorizer` guard cover the Responses path;
  probe script guards both wires; I3 checklist for any newly configured
  model (example config, install scripts, vscode config, 4 pricing
  tables); `/doctor` rows if W0 (a) forces renames.
- Call graphs + graphify refresh — this is the graph that shows **one
  handler, two providers**.

**Fences:** live canary `anthropic/claude-sonnet-5` via
`/task --tools read_file`; Sonar smoke over the new wire; citations
intact per W0 (c); **gateway-smoke 7/7, `POST /v1/oneshot`
byte-identical** (ppxai-sre depends). **Runnable after:** Perplexity
fully usable on the surviving wire before 09-27.

## W4 — chat_completions + generate_content become handlers (ADR step 4 · closes Item 62 · ~1.5d)

`convert_messages` moves into each handler (protocol-owned return type);
Gemini's incompatible override **deleted**; `assert_wire_blocks_clean`
travels with every converter. Call graphs + graphify refresh — the
end-state graph: 4 providers, 3 handlers, zero bespoke wire paths.

**Fences:** validator asserted per handler on fixture messages; full
suite; client-parity harness untouched. **Simplification report:** final
LoC delta + deleted-override list.

## W5 — closeout (~0.5d)

ADR 0012 → Implemented; Items 61 + 62 archived; CHANGELOG +
release-notes-v1.19.1-DRAFT; Fleet Atlas dated successor.

---

## Configuration change inventory (every touchpoint, mapped to its iteration)

Audited 2026-08-30 by grep, not assumption. "User-side" = existing
`~/.ppxai/ppxai-config.json` files in the field, reached only via `/doctor`.

| Touchpoint | What changes | Iteration |
|---|---|---|
| `providers.<p>.capabilities.*` + `models.<m>.capabilities.*` vs the profile override keys | **merge into one key family** — clean break + `/doctor` config-shape scan shipped WITH it (Q0b) | W1 |
| new `wire_protocol` key in the unified facts config surface | operator per-model/per-provider protocol override becomes possible (and provably load-bearing) | W1 declare · W2 consume |
| `ppxai-config.example.json` perplexity block | Agent-fleet model additions; **`sonar`→`perplexity/sonar` ID renames are CONFIRMED required (W0 (a))**; **`base_url` gains the `/v1` suffix — measured, not conditional** (`constants.py:271` holds the bare host, which 404s on Responses) | W3 |
| **`tools.web_search.perplexity_model` default `"sonar"` + `web_premium.py:177` hardcoded client** | ⚠️ NOT previously in plan: the web_search tool runs its **own second Perplexity client** over chat-completions — dies 09-27 independently of the provider. Backend must route through the same wire resolution (root-cause rule: one shared path, not a second patched client) | **W3 scope added** |
| `CODING_MODEL = "sonar-pro"` (`config/__init__.py:154`) + `RECOMMENDED_DEFAULTS["perplexity"]` (`model_deprecations.py:374`) | follow any ID rename | W3 |
| install.sh · scripts/install.ps1 · vscode-extension/src/config.ts · 4 pricing tables | I3 checklist for every newly configured model | W3 |
| `/doctor` deprecation rows | user-side migration for renamed IDs + retired wire | W3 |
| egress allowlists (`search_backends.py`, `network_policy.py`) | host-level (`api.perplexity.ai`) — expected unchanged; **verified in W3, not assumed** | W3 fence |
| `execution.run.grounding` / oneshot enrichment docs | wording references the provider-native search path; behaviour covered by the byte-identical oneshot fence | W5 |

## Open questions for the owner (raise-before-code list)

| # | Question | Default if confirmed |
|---|---|---|
| Q0a | Boolean-vs-mode: does `tool_calling.mode` subsume `native_tool_calling`, with the boolean derived, or the reverse? (decided in ADR 0013) | mode wins; boolean becomes derived |
| Q0b | Config surface after unification: clean break on the two override key families (ADR-0010 style, with `/doctor` scan), or dual-read window? | clean break + scan, matching 0010 precedent |
| Q1 | `WireContext` shape: plain dataclass carrying client + hooks, or does the handler receive the provider behind a narrow Protocol? | dataclass — keeps handlers ignorant of providers |
| Q2 | Post-cutover, does `PerplexityProvider` keep a chat_completions path at all? **W0 (a) measured the opposite of this question's premise: the bare IDs are NOT served on Responses**, so the two wires serve *disjoint* model IDs until 09-27 | Responses-only after cutover (dead wire code is debt), with the ID rename carried by `/doctor` rows — but this is now an owner call, not a default |
| Q3 | W3 configured set | 3 Sonar + `anthropic/claude-sonnet-5` |
| Q4 | Drift rows in W2: if `gpt-5-pro`/`gpt-5.2-pro` prove chat-incapable, fix profile to `responses`; if `gpt-5.3-codex` serves chat fine, which side wins? | measurement wins; tie → official docs |
| Q5 | Does `PROMPT_BASED_MODEL_PREFIXES` fold in during W4 (finishing I5 early) or stay a separate iteration? | separate — W4 stays single-purpose |

## Risk register

| Risk | Detected by | Mitigation |
|---|---|---|
| ~~Bare Sonar IDs absent on Responses~~ → **CONFIRMED W0 (a)**: user-facing ID rename is now certain | measured | `/doctor` deprecation rows + config/install/vscode/pricing updates — **in W3 scope**, no longer a risk |
| ~~Citations differ~~ → **CONFIRMED W0 (c)**: search is an explicit tool; citations are `search_results` items, `annotations` empty | measured | `web_premium.py` requests `web_search` and reads `search_results`; handler-owned parsing, fenced with a fixture |
| Endpoint dies **early** (Gemini precedent) | — | W3 target 09-20 |
| Wrong drift-row resolution in W2 | per-row probe | decide from measurement, never copy |
| `/v1/oneshot` contract drift | W3 gateway-smoke | byte-identical fence is a hard gate |
| Fallout outside the diff | full suite each iteration | root-cause rule (Working rule 4) — no "pre-existing" dismissals |

## Sequencing summary

    W0 ✅ DONE → W1 (UNIFY facts + ADR 0013, ~3d)
      → W2 (extract handler + routing from facts, ~1.5d)
      → W3 (Perplexity Responses, ~2d, DONE BY 09-20)
      → W4 (remaining handlers) → W5 (closeout)

~7 working days to deadline safety (W0–W3) against ~14 available before
09-20 — buffer holds. Owner gate + green suite + call-graph refresh after
every iteration.
