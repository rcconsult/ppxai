# v1.18.1 — Command Unification (Option A, no compromises)

**Branch:** `feature/v1.18.1` (off master `9f1c1f4c`)
**Goal:** Every slash command flows through `POST /command/<name>` → Python `CommandFactory`. No bespoke REST endpoints for command logic. Same wire protocol for web app and VSCode extension. Eliminate the split-brain.

## Why this matters now

The PyInstaller hidden-imports bug shipped in v1.17.4 → v1.18.0 (six releases) without anyone noticing because `POST /command/` was a dead code path for everything except `/usage`. The 35-case JS dispatcher in `command-dispatcher.js` and the parallel registrations in `CommandFactory` were a maintenance hazard masquerading as a working design — every command path was implemented twice, and only one of the two implementations was actually load-bearing.

**Eliminating the parallel implementations** means:
- One place to change a command's behavior.
- Tests that exercise the factory cover all clients.
- The PyInstaller spec failure mode that just bit us becomes a single symptom (every command broken on frozen builds), not a silent six-release drift.
- Web/VSCode extension stay as thin renderers — they don't re-implement business logic.

## Locked design decisions (user confirmed 2026-04-25)

1. **Wire envelope.** `POST /command/<name>` returns a structured envelope, not raw `CommandResult.to_dict()`. The envelope cleanly separates the rendered payload from UI side-effect hints (open panel, spawn terminal, refresh tree, etc.) so clients don't have to peek at `metadata` to decide whether to act.
2. **Factory is the single dispatcher.** If a command is registered in the Python `CommandFactory`, every client (web, VSCode, Rich, Textual) reaches it via `POST /command/<name>`. No bespoke REST endpoint may duplicate command logic.
3. **VSCode uses the same path.** Identical wire protocol as the web app. The VSCode extension is a renderer over the same envelope, not a parallel command implementation.

## New wire envelope

`POST /command/<name>` will return:

```json
{
  "ok": true,
  "result": { /* CommandResult.to_dict() — rendered payload */ },
  "side_effects": [
    { "kind": "open_html_preview", "url": "http://127.0.0.1:54321/", "filepath": "/abs/path/index.html" },
    { "kind": "open_terminal", "cwd": "/abs/cwd" },
    { "kind": "open_editor", "filepath": "/abs/file.py", "line": 12, "column": 5 },
    { "kind": "open_viewer", "filepath": "/abs/doc.md" },
    { "kind": "refresh_file_tree", "cwd": "/abs/cwd" },
    { "kind": "show_image", "filepath": "/abs/img.png" },
    { "kind": "show_pdf", "filepath": "/abs/doc.pdf" },
    { "kind": "set_theme", "name": "dracula" },
    { "kind": "reveal_in_explorer", "filepath": "/abs/file.py" },
    { "kind": "prompt_quick_pick", "title": "Multiple matches", "items": [...], "request_id": "..." },
    { "kind": "run_shell", "command": "kubectl logs ...", "cwd": "/abs/cwd" },
    { "kind": "notify", "level": "info|warn|error", "message": "..." },
    { "kind": "vscode_delegate", "command": "workbench.action.findInFiles", "args": [{"query": "TODO"}] }
  ],
  "version": 1
}
```

Errors (4xx/5xx) keep returning HTTPException as today. The `ok` field is reserved for command-level success/failure inside a 200 response, mirroring `CommandResult.status`.

**Schema rules:**
- `result` is `CommandResult.to_dict()` — unchanged shape, just nested under `result`.
- `side_effects` is always an array (possibly empty). Each entry has a `kind` discriminator.
- `kind` values are an open enum — clients ignore unknown kinds gracefully. Adding a new kind is non-breaking.
- `version: 1` for forward-compat. Bump if envelope shape changes.

**Why an envelope instead of `metadata` flags:** UI hints aren't metadata about the result — they're orthogonal directives to the renderer. Mixing them into `result.metadata` blurs the contract and forces clients to scan `metadata` for magic keys.

## Side-effect kinds: name the intent, let the client choose the rendering

Each `kind` describes **what the user asked the engine to do**, not how to render it. Clients are free to pick the most native rendering they have:

- The web app builds panels because that's all it has (xterm.js, CodeMirror, embedded iframe).
- The VSCode extension delegates to first-party VSCode APIs whenever possible — `vscode.window.createTerminal`, `vscode.workspace.openTextDocument`, `vscode.commands.executeCommand('vscode.open', ...)`. This gives the user their chosen shell, IntelliSense, debugging integration, multi-cursor, breakpoints, the file types their installed extensions handle, etc.

