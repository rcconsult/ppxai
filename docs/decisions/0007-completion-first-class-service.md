# ADR 0007 — One command registry: completion, help and the roster from a single declaration

**Date:** 2026-06-14 (revised 2026-08-15; re-measured 2026-09-20 on
`bugfix/v1.19.3` — the 08-15 evidence had decayed, see §Re-measured;
**revised 2026-09-20 — goal restated by the owner and the roster decision
changed from AppState push to a pull endpoint, see §Goal and §Decision**;
**revised again 2026-09-20 — `/quit` (alias `/exit`) gated to
`{rich, textual}`, reversing the "universal" call in the same section
below: ending a GUI session is a UI button workflow, not a command**.
Originally titled "Completion as a first-class service; command roster via
AppState".)
**Status:** **Accepted 2026-09-21 — implemented** (owner sign-off; on
`bugfix/v1.19.3`, unreleased). All five steps are done: step 1 shipped v1.18.8;
steps 2 + 2.5, **step 3a (web fetches the roster; `commands.js`
deleted)**, **step 3a-sec (sensitive subcommands)**, **step 3b (VSCode
fetches it; `commands.ts` deleted)**, **step 4 (completion is DERIVED
from the spec; the `engine → commands` import is GONE)** and **step 5
(the parity fence — `tests/test_command_parity_fence.py`, 128 tests)**
all landed 2026-09-21 on `bugfix/v1.19.3`
(`CommandFactory.iter_completion_specs`, `commands/factory.py`).
`CommandSpec` is the only command declaration left in the tree, and the
fence is what keeps it that way. The status was held at Proposed until
the owner flipped it; the remaining open questions (the plan's §Open
owner decisions) are follow-ups to an accepted record, not conditions on
it. Extracting a `ppxai/completion/` package is now optional and
cosmetic (see §Future). The "target v1.19.x" in the 08-15 revision has now been passed by v1.19.0, v1.19.1 and v1.19.2 without step 2 landing — it was a hope, not a plan, and is restated below as an explicit deferral with triggers rather than a date.

**After acceptance (2026-09-21 follow-ups).** Three of the open owner
decisions were decided the same day the record was accepted: **(A)**
`/q` was registered as a declared alias of `/quit`
(`ppxai/commands/client_handled.py`), so `TEXTUAL_LEGACY_QUIT_NAMES`
and its baseline are gone from `ppxai/tui/app.py` and the fence.
**(B)** `/help <cmd>` now renders a "Subcommands" section
(`CommandFactory.get_command_help`), so the step-4 note above that the
move "changed no help output" is superseded. **(C)** four of the five
VSCode `LEGACY_INTERCEPTS` (`tools`, `context`, `ls`, `tree`) were
migrated to factory routing; `LEGACY_INTERCEPT_BASELINE` is down to one
row, `checkpoint`. **DECIDED 2026-09-21: option B** for
`/checkpoint clear` (an irreversible delete whose only confirmation
today is VSCode's modal) — build a confirmation that works in all four
clients, including both TUIs (neither consumes command `side_effects`
today), then migrate `checkpoint` off this table. Detail:
`docs/plan-adr-0007-completion-service.md` §"Step 5 follow-ups
(2026-09-21, owner decisions)". **(D)** Open owner decision 5 (the
AppState schema endpoint) also closed same day, later: it was built,
not just corrected — see the second correction in §"Which mirrors can
go, and which cannot" below (commit `1953c29c`).

> **Update (2026-09-21, commit `beffa197`, later the same day). DONE,
> not in progress.** `checkpoint` migrated too. `LEGACY_INTERCEPTS`
> is not "down to zero rows" — it and `LEGACY_HANDLERS`, the router's
> legacy branch, `handlers/commands.ts` and `handlers/types.ts` are all
> deleted from `vscode-extension/src/`. `/checkpoint clear` with no
> flag now returns `prompt_quick_pick` (Cancel first, the destructive
> row second) in all four clients, and both TUIs consume
> `CommandResult.side_effects` for the first time — see
> `ppxai/commands/agent.py::_checkpoint_clear`,
> `ppxai/rendering/rich_renderer.py::consume_prompt_side_effects`, and
> `ppxai/tui/widgets/dialog.py::QuickPickDialog`. The step-5 parity
> fence no longer models this as a shrinking baseline;
> `tests/test_command_parity_fence.py` asserts the mechanism's absence.

**Related:**
- `ppxai/engine/completion.py` — current home of `complete()`
- `ppxai/commands/factory.py` — `CommandFactory`, `CompletionCommandInfo`, `iter_completion_specs()`
- `docs/patterns/protocol-dependency-inversion.md` — the v1.17.0 leaf-Protocol idiom this builds on
- `docs/patterns/appstate.md` — observable state + `state_sync` push to all clients
- ADR 0002 — CommandContext three-pattern split (the per-client delivery shape completion also lives across)
- Debt item 29 — the layering finding that triggered this; v1.18.8 landed the seed (`iter_completion_specs()`)

## Goal

**A command is defined once, and everything else is derived.** Its metadata
— name, aliases, description, usage, category, subcommands, which clients
implement it — is declared in one place, the Python command registry, and
propagates from there to completion, `/help`, palettes and menus in every
client. Commands are built once; the infrastructure guarantees that any
client, app or service can rely on the roster without restating it.

This was always the point of this record. Earlier revisions let the *layer
inversion* (`engine → commands`) read as the decision and the roster as a
nice-to-have, which is backwards: the inversion is a symptom of completion
having no proper source to read from, and it disappears as a side effect of
fixing that.

### How far the system is from the goal (measured 2026-09-20)

A command's metadata lives in **five places**, none complete (**six**, in
fact — see the correction under the table: `vscode-extension/src/shared/
commands.ts` is an independent copy, not a shared file):

