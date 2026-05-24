# Release Notes — v1.18.1

> **Scope:** Command-dispatch unification (Option A) + state-sync
> determinism (Phases A–D) + `validate_agent_task` safety gate +
> `pypdfium2` swap. 24 commits over the v1.18.0 baseline.
>
> **Tests:** 2926 passing, 0 skipped (was 2924 + 2 poppler-skipped at v1.18.0).
> 4 unrelated Perplexity-API integration failures pre-date this branch.

## Summary

Two big architectural pushes plus two scope-limited fixes.

**Architecture:**

1. **Command-dispatch unification (Option A).** Every slash command flows through `POST /command/<name>` via the Python `CommandFactory`. The pre-v1.18.1 35-case dispatchers in `ppxai/web/shared/command-dispatcher.js` (~775 LoC) and `vscode-extension/src/chatPanel.ts:handleSlashCommand` (~557 LoC) are now thin shells over the v1 wire envelope `{ok, result, side_effects, events, version}`.
2. **State-sync determinism (Phases A–D).** Engine state is canonical and observable to clients within one round-trip. Visibility/focus events trigger re-anchor; REST mutations piggyback their drained events; the file tree subscribes to `AppState`; `cwd_anchor` mismatches surface as 409s with structured recovery payloads.

**Correctness:**

3. **`validate_agent_task` shared safety gate.** Pre-v1.18.1, `/agent fix` from web users bypassed the `min_task_words` check entirely. v1.18.1 centralises validation; `/chat` and the factory both invoke it.
4. **`pypdfium2` replaces `pdf2image+poppler`.** No more system binary requirement; PyInstaller binaries are self-contained.
5. **Bonus — published binaries actually have PDF/Excel/PPTX/Gemini tooling.** Surfaced during release pre-flight: CI build jobs installed only `--extra build --extra server` (or `--extra tui`), so the `[data]` / `[gemini]` / `[search]` modules listed in spec hiddenimports silently dropped at PyInstaller time. The bug is pre-existing — server binaries since v1.17.4 have shipped with broken PDF rasterization (and v1.16.0+ with broken native Gemini, broken DDG search). v1.18.1 is the first release where shipped binaries fulfil the published feature set. Fix is `--all-extras` in every build job, mirroring the test job.

## What's new

### Command-dispatch unification

Pre-v1.18.1, the same slash command was implemented twice — once in the Python `CommandFactory` (Rich + Textual TUIs) and once in the JS dispatcher / VSCode extension. Most commands didn't actually go through `POST /command/<name>`; they hit bespoke REST endpoints (`/sessions`, `/checkpoint/list`, `/working-dir`, `/files/read`, ...) and the JS/TS clients duplicated the formatting logic. The factory and the JS/TS lists drifted — at v1.18.0, nine of ten builtin command modules were missing from the PyInstaller specs and nobody noticed for six releases because only `/usage` actually exercised the factory path.

v1.18.1's invariant: **every command flows through the factory's `POST /command/<name>`**, and the wire envelope is:

```json
{
  "ok": true,
  "result": { "...CommandResult.to_dict()..." },
  "side_effects": [{ "kind": "open_editor", "filepath": "/x" }],
  "events": [{ "type": "state_sync", "data": { "working_dir": "/x" } }],
  "version": 1
}
```

`result` is the rendered payload (TableResult, MarkdownResult, FileViewResult, etc.). `side_effects` are orthogonal UI directives. `events` are SSE-shaped state mutations drained from the engine queue (Phase B).

### `SideEffectKind` taxonomy (15 kinds)

Side-effects name the user's intent, not the rendering:

| Kind | Web rendering | VSCode delegation |
|------|---------------|-------------------|
| `open_editor` | CodeMirror panel | `vscode.window.showTextDocument` |
| `open_viewer` | iframe / xlsx-viewer | `vscode.commands.executeCommand('vscode.open')` |
| `show_image` | image panel | same |
| `show_pdf` | PDF embed | same |
| `reveal_in_explorer` | file tree highlight | `revealInExplorer` |
| `open_terminal` | xterm.js panel | `vscode.window.createTerminal` |
| `run_shell` | terminal panel + sendText | `createTerminal` + `sendText` |
| `open_html_preview` | iframe panel | existing `previewPanel.ts` WebviewPanel |
| `refresh_file_tree` | file tree refresh | `workbench.files.action.refreshFilesExplorer` |
| `set_theme` | webview CSS class | webview-only theme |
| `copy_to_clipboard` | navigator.clipboard | `vscode.env.clipboard.writeText` |
| `attach_file` | attachment chip strip | webview attachment refresh |
| `prompt_quick_pick` | popover | `vscode.window.showQuickPick` |
| `notify` | toast | `vscode.window.show*Message` |
| `vscode_delegate` | (ignored) | `vscode.commands.executeCommand(...)` |

