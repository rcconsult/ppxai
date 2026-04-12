# Release Notes — v1.17.4

## Summary

**File Upload & Multimodal Attachments** — complete end-to-end support for attaching images, PDFs, Excel spreadsheets, PowerPoint presentations, and text/code files to AI conversations across all four ppxai clients (Rich TUI, Textual TUI, Web App, VSCode Extension).

Users can attach files via `/attach` (Rich/Textual), drag-drop (Web), file picker (Web/VSCode), or file tree `a` key (Textual). Files are validated, preprocessed per type and model capability, stored efficiently via content-addressed SessionFileStore, and sent to vision-capable AI models as multimodal content. Session save/load round-trips attachments via compact file_id references — session JSON stays small while binary bytes live on disk.

## Features

### File Upload Pipeline (Phases 0-3)
- **Multimodal message plumbing** — `Message.content` widened to `Union[str, List[Dict]]` across all 4 clients + providers. Gemini image_url → inline_data conversion. 16 str-assuming call sites fixed.
- **`/attach <path...>`** slash command with inline iTerm2/Sixel image preview, `📎` status bar badge, path autocomplete with directory traversal
- **`/attach remove <name>`** and `/attach remove all` to evict committed attachments from session history (stops re-sending and re-billing)
- **SessionFileStore** — content-addressed binary storage with staging → session directory lifecycle. Dual-format sessions: flat `.json` for text-only, directory with `uploads/` for multimodal.
- **File preprocessing dispatcher** — `preprocess_file()` routes images/text/PDF/Office per model vision capability with magic-byte sniffing, provider-aware size limits (5-50 MB per provider), and dimension-based token cost estimation
- **Server `POST /chat`** accepts `files[]` array for web/VSCode multimodal uploads
- **SSE `state_sync`** pushes `context_attachments` to all connected clients automatically

### AI Tools (Phase 2.8, 4)
- **PDF tools** — `read_pdf` (text extraction by pages, range selector, 100KB truncation) and `get_pdf_page_image` (page rasterization to PNG data URI via pdf2image/poppler)
- **Excel tools** — `list_excel_sheets` (sheet names + dimensions + header preview) and `read_excel_sheet` (markdown table or CSV output with row limiting)
- **PPTX tools** — `list_pptx_slides` (slide inventory with shape type counts), `read_pptx_slide_text` (text + tables as markdown), `render_pptx_slide` (slide → PNG via LibreOffice headless), `summarize_pptx_visual` (all slides → VL model captions in one call)
- **Word tools** — `read_docx` (text extraction via stdlib zipfile + xml.etree, no python-docx dependency)
- **CSV tools** — `read_csv` (row ranges, column filtering, markdown/CSV output) and `list_csv_columns` (column names, types, row count). Large CSVs (>50KB) lazy-loaded via SessionFileStore instead of inlining

### Model & Config Management (Phase 2.3-2.7)
- **`supports_vision` flag** on ModelProfile — set for GPT-5.x, GPT-4.x, Gemini 2.5/3/3.1, Gemma 4, Sonar/Sonar Pro, and local VL models (qwen3-vl, llava, pixtral, minicpm-v)
- **Gemma 4 family** added — 31B dense, 26B MoE, E4B edge, E2B edge. Free tier via Gemini API. Vision + audio capable.
- **Gemini 3.1 Flash Lite** added — cheapest Gemini 3 tier
- **Deprecation tracking** — gemini-3-pro-preview removed (shut down 2026-03-09), 2.0/2.5 models flagged with shutdown dates
- **`/doctor`** — read-only config advisor scanning for dead/deprecated/new models with days-remaining countdowns and migration recommendations
- **VL sidecar config** — `tools.vision_model` section for auto-captioning images on text-only models via an external VL endpoint

