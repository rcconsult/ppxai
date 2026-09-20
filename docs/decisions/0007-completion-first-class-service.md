# ADR 0007 — One command registry: completion, help and the roster from a single declaration

**Date:** 2026-06-14 (revised 2026-08-15; re-measured 2026-09-20 on
`bugfix/v1.19.3` — the 08-15 evidence had decayed, see §Re-measured;
**revised 2026-09-20 — goal restated by the owner and the roster decision
changed from AppState push to a pull endpoint, see §Goal and §Decision**.
Originally titled "Completion as a first-class service; command roster via
AppState".)
**Status:** Proposed — step 1 shipped v1.18.8 (`CommandFactory.iter_completion_specs`, `commands/factory.py`); step 2 (extract `ppxai/completion/` package) **still open**. The "target v1.19.x" in the 08-15 revision has now been passed by v1.19.0, v1.19.1 and v1.19.2 without step 2 landing — it was a hope, not a plan, and is restated below as an explicit deferral with triggers rather than a date.
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

A command's metadata lives in **five places**, none complete:

| # | Where | Carries |
|---|---|---|
| 1 | `CommandSpec` (`commands/factory.py`) | name, description, category, aliases, usage, hidden |
| 2 | `web/shared/commands.js` (376 lines, hand-written) | description, usage, category, **subcommands** — restated in JS, **aliases restated as standalone entries** |
| 3 | `web/app.js:199` inline fallback catalog | a second JS copy, used when `SharedCommands` fails to load |
| 4 | `engine/completion.py` `_*_SUBCOMMANDS` tables (six of them) | **subcommands** — a second hand-written set, in Python |
| 5 | `engine/completion.py` `_BUILTIN_SPECIAL_COMMANDS` | the client-handled commands + their `clients` gating — in Python, but **outside the registry** |

The rosters disagree. Nine canonical non-hidden Python commands are missing
from JS: `attach`, `autoroute`, `copy`, `debug-log`, `doctor`, `keys`,
`preview-log`, `reload`, `undo`.

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
is gated to `{web, vscode}`; `/quit` and `/exit` end the client process.
They are declared in `_BUILTIN_SPECIAL_COMMANDS` as loose dicts because the
registry has no way to express a command with no server handler — which is
why they sit outside it, and why web `/help` is stitched from two sources
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
  aliases — `CommandSpec.aliases`, with collision checks and resolution in
  the factory. JS must simply stop restating them.) Without this the registry can never
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
2. **Open, no target release.** Sequenced by the goal, not by the layer
   inversion (revised 2026-09-20 — the earlier (a)/(b)/(c) split treated
   the roster as the optional tail; it is the head):

   1. **Enrich `CommandSpec`** — `subcommands`, `clients`, argument kinds,
      and client-handled specs for `token` / `quit` / `exit`. Widen `CompletionCommandInfo` (or replace it) so the
      published view carries `usage`, `category` and subcommands.
   2. **`GET /commands`** serves the full snapshot; `/reload` signals
      roster-changed.
   3. **JS clients fetch at startup**; `commands.js` becomes a loader, then
      is deleted.
   4. **Derive, don't restate** — completion's `_*_SUBCOMMANDS` tables and
      `/help` read the spec. At this point `engine/completion.py` stops
      importing `CommandFactory`, closing the layer inversion and the
      package cycle as a side effect; `TestEngineCompletionStaysALeaf`
      can then be deleted (it says so itself).
   5. **Parity fence** — no client renders an undeclared command; no
      declared command goes unrendered; and every `client_action` named in
      Python is implemented by every client in that spec's `clients`.

   Each step ships alone. Steps 1–2 are server-only and change no client.

   **The guard is in place meanwhile** (2026-09-20):
   `tests/test_no_new_lazy_imports.py::TestEngineCompletionStaysALeaf`
   fences `engine.completion`'s leaf status. Mutating an import in proved
   the package cycle empirically — a module-scope import of it from
   `engine/client.py` takes the whole pytest run down at collection with
   `ImportError: cannot import name 'EngineClient' from partially
   initialized module 'ppxai.engine'`, via
   `completion -> commands.factory -> commands.handler -> engine`.

   Relocating `complete()` to a `ppxai/completion/` package (the original
   step-2 headline) is **optional after step 4** — once the upward import
   is gone, where the module sits is cosmetic. Do not build the
   `CompletionService` DI class ahead of need: a service holding a context
   collaborator while callers still scrape context is worse than either
   endpoint.

   Plan: [plan-adr-0007-completion-service.md](../plan-adr-0007-completion-service.md).

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
