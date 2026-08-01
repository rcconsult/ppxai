# ADR 0002 — CommandContext three-pattern split

**Date:** 2026-04-29
**Status:** Accepted — implemented (Pattern A `rich/context.py` proxy, Textual inline on `app.py`, Pattern B `server/context.py` explicit delegation)
**Related:**
- `ppxai/commands/context.py`
- `ppxai/commands/protocol.py`
- ADR 0001 — `/keys` cross-client behavior (the v1.18.1 unification that forces every command to share a context contract)
- v1.17.1 commit `b6e9408a` — proxy-pattern refactor that established the current shape

## Context

The `CommandContext` protocol (`ppxai/commands/protocol.py`) is the
typed interface that command handlers expect to receive. Three
clients run those handlers — Rich TUI, Textual TUI, HTTP server — and
each delivers the protocol differently:

```
Rich TUI:    handler.engine_client + handler.session + handler.set_model + ...
                        ↓
                 RichCommandContext(handler)         ← Pattern A: __getattr__ proxy
                        ↓
                 spec.handler(ctx, args)

Textual TUI: PPXAIDEApp.engine_client + .session + .set_model + ...
                        ↓
                 spec.handler(self, args)             ← No adapter — app IS the context

HTTP server: EngineClient (no UI handler)
                        ↓
                 ServerCommandContext(engine)        ← Pattern B: explicit delegation
                        ↓
                 spec.handler(ctx, args)
```

This three-pattern split is **deliberate** but cosmetically
inconsistent. Reviewers (human and LLM) periodically read
`commands/context.py`, see Rich uses a proxy, see PPXAIDEApp
implements `CommandContext` directly, and conclude "this is
inconsistent — should refactor." We've re-litigated this question
twice (v1.17.1 chose Pattern A; v1.18.2 Item 1 narrowing
re-confirmed). This ADR pins the rationale so the question doesn't
re-open without new evidence.

## Decision

**Keep the three-pattern split.** Specifically:

1. **Rich TUI uses Pattern A.** `RichCommandContext(handler)` wraps
   `CommandHandler` via `_CommandContextProxy.__getattr__`. The
   wrapped class implements every `CommandContext` member as a
   property/method (~16 members). The proxy adds two
   `get_config_value` / `set_config_value` overrides with `hasattr`
   guards.

2. **Textual TUI uses no adapter.** `app.py::_handle_command`
   passes `self` (the `PPXAIDEApp` instance) directly to
   `spec.handler`. `PPXAIDEApp` implements `CommandContext`
   methods inline (~16 members, ~100 LoC). No wrapper class is
   instantiated.

3. **HTTP server uses Pattern B.** `ServerCommandContext(engine)`
   holds an `EngineClientProtocol` reference and implements every
   `CommandContext` member explicitly against `engine.state.get/set`
   or direct engine method calls. No proxy — there's no UI handler
   to wrap. (Item 10, v1.18.2: typed against the protocol.)

The unused `TextualCommandContext` class (a Pattern A wrapper for
PPXAIDEApp that was created in v1.15.0 but never wired into
`app.py`) was deleted on 2026-04-29 — it had been dead code for
13 releases.

## Why this and not the alternatives

### Alternative 1: Unify all three on Pattern B (explicit delegation)

`commands/context.py` would house `RichCommandContext`,
`TextualCommandContext`, `ServerCommandContext` — all explicit
`@property` / method definitions delegating to the wrapped object.
The 16 members on `CommandHandler` (Rich) and the 16 on
`PPXAIDEApp` (Textual) could then be deleted; `commands/context.py`
becomes the single source of truth for what `CommandContext`
exposes.

**Cost.**
- ~200 LoC of explicit delegation lands in `commands/context.py`,
  triple-implemented (Rich/Textual/Server). Some methods would still
  have UI side-effects:
  - `CommandHandler.set_model` calls `console.print(...)` for
    context-reset notifications.
  - `PPXAIDEApp.set_model` calls `self.notify(...)` (Textual
    notification) for the same reason.
  - `ServerCommandContext.set_model` does neither.
  Encoding "the engine call + the UI side-effect" cleanly across
  three contexts means either the contexts grow callback parameters
  (notify/console handles) or the side-effects move into AppState
  observers (~half-day refactor on its own).
