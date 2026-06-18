# Model Selection Guide — Planner / Executor Strategy

**Created:** 2026-04-26
**Status:** Reference. Update when benchmark numbers shift materially.
**Audience:** ppxai users picking models per session, and contributors
designing the multi-model routing implementation.

This guide answers a single question: **which OpenAI model should I use for
which phase of work?** It's grounded in the [36-test benchmark
suite](../benchmarks/llm-eval/) and the cost structure of the OpenAI API
as of 2026-04-26.

For broader model taxonomy across providers (Tier S/A/B/C/D, parser quirks,
behavior archetypes), see [model-behavior-analysis.md](model-behavior-analysis.md).
For deferred multi-model routing automation, see [TODO-routing.md](TODO-routing.md).

## TL;DR

| Phase | Model | Cost (in / out per MTok) | Why |
|---|---|---|---|
| **Architecture / planning** | **`gpt-5.5`** (raw, minimal hints) | $5 / $30 | 1M context, deepest reasoning of the GPT-5.x family, 91.7% raw on the suite |
| **Hardest cross-cutting decisions** | `gpt-5.5-pro` | $30 / $180 | Premium ceiling for once-a-quarter ADRs |
| **Implementation / coding** | **`gpt-5.4-mini`** | $0.75 / $4.50 | Champion at 97.5% with hints, 6.7× cheaper than gpt-5.5 |
| Cheap quick tasks | `gpt-5.4-nano` (untested) | $0.20 / $1.25 | Worth benchmarking before promoting |
| Air-gapped / in-cluster | **`Qwen3.6-27B-FP8-agent`** | local ($0) | **93.6% no-hints (33/36)** — best self-hosted on the suite, agent-tuned native tool calling, 128K ctx. Prev pick `Qwen3-Coder-Next-NVFP4` (90% on DGX Spark) |
| **Avoid** | `gpt-5.3-codex` | $1.75 / $14 | Dominated by both gpt-5.4-mini and gpt-5.5; structurally cautious about tool use |

## The split

Coding work has two distinct phases that benefit from different model
characteristics:

### Phase 1 — Architecture / planning

You're designing a refactor, drafting an ADR, mapping a multi-file change,
deciding how a new feature plugs into existing structure. The work is
infrequent (a few calls per week) but each call is high-leverage — a bad
plan compounds across many implementation steps later.

**Criteria:**
- Deep multi-step reasoning
- Long context (whole-codebase or whole-subsystem in one prompt)
- Coherent multi-section output
- Cost matters less because volume is low

**Pick: `gpt-5.5` (raw, with stripped hints)**

- 91.7% raw on the 36-test suite — best of the GPT-5.x family at flagship tier
- 1M context window holds entire ppxai source tree if needed
- First fully retrained base since GPT-4.5 — improved reasoning over 5.4
- $5 / $30 per MTok feels expensive but applies to a small number of calls

**Important caveat — strip the hints.** gpt-5.5 benchmarks WORSE with
prescriptive `MUST` / `NEVER` / `After 2 failures STOP` hints than without
them. The cloned-from-gpt-5.4 hint set caused regressions on
`claim_without_action` (fabricated audit) and `multi_tool_sequence`
(skipped info-passing). [AGENTS.md](../AGENTS.md) `gpt-5.5*` block has
been stripped to 3 behavioral anchors only:

```yaml
"gpt-5.5*":
  - "Use the tools API for function calls — do not output tool-call JSON in response text."
  - "For code modifications, use apply_patch with complete unified diffs (3+ context lines before/after each change)."
  - "Use information returned by earlier tool calls when chaining subsequent calls."
```

The `gpt-5*` fallback block in both `AGENTS.md` and `~/.ppxai/AGENTS.md`
also had `CRITICAL: STOP retrying after 2 failures` and `Avoid duplicate /
Chain DIFFERENT calls` removed in the same audit.

**Upgrade to `gpt-5.5-pro`** ($30 / $180) only when:
- The decision affects the next 6+ months of work (think: AppState codegen,
  multi-model routing, agent loop unification)
