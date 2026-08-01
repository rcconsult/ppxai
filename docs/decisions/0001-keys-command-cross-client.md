# ADR 0001 — `/keys` cross-client behavior in v1.18.1

**Date:** 2026-04-25
**Status:** Accepted — implemented (`commands/system.py::handle_keys`: universal Markdown + `vscode_delegate` on HTTP contexts, rich key table on TUI)
**Related:** `docs/archive/TODO-v1.18.1-command-unification.md` Phase 2 step 1f

## Context

`/keys` is a TUI-introspection command. Today its server-side handler
(`ppxai/commands/system.py::handle_keys`) returns a `TextResult`
built from `ppxai.tui.keys.get_keys_table()` — a formatted table of
the **Textual binding registry** (`ALL_KEYS` in `ppxai/tui/keys.py`).

That registry is meaningless to web and VSCode clients because:

- **Textual bindings** name widgets that don't exist outside the
  Textual TUI (file tree, side panel, data viewer, full-screen editor).
- **VSCode** has its own keybinding system: command IDs registered in
  `vscode-extension/package.json::contributes.keybindings`, plus the
  user's `keybindings.json` overrides. Reading the Textual table tells
  a VSCode user nothing about which keys actually do something inside
  their VSCode session.
- **Web** has DOM keyboard-event mappings inside `app.js` and the
  webview components. There is no central registry today.

The command unification migration in v1.18.1 routes every command
through `POST /command/<name>` so all three clients exercise the same
factory handler. That forces us to answer: what should `/keys` say
when it isn't running in a Textual TUI?

## Options considered

### Option A — Per-client binding registries served by the engine

Each client maintains its own structured binding registry (web in JS,
VSCode contributed via `package.json`, Textual via `tui/keys.py`).
The HTTP request includes an `X-Client: web|vscode|textual` header.
The factory handler `handle_keys` looks up the client-specific
registry and returns it.

**Cost.** Adds two new registries that don't exist today. Web bindings
are scattered across `app.js`, components, and webview event handlers
— consolidating them is a real refactor (~150 LoC across three or
four files plus a structured manifest). VSCode bindings live in
`package.json` but the engine has to either bundle a snapshot or
fetch them from the extension host (round-trip + caching).

**Benefit.** `/keys` works correctly and gives the user actionable
information specific to where they are.

### Option B — `MarkdownResult` of cross-client universals + native delegation

`/keys` returns a small `MarkdownResult` listing the bindings that
ARE universal across all three clients (essentially: chat-input
controls — `Enter`/`Ctrl+Enter` to submit, `Esc` to interrupt,
`↑/↓` for history). Plus client-specific side-effects:

- VSCode: `{kind: "vscode_delegate", command: "workbench.action.openGlobalKeybindings"}`
  → opens the user's keybinding editor where they can find anything
- Web: `{kind: "notify", level: "info", message: "Web keyboard shortcuts are listed at <docs URL>"}`
- Textual: existing rich table via the current handler (unchanged)

**Cost.** Trivial. Reuses the existing handler for Textual, adds two
side-effects for the other clients, lists ~5 universal bindings.
~30 LoC change to `handle_keys`.

**Benefit.** `/keys` does *something* useful in every client without
building new infrastructure. The VSCode user gets directly to the
canonical place to inspect/edit keys; the web user gets pointed at
docs (which we'd need to write — but we'd need to write them anyway
for Option A).

**Limitation.** The "universal" list is small and somewhat
hand-curated. The web fallback is weak (a docs link is worse UX
than a real binding table). VSCode's native keybinding editor doesn't
filter to ppxai-specific bindings — the user has to type "ppxai" to
find them.

## Decision

**Option B.** For v1.18.1.

## Why this and not Option A

