# ADR 0007 — Completion as a first-class service; command roster via AppState

**Date:** 2026-06-14 (revised 2026-08-15, re-measured 2026-09-20 on
`bugfix/v1.19.3` — the 08-15 evidence had decayed; see §Re-measured)
**Status:** Proposed — step 1 shipped v1.18.8 (`CommandFactory.iter_completion_specs`, `commands/factory.py`); step 2 (extract `ppxai/completion/` package) **still open**. The "target v1.19.x" in the 08-15 revision has now been passed by v1.19.0, v1.19.1 and v1.19.2 without step 2 landing — it was a hope, not a plan, and is restated below as an explicit deferral with triggers rather than a date.
**Related:**
- `ppxai/engine/completion.py` — current home of `complete()`
- `ppxai/commands/factory.py` — `CommandFactory`, `CompletionCommandInfo`, `iter_completion_specs()`
- `docs/patterns/protocol-dependency-inversion.md` — the v1.17.0 leaf-Protocol idiom this builds on
- `docs/patterns/appstate.md` — observable state + `state_sync` push to all clients
- ADR 0002 — CommandContext three-pattern split (the per-client delivery shape completion also lives across)
- Debt item 29 — the layering finding that triggered this; v1.18.8 landed the seed (`iter_completion_specs()`)

## Context

Autocomplete for all four clients (Rich, Textual, Web, VSCode) is served
by a single function, `engine.completion.complete()`. It is the only
`engine → commands` import in the entire engine package: it reaches up
into the `commands` layer to read the command roster from `CommandFactory`.

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

### Roster data → published through AppState

- AppState carries a **command-roster snapshot** (the
  `iter_completion_specs()` view), pushed to every client via the existing
  `state_sync` channel.
- Command evolution then propagates to **non-autocomplete** surfaces
  (palettes, `/help`, menus) declaratively: register a command
  server-side, every client re-renders on the next state push, with no
  client code. AppState owns the *data*; `CompletionService` owns the
  *behaviour* — they are not merged.

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
  *data*, not a service host. Only the roster snapshot belongs there.

## Future / proper solution

This ADR *is* the proper solution; v1.18.8 shipped only the forward-compatible
seed. Incremental path:

1. **v1.18.8 (done):** `CommandFactory.iter_completion_specs()` +
   `CompletionCommandInfo`; `engine.completion` stops reading factory
   privates. No cascade — the `complete()` seam is unchanged. (Debt 29
   privates-reach closed.)
2. **Deferred, no target release.** Define `CommandRegistryProtocol` +
   `CompletionContextProtocol` (leaf modules); lift `complete()` into
   `ppxai/completion/CompletionService`; wire it at each composition root
   (preloaded); collapse the three client context-scrapers; publish the
   roster snapshot via AppState.

   **Scoped 2026-09-20.** The full step 2 is three separable pieces, and
   they are worth costing separately because only the first is small:

   | Piece | What it touches | Size |
   |---|---|---|
   | (a) Invert the edge | 2 call sites in `engine/completion.py`, 3 callers, 1 leaf Protocol | small — the edge, and nothing else |
   | (b) Move to `ppxai/completion/` | relocate an 884-line module, retarget 3 imports | mechanical, but it is the piece that makes the layering claim true |
   | (c) Collapse the 3 context-scrapers + publish the roster via AppState | `rich/main.py`, `tui/completer.py`, `server/routes/completion.py`, plus the AppState DTO and its 3 client mirrors and sentinel tests | the expensive piece, and the only one that pays a user-visible dividend (palettes / `/help` / menus update with no per-client code) |

   (a) alone removes the `engine → commands` import and the package cycle
   with it. (a)+(b) discharge the ADR's layering argument. (c) is a
   separate feature wearing the same ADR's clothes, and is the reason this
   record has looked too expensive to start three releases running.

   **The cheap defence is in place as of 2026-09-20**, independent of all
   three pieces: `tests/test_no_new_lazy_imports.py::TestEngineCompletionStaysALeaf`
   asserts that no module under `ppxai/engine/` imports
   `engine.completion`, at module scope or inside a function.

   Mutating one in **proved the cycle empirically**, which no previous pass
   had done. A module-scope import in `engine/client.py` does not merely
   fail a test — it takes the whole pytest run down at collection with
   `ImportError: cannot import name 'EngineClient' from partially
   initialized module 'ppxai.engine'`, via
   `completion -> commands.factory -> commands.handler -> engine`. The
   package cycle described above is therefore not theoretical; it is one
   import away, and the guard exists because the *function-level* form of
   that same import defers the failure to call time, where nothing else
   would catch it.

   The guard is disposable: when step 2 lands and `complete()` leaves
   `ppxai/engine/`, delete the class. `test_the_engine_root_is_where_we_think`
   says so in its own failure message.

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