**Open-enum invariant:** clients ignore unknown kinds gracefully. Adding a new kind is non-breaking. Taxonomy sentinel test in `tests/test_command_envelope.py::TestSideEffectKindTaxonomy` pins the v1.18.1 set.

### `prompt_quick_pick` resume protocol (ADR Q3 (b))

When an engine handler needs the user to pick one of N options, it emits `PROMPT_QUICK_PICK` with `items: [{label, value}]`. **The chosen `value` IS the literal next args.** The client re-issues `POST /command/<command_to_resume>` with `args=<chosen value>` — no server-side continuation state. Every POST is idempotent given the args.

Example: `/show @config` finds 3 matches → emits `PROMPT_QUICK_PICK` with each item's `value` set to the absolute path. User picks one → client POSTs `/command/show` with `args=<absolute path>`. Second pass takes the direct branch, returns the rendered file view.

### State-sync determinism (Phases A–D)

Pre-v1.18.1, the only path that delivered engine state changes to clients was the SSE stream inside `POST /chat`. Outside an active chat, `engine.set_working_dir()` (and similar) enqueued `state_sync` events into `engine._event_queue`, but no consumer drained the queue until the next chat opened an SSE generator. Drift symptoms: file-tree clicks against a stale cwd → 404; multi-tab divergence; tab sleep / focus restore / browser back-forward leaving the UI on the old cwd.

The fix is layered:

- **Phase A — visibility re-anchor.** Web `document.visibilitychange → visible` and VSCode `vscode.window.onDidChangeWindowState → focused` fetch `GET /state` and feed the snapshot through `AppState`. Shared `_reanchorFromServer` helper across both clients.
- **Phase B — REST piggyback.** `with_drained_events(payload, engine)` wraps state-mutating REST responses with `events: [...]` drained from `engine._event_queue`. Clients feed them through the same dispatcher that handles live SSE.
- **Phase C — file tree subscribes to AppState.** The web file tree consumes `state.workingDir` via `AppState.on()` instead of caching `_fileTreeCurrentPath`. Eliminates the 300ms debounce.
- **Phase D — `cwd_anchor` 409.** `/files/read|write|image` accept an optional `cwd_anchor`. Server returns `409 + {expected, actual, events}` on mismatch. Web file-view widgets and VSCode's `chatPanel.handleCwdAnchorMismatch` recover by draining the events and surfacing a notice.

Drift becomes named, surfaced, recoverable.

### Server-side `validate_agent_task` shared safety gate

Pre-v1.18.1, `min_task_words` validation lived only in the TUI factory path (`handle_agent`). Web users running `/agent fix` via `streamChat` hit `/chat` directly with no `/agent` awareness — the LLM-with-tools just went. A real safety gap.

v1.18.1 closes it:

1. New public helper `ppxai/commands/agent.py::validate_agent_task(task, min_words)` returns `None` for valid tasks, `NotificationResult(WARNING)` for vague ones.
2. `/chat` route gates `/agent <task>` messages before lock acquisition.
3. `handle_agent` in the factory uses the same helper.
4. Friendlier rejection: not a red `ErrorResult`, a question framed as `NotificationResult(WARNING)` with concrete examples (`/agent Fix the off-by-one in src/parser.py:line_count()`).

23 new tests in [tests/test_agent_task_validation.py](../tests/test_agent_task_validation.py).

### `/spec` rich templates ported to factory

Pre-v1.18.1, `/spec` returned a 5-line stub from the factory while VSCode had ~50-line rich templates inline. Cross-client divergence — TUI users got the stub, VSCode users got the full template, web users got nothing useful.

v1.18.1 ports the full templates (`api`, `cli`, `lib`, `algo`, `ui`) + guidelines into `ppxai/commands/system.py::handle_spec`. All four clients see identical content. VSCode's `handleSpecCommand` is gone.