### Cross-Client Features (Phases 5-7)
- **Web app** — paperclip button, drag-drop zone, attachment badges strip, send with files via POST /chat
- **Web preview** — PDF (Blob URL + iframe), Excel (SheetJS + DataTableViewer with sort/filter/pagination), PPTX (slide navigator with LibreOffice-rendered images), resizable split panel
- **VSCode extension** — webview file picker, drag-drop with overlay, image thumbnail badges, inline attachment display in messages, context attachments badge, dynamic autocomplete via `POST /complete` (56+ commands, path args, @file refs)
- **Textual TUI** — file tree `a` key to attach, `Ctrl+U` shortcut, send integration with multimodal content, footer StatusBar badge
- **AppState `context_attachments`** — canonical cross-client field pushed via SSE state_sync. All 4 clients subscribe to it for their attachment badge/chip UI. Clickable badge opens file preview.

### Autocomplete — unified across all 4 clients (Phase 1 + Task #11 + parity rollout)

`ppxai/engine/completion.py` is now the **single source of truth** for
autocomplete across Rich TUI, Textual TUI, Web, and VSCode. Rich and
Textual call it in-process; Web and VSCode reach it via `POST /complete`.
All client-side subcommand tables were deleted — the engine owns them.

**Completion sources (all clients, all triggers)**
- **Slash command names** — live `CommandFactory` reader with aliases (`/att` → `/attach`), hidden-command filtering, and builtin specials (`/quit`, `/exit`). Replaces the pre-v1.17 27-entry hardcoded list; now 56+ entries, auto-discovered.
- **Shell-style path arguments** — `/attach`, `/cd`, `/ls`, `/tree`, `/show`, `/preview` with per-command file/dir filters, alias resolution, hidden-file opt-in, sub-path navigation.
- **Subcommands** — `/tools`, `/usage`, `/checkpoint`, `/status`, `/theme` with both first-level args (`/tools en` → `enable`) and second-level args (`/usage show <mode>`, `/theme emoji on/off`, `/checkpoint backend <backend>`, `/tools help <tool>`).
- **Dynamic `/model <name>`** — reads from the active provider's config so typing `/model gpt-4` surfaces the matching models.
- **Dynamic `/provider <name>`** — reads from `PROVIDERS` so the list matches whatever is configured.
- **`@file` references + context providers** — `@git`, `@tree`, `@clipboard`, `@url` appear alongside filesystem matches in one unified dropdown.

**Architectural cleanup**
- **Rich `PPXAICompleter`**: ~594 lines → ~85 lines. Deleted `_get_commands()` cache (dead code), `_get_files()`, `_get_model_names()`, `_get_provider_names()`, `_get_tool_names()`, `_PATH_ARG_COMMANDS`, `TOOLS_SUBCOMMANDS`, `THEME_NAMES`, `USAGE_SUBCOMMANDS`, `CHECKPOINT_SUBCOMMANDS`, `STATUS_SUBCOMMANDS`, `USAGE_DISPLAY_MODES`, `CHECKPOINT_BACKENDS`, `IGNORE_DIRS`, `_BUILTIN_SPECIAL_COMMANDS`. Hoisted both lazy imports to module top (no more `TYPE_CHECKING`-style dodges).
- **Textual `TextualCompleter`**: ~238 lines → ~100 lines. Same pattern as Rich — all subcommand tables and dynamic lookup helpers deleted.
- **VSCode webview**: unified `@` and `/` triggers onto a single `POST /complete` path. Retired `handleSearchFilesForAutocomplete` in `chatPanel.ts` and the `fileSuggestions` webview message type. `selectAutocompleteItem` simplified to one code path using `replace_start` for everything. New `kind → icon` map (📁 dir, 📄 file, 🏷️ context_ref, 🔗 alias, 🔧 tool, 🤖 model, 🌐 provider, 🎨 theme, ▸ subcommand, ⌘ command). Dead state vars (`autocompleteMode`, `autocompleteDisabled`, `autocompleteStartPos`, `autocompleteQuery`) removed.
- **Web**: no code change needed — already consuming `POST /complete` correctly. New subcommand / model / provider / context-provider items flow through automatically via the existing `replace_start` + `kind` dispatch.
- **Server route**: `POST /complete` now passes `current_provider` and live `tool_names` from `s.engine.tool_manager.list_tools()` so `/tools help <tab>`, `/model <tab>`, and `/provider <tab>` work for Web and VSCode with the same fidelity Rich + Textual already had.

