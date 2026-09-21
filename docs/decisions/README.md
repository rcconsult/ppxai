# Architecture Decision Records (ADRs)

## Index

Status is summarised; the record itself is authoritative.

| # | Decision | Status |
|---|---|---|
| [0001](0001-keys-command-cross-client.md) | `/keys` cross-client behavior | ✅ Accepted — implemented |
| [0002](0002-command-context-three-pattern-split.md) | CommandContext three-pattern split | ✅ Accepted — implemented |
| [0003](0003-agent-platform-architecture.md) | Agent platform architecture | ✅ Accepted — Stage 2 shipped v1.19.0 (T9 container tier deferred) |
| [0004](0004-llm-gateway-features.md) | LLM gateway features | ✅ Accepted — implemented; §4 revised by ADR 0009 |
| [0005](0005-inspection-triplet.md) | Inspection Triplet for runtime observability | ✅ Accepted — implemented |
| [0006](0006-content-block-schema-separation.md) | Engine-internal vs wire content schema | ✅ Accepted — implemented |
| [0007](0007-completion-first-class-service.md) | One command registry: completion, help and the roster from a single declaration | 🟡 Proposed — steps 1–4 implemented, **only step 5 (parity fence) open**, no target release. **Revised 2026-09-20: goal restated (define once, derive everywhere); roster decision changed from AppState push to a `GET /commands` pull endpoint.** **2026-09-21: all six hand-written rosters are gone (steps 3a/3b/4), and step 4 removed the `engine → commands` import — `ppxai/engine/` imports nothing from `ppxai.commands`, fenced at zero by `TestEngineImportsNoCommands`, which replaces the retired `TestEngineCompletionStaysALeaf`** |
| [0008](0008-cross-tier-cost-and-resource-accounting.md) | Cross-tier cost + shared-resource accounting | ✅ Accepted 2026-09-06 — Option A implemented (`ppxai/usage_events.py`, taps in `engine/task_runner.py` + `engine/session.py`, rollup in `/cost`). **Debt Item 49 closed.** |
| [0009](0009-task-execution-profiles.md) | Task execution profiles + web_search enrichment | ✅ Accepted — all four steps implemented v1.19.1 |
| [0010](0010-config-shape-review.md) | Config shape: three axes | ✅ Implemented v1.19.1 — **clean break**, one deviation from the planned migration |
| [0011](0011-command-taxonomy-streamline.md) | Command taxonomy (`/auto` · `/run` · `/task`) | ✅ Accepted — implemented v1.19.1 |
| [0012](0012-wire-protocol-as-per-model-capability.md) | Per-model facts: one resolution system, wire protocol included | ✅ Implemented v1.19.1 — all four migration steps: unified `ModelFacts`/`ProviderCapabilities` split, `ProtocolHandler` + **four** wire handlers, `wire_protocol` routing, Perplexity on two wires. **Items 61 + 62 closed.** §6 (Anthropic `messages`) **shipped in v1.19.1**, opt-in and untested against the live API (Item 71). Resolution logic moved from `config/facts_config.py` to `engine/facts_config.py` on 2026-09-20 |

The only open record is **0007 step 2**; everything else is
implemented. Numbering is sequential — the next record is `0013`.

## About these records

Short, dated records of architecture decisions where the chosen
option is non-obvious or where we deliberately deferred a "proper"
solution. Each record names:

- **Context** — what problem are we solving, what constraints apply
- **Decision** — what we chose
- **Why this and not the alternatives** — the trade-off we accepted
- **Future / proper solution** — what we'd do if/when constraints change
- **Triggers to revisit** — concrete signals that should prompt a re-evaluation

Format: `NNNN-short-slug.md`, lowercase, kebab-case. Numbering is
strictly sequential — never re-number, never re-use.

Records are immutable **once Accepted**. An Accepted record captures
*what we knew when we decided*; to change an Accepted **decision**, write
a new record that supersedes the old one and add a "Superseded by:"
header to the old record. Don't delete or rewrite the history of an
Accepted decision.

**Permitted exception — factual-reality corrections.** Editing an
Accepted record in place is allowed *only* when it corrects the record to
match what actually shipped, without altering the decision: ticking a
deliverables checklist after the work merged, fixing a version label that
slipped during planning (e.g. "v1.19.x" → "v1.18.6"), correcting a path
or filename to the shape that was implemented, or removing a reference to
a stopgap that was ultimately not taken. Mark such an edit with a dated
note (e.g. `Boxes ticked 2026-06-15 to reflect shipped reality`) and
leave the Status unchanged. The test: *would the original deciders
recognize this as the same decision, just described accurately?* If yes,
edit in place; if it changes the decision, supersede instead.

While a record is **Status: Proposed** (or otherwise not yet Accepted)
it is a living draft and **may be revised in place** as the design is
refined — note the revision in the `Date:` line (e.g.
`2026-05-03 (revised 2026-06-15 — MVP design resolved)`). Immutability
binds at acceptance, not at first write: a Proposed ADR hasn't decided
anything yet, so in-place iteration is how a design converges before it
is locked. (This matches established practice — e.g. ADR 0003 and ADR
0006 were both revised in place while not-yet-final.)