### `pypdfium2` replaces `pdf2image+poppler`

`pdf2image` shells out to `pdftoppm` from poppler — a system binary that isn't installed on every dev/CI machine, isn't bundled with PyInstaller output, and silently breaks released binaries on machines without it. The 2 poppler-dependent tests in `test_pdf_tools.py` were skipped on dev machines and the published binaries had been silently broken for poppler-less users.

`pypdfium2` 5.7+ replaces both:

- `GetPdfPageImageTool`: `convert_from_path` → `PdfDocument + page.render`
- `SummarizePptxVisualTool` slide rasterizer: subprocess `pdftoppm` → `PdfDocument` iteration

`pypdfium2` is pure-wheel bindings to Google's PDFium (the renderer in Chrome). License: BSD-3 OR Apache-2.0 — permissive, no AGPL drag. Wheels for Linux/macOS/Windows on PyPI. PyInstaller binaries are now truly self-contained.

### CI build jobs install `--all-extras` (pre-existing fix)

Surfaced during the v1.18.1 release pre-flight audit, but the bug pre-dates this branch. CI build jobs installed `--extra build --extra server` (or `--tui`), but `ppxai-server.spec` lists `pypdf`, `pypdfium2`, `openpyxl`, `python-pptx` (the `[data]` extras), `google.genai` (`[gemini]`), and `ddgs` (`[search]`) in hiddenimports. PyInstaller's contract for hidden imports: a name not importable in the build env logs a warning and the build succeeds with the module missing. So the published binaries since v1.17.4 silently shipped without the [data] tooling, since v1.16.0 without native Gemini, and since whenever `[search]` landed without DDG search.

The runtime impact is graceful — users get "pdf2image is not installed" instead of a crash — so the bug went undetected for six releases.

Fix: every PyInstaller job in `.github/workflows/build.yml` now uses `uv sync --frozen --all-extras`, matching the test job. Adds <2s to install steps and ensures the build venv covers every spec's hiddenimports + every dynamic import in the command-loading and file-preprocessing chains.

`uv.lock` was also stale after the pypdfium2 swap — regenerated in the same commit.

## Architecture docs

Two new "Critical Architecture Pattern" sections in [CLAUDE.md](../CLAUDE.md), added during the work:

- §"Critical Architecture Pattern: Command Dispatch via Envelope (v1.18.1)" — the dispatch flow, side-effect kinds, the `prompt_quick_pick` resume protocol, the rules.
- §"Critical Architecture Pattern: State-Sync Determinism (v1.18.1)" — the four channels (SSE during chat, `/state` snapshot on demand, REST piggyback, `cwd_anchor` mismatch), the rules.

First ADR: [docs/decisions/0001-keys-command-cross-client.md](decisions/0001-keys-command-cross-client.md) — establishes the ADR convention and pins the cross-client routing for `/keys`.

## Test coverage

Major test additions:

| Suite | New tests | Purpose |
|-------|----------:|---------|
| [test_command_envelope.py](../tests/test_command_envelope.py) | 21 | v1 envelope shape, side-effect taxonomy sentinel, handler emission |
| [test_rest_event_piggyback.py](../tests/test_rest_event_piggyback.py) | ~15 | Phase B drain helper + per-route integration |
| [test_files_cwd_anchor.py](../tests/test_files_cwd_anchor.py) | ~20 | Phase D 409 path on /files/read|write|image |
| [test_web_command_dispatcher_v18_1.py](../tests/test_web_command_dispatcher_v18_1.py) | ~10 | Web dispatcher shape + drain |
| [test_web_cwd_anchor_client.py](../tests/test_web_cwd_anchor_client.py) | ~12 | Web's `handleCwdAnchorMismatch` |
| [test_agent_task_validation.py](../tests/test_agent_task_validation.py) | 23 | Cross-client agent-task validation gate |
| [test_vscode_step5a_helpers.py](../tests/test_vscode_step5a_helpers.py) | ~25 | sideEffectsHandler.ts + commandRenderer.ts contracts |
| [test_vscode_visibility_reanchor.py](../tests/test_vscode_visibility_reanchor.py) | ~6 | Phase A re-anchor parity |
| [test_vscode_step5b2_dispatcher.py](../tests/test_vscode_step5b2_dispatcher.py) | 26 | VSCode dispatcher shape, removed-handler tombstones |
| [test_vscode_step5c_state_sync.py](../tests/test_vscode_step5c_state_sync.py) | 20 | VSCode Phase B + D wiring + cross-client parity |
| [test_server_smoke_e2e.py](../tests/test_server_smoke_e2e.py) | 2 | Spawned-server smoke for envelope events + 409 |