| # | Where | Carries |
|---|---|---|
| 1 | `CommandSpec` (`commands/factory.py`) | name, description, category, aliases, usage, hidden |
| 2 | `web/shared/commands.js` (376 lines, hand-written) | description, usage, category, **subcommands** — restated in JS, **aliases restated as standalone entries**. **DELETED by step 3a (2026-09-21)** |
| 3 | `web/app.js:199` inline fallback catalog | a second JS copy, used when `SharedCommands` fails to load. **DELETED by step 3a** |
| 4 | `engine/completion.py` `_*_SUBCOMMANDS` tables (six of them — **seven, in fact**) | **subcommands** — a second hand-written set, in Python. **DELETED by step 4 (2026-09-21)**: all seven moved onto `CommandSpec.subcommands` |
| 5 | `engine/completion.py` `_BUILTIN_SPECIAL_COMMANDS` | the client-handled commands + their `clients` gating — in Python, but **outside the registry** |

The rosters disagree. Nine canonical non-hidden Python commands are missing
from JS: `attach`, `autoroute`, `copy`, `debug-log`, `doctor`, `keys`,
`preview-log`, `reload`, `undo`.

> **Correction (2026-09-21).** The table above says "five places" and
> counts only the WEB JS roster. There were **six**:
> `vscode-extension/src/shared/commands.ts` is a SEPARATE hand-written
> roster (31 entries) with its own drift — it lists neither `/run`,
> `/task` nor `/token`, all three of which `chatPanel.ts` intercepts.
> `commands.js`'s own header claimed it was "the single source of truth"
> for both clients, which was never true. Step 3a deleted rows 2 and 3
> (web fetches `GET /commands?client=web` now) and **step 3b, the same
> day, deleted `commands.ts`** (VSCode fetches
> `GET /commands?client=vscode` via `src/commandRoster.ts`). The two
> shipped separately precisely because they never shared a file. Row 4,
> the `_*_SUBCOMMANDS` tables, **went the same day in step 4** — and
> there were **seven** of them, not six: `_RUN_SUBCOMMANDS` (the U3
> one-off family) post-dated the count. All six places are now gone;
> `CommandSpec` is the only declaration left.
>
> **Correction (2026-09-20, same day).** The first version of this section
> listed `cat`, `sh`, `term`, `token` as "in JS, missing from Python" and
> built an argument on it. That diff compared Python CANONICAL names against
> ALL JS names, so it was wrong for three of the four: `cat` is a registered
> alias of `/show`, and `sh` / `term` of `/terminal`. The true JS-only set is
> **`token` alone**. The real duplication for the other three is different
> and worth naming: an alias is a *field* on a Python spec and a hand-written
> *standalone entry* in JS ("Alias for /show").

**The client-handled commands are `/token`, `/quit`, `/exit`.** `/token`
manages the bearer the *client* attaches, so it cannot run server-side and
is gated to `{web, vscode}`; `/quit` and `/exit` end the client process
and are gated to `{rich, textual}` (owner decision, 2026-09-20 —
reverses an earlier "universal" call: ending a GUI session is a UI button
workflow, not a command — the web app has a header button for it and
VSCode already has Disconnect). They are declared in
`_BUILTIN_SPECIAL_COMMANDS` as loose dicts because the registry has no way
to express a command with no server handler — which is why they sit
outside it, and why web `/help` is stitched from two sources
(`command-dispatcher.js::_appendExperimentalHelp`).

And the v1.18.8 seed is too thin to be the source: `CompletionCommandInfo`
carries name / description / hidden / alias data only. It drops `usage` and
`category`, which `CommandSpec` already has, and has no subcommands — so
publishing it as-is could not replace `commands.js`.

Verify: `python -c "from ppxai.commands.factory import CommandFactory; ..."`
against `grep -E "^    '/[a-z-]+':" ppxai/web/shared/commands.js`; the diff
script is in [plan-adr-0007-completion-service.md](../plan-adr-0007-completion-service.md).

## Context

Autocomplete for all four clients (Rich, Textual, Web, VSCode) is served
by a single function, `engine.completion.complete()`. It **was** the only
`engine → commands` import in the entire engine package: it reached up
into the `commands` layer to read the command roster from
`CommandFactory`. **Step 4 (2026-09-21) removed it — the count is now
ZERO** (see the dated note in §Re-measured). The rest of this section is
the diagnosis that produced the decision, kept as written.

A v1.18.7 post-release review flagged this as a layer inversion. The
deeper observation (review gate, debt 29): **completion is not engine-owned
data at all.** It is a *capability* computed over two inputs that live in
two different layers —

- the **command space** (names / aliases / descriptions), owned by
  `commands/CommandFactory`, and
- **live context** (working_dir, current provider, tool list), owned by
  the engine / AppState.

Parking that capability inside `engine/` is what forced the upward import.
It belongs to neither layer exclusively. Three separate client glue layers
(`rich/main.py`, `tui/completer.py`, `server/routes/completion.py`) also
each re-scrape the same context off `engine_client` before calling
`complete()` — duplicated wiring that confirms completion wants to *own*
its context, not be handed it three different ways.

Two distinct concerns are tangled here:

1. **Behaviour** — "given a buffer + cursor + context, return candidates."
2. **Roster data** — "what commands exist right now," which must reach not
   only autocomplete but also command palettes, `/help`, and menus, across
   all clients, with no per-client code when a command is added.

The call graph shows the coupling sits entirely *below* the shared
`complete()` seam, so the seam is the right place to invert, and the roster
is the right thing to publish.

> **Correction (2026-08-15):** the original text said "no client references
> `CommandFactory`". That is no longer true — the two in-process TUIs
> dispatch through it directly (`rich/main.py:20`,
> `rich/event_handler.py:20`, `tui/app.py:61`). It does not change the
> decision: those are *dispatch* references, not roster reads, and the
> roster is still funnelled through the single `complete()` seam. It does
> mean the eventual `CompletionService` cannot assume the command layer is
> reachable only from completion.

### Re-measured status (2026-08-15, `bugfix/v1.19.1`)

What step 1 actually fixed, and what is left:

- ✅ **Private-registry access is gone.** `engine/completion.py` reads the
  public `iter_completion_specs()` snapshot and `CommandFactory.get()` for
  alias resolution. No `_registry` / `_aliases` poking remains.
- ⚠️ **The layer inversion itself is unchanged**: `from ..commands.factory
  import CommandFactory` at `ppxai/engine/completion.py:48`. It is the
  **only** `engine → commands` import in the entire engine package — the
  extraction stays a one-edge job.

  > **CLOSED 2026-09-21 (step 4), on `bugfix/v1.19.3`, unreleased.** That
  > import is deleted and the count is **zero**:
  > `grep -rnE "from \.\.commands|from ppxai\.commands|import ppxai\.commands" ppxai/engine/`
  > returns nothing, checked across the whole package including
  > function-level imports. No other `engine → commands` edge existed.
  > `complete()` now takes a required, keyword-only `roster=` and each
  > caller passes `CommandFactory.roster(<its client>)["commands"]`; the
  > `client` parameter is gone with the gate, which is structural now.
  > The "one-edge job" estimate held exactly — and it turned out to be one
  > keyword argument, not a package extraction, because steps 1–2 had
  > already turned the roster into plain data.
  >
  > Held at zero by
  > `tests/test_no_new_lazy_imports.py::TestEngineImportsNoCommands`,
  > which REPLACES `TestEngineCompletionStaysALeaf` (deleted, as its own
  > failure message instructed — with no upward import there is nothing
  > left to be a leaf about). Mutation-verified on the new shape: restoring
  > the module-scope import breaks NOTHING visible — 6,285 tests still
  > collect, `import ppxai.engine.completion` still succeeds standalone,
  > the completion suites stay green — so unlike the other two guards in
  > that file, the fence is the only thing that can see this rule.