The engine doesn't know or care which client honors a side-effect. It emits intent; clients translate.

| `kind` | User intent | Web rendering | VSCode rendering (delegate to platform) |
|---|---|---|---|
| `open_editor` | "let the user edit this file" | CodeMirror 6 in side panel | `vscode.workspace.openTextDocument` + `showTextDocument({viewColumn: One, preview: false})` — full IDE features inherit free |
| `open_viewer` | "show this file read-only" | preview panel with type-appropriate viewer | `vscode.commands.executeCommand('vscode.open', uri, {preview: true, viewColumn: Beside})` — user's chosen viewer extensions handle non-text files |
| `open_terminal` | "give the user a terminal at this cwd" | xterm.js panel | `vscode.window.createTerminal({cwd}).show()` — user's shell, profile, history, terminal grouping |
| `run_shell` | "execute this command for the user, leave the terminal open" | xterm.js with command pre-typed | `createTerminal({cwd}) + sendText(command)` — already implemented at `chatPanel.ts:132`; just wire to envelope |
| `open_html_preview` | "render this HTML live (with reload)" | iframe in side panel | existing `previewPanel.ts` `WebviewPanel` |
| `show_image` | "display this image" | inline `<img>` viewer | `executeCommand('vscode.open', uri)` — lets installed image-viewer extensions take over |
| `show_pdf` | "display this PDF" | embedded PDF.js viewer | `executeCommand('vscode.open', uri)` — installed PDF extensions handle it |
| `reveal_in_explorer` | "highlight this in the file tree" | scroll/expand `FileTreeComponent` | `executeCommand('revealInExplorer', uri)` |
| `refresh_file_tree` | "the working tree changed under us" | refresh `FileTreeComponent` | usually a no-op (VSCode auto-watches), or `executeCommand('workbench.files.action.refreshFilesExplorer')` |
| `set_theme` | "user picked a theme" | swap CSS class on webview body | no-op on the extension host (this is webview-only UI; the user's VSCode theme is independent) |
| `prompt_quick_pick` | "let the user pick one of N options" | clickable list in chat | `vscode.window.showQuickPick(items)` — native palette UI; result POSTed back |
| `notify` | "tell the user something" | toast in chat | `vscode.window.showInformationMessage` / `Warning` / `Error` based on `level` |
| `vscode_delegate` | escape hatch for VSCode-only features that have no web equivalent | ignored | `vscode.commands.executeCommand(payload.command, ...payload.args)` |

**Three taxonomy decisions worth calling out:**

1. **`open_editor` vs `open_viewer` are split.** Earlier draft used a single `open_editor` with a `read_only` flag. VSCode wants different APIs (`showTextDocument` vs `vscode.open`), and the split makes the dispatcher mechanical.
2. **`spawn_terminal` renamed to `open_terminal`.** Same intent, less verb-noun collision, parallel to `open_editor` / `open_viewer`. `run_shell` is added as a strict superset for "open terminal AND type this command" — what `chatPanel.ts:runCommandInTerminal` already does.
3. **`vscode_delegate` is the escape hatch.** Use sparingly — most things should have a stable `kind` so web has parity. But for genuinely VSCode-only features (search-across-files, source-control panel focus, debug-start) it's cleaner than inventing a fake kind that web has no rendering for.

**Audit: VSCode delegations to preserve through the migration.**

The current extension already delegates correctly in many places. The migration must NOT regress these — they map to the new kinds 1:1:

| Current code | Location | Maps to kind |
|---|---|---|
| `vscode.window.createTerminal({cwd})` | `chatPanel.ts:138` | `open_terminal` |
| `createTerminal + sendText(command)` | `chatPanel.ts:132` (`runCommandInTerminal`) | `run_shell` |
| `showTextDocument(doc, {viewColumn: One, preview: false})` | `chatPanel.ts:2589` (`handleEditCommand`) | `open_editor` |
| `showTextDocument(doc, ViewColumn.Beside)` | `chatPanel.ts:243`, `:2440` | `open_viewer` (preview: true, Beside) |
| `executeCommand('vscode.open', uri)` for images | `chatPanel.ts:1693`, `:1719`, `:1733`, `:1759` | `show_image` / `show_pdf` |
| `WebviewPanel` for HTML preview | `previewPanel.ts` | `open_html_preview` |
| `showInformationMessage` / `showWarningMessage` / `showErrorMessage` | many | `notify` (level field) |
| `showQuickPick` for "multiple matches" | `chatPanel.ts:751`, `:814`, `:870` | `prompt_quick_pick` |

## Migration scope

### A. Web commands routed through bespoke REST endpoints (23) → migrate to factory

| Command | Current bespoke endpoint | Factory side |
|---|---|---|
| `/clear` | `POST /chat/clear` (apiClient.clearConversation) | already in factory (`session.py`) |
| `/save <name>` | `POST /sessions` (saveSession) | already in factory (`session.py`) |
| `/load <name>` | `POST /sessions/load` (loadSession) | already in factory (`session.py`) |
| `/sessions` | `GET /sessions` (listSessions) | already in factory (`session.py`) |
| `/export <fmt>` | `POST /export` (exportAnswer) | already in factory (`session.py`) |
| `/model <id>` | `GET /providers/models` + UI swap | already in factory (`provider.py`) |
| `/provider <id>` | `GET /providers` + UI swap | already in factory (`provider.py`) |
| `/tools …` (status/list/help/agent/set/config) | `GET /tools`, `POST /tools/config`, `GET /tools/help/<name>` | already in factory (`tools.py`) |
| `/checkpoint …` (list/info/clear/undo/backend) | 5 separate `/checkpoint/*` endpoints | already in factory (`utility.py`) |
| `/status` | `GET /status` (getStatus) | already in factory (`system.py`) |
| `/context …` (info/clear/reload/hints/bootstrap) | 5 `/context/*` endpoints | already in factory (`utility.py`) |
| `/cd <path>` | `POST /working-dir` | already in factory (`utility.py`) |
| `/pwd` | `GET /working-dir` | already in factory (`utility.py`) |
| `/config` | `GET /config/path` | already in factory (`system.py`) |
| `/ls <path>` | `GET /files?path=` | already in factory (`utility.py`) |
| `/tree <path>` | `GET /files/tree` | already in factory (`utility.py`) |
| `/show <file>`, `/cat <file>` | `GET /files/read` | already in factory (`display.py`) |

The bespoke REST endpoints stay alive for now (they back non-command UI: dropdowns, file-tree widget, autosave). What changes is the **command dispatch path** — `command-dispatcher.js` no longer calls `apiClient.getStatus()`, it calls `apiClient.executeCommand('status')`. Several endpoints become candidates for retirement once nothing dispatches commands through them; that audit happens in a follow-up PR (Phase 3 below).

### B. Web commands handled locally in JS → migrate to factory (5)

| Command | Current local handler | Migration |
|---|---|---|
| `/help` | `showHelp()` builds markdown locally from `SharedCommands` | factory `system.help` exists; envelope returns `MarkdownResult` |
| `/theme <name>` | `handleThemeCommand` swaps CSS class locally | factory has `system.theme`; `side_effects: [{kind:"set_theme", name}]` |
| `/preview <file>` | builds URL locally, opens panel | factory `display.preview` exists; `side_effects: [{kind:"open_preview", url, filepath}]` |
| `/terminal`, `/term`, `/sh` | `handleTerminalCommand` opens terminal panel | factory `system.terminal` exists; `side_effects: [{kind:"spawn_terminal", cwd}]` |
| `/edit <file>` | `app.handleEditCommand` opens editor panel | factory has `display.show` (read_only=false variant); add `display.edit` or extend `show`; `side_effects: [{kind:"open_editor", filepath, read_only:false}]` |

### C. Factory commands unreachable from web (8) → add web entries

These commands are registered server-side but the web JS dispatcher has no `case` for them:

`/copy`, `/autoroute`, `/undo`, `/attach`, `/doctor`, `/keys`, `/debug-log`, `/mycommand`

After Phase 1's switch table refactor (see below), the JS dispatcher becomes a generic forward-to-factory function — these commands work automatically. Phase 2 explicitly tests each one to confirm.

### D. Streaming commands (`/generate`, `/explain`, `/test`, `/docs`, `/debug`, `/implement`, `/convert`, `/spec`)

These keep using `POST /chat` because they're **chat-message-shaped** — the factory lookup just decides what system prompt to use, but the streaming response itself isn't a command result. **No change** to their dispatch path; they're listed here only to document why they're excluded from the migration.

### E. Side-effect emission per command

Each of the commands below emits one or more side-effects. Clients pick the rendering — see the full kind→behavior matrix in "Side-effect kinds" above:

| Command | side_effect kind | Payload |
|---|---|---|
| `/preview <file>` | `open_html_preview` | `{url, filepath}` |
| `/preview <file> --serve` | `open_html_preview` | `{url, filepath, served: true}` |
| `/preview <file> --proxy <port>` | `open_html_preview` | `{url, filepath, proxied: true}` |
| `/terminal`, `/term`, `/sh` | `open_terminal` | `{cwd}` |
| `/edit <file[:line[:col]]>` | `open_editor` | `{filepath, line?, column?}` |
| `/show <text-file>` | `open_viewer` | `{filepath}` |
| `/show <image>` | `show_image` | `{filepath}` |
| `/show <pdf>` | `show_pdf` | `{filepath}` |
| `/cd <path>` | `refresh_file_tree` | `{cwd}` |
| `/theme <name>` | `set_theme` | `{name}` (web only honors; VSCode no-ops) |
| `/show @query` (multiple matches) | `prompt_quick_pick` | `{title, items: [{label, value}], request_id}` |
| `/edit @query` (multiple matches) | `prompt_quick_pick` | same shape |
| any handler that wants to surface a recoverable error | `notify` | `{level, message}` |

Other commands return `side_effects: []`.

**Quick-pick result roundtrip.** When the user picks an option from a `prompt_quick_pick`, the client POSTs `/command/{name}/resume?request_id=...&choice=<value>` (or similar — exact endpoint TBD in Phase 2). The factory looks up the pending continuation by `request_id` and resumes the handler. This lets the engine emit "I need a choice" without blocking on a synchronous prompt, and lets both clients render the prompt natively.

## Implementation phases

### Phase 1 — Server: envelope + dispatcher rewrite

1. **`ppxai/server/routes/commands.py`** — wrap response in envelope. Build `side_effects` list from `result.metadata.side_effects` (a typed list the handlers populate). Keep envelope construction in the route, not in the handlers.
2. **`ppxai/commands/results.py`** — add `SideEffect` dataclass and `CommandResult.side_effects: List[SideEffect]` field. Helpers: `add_side_effect(kind, **payload)`. Each existing handler that opens panels gets a one-line addition.
3. **Tests** — `tests/test_command_envelope.py` — pin the envelope shape, exercise every kind. Sentinel test for `version=1`.
4. **Existing factory handlers updated** to emit side_effects: `display.preview`, `display.show` (when image/pdf), `system.terminal`, `display.edit` (new — see Phase 2), `utility.cd`, `system.theme`.

### Phase 2 — Server: gaps in factory + new side-effect kinds

1. **Rename + split side-effect kinds** in `ppxai/commands/results.py` SideEffect documentation:
   - `spawn_terminal` → `open_terminal`
   - Split single `open_editor` (with `read_only` flag) into separate `open_editor` (editable) + `open_viewer` (read-only)
   - Add `run_shell`, `reveal_in_explorer`, `prompt_quick_pick`, `vscode_delegate` as new kinds
   - Update existing handlers wired in Phase 1 (`/preview`, `/show`, `/cd`, `/theme`, `/terminal`) to emit the renamed kinds
2. **Add `display.edit`** (port from Textual `cmd_edit` in `ppxai/tui/commands.py:169`, including new-file creation) to handle `/edit <file>`. Emits `open_editor` side-effect with `{filepath, line, column}` (no `read_only` field — the kind itself signals editability).
3. **Update `/show`** to emit `open_viewer` for text files (currently just returns the result; clients infer the kind from `result.type`). Image and PDF paths already emit `show_image` / `show_pdf` (Phase 1).
4. **Quick-pick refactor.** Move the "multiple matches" logic out of `chatPanel.ts:751,814,870` and `app.js handleShowCommand` into `display.show` and `display.edit` — the factory handler emits `prompt_quick_pick` when fuzzy search returns multiple hits, instead of forcing each client to build its own picker.
5. **Verify each of the 8 unreachable commands** runs through `POST /command/`. Many are TUI-only today (`/keys`, `/copy`, `/debug-log`, `/mycommand`); web/VSCode renderers may render them no-op or emit `notify` side_effects. Decision per command, documented in this file.
6. **`/help` web parity** — confirm `system.help` returns a `MarkdownResult` whose content matches the JS-built version, or pick one canonical source.

### Phase 3 — Web app: rewrite `command-dispatcher.js`

1. **Replace 35-case switch with a thin shell**:
   ```js
   async dispatch(input) {
     const [cmd, ...rest] = input.trim().split(/\s+/);
     const args = rest.join(' ');

     // Streaming commands keep using /chat
     if (STREAMING_COMMANDS.has(cmd)) {
       this.app.addMessage('user', input);
       return this.app.streamChat(input);
     }

     this.app.showSystemMessage(`> ${input}`);
     const envelope = await this.app.apiClient.executeCommand(cmd.slice(1), args);
     this.renderer.render(envelope.result);
     this.sideEffects.apply(envelope.side_effects);
   }
   ```
2. **`renderer.js`** — type-based renderer keyed off `result.type` (already the convention from v1.15.0 type-based dispatch). Most types already have web renderers; this consolidates them.
3. **`side-effects.js`** — small handler that maps `kind` → DOM action (open panel, refresh file tree, etc.). Replaces the inline panel-opening code scattered across `app.js` / `command-dispatcher.js`.
4. **Smoke-test every command** from the migration scope tables in a dev server.

### Phase 4 — VSCode extension: same migration with platform delegation

The big advantage of VSCode is that we can delegate to first-party APIs and installed extensions. This phase preserves the existing delegations (see audit table in "Side-effect kinds") and routes them through the new envelope-driven dispatcher.

1. **`vscode-extension/src/chatPanel.ts`** — replace the per-command `case '/edit':` / `case '/show':` / `case '/preview':` branches (lines ~921-947) with a single dispatcher: `httpClient.executeCommand(cmd, args)` → envelope renderer + side-effect mapper. The existing methods (`handleEditCommand`, `handleShowCommand`, `handlePreviewCommand`) get rewritten as side-effect handlers, not command branches.

2. **`vscode-extension/media/webview/main.js`** — webview-side type renderer mirrors the web app's `renderer.js`. The webview only renders the `result` payload; all side effects round-trip to the extension host via `vscode.postMessage` because only the extension has the `vscode.*` API.

3. **Side-effect handler** — `vscode-extension/src/sideEffects.ts` (new) maps each kind to the right VSCode API. **Audit table from earlier MUST be honored 1:1** — these are existing behaviors users depend on:

   - `open_editor` → `workspace.openTextDocument` + `showTextDocument({viewColumn: One, preview: false})` with line/column jump
   - `open_viewer` → `executeCommand('vscode.open', uri, {preview: true, viewColumn: Beside})`
   - `open_terminal` → `window.createTerminal({cwd, name: 'ppxai'}).show()`
   - `run_shell` → `createTerminal + sendText(command)` (port from existing `runCommandInTerminal`)
   - `open_html_preview` → existing `previewPanel.ts` `WebviewPanel` (no change to that module)
   - `show_image` / `show_pdf` → `executeCommand('vscode.open', uri)` (delegates to the user's image/PDF extension; works for `.png`, `.jpg`, `.svg`, `.pdf`, etc.)
   - `reveal_in_explorer` → `executeCommand('revealInExplorer', uri)`
   - `refresh_file_tree` → `executeCommand('workbench.files.action.refreshFilesExplorer')` (or no-op if VSCode auto-watches)
   - `set_theme` → no-op on extension; the webview applies it to its own DOM
   - `prompt_quick_pick` → `window.showQuickPick(items)`; the chosen value POSTs back via `/command/{name}/resume`
   - `notify` → `showInformationMessage` / `showWarningMessage` / `showErrorMessage` based on `level`
   - `vscode_delegate` → `executeCommand(payload.command, ...payload.args)` — escape hatch

4. **Don't regress existing delegations.** Anything from the audit table that already works (terminal-command execution, native editor open, image-via-`vscode.open`) MUST keep working byte-for-byte. The migration changes WHERE the delegation is triggered (envelope `kind` instead of inline `case '/...':`) — not WHAT it does.

5. **Smoke-test every command** in a packaged `.vsix` against `ppxai-server`. Particular attention to:
   - `/edit` → opens in primary editor with line jump, NOT preview mode
   - `/show <pdf>` → opens with user's PDF extension (or built-in fallback)
   - `/terminal` → integrated terminal at session cwd, with the user's chosen shell profile
   - `/preview index.html` → existing WebviewPanel, no regression in live-reload behavior

### Phase 5 — Tests + doc

1. **`tests/test_command_envelope.py`** — envelope shape pinning.
2. **`tests/test_command_factory_completeness.py`** — every command name documented in `slashCommands` (web `app.js`) AND in VSCode `package.json` contributions exists in `CommandFactory`. Catches additions that drift the three sources.
3. **`tests/test_pyinstaller_spec_completeness.py`** (already exists) — already covers the hidden-imports failure mode.
4. **End-to-end tests** — `tests/test_command_e2e_web.py` hitting the FastAPI app via `httpx.AsyncClient`, exercising each command's envelope. ~40 tests total.
5. **Update `CLAUDE.md`** — Critical Architecture Pattern: "All command dispatch goes through `POST /command/<name>`. No bespoke REST endpoints for command logic. Side effects are envelope-driven."
6. **Update `docs/ARCHITECTURE.md`** — add command dispatch flow diagram.

## Risk register

| Risk | Mitigation |
|---|---|
| Breaking `/usage` (currently the only factory-routed command) | Keep envelope backward-compatible: clients can still read `result.*` directly; envelope just adds `result` and `side_effects` wrappers. Old `/usage` client code keeps working until ported. |
| Wire-protocol drift between Python factory + JS slashCommands list + VSCode package.json | Phase 5 completeness test |
| `/preview` server already emits ad-hoc URL — must not double-emit | Audit `display.preview` handler; consolidate URL build in one place |
| VSCode webview ↔ extension-host hop adds latency on side_effects | Acceptable — side_effects fire on user-initiated commands, not in stream loop |
| TUI handlers (Rich + Textual) currently call factory in-process — envelope must work for in-process callers too | Envelope is HTTP-shaped; TUIs unwrap `envelope.result` immediately. Or: factory returns `(CommandResult, List[SideEffect])` tuple internally; route wraps it for HTTP. |

## Out of scope for v1.18.1

- AppState codegen (deferred to v1.18.2 — see `docs/TODO-appstate-codegen.md`)
- Multi-model routing infrastructure (deferred to v1.18.2 — see `docs/TODO-routing.md`)
- Retiring bespoke REST endpoints (Phase 6, separate PR after migration is stable)

## Acceptance criteria

- [ ] `POST /command/<name>` returns the v1 envelope for every registered command.
- [ ] Web `command-dispatcher.js` has zero `case '/...':` branches outside the streaming-command set; everything else flows through `executeCommand`.
- [ ] VSCode `chatPanel.ts` has zero per-command branches outside the streaming-command set; envelope dispatcher routes everything.
- [ ] Every command name in web `slashCommands` and VSCode `package.json` exists in `CommandFactory` (verified by test).
- [ ] Every side-effect kind documented in this file has a handler in BOTH `web/sideEffects.js` and `vscode-extension/src/sideEffects.ts`. Unknown kinds are silently ignored (open-enum contract).
- [ ] VSCode delegations from the audit table are preserved byte-for-byte: `/edit` opens in primary editor (not preview), `/terminal` uses integrated terminal with user's shell profile, `/show <pdf>` delegates to installed PDF extension.
- [ ] `prompt_quick_pick` round-trip works: server emits, client renders (web list / VSCode quick-pick), choice POSTs back, handler resumes.
- [ ] `vscode_delegate` escape hatch exists and is documented; web ignores it cleanly.
- [ ] `tests/test_command_envelope.py` + `tests/test_command_e2e_web.py` green; `tests/test_command_factory_completeness.py` blocks future drift.
- [ ] PyInstaller spec completeness test still green.

## Open questions for next session

1. Should the in-process factory call (TUI) also go through the envelope, or should the route layer be the only place that wraps? **Tentative pick:** route wraps; TUI keeps direct factory access. Less churn, no functional difference.
2. `/help` content — is the JS-side help text richer than what `system.help` returns? Need to compare and consolidate.
3. Should we add a `kind: "follow_up_chat"` side effect for commands that want to inject a chat message after rendering? (Edge case, may not need.)
4. **`prompt_quick_pick` resume protocol.** Two options: (a) new `POST /command/{name}/resume?request_id=...` endpoint with a registry of pending continuations on the server; (b) treat the user's choice as a fresh `POST /command/<name>` with the `args` containing the resolved value. (b) is simpler but requires every `prompt_quick_pick`-emitting command to have idempotent semantics. **Tentative pick:** (b) for v1.18.1 — defer (a) until a command actually needs mid-flight state preserved.
5. **VSCode delegate audit.** Beyond the listed kinds, are there VSCode features the engine should be aware of so it can emit a `vscode_delegate` proactively? Examples: `git.openChange` for diff views, `workbench.action.openSettings` for `/config`, `workbench.action.tasks.runTask` for `/run`. None are blockers — `vscode_delegate` is the escape hatch, so this can grow organically.
