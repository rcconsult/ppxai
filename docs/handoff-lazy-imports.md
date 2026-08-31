# Lazy imports — sequenced cleanup plan (auditor → builder)

**Written 2026-08-31 by the auditor session (ppxai-28) for the builder
(ppxai-c7). Owner authorised: "we fix the imports issues one after
another as proposed, go".**

Measured against `3a1c4d9c`. **Re-derive before trusting any number
here** — the branch moves, and a stale baseline makes the step-1 fence
wrong in the direction that matters (too permissive).

---

## The finding

`ppxai/` contains **143 internal lazy imports** (a `from ppxai...` /
`from ..x` inside a function body). Classified by AST, with the
module-level dependency graph used to ask *would hoisting this create a
cycle?*:

| Category | Count | Disposition |
|---|---|---|
| **Hoistable — no cycle results** | **122** | step 2, mechanical |
| **Genuinely cycle-breaking** | **12** | step 3, structural |
| Self-import inside a package `__init__` | 9 | leave; see §Excluded |

Two further categories are **not** part of this work and must not be
touched:

- **28** optional-dependency guards — a `try: import yaml / except
  ImportError`. These are correct and deliberate.
- **31** stdlib/third-party imports inside functions (`subprocess` et
  al.). Deferring a heavy stdlib import is a legitimate startup-cost
  choice, not a cycle evasion.

**Verified empirically, not only statically:** hoisting
`config.execution` to module scope in `ppxai/commands/doctor.py`
imports cleanly with no cycle.

---

## Why this is in scope at all

[`docs/patterns/protocol-dependency-inversion.md`](patterns/protocol-dependency-inversion.md)
is marked **"CRITICAL — Required for all cross-module type
dependencies"** and states:

> 1. **NEVER use `TYPE_CHECKING`** — *it's a lazy import in disguise*
> 2. **NEVER use `Any` to dodge a circular import**

A function-level `from ..config import X` is the same evasion spelled
differently. The rule already exists; nothing enforces it.
[ADR 0007](decisions/0007-completion-first-class-service.md) line 104
already flags a location as "not where a lazy import could plausibly
live", so the concern is live in the repo's own docs.

---

## Step 1 — fence first (do this before any cleanup)

A test that fails on any **new** internal lazy import, with the current
set as an explicit baseline.

This is first because it is cheap and permanent while steps 2–3 are
large. It also means steps 2 and 3 shrink a number the fence already
watches, rather than racing an unbounded backlog.

**Requirements, each learned the hard way this session:**

- **Guard the vacuous pass FIRST.** An AST sweep that stops matching
  passes every check built on it. `test_the_sweep_finds_modules` before
  anything else — same shape as `test_the_parser_sees_every_row` and
  `test_the_sweep_finds_modules_to_check`, both of which you wrote.
- **Baseline as a data set, not a count.** `assert len(found) <= 143`
  passes while one import is fixed and a worse one is added. Pin
  `(module, target)` pairs so a swap is caught.
- **Resolve relative imports correctly.** My first pass did not, and
  produced phantom targets (`ppxai.commands.config.defaults`). For
  `__init__.py` the module IS its own package; for everything else the
  package is `name.rsplit('.',1)[0]`. Assert zero unresolved
  `ppxai.*` targets as part of the fence — that check is what caught
  my error.
- **Do not count the three exempt categories** (optional-dep guards,
  stdlib-in-function, package self-import) or the fence will fight
  correct code.

---

## Step 2 — hoist the 122

Mechanical, low risk. Move each to module scope, delete the inner
import.

Verify per batch, not per file:

1. `python -c "import <module>"` for each touched module — an actual
   import, not a static claim.
2. Full suite green.
3. Re-run the sweep: the hoistable count must fall by exactly the number
   moved, and the cycle-breaking count must **not** rise.

That third check is the one that matters. If hoisting turns a
"hoistable" import into a cycle, the graph was misread and the analysis
needs revisiting before continuing.

Batch by owning package (`commands/`, `engine/`, `server/`, `tui/`,
`config/`) so a regression bisects to a small diff.

---

## Step 3 — fix the 12 structurally

These are real. Hoisting them creates a cycle, so they need the
Protocol pattern (a `Protocol` in a leaf module, per the CRITICAL
pattern doc) or a genuine dependency-shape change.

Full list, measured at `3a1c4d9c`:

| Source | Line | Target | Note |
|---|---|---|---|
| `engine.model_facts` | 1287 | `engine.providers` | **layering inversion** |
| `engine.model_facts` | 1305 | `engine.providers` | ” |
| `engine.model_facts` | 1288 | `engine.providers.openai_compat` | ” |
| `engine.model_facts` | 1314 | `config.facts_config` | ” |
| `engine.model_facts` | 1322 | `config.facts_config` | ” |
| `server.routes.oneshot` | 345 | `server.routes.agent_v1` | route↔route |
| `server.routes.oneshot` | 595 | `server.routes.agent_v1` | ” |
| `server.routes.oneshot` | 619 | `server.routes.agent_v1` | ” |
| `tui.app` | 771 | `tui.session_restore_ops` | app↔ops |
| `tui.app` | 780 | `tui.session_restore_ops` | ” |
| `config.loader` | 183 | `config.tls` | intra-config |
| `version` | 37 | `ppxai` | package self-reference |

**`model_facts → engine.providers` is the interesting one.** The facts
table reaching back into providers is backwards: facts should be a leaf
that providers consume. This is the ADR 0012 area just refactored, so
the shape is fresh and the fix is likeliest to be clean. Do it first —
it is the one most likely to teach something about the other eleven.

`version → ppxai` may be irreducible (a module importing its own
package root). If so, say so and exempt it explicitly with a reason
rather than contorting the code.

---

## Excluded from all three steps

- The **9 package self-imports** (`engine.tools.builtin` importing from
  itself in `__init__.py`). That is how a package re-exports its own
  submodules; it is not an evasion.
- The **28** optional-dependency `try/except ImportError` guards.
- The **31** stdlib/third-party function-level imports.

---

## Ground rules

- **One step per commit, and stop between steps.** The owner said "one
  after another"; a single commit doing all three is unreviewable and
  is what §5 of the Item 65 plan got wrong by inviting a merged diff.
- Prove the fence catches a NEW lazy import (add one, watch it fail,
  remove it) — a baseline fence that cannot fail is this session's
  recurring defect.
- Re-derive every count in this file before quoting it.
