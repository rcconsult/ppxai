# ADR 0010 — Config shape review: three axes instead of per-code-path patchwork

**Date:** 2026-08-01
**Accepted:** 2026-08-01 — all four sign-off questions settled (see §"Sign-off").
**Status:** **Implemented** (v1.19.1) — with one deviation from the migration
plan below: the owner chose a **CLEAN BREAK over the dual-read window**
("we use git and versioning, so we go for the new config, we document
config breaking change"). No dual-read helper was built; the legacy
`tools.agent.*` tier keys are gone, not deprecated. See §"Implementation
note (v1.19.1)".
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
**for the oneshot tier**) — and ADR 0009's enrichment switch would have been
next (it instead lands directly at `execution.oneshot.enrichment`, per this
ADR and 0009 §6). Three of these answer
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

## Decision

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
    "session": {
      // RESERVED (sign-off Q4) — present so the interactive tier's shape is
      // reviewable early. Candidate keys, NON-NORMATIVE, each lands only via
      // its own reviewed change:
      //   "consent":   { /* default tool-consent posture; today spread over
      //                    tools.shell.require_consent, tools.container.
      //                    require_consent, per-tool flags */ }
      //   "loop":      { /* interactive tool-loop caps; today under
      //                    tools.agent.max_iterations + providers.<id>.
      //                    tool_calling.max_tool_iterations */ }
      //   "bootstrap": { /* context bootstrap; today top-level bootstrap.* */ }
    },
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
- **The config-shape migration itself changes no wire contract** — `/v1/*` is
  config-consuming, not config-shaped, so renaming keys alters no request or
  response. (Wire changes decided elsewhere are unaffected by this statement:
  ADR 0009 §4 adds the optional `grounding` response field on its own
  authority.) ppxai-sre's k8s config templates were flagged here as needing the
  rename in the same window. **Verified not applicable (2026-08-15):** a
  grep of that repo for all six moved keys plus `visualization.` returns
  zero hits, and its only manifests
  (`agents/outlook-monitor/k8s/{deployment,cronjob,service}.yaml`) carry no
  ppxai config keys at all. The consumer reaches ppxai through the Python
  API and `/v1/*`, not through a ppxai ConfigMap, so the silent-ignore
  hazard never reached it. Kept as a dated correction rather than deleted:
  the *practice* of checking consumers is right, the specific action item
  was a false alarm.

## Consequences

- Operators find tier policy in one block; the security surface
  (sandbox, ceiling, consent, egress) reads top-to-bottom in one place.
- ADR 0009's new keys land in their final home on day one (0009 §6) — no
  second migration.
- Cost: a dual-read window, a `/doctor` table entry per moved key, doc updates,
  and one release of "where did my key go" support noise. ~15 keys move; the
  provider axis (~40 keys) does not move at all.

## Implementation note (v1.19.1)

Built on `bugfix/v1.19.1`. **The Migration section above describes a dual-read
window that was NOT built** — the owner elected a clean break instead, on the
grounding that the project is versioned and the change is documented. Keep
that in mind when reading this ADR as history: §"Migration" records the plan,
this section records what shipped.

**What moved** (no dual-read; the old locations are ignored, not deprecated):

| Legacy (gone) | New |
|---|---|
| `tools.agent.task_tier_enabled` | `execution.task.enabled` |
| `tools.agent.sandbox.*` | `execution.task.sandbox.*` |
| `tools.agent.spawn_consent` | `execution.task.consent.spawn_consent` |
| `tools.agent.consent_ttl_s` | `execution.task.consent.consent_ttl_s` |
| `tools.agent.result_retention_s` | `execution.task.budgets.result_retention_s` |
| `tools.agent.default_subagent` | `execution.default_subagent` |

`tools.agent.*` keeps only the tool-intrinsic loop knobs (`max_iterations`,
`max_tool_iterations`, `max_same_tool_calls`, `context_char_limit`,
`min_task_words`, `auto_retry_empty`, `zombie_threshold`) — placement rule 1.

**Consequences of the clean break, versus the planned dual-read:**

- A stale `tools.agent.*` key is **silently ignored** and its setting reverts
  to the default. This is the one real cost of dropping dual-read, and it is
  why `/doctor` gained a `Config shape (ADR 0010)` section that scans the
  config **file** (not the accessors — they no longer look at the old paths at
  all, so a stale key is invisible to them by construction) and prints the
  old→new mapping for anything still there.
- The `GET /agent/config` response shape changed with it (it returns
  `get_agent_config()` verbatim). Not a `/v1/*` surface, so the gateway
  stability contract is untouched; the only consumer is the bundled VSCode
  extension, versioned together with the server.
- ~~ppxai-sre's k8s config templates need the rename in the same window~~
  — **verified not applicable 2026-08-15** (zero occurrences of any moved
  key in that repo; its manifests carry no ppxai config). Any *other*
  deployment that pins these keys in a ConfigMap still has no grace
  period.

**Also cleaned up under "no dead code, no misaligned bits":**

- Root-level `visualization.*` — deleted. Its accessor
  `get_visualization_config()` had **zero** production callers; the block was
  documenting a knob nothing read. Removed from the loader whitelist, the
  accessor surface, and `ppxai-config.example.json`.
- `ApiClient.getAgentConfig()` in `web/shared/api-client.js` — deleted; the
  web UI never called it.
- Duplicated literal defaults replaced with the canonical constants at four
  sites (`commands/agent.py`, `engine/chat.py`, `server/routes/chat.py`).
  They matched their constants at the time, so no behavior changed — but a
  copied default silently diverges the day the constant moves.

**Regression guards** (`tests/test_docs_consistency.py`,
`TestAdr0010MigrationStaysComplete`): the tier keys must not resurface on
`get_agent_config()`, and no active doc may instruct an operator to set a
legacy path (annotated "was `tools.agent.X`" provenance mentions are allowed
when the new path appears too). Both were mutation-tested.

## Sign-off

### Settled (2026-08-01)

1. **Top-level name: `execution`.** `agent` would repeat the current confusion
   (the block is not a tool, and "agent" already names the spawned LLM);
   `tiers` doesn't cover `profiles` / `egress_ceiling` /
   `default_subagent`, which span tiers.
2. **`tools.<tool>.egress` stays tool-intrinsic.** The hosts a tool needs are a
   property of the tool wherever it runs (0009 §2); which tiers *enforce* the
   list is the tier's business. Moving it under `execution` would recreate
   growth pattern 1 in reverse — tool facts scattered into tier blocks.
3. **Dual-read window: one minor release.** The direct-read sweep is part of
   the migration itself and `/doctor --fix` rewrites configs; a second release
   of dual-read is a second release with both names live in docs and support.
4. **`execution.session` is reserved NOW**, so the interactive tier's place in
   the shape is reviewable early, before a key needs it in a hurry. The block
   ships empty-but-present in the target sketch with **non-normative candidate
   keys as comments** (see sketch) — candidates, not commitments; each lands
   only through its own change with its own review, and reshaping the block
   before first use costs nothing.
