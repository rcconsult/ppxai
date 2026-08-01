# ADR 0010 — Config shape review: three axes instead of per-code-path patchwork

**Date:** 2026-08-01
**Status:** Proposed
**Related:**
- [`0009-task-execution-profiles.md`](0009-task-execution-profiles.md) — §6 pins where 0009's new keys land pending this ADR; the Q5 scoped-tuple rule is generalized here
- [`0003-agent-platform-architecture.md`](0003-agent-platform-architecture.md) — the execution tiers this config surface must describe
- `ppxai/config/` — the accessor modules (`tools.py`, `providers.py`, `features.py`, `context.py`, `paths.py`, `prompts.py`, `loader.py`) the survey below was read from
- `/doctor` deprecation table — the existing shipping mechanism for config migrations

---

## Context

`ppxai-config.json` has grown organically: each new feature or execution path
added a key where the code that read it already lived, not where an operator
would look for it. A production-code survey (2026-08-01, `ppxai/` only) shows
the full surface is ~120 keys across 12 top-level blocks. Three growth patterns
produced the patchwork feel:

### Pattern 1 — per-code-path keys accreting on tool blocks

`tools.web_search` carries: `preferred` / `perplexity_model` / `gemini_model`
(tool behavior), `enabled` (tool availability), `task_default_allow` (egress
baseline **for the /task tier**), `oneshot_grounding` (native-search switch
**for the oneshot tier**), and — per ADR 0009 — `oneshot_enrichment`
(model-triggered search **for the oneshot tier**). Three of these answer
questions about *tiers*, not about the search tool. Every future tier would add
another key here; the block is a timeline of code paths, not a description of a
tool.

### Pattern 2 — the execution tier configured as a tool

`tools.agent.*` holds the entire execution-tier surface: `task_tier_enabled`,
`sandbox.*` (enforcement, workdir, read_paths, specs_dir, skills_dir),
`default_subagent`, `zombie_threshold`, `spawn_consent`, `consent_ttl_s`,
`result_retention_s`, `checkpoint_backend`, and — per ADR 0009 — `profiles.*`
and `egress_ceiling`. "Agent" is not a tool an LLM calls; it is *where LLMs
run*. It sits under `tools.*` because the tier historically grew out of the
`spawn_subagent` tool. An operator configuring the security boundary of the
task tier is editing a sub-key of a sub-key of the tools block.

### Pattern 3 — override axes added ad hoc, per key

Some keys are overridable per provider (`providers.<id>.web_search.preferred`,
`providers.<id>.system_prompt`), some per model (`generation_params`,
`tool_calling`, `extra_body`, `reasoning_trigger` — model wins), some per both,
each wired independently at its own read site. ADR 0009 Problem 4 documented
the failure this breeds: two resolvers reading the "same" preference from
different scopes and disagreeing (the `preferred` egress divergence). There is
no stated rule for which keys are overridable, at which scopes, or how related
fields resolve together.

Also observed, lower stakes: root-level strays (`file_tree.*` from a v1.18.7
constant migration; `visualization.*` read from `config/tools.py`), and legacy
compat keys (`tools.shell.use_rtk` superseded by the wrapper framework).

## Decision (proposed)

Organize the config around **three axes**, matching the questions an operator
actually asks:

| Axis | Block | Question it answers |
|---|---|---|
| **WHO answers** | `providers.*` | Which LLMs, endpoints, keys, models, generation params |
| **WHAT capabilities** | `tools.*` | What each tool is and how it behaves — intrinsically, tier-independent |
| **WHERE work runs** | `execution.*` (new top level) | Tiers, their enablement, grants/profiles, sandbox, egress ceiling, consent, budgets |

### Target shape (sketch)