- The stakes justify a 6× cost premium over plain gpt-5.5
- Otherwise gpt-5.5 is enough — pro doesn't change the floor, just the ceiling

### Phase 2 — Implementation / execution

You have a locked plan. Now you're writing code, applying patches, running
tests, fixing the failures, repeating. Many small calls, mostly isolated
to a few files at a time.

**Criteria:**
- High tool-call accuracy (apply_patch with diffs is the dominant tool)
- Reliable across many small file edits
- Cost matters a lot — implementation = many calls
- Long context less important — most edits touch ≤5 files

**Pick: `gpt-5.4-mini`**

- 97.5% with hints / 90.2% without on the 36-test suite — current champion
- 400K context, plenty for "edit these 3 files" steps
- $0.75 / $4.50 per MTok — 6.7× cheaper than gpt-5.5 input/output
- Excels at apply_patch, multi-file edits, test verification — the actual
  work of implementation

The hint set in [AGENTS.md](../AGENTS.md) `gpt-5.4-mini*` is benchmark-
validated to add +7.3% over no-hints — the strongest hint contribution of
any model tested. Don't strip it without re-running benchmarks.

## Cost math — why the split pays off

A representative workflow: 1 planning call (10K input tokens / 5K output)
+ 20 implementation calls (3K input / 1K output each).

| Strategy | Planning cost | Implementation cost | **Total** |
|---|---:|---:|---:|
| Pure gpt-5.5 | $0.05 + $0.15 = $0.20 | 20 × ($0.015 + $0.03) = $0.90 | **$1.10** |
| Pure gpt-5.4-mini | $0.0075 + $0.0225 = $0.030 | 20 × ($0.00225 + $0.0045) = $0.135 | **$0.165** |
| **Planner + Executor split** | $0.05 + $0.15 = $0.20 (gpt-5.5) | $0.135 (gpt-5.4-mini) | **$0.335** |

The split costs **3.3× more than pure gpt-5.4-mini** but **3.3× less than
pure gpt-5.5**, while preserving the deep-reasoning benefit on the
architecture phase. For high-stakes refactor planning the premium is small
absolute money for materially better plans.

For low-stakes work (one-off bug fixes, small feature additions), skip the
planner and just use gpt-5.4-mini end-to-end.

## How to use today

ppxai's current architecture has no automatic intent-based routing. Switch
manually:

```bash
# Start in architecture mode
/model gpt-5.5

# ... draft the plan, get the strategy locked in ...

# Switch to implementation mode
/model gpt-5.4-mini

# ... grind through the actual work ...
```

Or set defaults in `~/.ppxai/ppxai-config.json`:

```json
"openai": {
  "default_model": "gpt-5.4-mini",
  "coding_model": "gpt-5.4-mini",
  ...
}
```

Then explicitly invoke gpt-5.5 for planning sessions via `/model gpt-5.5`.

The discipline of typing `/model` to switch is itself useful — it forces a
phase break between thinking and doing.

## Future automation — multi-model routing

The deferred work in [TODO-routing.md](TODO-routing.md) Phase 5 (originally
v1.18.2-targeted) would add intent-based routing so the engine
automatically picks gpt-5.5 for planning-shaped requests and gpt-5.4-mini
for execution-shaped requests within a single session. Until that lands,
the manual `/model` switch is the workaround.

## When to revisit this guide

Update this doc when any of the following change materially:

1. **OpenAI ships a new flagship** that scores ≥95% on the 36-test suite
   raw. gpt-5.5 raw is at 91.7%; if a successor crosses gpt-5.4-mini's
   97.5% hinted ceiling without needing hints, the split itself becomes
   moot — use the new model for both phases.
2. **gpt-5.5-pro gets benchmarked.** Currently untested ($15-20 per
   benchmark run was deemed cost-prohibitive). If pro substantially
   outperforms 5.5 on architecture-shaped tests, promote it as the
   planning default.
