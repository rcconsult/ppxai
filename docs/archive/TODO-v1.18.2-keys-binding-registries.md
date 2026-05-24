# v1.18.2 — Per-client keyboard binding registries (Option A for `/keys`)

**Status:** Deferred from v1.18.1
**Decision record:** [docs/decisions/0001-keys-command-cross-client.md](decisions/0001-keys-command-cross-client.md)

## Background

`/keys` in v1.18.1 ships with **Option B** — a small `MarkdownResult`
of cross-client universal bindings plus a `vscode_delegate` side-effect
that opens the VSCode keybinding editor. That works in every client
without building new infrastructure, but the web/VSCode rendering is
weaker than what users get in the Textual TUI (which has a real
binding registry).

This TODO tracks the deferred **Option A** work: structured per-client
binding registries so `/keys` can return a correct, native table in
every client.

See [ADR 0001](decisions/0001-keys-command-cross-client.md) for the
full context, the trade-off accepted, and the triggers that should
prompt re-evaluation.

## Scope

1. **Web binding registry.** Consolidate the scattered DOM keyboard
   handlers in `app.js` and components into a single
   `ppxai/web/shared/keys.js` mirror of `ppxai/tui/keys.py` —
   structured array of `{key, owner, description, action, universal?}`
   records with a `get_keys_table()` analogue.
2. **VSCode binding registry.** Extension contributes its bindings
   block in `package.json::contributes.keybindings` (already partly
   true). Either:
   - (a) engine reads `package.json` directly via a known path, or
   - (b) extension posts its registry to the server on activation
     (`POST /clients/keys`) and the server caches per-session.
   (a) is purer; (b) is more flexible if VSCode keybindings ever
   need to be dynamic.
3. **Engine handler.** `handle_keys` in `ppxai/commands/system.py`
   reads `X-Client` header (or the `is_textual_client()` helper added
   in v1.18.1) and returns the matching registry's formatted table
   as a `MarkdownResult` or `TableResult`.
4. **Universal flag.** Tag bindings with `universal: true` in each
   registry so the engine can synthesize a "common keys" section
   when called without a client header (or in a TUI summary view).

## Estimated cost

~250–350 LoC across web, VSCode, and engine. Not enormous; it's
deferred only because there's no signal that v1.18.1's Option B is
inadequate. Re-evaluate when the [ADR 0001 triggers](decisions/0001-keys-command-cross-client.md#triggers-to-revisit)
fire.

## Acceptance criteria (when picked up)

- [ ] `/keys` in web returns a real binding table from
      `ppxai/web/shared/keys.js`, not a docs link.
- [ ] `/keys` in VSCode returns a binding table sourced from the
      extension's contributions (no longer needs `vscode_delegate`
      to the global keybinding editor — though the side-effect can
      remain as an additional convenience).
- [ ] Universal-flagged bindings render identically across all three
      clients.
- [ ] Existing v1.18.1 `vscode_delegate` side-effect still works
      (additive, not replacing).
- [ ] `tests/test_keys_command_per_client.py` proves each client gets
      its own table when `X-Client` is set.
