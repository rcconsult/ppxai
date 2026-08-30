# Per-model facts — resolution call graphs (ADR 0012)

**Purpose:** a reference map of how a per-model question gets answered,
traced from code. Use it for debugging (where does this answer come from?),
refactoring (what depends on this seam?), and onboarding (the shape of the
capability system at a glance).

Created in W1 of [`plan-adr-0012-implementation.md`](plan-adr-0012-implementation.md).
The design record is [ADR 0012](decisions/0012-wire-protocol-as-per-model-capability.md).

Traced by hand and cross-checked against `graphify update .` (refreshed
2026-08-30 in W1: 8,261 nodes / 39,569 edges). That check is what confirms
the collapse actually happened rather than merely being tested: the five
accessors this ADR deletes —`get_capabilities_for_model`,
`shipped_capabilities_for_model`, `get_effective_profile`,
`get_tool_calling_config`, `apply_capability_overrides` — resolve to **zero
nodes**, so no caller anywhere still reaches them.

---

## The shape in one picture

Two disjoint records, two accessors, and **nothing that merges them**:

```
                    ┌──────────────────────────────────────┐
                    │  What does this ENDPOINT do?         │
                    │  web_search · web_fetch · weather    │
                    │  citations · streaming               │
                    └──────────────────────────────────────┘
                                    │
                    BaseProvider.get_capabilities()          ← no model arg
                                    │
                    ┌───────────────┴───────────────┐
            default_capabilities            providers.<p>.facts
            (provider class)                (operator, per provider)


                    ┌──────────────────────────────────────┐
                    │  What does this MODEL do?            │
                    │  wire_protocol · tool_mode ·         │
                    │  fallbacks · limits · vision · tier  │
                    └──────────────────────────────────────┘
                                    │
                 BaseProvider.get_facts_for_model(model)
                                    │
                    ┌───────────────┴───────────────┐
            shipped_facts_for_model()      providers.<p>.models.<m>.facts
                    │                      (operator, per model)
        ┌───────────┴───────────┐
  <Provider>.shipped_model_facts   SHIPPED_MODEL_FACTS
  (provider's own rows)            (global seed, 65 globs)
```

**The disjointness is the design.** No field appears on both records, so a
provider block cannot state a model fact and a model block cannot state an
endpoint fact. There is no arbitration step in either graph because there
is nothing to arbitrate — which is what makes debt Item 43's regression
structurally impossible rather than merely tested against.

---

## Graph 1 — the send path (`chat_with_tools`)

The path that decides whether a tools array reaches the wire.

```
ppxai/engine/chat.py::chat_with_tools()
  │
  ├─ facts = ctx.provider.get_facts_for_model(ctx.model)        [chat.py:600]
  │    │
  │    └─ BaseProvider.get_facts_for_model()      [providers/base.py]
  │         ├─ self.shipped_facts_for_model(model)
  │         │    └─ model_facts.shipped_facts_for_model(model, self.shipped_model_facts)
  │         │         ├─ match_table(provider table)   ← exact ids, then globs
  │         │         └─ match_table(SHIPPED_MODEL_FACTS)
  │         │              └─ UNMEASURED  (tool_mode="prompt_based")
  │         └─ facts_config.resolve_model_facts(shipped, provider, model)
  │              └─ apply_overrides(shipped, model_fact_overrides(...))
  │                   └─ reads providers.<p>.models.<m>.facts FROM THE FILE
  │
  ├─ use_native_tools = facts.tool_mode != "prompt_based"       [chat.py:637]
  │
  └─ facts.fallback_on_empty / .fallback_on_failure /
     .strip_json_from_text / .parallel_tool_calls / .max_tool_iterations
```

**What this replaced.** Two systems asked in a fixed order: `get_profile()`
for `tool_calling.mode`, then `ProviderCapabilities.native_tool_calling` as
a gate. `mode == "prompt_based"` short-circuited *before* the capability was
read — debt Item 43's Layer-2 bug — so a capability resolving native never
reached the wire. `get_effective_profile` (deleted) merged a third
vocabulary on top, from AGENTS.md.

## Graph 2 — the provider send paths

Each provider gates its tools array on the same hook. The fence for this is
`tests/test_per_model_capabilities.py` (source scan, so a NEW provider or a
NEW send path is covered the day it is written).

```
openai_native._chat_completions_api()  ┐
openai_native._chat_responses_api()    ├─ self.get_facts_for_model(model)
openai_compat.chat()                   │    .tool_mode != "prompt_based"
gemini._build_config(model=...)        ┘
```

`gemini._build_config` takes `model` for exactly this reason; reading
`self.capabilities` made the per-model answer unreachable (plan I1).

## Graph 3 — resolution without a provider instance

Some callers need an answer before any provider exists — there is no API key
at admission time, and `/doctor` has no session at all. They share **one**
set of entry points, and the sharing is the point: the guard that refuses a
run and the message that suggests an alternative read the same resolution,
so the suggestion cannot recommend a model the guard would reject.

```
model_facts.provider_class_for(provider)          ← WHOSE class serves this?
  ├─ providers.get_provider_class(provider)
  └─ fallback: OpenAICompatibleProvider
       (get_provider_class() returns None for every openai_compat-TYPE
        provider — openrouter, nvidia, a vLLM box, an Ollama host — because
        those are configured by NAME, not registered. provider_ops falls
        back the same way, so a caller that stops at None disagrees with
        the deployment about what a provider is.)

model_facts.facts_without_an_instance(provider, model)   → ModelFacts
  ├─ provider_class_for(provider)
  ├─ shipped_facts_for_model(model, cls.shipped_model_facts,
  │                          cls.unmeasured_facts)
  └─ facts_config.resolve_model_facts(...)

model_facts.capabilities_without_an_instance(provider)   → ProviderCapabilities
  ├─ provider_class_for(provider).default_capabilities
  └─ facts_config.apply_provider_overrides(...)

  callers:
    task_authorizer._reject_tool_incapable_model()   ← the admission guard
    task_authorizer._tool_capable_models_hint()      ← its error message
    config/execution.py::get_effective_oneshot_path()  ← both records
    config/facts_config.py::complete_record_for()    ← /doctor's scaffold
```