**Stable JSON schema** (relayed unchanged by the server to HTTP clients):
```
{
  "text":          str,   # text to insert
  "display":       str,   # dropdown label
  "description":   str,   # meta/hover text
  "kind":          str,   # command|alias|dir|file|file_ref|context_ref
                          # |subcommand|tool|model|provider|theme
  "replace_start": int    # negative offset from cursor
}
```

**Tests**
- `tests/test_completion_provider.py`: 21 → **39 tests** (+18). New classes: `TestContextProviderCompletion`, `TestSubcommandCompletion`, `TestDynamicCompletion`.
- Deleted stale `TestDynamicCommandList` + `TestCacheInvalidation` in `tests/test_completer_dynamic.py` — those pinned the Rich-internal cache that's now dead code. Equivalent coverage exists in `test_completion_provider.py`.
- Full suite: **2288 passing, 2 skipped, zero regressions** (includes +22 tests from the schema DTO rewrite — see below: 12 new in `TestSchemaDTO` / `TestAppStateFieldCoverage` and 10 new in `tests/test_schema_endpoint.py`).

### Schema-driven cross-language AppState (golden source of truth)

**Problem.** The web (`ppxai/web/app.js::handleStateSync`) and VSCode
(`vscode-extension/src/chatPanel.ts` `state:sync` handler) used to
maintain hand-written 10-entry `keyMap`s for Python snake_case →
JS/TS camelCase translation on incoming SSE `state_sync` events, with
a `|| pyKey` fallback that silently masked contract drift. If a new
field landed in `_SSE_SYNC_FIELDS` (Python) without matching updates
to both client keyMaps, the field would fall through:
- **Web**: the `AppState` Proxy silently stored the snake_case key
  as a new property, so the UI's camelCase accessors kept showing
  stale data.
- **VSCode**: `AppState.update()` silently dropped unknown keys via
  its `if (key in this._data)` guard — worse, state simply didn't
  advance.

Neither client warned. Adding a new cross-client field was a silent
landmine waiting to ship broken. Even worse, Python, Web, and VSCode
each had their own hand-maintained schema definition, creating three
places that could drift independently.

**Fix — one JSON DTO, loaded by every client at startup.**

The canonical AppState schema is now a single JSON file:
`ppxai/engine/app_state_schema.json`. Every canonical field, its
Python snake_case name, its JS/TS camelCase name, its type, and its
default value are declared once in this file. Python, Web, and
VSCode all load the same schema at startup and derive their field
maps from it. **There are zero hand-maintained parallel schemas.**

**The golden source of truth:**

```json
{
  "version": "1.0",
  "fields": {
    "provider":            {"client": "currentProvider",  "type": "string",  "default": "",    "group": "core"},
    "tools_enabled":       {"client": "toolsEnabled",     "type": "boolean", "default": false, "group": "features"},
    "context_attachments": {"client": "contextAttachments", "type": "array", "default": [],    "group": "multimodal"},
    ...18 entries total
  }
}
```

**Per-client loading:**

| Client | Loading mechanism | Sync/async |
|---|---|---|
| **Python** (`ppxai/engine/app_state.py`) | `importlib.resources.files("ppxai.engine") / "app_state_schema.json"` parsed at module import. `AppState.FIELDS` is derived. | Sync at import |
| **Web** (`ppxai/web/shared/app-state.js`) | `window.APP_STATE_SCHEMA` injected into `index.html` by `ppxai/server/routes/static.py::serve_index` before `shared/app-state.js` runs. `AppState` constructor reads the global. | Sync at module load |
| **VSCode** (`vscode-extension/src/appState.ts`) | `fs.readFileSync()` of `../resources/app-state-schema.json` at module init. The bundled copy is kept in sync with the Python source by `scripts/sync-schema.js` running as a `precompile` hook in `package.json`. | Sync at module load |

