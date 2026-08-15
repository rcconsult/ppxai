# Pattern: Command Dispatch via Envelope

**Added:** v1.18.1
**Status:** **CRITICAL — ALL slash command logic flows through `POST /command/<name>`**
**Reference:** `ppxai/server/routes/commands.py`, `ppxai/commands/results.py::SideEffect`,
`docs/decisions/0001-keys-command-cross-client.md`

## Problem

Pre-v1.18.1, the same slash command was implemented twice — once in the Python `CommandFactory` (Rich + Textual TUIs) and once in `ppxai/web/shared/command-dispatcher.js` / `vscode-extension/src/chatPanel.ts`. Most commands didn't actually go through `POST /command/<name>`; they hit bespoke REST endpoints (`/sessions`, `/checkpoint/list`, `/working-dir`, `/files/read`, ...) and the JS/TS clients duplicated the formatting logic. The factory and the JS/TS lists drifted — at v1.18.0 nine of ten builtin command modules were missing from the PyInstaller specs and nobody noticed for six releases because only `/usage` actually exercised the factory path.

## Solution: One dispatch path, one wire envelope, intent-named side-effects

1. **Every command** lives in `CommandFactory`. The web JS dispatcher and the VSCode extension dispatcher are thin shells that call `apiClient.executeCommand(name, args)` → `POST /command/<name>` → `CommandFactory.get(name).handler(context, args)`.

2. **The wire envelope** (`POST /command/<name>` response):
   ```json
   {
     "ok": true,
     "result": { ...CommandResult.to_dict()... },
     "side_effects": [{"kind": "...", ...payload}],
     "events": [ ... ],
     "version": 1
   }
   ```
   `result` is the rendered payload (TableResult, MarkdownResult, FileViewResult, etc.). `side_effects` are orthogonal UI directives. **`events`** carries any engine side-channel events the handler enqueued (`state_sync`, `working_dir_changed`, …), drained into the response by `with_drained_events()` — without that piggyback they would sit in `engine._event_queue` until the next SSE turn. It is part of the envelope, not an extra.

3. **Side-effect kinds name the user's intent, not the rendering.** Web builds panels (xterm.js, CodeMirror, iframe); VSCode delegates to first-party APIs (`createTerminal`, `showTextDocument`, `executeCommand('vscode.open')`). The kind is the contract; the rendering is the client's choice. See `ppxai/commands/results.py::SideEffectKind` for the canonical list (**16 kinds** as of v1.19.1; 15 at v1.18.1).

4. **Open-enum invariant.** Clients ignore unknown kinds gracefully. Adding a new kind is non-breaking. `vscode_delegate` is the escape hatch for VSCode-only features (e.g. `workbench.action.openGlobalKeybindings`); web ignores it.

## TUI handlers vs HTTP handlers

The factory handlers are called from BOTH paths:
- **In-process** (Rich/Textual): `CommandFactory.get("name").handler(context, args)` with a `RichCommandContext`, or — for Textual — the app object itself, which satisfies the protocol directly. (`TextualCommandContext` was removed in v1.18.2; see ADR 0002 for why the three patterns are deliberately not unified.) The result's `side_effects` field is read directly by the TUI renderer; no envelope wrap.
- **HTTP** (web/VSCode): `POST /command/<name>` → `ServerCommandContext` → handler → route layer wraps the result in the v1 envelope.

Handlers branch on `isinstance(context, ServerCommandContext)` when they need to format differently for HTTP (e.g. `/help` returns `MarkdownResult` for HTTP and `TextResult` with Rich markup for TUI; same content, two formatters via `CommandFactory.generate_help(markdown=True)`).

## `prompt_quick_pick` resume protocol

When an engine handler needs the user to pick one of N options, it emits `PROMPT_QUICK_PICK` with `items: [{label, value}]`. **The chosen value IS the literal next args.** The client re-issues `POST /command/<command_to_resume>` with `args=<chosen value>` — no server-side continuation state. Every POST is idempotent given the args.