3. **gpt-5.4-nano gets benchmarked.** At $0.20/$1.25 it's 4× cheaper than
   gpt-5.4-mini; if it scores ≥85%, it becomes the executor for
   high-volume low-stakes implementation work.
4. **Multi-model routing lands.** The manual switch advice becomes
   historical — replace it with the automatic-routing config syntax.

## Don't do these

- **Don't use `gpt-5.3-codex`.** Despite OpenAI's "most capable agentic
  coding model to date" marketing, ppxai's measurement shows 75% with
  hints / 69.4% without — dominated by both gpt-5.4-mini and gpt-5.5. 5
  of 7 `agentic_tool_loops` tests fail in both modes ("No tool call
  made") because the Codex variant is structurally cautious about tool
  use. The gpt-5.4 mainline already absorbed gpt-5.3-codex's
  capabilities; the dedicated variant adds nothing.
- **Don't add prescriptive `MUST` / `NEVER` / `STOP after N failures`
  hints to gpt-5.5.** They actively hurt the score (-5.6 points
  measured). gpt-5.5 is a more compliant base model than gpt-5.4 and
  applies prescriptive hints too literally.
- **Don't promote `gpt-5.5` as the universal default.** It's 6.7× the
  price of gpt-5.4-mini for marginal gain on implementation tasks.
  gpt-5.4-mini stays the daily-driver default.

## Source data

Last benchmark run: **2026-04-26** (this commit). Methodology: 36 tests
across 9 categories, `--agents-md both` to measure WITH-vs-WITHOUT-hints
delta, 180s timeout, native tool calling, real OpenAI API tokens.

Final scores after the surgical hint strip (two `gpt-5*` blocks pruned —
removed the prescriptive `CRITICAL: STOP retrying after 2 failures` and
`Avoid duplicate / Chain DIFFERENT calls` hints from both project AGENTS.md
and `~/.ppxai/AGENTS.md`):

| Model | WITH (final) | WITHOUT | Δ | Notes |
|---|---:|---:|---:|---|
| gpt-5.4-mini | 32/36 (90.2 scored) | 32/36 (90.2 scored) | 0.0 | Champion. Same passing count post-strip; one test traded (consecutive_tool_loop +, respects_tool_failure -). |
| **gpt-5.5** | **34/36 (92.1 scored)** | 33/36 (90.5 scored) | +1.6 | **+3 tests vs PRE-strip (was 31/36).** Surgical strip turned the regression into a +1.6 gain over no-hints baseline. |
| gpt-5.4 | _2026-04-12 ref: 84.2 / 84.2, 0.0_ | | | Older run, not re-tested |
| gpt-5.3-codex | 27/36 (72.5 scored) | 25/36 (65.9 scored) | +6.6 | Dominated; do not promote |

**The surgical hint strip thesis is validated.** Pre-strip, gpt-5.5 WITH
hints scored worse than WITHOUT (-5.6 score points) because two
prescriptive hints in the `gpt-5*` blocks (`STOP retrying after 2
failures` → fabrication; `Avoid duplicate / Chain DIFFERENT calls` →
skipped info-passing) caused 3 specific failures: `claim_without_action`,
`fix_verify`, `multi_tool_sequence`. Removing those two hints — keeping
the remaining behavioral guidance — recovered all 3 tests. gpt-5.5 now
scores higher WITH the curated hint set than WITHOUT any hints.

The same strip slightly affected gpt-5.4-mini (-3.0 score points, but 0
change in passing count) — the older verbose wording in `gpt-5*` was
contributing marginally over the more concise wording in the model-
specific block. The marginal regression is acceptable in exchange for
the much larger gpt-5.5 improvement.

The "scored" percentage uses partial-credit weighting (some tests are
worth more than 1 point); the passing count is the strict count.

## Related documents

- [model-behavior-analysis.md](model-behavior-analysis.md) — broader taxonomy across all providers
- [TODO-routing.md](TODO-routing.md) — multi-model routing automation work
- [AGENTS.md](../AGENTS.md) — project-level model hint blocks
- `~/.ppxai/AGENTS.md` — user-level model hint blocks (per-machine)