**Golden-source chain:**

```
   ppxai/engine/app_state_schema.json   ← canonical, commit this
                 │
       ┌─────────┼─────────┐
       ▼         ▼         ▼
   Python      Web       VSCode
   AppState   AppState   AppState
       │         │         │
       │         │         ▼
       │         │     resources/app-state-schema.json (bundled)
       │         │         │
       │         │     sync-schema.js (precompile hook)
       │         │         │
       │         │         └── byte-equality enforced by test
       │         │
       │         ▼
       │     HTML injection via server/routes/static.py
       │         │
       │         └── window.APP_STATE_SCHEMA global
       │
       ▼
   GET /schema/app-state  (diagnostic endpoint, server/routes/schema.py)
```

**Adding a new field now takes one edit to one file.** Update
`app_state_schema.json`, bump the sentinel test in
`tests/test_app_state.py::TestSchemaDTO::test_schema_has_fields_dict`,
and everything else propagates automatically:
- Python's `AppState.FIELDS` picks it up at next import
- The server's `/schema/app-state` endpoint returns it
- The server injects the new schema into `index.html` on next page load
- The web `AppState` reads it from `window.APP_STATE_SCHEMA` on next page load
- `scripts/sync-schema.js` copies the updated JSON to VSCode's `resources/`
- The VSCode `AppState` picks it up on next extension activation

