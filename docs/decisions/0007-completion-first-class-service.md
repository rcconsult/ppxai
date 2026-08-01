# ADR 0007 — Completion as a first-class service; command roster via AppState

**Date:** 2026-06-14
**Status:** Proposed — step 1 shipped v1.18.8 (`CommandFactory.iter_completion_specs`, `commands/factory.py`); step 2 (extract `ppxai/completion/` package) open, target v1.19.x
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
`complete()` seam — no client references `CommandFactory` — so the seam is
the right place to invert, and the roster is the right thing to publish.

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
2. **v1.19.x:** define `CommandRegistryProtocol` + `CompletionContextProtocol`
   (leaf modules); lift `complete()` into `ppxai/completion/CompletionService`;
   wire it at each composition root (preloaded); collapse the three client
   context-scrapers; publish the roster snapshot via AppState.

## Triggers to revisit

- A "ship the engine as a standalone library" goal (makes the residual
  `engine → commands` import a hard blocker, not a smell).
- A second client surface needing the live command roster (palette, menu),
  which makes the AppState roster publication pay for itself.
- A second cross-layer capability appearing with the same "belongs to no
  one layer" shape — at which point a small service registry may beat
  per-capability composition-root wiring.