Example: `/show @config` finds 3 matches → emits `PROMPT_QUICK_PICK` with each item's `value` set to the absolute path. User picks one → client POSTs `/command/show` with `args=<absolute path>`. Second pass takes the direct branch, returns the rendered file view.

## `prompt_text` resume protocol (v1.18.3)

For free-text follow-ups (where the answer isn't from a finite set), engine emits `PROMPT_TEXT` with `{title, question, command_to_resume, original_args, placeholder}`. **The reply is concatenated to the original args with an em-dash separator** — `args = "<original_args> — <user_reply>"` — so handlers can distinguish the brief from the elaboration if they want. No server-side continuation state.

- **Web** — renders an inline form below the notification; on submit, dispatches `/<command_to_resume> <args>`.
- **VSCode** — `vscode.window.showInputBox({prompt: question, placeHolder})`; on non-empty reply, dispatches via `dispatchCommandFromSideEffect`.
- **TUI** — ignores the kind (open-enum invariant). The notification message that accompanies the side-effect serves as the user-visible nudge; the user retypes `/auto` themselves with more detail.

First user: `validate_agent_task` rejection. `/auto fix` → engine returns `NotificationResult(WARNING)` + `prompt_text` side-effect → web/VSCode auto-resume the elaboration without the user retyping the slash command.

## Buttons are command call sites too (v1.19.1)

Rule 1 below is usually read as "don't add new endpoints." The other half is
easier to miss: **a UI affordance that performs a command must dispatch that
command**, not call a bespoke endpoint that happens to do the same thing
server-side.

Until v1.19.1 the web Clear button, the VSCode webview Clear button, and the
`ppxai.clearHistory` palette command all called `POST /sessions/clear`
directly while a typed `/clear` went through the envelope. Same server-side
effect, but the bespoke call **discards the response body** — and the body is
where `events[]` lives. So every AppState field the handler pushed had to be
re-fetched by hand at each call site, and a missed site was a silently stale
badge (debt Item 48: the buttons kept the staleness bug alive after the typed
command was fixed).

This fails silently by construction: the UI still clears, nothing errors,
only derived state drifts. Guard it with source sentinels —
`tests/test_context_percentage_state.py::TestClearGoesThroughTheCommandEnvelope`
pins all three entry points onto the one dispatch path.

The shape to copy: give the client ONE method that dispatches the command
(`PpxaiApp.clearConversation`, `ChatViewProvider.clearConversation`); every
entry point calls it; only genuinely client-side state (staged files, a local
history mirror) is reset by hand next to it, with a comment saying why no
server event can do it.

## Rules

1. **Never add a bespoke REST endpoint for command logic**, and never call
   one from a UI affordance that is performing a command (see above). Routes like `/sessions`, `/checkpoint/list` exist for non-command UI (dropdowns, file-tree widget); they MUST NOT duplicate handler logic that lives in the factory.
2. **`SideEffectKind` constants over bare strings.** Use `result.add_side_effect(SideEffectKind.OPEN_EDITOR, filepath=p)` so a typo is `AttributeError`, not silently-ignored. The taxonomy sentinel test (`tests/test_command_envelope.py::TestSideEffectKindTaxonomy`) pins the exact set of v1.18.1 kinds; add a new kind in BOTH the constants class AND the `SideEffect` docstring AND the sentinel's `EXPECTED_KINDS_V1` set.
3. **Test the envelope shape, not just the result type.** The envelope contract (`{ok, result, side_effects, version}`) is what web/VSCode read. `tests/test_command_envelope.py` pins it.
4. **Per-command behavior tests live next to the handler.** Each handler gets a `tests/test_<command>_handler.py` with branches for: existing-arg, missing-arg, malformed-arg, server-side capability mismatch.
5. **Mock persistence at the binding site.** Tests that drive handlers writing to disk (`set_tui_config`, etc.) must mock the helper on the importing module's namespace — monkeypatching `HOME` does NOT redirect the path because `USER_CONFIG_FILE` is module-load-resolved.