- Every command call path changes. There are 14+ command modules
  in `ppxai/commands/` calling `context.engine_client.X` and
  `context.session.X`; behavior is unchanged but the dispatch
  shape is.
- The proxy → explicit migration was the *opposite* direction of
  v1.17.1's `b6e9408a` refactor (which moved 80 lines OUT of
  context.py). Reverting it without a forcing function is churn.

**Benefit.** Single source of truth ("where does CommandContext
live?"). New contributors don't ask the three-pattern question.

**Verdict: defer.** The current split works; the win is aesthetic.
Spend the day when there's a forcing function.

### Alternative 2: Unify all three on Pattern A (proxy)

`ServerCommandContext` becomes a proxy wrapping a "fake handler"
that exposes the protocol. But the server has no UI handler — the
"fake handler" would be either the engine itself (which doesn't
implement the UI side of the protocol) or a synthetic wrapper
(which is just Pattern B with extra steps). **Rejected** —
Pattern A requires a wrapped object that *naturally* implements
the protocol.

### Alternative 3: Wire `TextualCommandContext` so Textual matches Rich

Use `TextualCommandContext(self)` at `app.py:1169` instead of
`self`. The wrapped `PPXAIDEApp` would still need its 16
`CommandContext` methods (the proxy forwards to them). Net
change: zero — the methods can't be removed.

**Verdict: rejected** — adds an unused wrapping layer with no
benefit. The class was dead code; we deleted it.

## Trade-offs accepted

1. **Three patterns to learn.** New contributors need to read this
   ADR to understand why Rich is one shape, Textual is another,
   Server a third. The pin is worth ~10 minutes of confusion saved
   per re-encounter, multiplied by everyone who reads
   `commands/context.py`.

2. **No single source of truth for CommandContext implementation.**
   16 methods on `CommandHandler`, 16 on `PPXAIDEApp`, 16 in
   `ServerCommandContext`. Adding a CommandContext member means
   touching all three. The protocol itself enforces the contract;
   the implementations are mechanical.

3. **The "boilerplate" reading is permanent.** Anyone scanning
   `app.py` for size will count those 16 methods (~100 LoC) as
   "not pulling weight." This ADR is the answer to "should we
   pull these out" — they're the implementation, they live where
   they live for a reason.

## Future / proper solution

When all of the following are true:

- A fourth context type is added (e.g. mobile, Slack bot, headless CLI)
- The new context's needs differ from the existing three enough that
  Pattern B (explicit) is the right fit
- We're already touching the command-dispatch path

THEN unify on Pattern B. The work is ~1-2 days; the engine-state-vs-
UI-state interleaving (`set_model` notify) needs a clean answer
(probably AppState observer that watches for `last_model_switch_reset`
changes and emits the user-facing warning, decoupled from
`set_model` itself).

Until then: keep the three-pattern split. Don't refactor on
speculation. Don't delete the inline methods on `CommandHandler` /
`PPXAIDEApp` thinking they're "boilerplate" — they're the
implementation Pattern A requires.

## Triggers to revisit

1. **A 4th context type lands** that doesn't fit cleanly into the
   existing three patterns.
2. **CommandContext gains 5+ new members in one release** that have
   to be triple-implemented (mechanical churn becomes painful).
3. **An external SDK consumer needs `commands/`** (related to the
   "ppxai SDK extraction" thinking in the v1.18.2 conversation). At
   that point a clean Pattern B in `commands/context.py` is more
   shippable than three concrete classes scattered across files.
4. **The v1.17.1 proxy refactor's rationale becomes invalid** —
   e.g., the wrapped classes stop naturally implementing the
   protocol surface (they currently do because the same methods
   serve direct callers inside Rich/Textual code).

## Notes for future readers

- The "dead `TextualCommandContext`" was the actual leftover, not
  the inline methods on PPXAIDEApp. We removed it on 2026-04-29.
- `ServerCommandContext` types against `EngineClientProtocol` (Item
  10, v1.18.2 — `ppxai/engine/types.py::EngineClientProtocol`),
  not the concrete `EngineClient`. That's a separate decoupling
  win, orthogonal to this ADR.
- The three patterns aren't symmetric in cost: Rich/Textual share a
  natural shape (TUI handler implements protocol → adapter or
  direct pass works), Server is the one that *had* to be Pattern B.
  The split is "two natural + one necessary," not "three arbitrary."