```jsonc
{
  "providers": { /* unchanged axis; overrides per the scoped-tuple rule */ },

  "tools": {
    "web_search": {
      "enabled": true,
      "preferred": "auto",        // + "strict" — ADR 0009 Q5 scoped tuple
      "perplexity_model": "sonar",
      "gemini_model": "gemini-2.5-flash",
      "egress": ["api.perplexity.ai", "..."]   // FINAL name for ADR 0009's
                                               // task_default_allow (0009 §6
                                               // marks that name provisional);
                                               // "hosts this tool needs" is
                                               // tool-intrinsic (0009 §2)
    },
    "get_weather": { "egress": ["api.open-meteo.com", "wttr.in"] },
    "shell":  { /* unchanged */ }
  },

  "execution": {
    "session":  { /* interactive tier defaults, future */ },
    "task": {
      "enabled": false,           // was tools.agent.task_tier_enabled
      "sandbox":  { /* was tools.agent.sandbox */ },
      "consent":  { /* spawn_consent, consent_ttl_s */ },
      "budgets":  { /* max_iterations, zombie_threshold, retention */ }
    },
    "oneshot": {
      "grounding": false,         // was tools.web_search.oneshot_grounding
      "enrichment": false         // ADR 0009 §4 — model-triggered search
    },
    "profiles": { /* ADR 0009 §1 — named grants, AgentSpec shape */ },
    "default_subagent": { "provider": "...", "model": "..." },
    "egress_ceiling": []          // ADR 0009 Q3
  }
}
```

### Placement rules (normative, so the patchwork cannot regrow)

1. **A key describing what a tool does** → `tools.<tool>.*`, tier-independent.
2. **A key describing whether/how a tier runs** → `execution.<tier>.*`. A tier
   switch never lands on a tool block again, whatever code reads it.
3. **A key composing grants across tiers** (profiles, ceiling, subagent
   defaults) → `execution.*` root.
4. **Overridable keys declare their scopes** (global / provider / model), and
   related fields resolve as **one scoped tuple** (ADR 0009 Q5): select the
   scope first, read all related fields from it. No independent per-field
   fallback, anywhere.
5. **New code paths get no new key location** — they get a key in the axis
   block that answers their question. If none fits, that is a design smell to
   raise, not a reason to append to whatever block is nearest.

## Migration

- **Dual-read for one minor release:** a shared dual-read helper reads the new
  location first, falls back to the legacy key, and emits a deprecation warning
  once per run. The `config/` accessor modules cover **most** read sites, but
  they are NOT the single choke point today — direct config reads exist outside
  them (verified: `engine/client.py` L288 `checkpoint_backend`,
  `engine/tools/builtin/web_premium.py` provider-override reads,
  `server/routes/agent_v1.py` `task_default_allow`/`enabled`,
  `server/routes/oneshot.py` `oneshot_grounding`, plus reads in
  `engine/completion.py`, `tui/`, and `commands/`). **Migration work item:
  enumerate every direct read (`grep` for `get_tool_config` and raw
  `config.get` chains outside `config/`) and route each moved key through the
  dual-read helper** — either by moving the read into an accessor or calling
  the helper at the site. A moved key with a missed direct read silently
  reverts to its default; the sweep is part of the migration, not cleanup
  after it.
- **`/doctor`** gains the old→new mapping in its existing deprecation table and
  can print the migrated JSON (or write it with `--fix`, consistent with
  current `/doctor` behavior).
- **Remove legacy reads** the following minor release.
- `tools.shell.use_rtk` / `use_rtk_prompt_hint` (already superseded by the
  wrapper framework) ride the same deprecation train.
- The v1 gateway (`/v1/*`) is config-consuming, not config-shaped: no wire
  change. ppxai-sre's k8s config templates need the rename in the same window —
  coordinate per the consumer-alignment practice of ADR 0009.

## Consequences

- Operators find tier policy in one block; the security surface
  (sandbox, ceiling, consent, egress) reads top-to-bottom in one place.
- ADR 0009's new keys land in their final home on day one (0009 §6) — no
  second migration.
- Cost: a dual-read window, a `/doctor` table entry per moved key, doc updates,
  and one release of "where did my key go" support noise. ~15 keys move; the
  provider axis (~40 keys) does not move at all.

## Sign-off (open)

1. Top-level name: `execution` vs `agent` vs `tiers`.
2. Does `tools.<tool>.egress` (renamed `task_default_allow`) stay tool-intrinsic,
   or belong under `execution` as a grant fragment? (0009 §2/§6 argue
   tool-intrinsic; the counterargument is that egress is only *consumed* by
   sealed tiers.)
3. Dual-read window: one minor release or two?
4. Does `session` (interactive tier) get an `execution.session` block now
   (empty, reserved) or only when it first needs a key?