The only manual edit left is the VSCode `AppStateFields` TypeScript
interface, which is hand-maintained as **type documentation only**
(the schema doesn't produce a TS interface at runtime). The v1.18.x
schema generator will automate even that step.

**Drift detection is now architectural, not accidental:**

1. `TestSchemaDTO::test_vscode_bundled_copy_matches_canonical` does
   byte-for-byte equality between `ppxai/engine/app_state_schema.json`
   and `vscode-extension/resources/app-state-schema.json`. CI fails
   if someone edits one without running `npm run sync-schema`.
2. `TestSchemaDTO::test_every_field_has_required_properties` pins
   the schema format — `client`, `type`, `default`, `group` must all
   be present on every field.
3. `TestSchemaDTO::test_field_defaults_match_declared_type` catches
   mismatches between a field's declared type and its default value
   (e.g. `{"type": "boolean", "default": 0}` would fail).
4. `TestSchemaDTO::test_field_names_are_snake_case` and
   `test_client_names_are_camel_case` pin the naming contract.
5. `TestSseSyncFieldsContract::test_sync_fields_have_client_names_in_schema`
   ensures every `_SSE_SYNC_FIELDS` entry has a matching schema entry
   (so the facades can translate it).
6. Runtime drift warnings in both `updateFromPython()` implementations
   fire if the server pushes a field not in the current schema —
   which would mean server and client are running different ppxai
   versions.

**Call sites stay small:**

```js
// web/app.js :: handleStateSync
this.state.updateFromPython(changes);  // single cross-language call
// ... plus existing DOM side-effect dispatch
```

```ts
// chatPanel.ts :: state:sync handler
const mapped = this._appState.updateFromPython(changes);
postMessage({ type: 'stateSync', changes: mapped });
```

**Files:**
- `ppxai/engine/app_state_schema.json` — new, canonical source (18 fields)
- `ppxai/engine/app_state.py` — `FIELDS` now derived via
  `_build_fields(SCHEMA)`; `AppState.SCHEMA` exposed for the server
  endpoint and tests; mutable defaults cloned per instance
- `ppxai/server/routes/schema.py` — new, `GET /schema/app-state`
  returns the canonical schema as JSON (registered in
  `server/routes/__init__.py`)
- `ppxai/server/routes/static.py` — `serve_index` rewritten to
  inject `<script>window.APP_STATE_SCHEMA = {...}</script>` into
  `index.html` before the `shared/app-state.js` tag
- `ppxai/web/shared/app-state.js` — rewritten to read the schema
  from `window.APP_STATE_SCHEMA` at construction, derive
  `_pythonToJs` and defaults dynamically, expose `jsToPython`
  inverse lazily
- `vscode-extension/src/appState.ts` — rewritten to load the
  bundled schema via `fs.readFileSync`, derive `PYTHON_TO_TS` +
  defaults at module init, expose `TS_TO_PYTHON` inverse
- `vscode-extension/resources/app-state-schema.json` — new,
  bundled copy of the canonical source (kept in sync by
  `scripts/sync-schema.js`)
- `vscode-extension/scripts/sync-schema.js` — new, copies the
  canonical JSON into `resources/` with JSON validation; runs
  via `precompile` and `prewatch` hooks in `package.json`
- `vscode-extension/package.json` — added `sync-schema`,
  `precompile`, `prewatch` script entries
- `tests/test_app_state.py` — added `TestSchemaDTO` class (10
  tests) pinning schema format and VSCode bundled-copy equality;
  added `TestAppStateFieldCoverage::test_mutable_defaults_not_shared_between_instances`
  to catch the mutable-default leak; updated
  `TestSseSyncFieldsContract` to reference the schema-driven facades
- `tests/test_schema_endpoint.py` — new, 10 tests covering the
  `GET /schema/app-state` endpoint and the HTML schema injection
  pipeline

**Behaviour change:** none for end users. The 10 fields the server
pushes via `_SSE_SYNC_FIELDS` are unchanged. What changed is the
architecture: there's now one canonical schema instead of three, and
adding a field means editing one file.

## Bug Fixes
- **`/save <name>` now honors the name argument** — was silently ignoring the user's chosen name
- **`/save` warns about unsent attachments** — staged files from `/attach` that haven't been sent yet are not included in the save; the user gets a clear warning
- **`/ls <file>` shows file entry** — matches shell `ls` semantics; was returning "Not a directory" error
- **Image validation rejects fake images** — a .png file containing non-image bytes is caught at attach time with a clear "Unrecognized image format" error
- **Terminal PTY on Windows** — server no longer crashes on Windows due to Unix-only `fcntl`/`pty`/`termios` imports; WebSocket endpoint returns clear error
- **ppxai-desktop version reporting** — PyInstaller spec now includes `ppxai.version` hidden import; frozen binary reports correct version

## Dependencies

**Python (pip):**
- `pypdf>=4.0` — PDF text extraction
- `pdf2image>=1.17` — PDF page rasterization
- `openpyxl>=3.1` — Excel reading
- `python-pptx>=1.0` — PowerPoint reading

All in the `[data]` optional extras group: `pip install 'ppxai[data]'`

**System (apt):**
- `poppler-utils` — `pdftoppm` for PDF page rasterization (required by `pdf2image`)
- `libreoffice-nogui` — PPTX/DOCX slide rendering via headless mode (required by `render_pptx_slide`, `summarize_pptx_visual`)

**JavaScript (web app):**
- `xlsx.full.min.js` (SheetJS, 930KB, Apache 2.0) — client-side Excel parsing for split panel preview

## K8s Deployment (coder)

- **Dockerfile** includes `[data]` extras + system packages
- **Data persistence** — `PPXAI_DATA_DIR=/workspace/.ppxai` on Retain PVC
- **PV affinity** — `SessionMeta.workspace_pv` prevents PVC mis-binding
- **deploy.sh** — namespace pre-creation, Reflector secret recovery, API key auto-creation
- **Ingress** — `proxy-body-size: 50m` for file uploads
- **VL sidecar** — Qwen3-VL-8B for `summarize_pptx_visual` and image auto-captioning

## Test Coverage
- **Starting point:** 1,753 tests
- **Final count:** 2,253 tests (2,201 passing + 7 skipped in local env; additional tests for PPTX render, CSV, Word)
- **New tests:** 500
- **Regressions:** 0
- **Skipped:** 7 (poppler-dependent, platform-specific, optional deps)