- **Scope discipline.** v1.18.1 is already large (command unification
  + state-sync determinism). Adding two new structured registries
  expands the surface area without solving a hot user pain point —
  there's no evidence users are blocked on `/keys` in web/VSCode today
  (the command essentially didn't reach them before this migration).
- **Cheap to upgrade later.** Option B's `vscode_delegate` and
  `notify` paths are still valid even after Option A lands —
  Option A would just augment them with a pre-built table. The two
  options compose; (B) is a strict subset of (A).
- **Forces us to write the docs.** Web's `notify(docs URL)` only
  works if the URL exists. Writing that doc is a forcing function
  for a piece of cross-client documentation we owe users anyway.

## Future / proper solution

When we revisit, **Option A** is the target:

1. **Web binding registry.** Consolidate the scattered DOM keyboard
   handlers in `app.js` and components into a single
   `ppxai/web/shared/keys.js` mirror of `ppxai/tui/keys.py` — a
   structured array of `{key, owner, description, action}` records
   with a `get_keys_table()` analogue.
2. **VSCode binding registry.** Either (a) the extension contributes
   a `package.json::contributes.keybindings` block and the engine
   reads it via `keybindings.json` parser, or (b) the extension
   posts its own registry to the server on activation
   (`POST /clients/keys`) and the server caches it per-session.
   (a) is purer; (b) is more flexible if VSCode keybindings ever
   need to be dynamic.
3. **Engine handler.** `handle_keys` reads `X-Client` header (already
   used elsewhere for telemetry) and returns the matching registry's
   formatted table as a `MarkdownResult` or `TableResult`.
4. **Cross-client universals.** Tag bindings with a `universal: true`
   flag in each registry so the engine can synthesize a "common keys"
   section even when called without a client header.

Estimated cost when we do it: ~250–350 LoC across web, VSCode, and
engine — not enormous, but only worth doing when there's a user
signal that `/keys` matters in web/VSCode.

## Triggers to revisit

Re-evaluate this decision if any of these become true:

- Users (1+ in the wild) report confusion about which keys work in
  web or VSCode and ask for a `/keys`-style introspection.
- Web grows enough keyboard-driven UI (file tree navigation,
  panel switching, command palette) that hand-tracking the bindings
  in docs becomes a maintenance burden.
- VSCode's keybinding system gains an API for "let extensions list
  their own bindings" (today this requires reading `package.json` +
  the user's `keybindings.json`, which is brittle).
- We ship a major refactor that touches the web event-handler layout
  anyway (e.g. moving to a state machine for input handling) — fold
  the registry migration into that work for free.

## Implementation notes for v1.18.1

The Option B handler in `ppxai/commands/system.py::handle_keys`:

```python
def handle_keys(context: CommandContext, args: str) -> CommandResult:
    # Textual path: existing rich table (unchanged)
    if context.is_textual_client():  # to be added; falls back to True if env says TUI
        try:
            from ..tui.keys import get_keys_table, get_conflicts_table
            ...
        except ImportError:
            pass  # fall through to universal-only

    # Universal cross-client bindings
    md = """## Keyboard Shortcuts (universal)

| Key | Action |
|---|---|
| `Enter` | Submit message (web/VSCode) |
| `Shift+Enter` | New line in input |
| `↑` / `↓` | Command history |
| `Esc` | Interrupt streaming |
| `Ctrl+Enter` (or `Ctrl+J`) | Submit (Textual TUI) |

For client-specific shortcuts:
- **Web:** see https://ppxai.dev/docs/keys/web
- **VSCode:** opening keybinding editor — search "ppxai"
- **Textual TUI:** run `/keys` inside the TUI"""

    result = MarkdownResult(
        status=ResultStatus.INFO,
        message="Keyboard Shortcuts",
        content=md,
    )
    # Side-effects per client capability — unknown kinds are no-ops
    result.add_side_effect("vscode_delegate",
                           command="workbench.action.openGlobalKeybindings")
    return result
```

The web client honors the `MarkdownResult` rendering and ignores
`vscode_delegate` (per the open-enum contract). VSCode honors both:
the panel renders the markdown AND the keybinding editor opens.
Textual doesn't take this path — its `is_textual_client()` short-circuit
returns the existing rich table.

`is_textual_client()` is a small helper on `CommandContext` to be
added in step 1f. Initial implementation: returns `True` if the
context was constructed by Rich/Textual TUI (in-process call), `False`
if constructed by `ServerCommandContext` (HTTP call). This isn't
strictly Textual vs not-Textual — it's "was this the in-process
TUI path?" — which is what we actually want.
