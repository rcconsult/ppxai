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
    { "kind": "open_preview", "url": "http://127.0.0.1:54321/", "filepath": "/abs/path/index.html" },
    { "kind": "spawn_terminal", "cwd": "/abs/cwd" },
    { "kind": "open_editor", "filepath": "/abs/file.py", "line": 12, "read_only": false },
    { "kind": "refresh_file_tree", "cwd": "/abs/cwd" },
    { "kind": "show_image", "filepath": "/abs/img.png" },
    { "kind": "show_pdf", "filepath": "/abs/doc.pdf" },
    { "kind": "notify", "level": "info|warn|error", "message": "..." }
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

### E. Side-effect taxonomy

Five commands have UI side effects beyond rendering a payload. Each gets a side-effect entry from the server, and the client picks which UI directive to honor:

| Command | side_effect kind | Payload | Web behavior | VSCode behavior |
|---|---|---|---|---|
| `/preview <file>` | `open_preview` | `{url, filepath}` | iframe in side panel | WebviewPanel |
| `/terminal` | `spawn_terminal` | `{cwd}` | xterm.js panel | open VSCode integrated terminal at `cwd` |
| `/edit <file>` | `open_editor` | `{filepath, line?, read_only:false}` | CodeMirror in side panel | `vscode.window.showTextDocument` |
| `/show <img|pdf>` | `show_image` or `show_pdf` | `{filepath}` | inline image / PDF embed | `vscode.commands.executeCommand('vscode.open', uri)` |
| `/cd <path>` | `refresh_file_tree` | `{cwd}` | file-tree widget refresh | webview file-tree refresh + working-dir badge |

Other commands return `side_effects: []`.

## Implementation phases

### Phase 1 — Server: envelope + dispatcher rewrite

1. **`ppxai/server/routes/commands.py`** — wrap response in envelope. Build `side_effects` list from `result.metadata.side_effects` (a typed list the handlers populate). Keep envelope construction in the route, not in the handlers.
2. **`ppxai/commands/results.py`** — add `SideEffect` dataclass and `CommandResult.side_effects: List[SideEffect]` field. Helpers: `add_side_effect(kind, **payload)`. Each existing handler that opens panels gets a one-line addition.
3. **Tests** — `tests/test_command_envelope.py` — pin the envelope shape, exercise every kind. Sentinel test for `version=1`.
4. **Existing factory handlers updated** to emit side_effects: `display.preview`, `display.show` (when image/pdf), `system.terminal`, `display.edit` (new — see Phase 2), `utility.cd`, `system.theme`.

### Phase 2 — Server: gaps in factory

1. **Add `display.edit`** (or extend `display.show` with `read_only=False` variant) to handle `/edit <file>`.
2. **Verify each of the 8 unreachable commands** runs through `POST /command/`. Many are TUI-only today (`/keys`, `/copy`, `/debug-log`, `/mycommand`); web/VSCode renderers may render them no-op or emit `notify` side_effects. Decision per command, documented in this file.
3. **`/help` web parity** — confirm `system.help` returns a `MarkdownResult` whose content matches the JS-built version, or pick one canonical source.

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

### Phase 4 — VSCode extension: same migration

1. **`vscode-extension/src/chatPanel.ts`** — replace bespoke command branches with `httpClient.executeCommand(cmd, args)` + envelope rendering.
2. **`vscode-extension/media/webview/main.js`** — webview-side type renderer mirrors the web app's `renderer.js`.
3. **Side-effect handler** — extension-side code that maps envelope `kind` to VSCode APIs (`showTextDocument`, `executeCommand('vscode.open')`, integrated terminal API). The webview asks the extension host to do it via existing `vscode.postMessage` channel.
4. **Smoke-test every command** in a packaged `.vsix` against `ppxai-server`.

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
- [ ] VSCode extension command dispatch mirrors the web flow.
- [ ] Every command name in web `slashCommands` and VSCode `package.json` exists in `CommandFactory` (verified by test).
- [ ] Side-effect kinds documented in this file are honored by both clients.
- [ ] All 5 commands with UI side effects work end-to-end on Web AND VSCode.
- [ ] `tests/test_command_envelope.py` + `tests/test_command_e2e_web.py` green.
- [ ] PyInstaller spec completeness test still green.

## Open questions for next session

1. Should the in-process factory call (TUI) also go through the envelope, or should the route layer be the only place that wraps? **Tentative pick:** route wraps; TUI keeps direct factory access. Less churn, no functional difference.
2. `/help` content — is the JS-side help text richer than what `system.help` returns? Need to compare and consolidate.
3. Should we add a `kind: "follow_up_chat"` side effect for commands that want to inject a chat message after rendering? (Edge case, may not need.)