Extracted in W1 because the same four-line sequence had been written out at
each site, and *that repetition is the bug*: four copies of one ladder is how
a fifth caller gets a rung wrong.

### Two questions that look alike and are not

```
  "Should we attach a native tools array?"   facts.tool_mode != "prompt_based"
                                             → the SEND path (Graphs 1, 2)

  "Can this model drive a tool loop at all?" can_drive_a_tool_loop(facts)
                                             → the oneshot enrichment gate
```

Every `ToolMode` value answers **yes** to the second: prompt-based tool
calling is still tool calling — `chat.py` parses the JSON out of the
response text, which is what `prompt_based` MEANS. Pre-ADR the gate asked
`mode != "none"`, and `"none"` is the only value that ever meant incapable;
it has no successor in `ToolMode`. Asking the send-path question at the gate
dropped every prompt-based model to closed-book (latent — both enrichment
switches default off).

### The provider-owned floor

`shipped_facts_for_model` takes a third argument, and it is not a default in
the usual sense:

```
  match provider table   (exact ids, then globs)
    └─ match SHIPPED_MODEL_FACTS
         └─ cls.unmeasured_facts  ?? UNMEASURED
```

The global `UNMEASURED` says `wire_protocol="chat_completions"` — safe for
every provider that speaks it, and simply WRONG for Gemini, which has no
such wire. A provider therefore supplies a **complete** alternative record
(`BaseProvider.unmeasured_facts`), chosen whole. Nothing is merged
field-by-field, so ADR 0012's "nothing to arbitrate" still holds. `tool_mode`
stays conservative in that record: a protocol is a fact about the endpoint
and is knowable without measuring; tool support is not.

## Graph 4 — `/doctor` and the config-shape scans

All four scans read the config **FILE**, never the accessors. Under a clean
break the accessors cannot see a legacy key by construction, so only a file
scan can tell an operator their setting stopped applying.

```
commands/doctor.py::_format_facts_section()
  ├─ facts_config.migration_plan()              → legacy keys + where they go
  │    └─ legacy_blocks_in_config()             (the file)
  ├─ facts_config.misplaced_fields_in_config()  → model fact in a provider block
  ├─ facts_config.wrong_typed_fields_in_config()→ values no coercion rescues
  └─ facts_config.incomplete_blocks_in_config() → Q0d: records must be complete

commands/doctor.py  →  facts_config.complete_record_for(provider, model)
                          └─ facts_without_an_instance()   [Graph 3]
```

`migration_plan()` **pushes provider-level model facts DOWN**: a legacy
`providers.<p>.capabilities.native_tool_calling` maps to
`providers.<p>.models.<m>.facts.tool_mode` for every configured model, not
to a provider-level `facts.tool_mode`. The provider-level target would be
ignored by the resolver and then flagged by the misplaced scan — advice that
leaves the operator demoted and warned. Fenced by a property test:
*every target the plan emits must be a location the misplaced scan accepts*.

## Graph 5 — `/provider model info`

```
commands/provider.py::handle_model_info()
  ├─ shipped_facts_for_model(model_id, cls.shipped_model_facts)
  ├─ facts_config.model_fact_overrides(provider, model_id)
  ├─ apply_overrides(...)              → the effective record
  └─ is_unmeasured(...)                → "(unmeasured)" rather than a false tier
```

This display used to re-implement the merge a **third** time, with its own
layer order and field list — which is how `api_path` came to be shown here
while nothing routed on it (debt Item 61). It now reports what the send path
will actually do, and labels each field's source (`config` / `built-in` /
`unmeasured`).

---

## Where the answer comes from — precedence, in one table

| Rung | Source | Wins over |
|---|---|---|
| 1 | `providers.<p>.models.<m>.facts` | everything |
| 2 | `<Provider>.shipped_model_facts` | the global seed |
| 3 | `SHIPPED_MODEL_FACTS` (65 globs) | either floor |
| 4a | `<Provider>.unmeasured_facts`, when declared | the global floor |
| 4b | `UNMEASURED` (`tool_mode="prompt_based"`, `chat_completions`) | — |

The endpoint record has its own two rungs, and they never meet the four
above — that is the disjointness, restated as a table:

| Rung | Source |
|---|---|
| 1 | `providers.<p>.facts` |
| 2 | `<Provider>.default_capabilities` |

Within rungs 2 and 3, **exact ids beat globs** (two-pass `match_table`), so
correctness does not depend on where a row was pasted. Between rungs, a
provider row wins **whole** — rows are complete records, so there is no
field-level merge and nothing to arbitrate.

The provider dimension at rung 2 is load-bearing, not decoration:
`anthropic/claude-sonnet-5` is reached over `responses` on Perplexity and
`chat_completions` on OpenRouter, so one global row cannot state its
`wire_protocol` correctly for both. That is the seam W3's fleet rows land in.

---

## Not yet consumed

`wire_protocol` is **resolved but not yet routed on** — W2 makes
`openai_native`'s three `_is_responses_api_model()` branches read it, which
is what finally closes debt Item 61. Until then the field is data with one
reader (`/provider`), and this doc should be updated the same day that
changes.