**Suite: 2926 passing, 0 skipped** (was 2924 + 2 poppler-skipped at v1.18.0). 4 unrelated Perplexity-API integration failures pre-date this branch.

## Deferred to v1.18.2

- **Agent loop unification across HTTP clients.** Validation unified in v1.18.1; the loop body still runs client-side in VSCode and via the streaming `/chat` path on web because factory's `handle_agent` is TUI-shaped (`asyncio.run`, `console.print`). [docs/archive/TODO-v1.18.2-agent-loop-unification.md](archive/TODO-v1.18.2-agent-loop-unification.md) tracks the work.
- **`prompt_text` side-effect kind** for free-text follow-ups when `prompt_quick_pick`'s finite-choice shape doesn't fit. [docs/archive/TODO-v1.18.2-prompt-text-kind.md](archive/TODO-v1.18.2-prompt-text-kind.md).

## Upgrade notes

- **For library consumers:** the v1 envelope adds an `events` field. Code that reads `body.result` works unchanged. Code that did `set(body.keys()) == {"ok", "result", "side_effects", "version"}` needs the 5-key set `{"ok", "result", "side_effects", "events", "version"}`.
- **For PyInstaller-binary users:** poppler is no longer needed. Existing installs continue to work; `pip install 'ppxai[data]'` now pulls `pypdfium2` instead of `pdf2image`.
- **For web/VSCode clients:** any custom integration that issued raw `POST /command/<name>` requests should switch to consuming the v1 envelope (`{ok, result, side_effects, events, version}`).

## Commits

```
3e536f69 feat(pdf): swap pdf2image+poppler for pypdfium2 — pure-wheel, no system binary
c5e067fe test(e2e): drift simulation + piggyback drain via real spawned server (Step 6)
8b656e1f feat(vscode): REST piggyback drain + cwd_anchor 409 helper (5c, Phase B + D)
65eb7b8e feat(vscode): rewrite chatPanel dispatcher as thin shell over factory envelope (5b.2)
09f35124 feat(server): port spec templates + shared agent-task validation (5b.1)
4c1dcf50 feat(vscode): typed v1 envelope + sideEffectsHandler/commandRenderer modules (5a)
d245eec1 feat(server,web): cwd_anchor + 409 conflict for stale-relpath drift
42119ee7 feat(web): file-tree subscribes to AppState; drop _fileTreeCurrentPath cache
1a2a947c feat(web): rewrite command-dispatcher as thin shell + drain envelope events[]
2333e627 feat(web): add shared/result-renderer.js + shared/side-effects.js modules
1ba8e315 feat(server): with_drained_events helper + apply to state-mutating REST endpoints
f27175fc docs(v1.18.1): capture command-envelope + state-sync patterns mid-flight
068c5c97 feat(vscode): onDidChangeWindowState re-anchor for AppState (parity with web)
a81d686d feat(web): visibilitychange re-anchor + shared _reanchorFromServer helper
375b4ad0 feat(commands): reconcile /help — factory is canonical, branches on context
9f310e05 feat(commands): wire side-effects for the 7 web-unreachable factory commands
ca20cb40 feat(commands): @query fuzzy search with PROMPT_QUICK_PICK on multiple matches
7fa21364 feat(commands): /show emits OPEN_VIEWER for FileViewResult branches
6fe59908 feat(commands): add /edit handler in factory with prompt_quick_pick on missing file
fdd6a238 feat(commands): SideEffectKind constants + v1.18.1 taxonomy sentinel
4991b382 refactor(commands): rename + split SideEffect kinds for v1.18.1 taxonomy
f2ebd3c9 docs(adr): introduce decision-record convention; ADR 0001 for /keys cross-client
331d3a4e docs(v1.18.1): state-sync determinism plan + side-effect taxonomy refinements
2729796b feat(v1.18.1): Phase 1 — command-dispatch envelope + side-effects + server smoke test
```