- 🔎 **It does not block SDK embedding — measured on the real consumer
  surface.** The 2026-08-15 measurement listed eight symbols, one of which
  (`engine.model_profiles.get_profile`) **no longer exists** — Item 65
  deleted that module. Re-read off ppxai-sre at HEAD (2026-09-20), the
  surface is now eleven modules:
  `engine.client.EngineClient`, `engine.types.{Event, EventType}`,
  `engine.tools.base.FunctionTool`, `engine.tools.manager.ToolManager`,
  `engine.bootstrap.BootstrapContext`, `engine.session.SessionManager`,
  `engine.provider_ops` (+ `ModelSwitchInFlightError`),
  `engine.facts_resolver.facts_without_an_instance` (the replacement for the
  deleted profile accessor), `config.loader.PPXAI_HOME`,
  `config.providers.{get_provider_config, get_default_provider}`.
  Importing all of them loads **77** `ppxai.*` modules (was 64) and **zero**
  `ppxai.commands` modules; nothing under `ppxai.*completion` is imported.
  The inversion is latent, traversed only when a caller imports completion
  explicitly, which today only the three client glue layers do.

  **Measured as three composable spans (2026-08-15).** A `sys.meta_path`
  observer was installed *before* any ppxai import, recording every
  `ppxai.commands*` / `ppxai.*completion*` resolution with its stack, then
  real execution was driven — not bare imports. Each span is independently
  re-runnable:

  | Span | What was driven | 2026-08-15 | 2026-09-20 |
  |---|---|---|---|
  | Import time + full consumer surface | every ppxai symbol the consumer imports | **0 / 0** (64) | **0 / 0** (77) |
  | Client + tool-manager construction | `EngineClient()`, `ToolManager()` | **0 / 0** (64) | **0 / 0** (77) |
  | Consumer-called symbols | `SessionManager()`, `facts_without_an_instance()`, `get_provider_config()`, `get_default_provider()` | not run | **0 / 0** (77) |
  | Request-time loop + tool dispatch | `tests/test_tool_messages.py` in full — 41 tests, native branch, multi-tool batches, mid-batch error, interrupt, loop detection, session serialization | **0 / 0** (73) | **0 / 0** (90) |

  A note on the observer's filter, because the first re-run got it wrong:
  matching the bare substring `completion` produces 56 false hits from
  `openai.types.completion` and from ppxai's own **`engine.providers.wire.
  chat_completions`** — the ADR 0012 wire handler, an unrelated name that
  did not exist when this was first measured. The filter must be
  `ppxai.commands*` or `ppxai.*` ending in `completion`. With that filter
  every span reports zero hits and zero stack frames.

  The third span injects a scripted `MockProvider` directly, so it exercises
  the *loop* rather than provider construction — which is precisely what the
  second span covers, so the three compose. The observer recorded stack
  frames for attribution and never fired.

  **The resulting claim, stated exactly:** no `engine → commands` coupling
  at import time, package load, client construction, or request-time
  execution including tool dispatch. **The only unexercised code is the
  provider's own network round-trip** — HTTP and serialization under
  `engine/providers/`, structurally not a place the command layer can be
  reached from. Closing that last sliver would need live credentials and is
  not where a lazy import could plausibly live.

  (Baseline reproduced on this side: `tests/test_tool_messages.py` is 41
  tests, green in 1.27s.)

  Note the consumer's engine entry point is **`EngineClient`**, not
  `task_runner` — `build_task_runner`'s extraction (`eeb82076`) widened
  what an embedder *could* drive in-process, but ppxai-sre has not adopted
  it and reaches the engine through a single `engine.chat()` call today.
- 🔁 **New in the 2026-09-20 pass: the edge closes a *package*-level
  cycle, which the earlier measurements never stated.** Importing
  `ppxai.commands.factory` pulls **52 `ppxai.engine` modules**. So the
  direction of travel is `engine.completion → commands.factory →
  engine.*`: the `engine` package depends on the `commands` package, which
  depends back on `engine`.

  The **module** graph stays acyclic, and this is why nothing breaks:
  `commands.factory` does *not* pull `engine.completion` (verified), and no
  module inside `engine` imports `engine.completion` either — it is a leaf
  that only the three client glue layers reach. `import
  ppxai.engine.completion` therefore succeeds standalone, and the
  `tests/test_no_new_lazy_imports.py` sweep added in Item 73 passes it
  without an exemption row.

  That is a meaningful distinction, not a technicality: it means the
  extraction is still a one-edge job with no cycle to untangle, **and** it
  means the current arrangement is one import away from a genuine cycle.
  Any future `engine` module that imports `engine.completion` — an obvious
  thing to do, since the name suggests it is engine-owned — closes the loop
  and turns this from a smell into an import error. The leaf status is
  load-bearing and undefended; nothing in the test suite would stop that
  import being added.

- 📈 **Surface has grown since the ADR was written.** `/task` and `/run`
  are now factory-registered, so the roster completion depends on is
  broader; completion also gained client-specific gating (the `clients`
  set, `engine/completion.py:70-78`) and dynamic run-id suggestions. None
  of that is new coupling, but it raises the cost of the eventual move:
  `engine/completion.py` is **884 lines** now. The coupling itself has not
  spread — it is still exactly **two call sites**,
  `CommandFactory.iter_completion_specs()` at `engine/completion.py:353`
  and `CommandFactory.get()` at `:412`, reached by **three** callers of
  `complete()` (`rich/main.py:32`, `tui/completer.py:24`,
  `server/routes/completion.py:18`).

Nothing here changes the decision. It moves the *priority*: this is an
architectural cleanup with no current correctness defect, not a
release-blocker.

## Decision

Split the two concerns and give each a first-class home.

### Behaviour → a `CompletionService` component, injected at startup

> **SUPERSEDED BY MEASUREMENT, 2026-09-21 (step 4). Not built, and not
> needed.** This subsection is kept as the reasoning of the time; what
> actually closed the inversion was **data in, not a Protocol**.
>
> The design below has completion hold a `CommandRegistryProtocol`
> collaborator inside a `CompletionService` in a new top-level
> `ppxai/completion/` package, constructed at three composition roots.
> Steps 1–2 removed the reason for all three pieces:
> `CommandFactory.roster(client)` already returns PLAIN DATA — one entry
> per canonical command with `aliases`, `hidden` and `subcommands`,
> already filtered by `client_sees`. There is no collaborator left to
> invert: a Protocol here would describe "an object that can hand me a
> list of dicts", which is a list of dicts.
>
> So step 4 gave `complete()` a required keyword-only `roster=` argument
> and each of its three callers — all of which already sit ABOVE
> `commands` — reads the roster itself. No Protocol, no service class, no
> new package, no global mutable state, and no `roster=None` fallback
> that would re-create the edge behind a branch. The
> `CompletionContextProtocol` half is untouched by this: the three
> context scrapers still duplicate each other, and collapsing them stays
> the optional, independent cleanup §Explicitly not in the path calls it.

- New first-class package `ppxai/completion/` (sibling to `engine`,
  `commands`, `server`), signalling completion is **not** subordinate to
  the engine.
- `CompletionService` holds two injected collaborators, each expressed as
  a **Protocol defined in a leaf module** (so the service imports neither
  concrete layer):
  - `CommandRegistryProtocol` — `iter_completion_specs()`, `resolve(name)`.
    `CommandFactory` already satisfies it structurally; its
    `iter_completion_specs()` + `CompletionCommandInfo` (landed in v1.18.8)
    are the concrete seed.
  - `CompletionContextProtocol` — `working_dir`, `provider`,
    `tool_list()`. The engine satisfies it structurally. The service
    builds context itself, collapsing the three duplicated client scrapers
    into one.
- The existing `complete()` logic moves into the service unchanged.
- **Composition-root ownership, preloaded at application startup.** Each
  entry point (`rich/main.py`, the ppxaide app, the server `lifespan`)
  constructs the service — injecting `CommandFactory` + the engine — during
  bootstrap, so it is present from the first keystroke and fails fast if
  the registry is missing. Clients call `service.complete(buffer, cursor)`;
  the server route resolves the session's service.
- This mirrors the existing `ToolManager` precedent: a standalone component
  injected and consumed via `engine.tool_manager.list_tools()`.

### Roster data → one complete declaration, served by a pull endpoint

**Revised 2026-09-20 (owner's design).** The original decision published the
roster *through AppState*, pushed over `state_sync`. That is replaced:

- **`CommandSpec` becomes the complete declaration.** It absorbs what is
  scattered today: `subcommands` (from the six `_*_SUBCOMMANDS` tables and
  from `commands.js`), `clients` gating (from `completion.py`'s static
  list), and argument kinds (path / model id / run id), so per-command
  completion behaviour is data rather than lookup tables.
- **Client-handled commands are registered too, and bind to a NAMED
  client action.** `token`, `quit`, `exit` become specs with no server
  handler, present in the roster and carrying the `clients` gating that
  `_BUILTIN_SPECIAL_COMMANDS` holds informally today. Each declares
  `client_action: "<name>"` (e.g. `"token.manage"`) — a name from a fixed
  vocabulary held in Python — plus `client_action_clients`, the set of
  clients that dispatch to it; any other client uses the server `handler`.
  That pair is how HYBRID commands work too: `/task`, `/run` and `/auto`
  have a real Python handler for the in-process TUIs and a client action
  for web/VSCode, which drive `/v1/agent/*` and never call
  `POST /command/task`. **Python owns what exists, who gets it, its help, its
  subcommands and which action it binds to; each client BUNDLES the
  implementation of the named action.** No executable code crosses the
  wire. This mirrors the envelope's existing `SideEffectKind` idiom — the
  server sends data, the client implements a closed vocabulary, unknown
  names are ignored — applied in the other direction.

  `client_handled` means **dispatch happens in the client**, not "no server
  involvement": `/token mint` calls `POST /v1/tokens`. It also means
  **never forwarded**: `/token set <value>` carries a secret, and a client
  that POSTs it to `/command/token` and lets the server refuse has already
  leaked it into a command body and server logs. The flag is therefore part
  of the PUBLISHED snapshot, so the client knows before dispatching.

  (`cat`, `sh`, `term` need no migration: they are already registered
  aliases — `CommandSpec.aliases`, resolved by the factory. JS must simply stop restating them.) Without this the registry can never
  be complete and JS keeps a private list forever.
- **In-process clients (Rich, Textual) read the registry directly** — they
  hold `CommandFactory` already. Nothing new.
- **Server-mediated clients (web, VSCode) fetch it: `GET /commands`**
  returns the full snapshot. Fetched once at JS startup — the payload is a
  few KB (≈43 commands × ~6 fields), so lazy loading is not worth its
  complexity. The dispatch half of this surface already exists
  (`POST /command/{name}` + the envelope); the read half is what is missing.
- **`commands.js` shrinks to a loader, then to nothing.** Completion's
  subcommand tables and `/help` are *derived* from the spec.
  (**Done for BOTH JS clients, steps 3a and 3b, 2026-09-21** — and
  neither became a loader: the fetch+cache landed in a new
  `web/shared/command-roster.js` and `vscode-extension/src/
  commandRoster.ts`, and both catalogs were deleted outright. Each
  client additionally **fails closed** with no roster rather than
  forwarding what it cannot classify; see the plan's steps 3a/3b for why
  that replaces the old hardcoded-branch-order guarantee for
  `/token set <value>`. The VSCode modules import no `vscode`, so the
  behavioural tests compile and run the real TypeScript under Node.)
- **A parity fence** fails when any client renders a command the registry
  does not declare, or the registry declares one a client does not render.
  The rosters drifted apart silently; only a test stops that.

**One wrinkle: the roster is not static.** `/reload` re-imports user
commands from `~/.ppxai/commands/` at runtime, so a fetch-once client goes
stale. The signal rides existing channels — `/reload`'s envelope emits a
roster-changed event (the envelope already carries `events`), or `/state`
carries a single integer roster version — and the client refetches. The
*payload* stays on the endpoint; only the *signal* is pushed.

**Why pull and not AppState push.** AppState is machinery for state that
changes constantly; the roster changes almost never. Putting it in AppState
means a new field in `engine/app_state_schema.json`, its hand-written mirrors
in `web/shared/app-state.js` and `vscode-extension/src/appState.ts`, and the
cross-language sentinel tests that pin them — that was the *entire* cost that
made this record look too expensive to start for three releases. A plain
endpoint touches none of it.
> **Note (2026-09-21):** "hand-written mirrors" overstates what an AppState
> field costs, and did so even before either file was corrected — see the
> "CORRECTION" and "CORRECTION OF THE CORRECTION" blocks in §"Which mirrors
> can go, and which cannot" below. Neither `web/shared/app-state.js` nor (as
> of 2026-09-21) `vscode-extension/src/appState.ts`'s generated TYPE layer
> is hand-edited to add a field. The pull-vs-push decision itself is not
> reopened by this note — a plain endpoint is still simpler for data that
> almost never changes — only the cost estimate that helped motivate it.

**The layer inversion closes as a side effect.** Once completion consumes
spec data handed to it, `engine/completion.py` no longer needs
`from ..commands.factory import CommandFactory` — the symptom this record
was originally filed for disappears without being targeted.

## Why this and not the alternatives

- **Keep `complete()` in `engine/`, invert via module-global injection
  (`set_command_registry()`).** Removes the import but adds global mutable
  state and a mandatory bootstrap call at every entry point; a forgotten
  wiring path fails silently (empty completions). Rejected — the failure
  mode is worse than the disease.
- **Host the service *on* the engine (`engine.completion`).** Convenient
  (clients already hold `engine_client`), but naming a thing that *composes*
  the commands layer from inside the engine re-introduces the very
  upward smell we are removing. Composition-root ownership keeps the
  direction clean.
- **Service locator / DI container.** ppxai has no DI machinery today;
  adding one for a single capability is disproportionate. Revisit only if a
  second cross-layer capability wants the same treatment.
- **Put the roster *behaviour* in AppState.** AppState is observable
  *data*, not a service host.
- **Ship the client-side command CODE from the server** (JS/TS carried on
  the Python spec, served by the endpoint, verified by checksum, executed by
  the client). Considered 2026-09-20 at the owner's suggestion, as the
  fullest form of "define it once". **Rejected, for four reasons:**
  1. *It is fine for web and dangerous for VSCode.* The web client already
     loads all its JS from `ppxai-server`, so that is no new trust boundary.
     But the VSCode webview CSP is `default-src 'none'; script-src
     'nonce-…' ${webview.cspSource}` — no `unsafe-eval`, no remote origin —
     and `/token` is handled in the **extension host** (`chatPanel.ts`), a
     Node process with the user's full privileges. Executing server-supplied
     code there is remote code execution by design; with remote deployments
     supported, one compromised server reaches every connecting developer's
     machine.
  2. *A checksum does not address that threat.* It proves the bytes were not
     altered in transit, which TLS already does. A compromised server
     supplies both the code and its checksum. What would help is a
     **signature** under a key pinned into the client at build time — and
     code signed at release time can simply be **bundled** at release time.
  3. *The thing that varies at runtime is metadata, not behaviour.*
     `/reload` and config change the roster; how `/token` writes to
     `localStorage` changes only on a release.
  4. *It would serve one command.* `quit`/`exit` are trivial and
     `cat`/`sh`/`term` are aliases.

  Named `client_action` bindings get the same single-declaration property
  without code on the wire. **Revisit only for third-party or user-authored
  client-side commands** — plugins whose UI behaviour cannot be known at
  build time. That needs the signing design above plus a sandbox, and is its
  own record, not a rider on this one.
- **Put the roster *data* in AppState, pushed via `state_sync`.** This was
  this record's own decision until 2026-09-20. Rejected on cost and fit:
  the roster is near-static, AppState is for fast-changing state, and the
  DTO + two mirrors + sentinel tests made it the expensive piece that kept
  the whole record from starting. A pull endpoint plus a change *signal*
  achieves the same propagation for a fraction of the surface.

## Future / proper solution

This ADR *is* the proper solution; v1.18.8 shipped only the forward-compatible
seed. Incremental path:

1. **v1.18.8 (done):** `CommandFactory.iter_completion_specs()` +
   `CompletionCommandInfo`; `engine.completion` stops reading factory
   privates. No cascade — the `complete()` seam is unchanged. (Debt 29
   privates-reach closed.)
2. **Done, no target release** (all five steps landed 2026-09-21 on
   `bugfix/v1.19.3`, unreleased). Sequenced by the goal, not by the layer
   inversion (revised 2026-09-20 — the earlier (a)/(b)/(c) split treated
   the roster as the optional tail; it is the head):

   1. **Enrich `CommandSpec`** — `subcommands`, `clients`, argument kinds,
      and client-handled specs for `token` / `quit` / `exit`. Widen `CompletionCommandInfo` (or replace it) so the
      published view carries `usage`, `category` and subcommands.
   2. **`GET /commands`** serves the full snapshot; `/reload` signals
      roster-changed.
   3. **JS clients fetch at startup**; the hand-written catalogs are
      deleted outright rather than becoming loaders. **Split: 3a (web)
      and 3b (VSCode) both DONE 2026-09-21** — the two clients kept
      SEPARATE hand-written rosters, so they shipped separately.
   4. **Derive, don't restate** — ✅ **DONE 2026-09-21.** All seven
      `_*_SUBCOMMANDS` tables moved onto `CommandSpec.subcommands`;
      completion reads the roster the caller hands it;
      `engine/completion.py` imports nothing from `ppxai.commands`, so
      the layer inversion and the package cycle are closed;
      `TestEngineCompletionStaysALeaf` is deleted and replaced by
      `TestEngineImportsNoCommands` (the rule, at zero, whole package).
      `/help` needed no change — it has been registry-generated since
      step 1b, and neither `generate_help` nor `get_command_help`
      renders subcommands, so the move changed no help output.
      > **Update (2026-09-21).** This is no longer current: open owner
      > decision 2 was decided the same day — `get_command_help` now
      > renders a "Subcommands" section from `CommandSpec.subcommands`.
      > See §After acceptance below.
   5. **Parity fence** — ✅ **DONE 2026-09-21.**
      `tests/test_command_parity_fence.py` (128 tests) asserts five
      things, each read off the PYTHON declaration and compared against
      the real client source: (a) action coverage in BOTH directions per
      client — no missing implementations, no orphan ones, nothing
      outside the `CLIENT_ACTIONS` vocabulary; (b) no undeclared
      intercepts — zero per-name branches in either JS client, and
      `LEGACY_INTERCEPTS` as an explicit five-row SHRINKING baseline that
      fails when it grows AND when it shrinks without its baseline row
      going too (**update, 2026-09-21: the table emptied to zero rows
      and was then deleted outright — see §After acceptance; the fence
      now asserts its absence rather than tracking a shrinking
      baseline**); (c) no surviving hand-written roster — every deletion in
      the plan's completeness table fenced as absent, plus a GENERIC
      detector (a literal naming ≥ 6 distinct registered commands, N
      measured against the real tree) with one named, self-fencing
      exemption; (d) side-effect kind coverage DERIVED from
      `SideEffectKind.all_kinds()` rather than from a third hand-written
      list; (e) roster self-consistency for every id in `KNOWN_CLIENTS`.

      Step 5 also closed the SEVENTH roster, which was on the Python
      side and which step 4 found: `rich/ui.py::display_welcome()` — a
      live hand-written ~30-command list rendered at Rich startup and
      **18 commands out of date** — now derives from
      `CommandFactory.roster("rich")`, taking it as plain data because
      `rich/ui.py` genuinely cannot import `ppxai.commands` (that
      package's `__init__` imports this module back). A second,
      caller-less welcome roster (`ui_components.py::render_welcome`)
      was deleted, and both TUI quit intercepts now derive their names
      from the spec via the new
      `CommandFactory.names_for_client_action()`, leaving exactly one
      named legacy extra (`"q"`, Textual only) as a recorded owner
      decision rather than a hidden literal.

      Retargeting the side-effect fences onto Python immediately found a
      live gap: `test_web_shared_modules.py`'s hardcoded kind set was
      missing `prompt_text`, which web has always implemented. That is
      the whole argument for (d) in one line — a hand-written expected
      set stops covering things silently.

   Each step ships alone. Steps 1–2 are server-only and change no client.

   **The guard that stood meanwhile** (2026-09-20 → 2026-09-21):
   `tests/test_no_new_lazy_imports.py::TestEngineCompletionStaysALeaf`
   fenced `engine.completion`'s leaf status. Mutating an import in proved
   the package cycle empirically — a module-scope import of it from
   `engine/client.py` took the whole pytest run down at collection with
   `ImportError: cannot import name 'EngineClient' from partially
   initialized module 'ppxai.engine'`, via
   `completion -> commands.factory -> commands.handler -> engine`.
   **Retired by step 4** and replaced with the permanent rule,
   `TestEngineImportsNoCommands`: no module under `ppxai/engine/` imports
   `ppxai.commands`, module scope or function level, held at zero.

   Relocating `complete()` to a `ppxai/completion/` package (the original
   step-2 headline) is **optional now that step 4 has landed** — the
   upward import is gone, so where the module sits is cosmetic. Do not
   build the `CompletionService` DI class ahead of need: a service holding
   a context collaborator while callers still scrape context is worse than
   either endpoint. Step 4 confirmed the stronger version of that
   caution — with the roster already plain data, the registry
   collaborator had nothing left to abstract either.

   Plan: [plan-adr-0007-completion-service.md](../plan-adr-0007-completion-service.md).

## Which mirrors can go, and which cannot

Recorded 2026-09-20 (owner's question: "the mirrors go away and get
populated via a GET call, correct?"). The answer is *yes for data, no for
behaviour*, and the distinction is worth keeping because "mirror" names
three different things in this codebase:

| Mirror | What it is | Fate |
|---|---|---|
| `web/shared/commands.js`, the `web/app.js:199` fallback catalog, alias entries restated as standalone commands, `_appendExperimentalHelp()` | **Data** — names, descriptions, usage, subcommands | ✅ **Deleted** in step 3a (2026-09-21); populated from `GET /commands?client=web` via `web/shared/command-roster.js`. `vscode-extension/src/shared/commands.ts` was the same class of mirror and is ✅ **deleted** in step 3b (same day), populated from `GET /commands?client=vscode` via `vscode-extension/src/commandRoster.ts` |
| `web/shared/side-effects.js` and the VSCode equivalent | **Behaviour** — 300 lines of handler implementations (`open_editor`, `copy_to_clipboard`, `prompt_text`, …) that *perform* an effect in the client | **Stays.** Not servable: this is the same line drawn when shipping client code from the server was rejected, and the same split as `client_action` — Python owns the NAME, the client bundles the IMPLEMENTATION |
| `web/shared/app-state.js`, `vscode-extension/src/appState.ts` | ~~**Data** — hand-written mirrors of `engine/app_state_schema.json`~~ ~~**Behaviour.** Corrected 2026-09-21: neither file restates the schema. Both are the observable-store CLASS and DERIVE field names, defaults and the Python↔JS name mapping from the schema at construction~~ **Corrected again, 2026-09-21 (later the same day): true for the DATA path on both clients, but VSCode also had a TYPE path — `interface AppStateFields` — that WAS a hand-written restatement and HAD drifted (22 schema fields vs 20 typed). Now generated; see the second correction below. | **Stays** for the DATA/behaviour class on both clients; the VSCode TYPE layer is now build-time generated (2026-09-21) — see the correction below |

**The rule:** a mirror of DATA can be replaced by a GET; a mirror of
BEHAVIOUR cannot, and should instead be held in line by a parity fence that
reads the Python-owned vocabulary.

What *can* be served for the behaviour mirrors is the **vocabulary** — the
list of `SideEffectKind` names and of `CLIENT_ACTIONS` — so a client can
verify at startup that it implements every name the server may send, and
warn on a gap. That is a parity check, not a replacement; it belongs with
step 5's fence.

> **Done as a BUILD-TIME check, not a runtime one (step 5, 2026-09-21).**
> `tests/test_command_parity_fence.py` reads both Python-owned
> vocabularies and compares them against what each client source
> actually implements, in both directions. A runtime warning was not
> built and is not needed: the gap it would report is a shipping bug, and
> a test that fails in CI catches it before the shipping rather than
> after. The `client_action` half additionally fails CLOSED at runtime
> already — a client-dispatched command whose action is unimplemented is
> refused with a clear error and **never** forwarded (steps 3a/3b), so
> the unsafe direction was closed by construction. The `SideEffectKind`
> half cannot fail closed by design (kinds are an OPEN enum: unknown
> kinds are ignored on purpose), which is exactly why that one needs a
> test and gets one.

### Follow-up, out of scope here: the AppState schema endpoint has no consumer

> **Heading now stale (2026-09-21, later the same day): the endpoint HAS a
> consumer.** `vscode-extension/src/schemaGuard.ts` calls
> `GET /schema/app-state` on every (re)connect — see the "CORRECTION OF THE
> CORRECTION" block above. Kept unedited below for the record of how this
> section's reasoning evolved same-day.

> **CORRECTION (2026-09-21) — the conclusion below is wrong; the grep is
> right.** No JS client *fetches* `GET /schema/app-state`, but neither
> client maintains the schema by hand either. Both are already derived
> from `ppxai/engine/app_state_schema.json`, by two other routes that the
> endpoint's own module docstring (`server/routes/schema.py:8-16`)
> describes and that were not read when this section was written:
>
> - **Web — derived at SERVE time.** `server/routes/static.py:41-47`
>   injects `window.APP_STATE_SCHEMA` into `index.html` from the running
>   server's `engine.app_state.SCHEMA`; `web/shared/app-state.js:46`
>   refuses to construct without it. This is strictly better than a fetch:
>   same source, no round-trip, and no version skew is possible because
>   the page and the schema come from the same process.
> - **VSCode — derived at BUILD time.** `vscode-extension/scripts/
>   sync-schema.js` copies the Python file to
>   `resources/app-state-schema.json` on `precompile`/`prepackage`/
>   `prewatch`; `src/appState.ts::_loadSchema` reads it. The copy is
>   tracked, and `tests/test_app_state.py` pins it identical to the source
>   (verified identical 2026-09-21).
>
> So this is NOT "the command-roster problem one stage further along".
> The roster's mirrors were hand-written DATA; these two files are the
> store's BEHAVIOUR with the data already flowing in. The owner asked for
> this to be wired up on the strength of the paragraph below, and the
> finding was returned instead of built.
>
> **What a runtime fetch would and would not buy (VSCode only; web needs
> nothing).** The one real gap is build-time vs run-time: an extension
> built at version X talking to a server at version Y. A fetch at connect
> would teach the extension Y's field names and defaults — but a field is
> only useful to code that reads it BY NAME, and that code is compiled
> into X. A roster entry is rendered generically (completion, help,
> dispatch), which is why fetching it pays; an AppState field is not. The
> skew is already DETECTED: both stores warn on a pushed field the schema
> does not declare. And the bundled copy cannot be dropped, because the
> extension constructs `AppState` before it has started the server it
> would fetch from. Net: a second source of truth with a precedence rule,
> for no behaviour. **Recommendation: do not build it; the endpoint stays
> what its docstring says it is — a diagnostic surface.** The same error
> also overstated one argument in "Why pull and not AppState push" above
> (adding an AppState field does not mean editing hand-written mirrors;
> it means the schema file, the sync script's copy, and the sentinel
> tests). The pull decision does not rest on that argument alone and is
> not reopened.

> **CORRECTION OF THE CORRECTION (2026-09-21, later the same day).**
> The correction above is right about the DATA path and wrong about
> completeness: it never looked at the TYPE path, because the question
> it was answering ("does either file restate the schema?") was read as
> "does either file restate the schema's *data*?" `web/shared/app-state.js`
> has no type layer to drift — JS is untyped — so the correction's web
> half stands unmodified. VSCode's TYPE half was a second, separate
> restatement the correction missed: `interface AppStateFields` in
> `src/appState.ts` was hand-written, and by the time this second
> correction was written the schema declared **22** fields against the
> interface's **20** — `lastMessageRole` (v1.18.0) and
> `modelSupportsVision` (v1.18.6) were never added, so no VSCode code
> could read either field by name, while `ppxai/web/app.js` had been
> gating its attach badge on `modelSupportsVision` since v1.18.6. The
> file's own header compounded this: it claimed a "constructor assertion"
> checked the interface against the schema (there was none — only a
> `as AppStateFields` cast) and promised a generator "the v1.18.x schema
> generator will auto-generate `AppStateFields`" that was never built.
> No test compared the two, so none of this was caught.
>
> The first correction's "**Recommendation: do not build it**" therefore
> rested on a half-wrong premise — it was correct that the DATA path
> needed no runtime fetch, and wrong to conclude from that alone that
> there was "nothing to build." The owner overrode the recommendation
> and had both halves built the same day (commit `1953c29c`):
>
> - **Build-time (closes the TYPE gap).** `vscode-extension/scripts/
>   sync-schema.js` now also emits `src/appState.generated.ts`; the
>   hand-written interface is deleted. The schema stays language-neutral
>   (`array`/`object` stay wide types), so a `TYPE_REFINEMENTS` map in
>   the generator narrows the three container fields and refuses to
>   refine a field the schema does not declare or one whose type is not
>   a container. Tracked and byte-stable, pinned by
>   `tests/test_app_state_generated_types.py` (regenerates in memory,
>   fails on any difference).
> - **Run-time (the gap the first correction argued was real but not
>   worth closing).** `vscode-extension/src/schemaGuard.ts` fetches
>   `GET /schema/app-state` on every (re)connect and compares FIELDS
>   with the bundled schema — the endpoint's first consumer since
>   v1.17.4. Identical: silent. Extra server fields: adopted for the
>   connection, logged once. A compiled-against field missing or
>   retyped: one visible warning naming the fields and both versions.
>   404/fetch failure: logged once, nothing blocked. This is the
>   **opposite posture from the command roster's fail-closed gate**,
>   deliberately: `AppState` is constructed as a field initialiser
>   before any server exists — there is no roster-shaped "refuse to
>   dispatch" available, because there is nothing to dispatch — and a
>   server too old to serve the endpoint is still a perfectly usable
>   server, so blocking chat over an unverifiable diagnostic would be a
>   self-inflicted outage.
>
> **What the first correction got right and still holds.** Adopted
> fields are stored, never rendered — the argument that "a field is only
> useful to code that reads it BY NAME, and that code is compiled into
> the build" is exactly why `schemaGuard.ts` adopts silently instead of
> trying to make an unknown field do anything. **What it missed:** the
> other direction. A field this build WAS compiled against — vanishing
> from, or retyped on, the server — used to be invisible; that silence
> is exactly the failure mode the TYPE-layer drift itself had just
> demonstrated (two fields absent for months, caught only by an
> unrelated grep). Closing that is the guarantee the run-time half
> buys, and it is why the recommendation changed.
>
> **`version` is still not the signal.** The schema's `"version"` key
> has read `"1.0"` since the file was created (`86adf127`) and none of
> the five field-changing commits since bumped it (verified:
> `git log -p --follow ppxai/engine/app_state_schema.json | grep
> '"version"'` returns one hit, the original add). `schemaGuard.ts`
> compares FIELDS; `version` is reported in the message only as context
> for whoever has to fix a real mismatch, never as the verdict.

`GET /schema/app-state` **already exists** (`ppxai/server/routes/schema.py:32`)
and **neither JS client calls it** — `grep -rn "schema/app-state" ppxai/web/
vscode-extension/src/` returns nothing (2026-09-20). The server offers the
schema while both clients keep maintaining it by hand, pinned in lockstep by
cross-language sentinel tests. It is the command-roster problem exactly, one
stage further along: the endpoint is built and only the consuming half is
missing.

Deliberately NOT folded into this record's plan: it touches the sentinel
tests and the `state_sync` contract, and deserves its own scoping. It is
written down here because nothing else in the repo records that the endpoint
is unconsumed, and because whoever finishes step 3 will have just built the
fetch-at-startup machinery that this would reuse.

## Triggers to revisit

- A "ship the engine as a standalone library" goal (makes the residual
  `engine → commands` import a hard blocker, not a smell).
  **Partially fired 2026-08-15:** ppxai-sre consumes ppxai as an SDK
  dependency to implement its agents, and `build_task_runner` was extracted
  to `ppxai/engine/task_runner.py` (`eeb82076`) precisely to serve that
  model. It is *not* yet hard-blocking, because that consumer's import path
  never reaches `engine.completion` (measured above). It becomes hard the
  moment any of these is true:
  - `ppxai/engine/` is packaged as its own distribution, so an unused
    upward import is a real dependency rather than a dormant one;
  - an embedder needs the command roster — a palette, a menu, an
    `/help` equivalent — **without** running the client command layer;
  - the `commands` package acquires an import-time side effect (config
    read, registry build, I/O) that an embedder must not pay for.
- A second client surface needing the live command roster (palette, menu),
  which makes the AppState roster publication pay for itself.
- A second cross-layer capability appearing with the same "belongs to no
  one layer" shape — at which point a small service registry may beat
  per-capability composition-root wiring.
