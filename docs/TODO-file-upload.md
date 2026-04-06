# TODO: File Upload & Data Processing

**Status:** In Progress — Phases 0, 1, and 2 complete
**Target:** v1.17.4
**Branch:** `feat/file-upload`
**Priority:** High — enables data analyst workflows (Excel, PDF, PPTX)
**Research:**
- `docs/ppxai-file-upload-data-processing.md` — design & preprocessing architecture
- `docs/multimodal-api-models-reference.md` — provider vision/multimodal capability matrix

---

## Progress Log

| Phase | Status | Notes |
|-------|--------|-------|
| **Phase 0** — Multimodal message plumbing | ✅ Complete | `Message.content: Union[str, list[dict]]` + `text_content()` helper; all 4 clients + providers updated; 16 str-assuming call sites fixed |
| **Phase 1** — Rich TUI `/attach` + multimodal rendering | ✅ Complete | `/attach <path...>` slash cmd, inline image preview via iTerm2/Sixel, `EngineClient.chat(MessageContent)` widened, interactive-verified against Perplexity Sonar Pro |
| **Phase 1 Follow-up** — AppState `context_attachments` promotion | ✅ Complete | Cross-client canonical field, `SessionManager.on_messages_changed` callback, `EngineClient._refresh_context_attachments()`, persistent status-bar badge. **Pattern to replicate for ppxaide/server/web/VSCode.** |
| **Phase 1 Follow-up** — Dynamic autocomplete | ✅ Complete | Replaced hardcoded 27-entry `COMMANDS` list with dynamic `CommandFactory` reader (55 entries); shell-style path-argument completion for `/attach`/`/cd`/`/ls`/`/tree`/`/show`/`/preview` with files-vs-dirs discrimination and alias resolution |
| **Phase 2** — Engine foundation | ✅ Complete | SessionFileStore (2.1/2.1a), `/attach remove` (2.1b), file preprocessing (2.2), Gemini/Gemma 4 models (2.3), `/doctor` config advisor (2.4), `supports_vision` (2.5), image validation (2.6), VL sidecar (2.7), PDF tools (2.8), `[data]` deps (2.9). Plus `/save` name fix + `/ls` file support. |
| **Phase 3** — Server API | ⏳ Next | `ChatRequest.files[]`, preprocessing in chat route, `state_sync` SSE for `context_attachments` |
| **Phase 4** — Excel + PPTX tools | 📋 Planned | |
| **Phase 5** — Web client | 📋 Planned | Drag-drop + AppState chips |
| **Phase 6** — VSCode client | 📋 Planned | Webview picker + AppState chips |
| **Phase 7** — Textual TUI | 📋 Planned | File tree attach + footer badge |
| **Post-Phase-7** — Command completion parity | 🕒 Deferred | Extract `CompletionProvider` to engine layer, add `POST /api/complete` server route, wire Textual Suggester + web/VSCode JS dropdowns. Orthogonal to file upload — ships after `feat/file-upload` merges. Tracked as Task #11. Design doc in conversation history (2026-04-05). |

**Tests:** 2179 passing (was 1753 before Phase 0). **426 new tests** across
Phases 0-2, zero regressions. 2 poppler-dependent tests deliberately skipped.

---

## Architectural Patterns Established

Two patterns landed during Phase 1 that every subsequent phase must follow.
Skipping them causes client drift and code duplication.

### Pattern 1: Cross-client state goes through AppState

Any piece of state that more than one client needs to render or react to must
live in `ppxai/engine/app_state.py::AppState.FIELDS`, with:

1. **Stable JSON-serializable schema** — plain dicts, not dataclasses. The
   field round-trips through SSE `state_sync` events unchanged to
   `ppxai/web/shared/app-state.js` and `vscode-extension/src/appState.ts`
   which mirror the same field names in camelCase.
2. **Engine-owned invalidation** — `EngineClient` recomputes on mutation via
   a session callback (`SessionManager.on_messages_changed` is the
   established pattern — add analogous callbacks for other mutable stores).
3. **No client-side scanning** — clients read `state.get("field_name")` or
   subscribe via `state.on("field_name", listener)`. They never iterate
   `session.messages` (or equivalent) themselves.
4. **Equality-dedup** — `AppState.set()` short-circuits when the new value
   equals the old, so callbacks stay quiet on no-op mutations (e.g., text
   turns added during a multimodal conversation don't spam `state_sync`
   events for unchanged `context_attachments`).
5. **Defensive copies** — public getters return copies so caller mutation
   can't corrupt the canonical state.

Worked example: `AppState.context_attachments` (v1.17.4 Phase 1) — entry
schema `{name, kind, media_type, turn_index}`, invalidated via
`session.on_messages_changed → EngineClient._refresh_context_attachments`,
subscribed from the Rich status bar. Tests: `test_context_attachments_state.py`.

### Pattern 2: Command registration is the source of truth

`CommandFactory._registry` is the only authoritative list of slash commands.
Anything that enumerates commands (help text, completion, documentation
generators) must read from it dynamically. Hardcoded lists always drift.

Worked example: `PPXAICompleter._get_commands()` — reads
`CommandFactory._registry` + `CommandFactory._aliases` on each tab press
(cached by registry size for O(1) lookups), includes `_BUILTIN_SPECIAL_COMMANDS`
for the two commands the factory doesn't own (`/quit`, `/exit`), filters
out hidden commands, annotates aliases with their canonical target. Tests:
`test_completer_dynamic.py`.

---

## Overview

Add file upload support across all ppxai clients. Users attach files (PDF, Excel,
PPTX, images, text/code) to chat messages. Files are preprocessed per type and
model capability — text files inline, PDFs/Office as session-stored references with
lazy tool-based extraction, images via native vision or auto-captioning.

### Design Principles

- **Rich TUI first** — most constrained client; if it works here, other clients are easier
- **Lazy extraction** — files stored in session, model calls tools to read content
- **Model-driven** — structural inventory tools first, selective deep read second
- **Scoped dependencies** — `[data]` optional group, tools self-register when deps available
- **All clients** — Rich TUI (slash cmd) → Web (drag-drop) → VSCode (picker) → Textual TUI (file tree)

### Implementation Order

| Phase | Scope | What |
|-------|-------|------|
| 0 | Engine | Multimodal message plumbing — `Message.content` Union type, provider + client fixes ✅ |
| 1 | Rich TUI + Engine | `/attach` command, inline image display, multimodal message rendering, **AppState `context_attachments` field**, dynamic autocomplete ✅ |
| 2 | Engine | SessionFileStore, **`context_attachments` schema migration (2.1a)**, **`/attach remove` (2.1b)**, preprocessing, Gemini/Gemma 4 models, vision config, PDF tools ✅ |
| 3 | Server | `ChatRequest.files[]`, preprocessing in chat route, **`context_attachments` in `state_sync` SSE (3.3)** |
| 4 | Engine | Excel + PPTX tools |
| 5 | Web | Drag-drop, file picker, staging chips, **`contextAttachments` AppState mirror + persistent chips (5.4)** |
| 6 | VSCode | Webview picker, context menu attach, **`contextAttachments` AppState mirror + webview chips (6.3)** |
| 7 | Textual TUI | File tree attach, Ctrl+U, staging badge, **footer `context_attachments` badge via observer (7.4)** |

**Bolded sub-steps** were added after the Phase 1 follow-up promoted
`context_attachments` to AppState. The promotion made the cross-client
wiring mechanical — each client now just subscribes to one field instead
of re-implementing its own attachment tracker.

---

## Phase 0: Multimodal Message Plumbing

**Prerequisite for all file upload work.** Current `Message.content` is `str`-only,
and all provider message converters assume text. Must widen the type and update
providers before image/multimodal content parts can flow through the system.

### 0.1 Widen Message Type

- [x] Update `Message.content` in `ppxai/engine/types.py`
  - Change `content: str` → `content: Union[str, List[Dict[str, Any]]]`
  - OpenAI multimodal format: `[{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]`
  - Add helper: `Message.text_content() -> str` — extracts text from either format (for logging, session display, token estimation fallback)

### 0.2 Update BaseProvider._convert_messages()

- [x] In `ppxai/engine/providers/base.py`: pass `m.content` as-is (str or list)
  - Currently: `msg = {"role": m.role, "content": m.content}` — already works if content is list
  - Audit all callers that read `m.content` expecting str — use `text_content()` helper

### 0.3 OpenAI + Perplexity — Verify Pass-Through

- [x] `openai_compat.py`, `openai_native.py`, `perplexity.py` — SDK accepts multimodal natively
  - Token estimation in `openai_compat.py` already handles `list[dict]` content (lines 123-127)
  - Verify: no string coercion on content between `_convert_messages()` and `client.chat.completions.create()`
  - Test: send a message with `image_url` content part to GPT-5.x, confirm image is received

### 0.4 Gemini — Content Part Conversion

- [x] Update `GeminiProvider._convert_messages()` in `ppxai/engine/providers/gemini.py`
  - String content → `[{"text": m.content}]` (unchanged)
  - List content → convert each part:
    - `{"type": "text", "text": "..."}` → `{"text": "..."}`
    - `{"type": "image_url", "image_url": {"url": "data:mime;base64,DATA"}}` → `{"inline_data": {"mime_type": "mime", "data": "DATA"}}`
  - System messages: extract text only (Gemini system_instruction is text-only)

### 0.5 Session & Engine — Fix str-Assuming Call Sites (~17 locations)

- [x] `ppxai/engine/session.py` — 6 locations
  - Lines 183, 217, 233, 241, 253: `len(msg.content)` → `len(msg.text_content())`
  - Line 672: markdown export `f"### {role}\n\n{msg.content}"` → use `text_content()`
- [x] `ppxai/engine/session_ops.py` — 3 locations
  - Line 89: `last_assistant_msg = msg.content` → `msg.text_content()` (written to file)
  - Line 130: `sum(len(m.content) for ...)` → `sum(len(m.text_content()) for ...)`
  - Line 169: `injection_pattern.sub('', msg.content)` → apply regex to `text_content()` only, or iterate text parts in list
- [x] `ppxai/engine/chat.py` — 2 locations
  - Line 899: `m.content for m in ...` → `m.text_content()`
  - Line 900: `if m.content` truthy check → `if m.text_content()`
- [x] `ppxai/engine/providers/openai_native.py` — 1 location
  - Line 684: `instructions_parts.append(m.content)` for system msgs → `m.text_content()` (system prompts are always text)
- [x] `ppxai/engine/providers/gemini.py` — 1 location
  - Line 461: `system_parts.append(m.content)` → `m.text_content()` (system_instruction is text-only)
- [x] `ppxai/common/logger.py` — 2 locations
  - Lines 231, 239: `msg.content[:80].replace('\n', '\\n')` → `msg.text_content()[:80].replace(...)`
- [x] `ppxai/server/streaming.py` — 2 locations
  - Lines 149, 210: `len(removed.content)` → `len(removed.text_content())`

### 0.6 Session Serialization — External File References

**Decision:** Binary multimodal content (images, PDFs) stored as external files alongside
the session JSON, not base64-inlined. Keeps session JSON small and fast to parse.

**Session storage format:**
```
~/.ppxai/sessions/
├── session_20260404_103000.json              # text-only session (unchanged, backward compat)
├── session_20260404_120000/                  # multimodal session (directory)
│   ├── session.json                          # conversation + metadata
│   └── uploads/                              # binary attachments
│       ├── upload_a1b2c3d4_report.pdf
│       └── upload_e5f6g7h8_chart.png
```

**Serialization (save):**
- [x] `_serialize_message()`: if `content` is `list[dict]`, scan for `image_url` parts with
  `data:` URIs — replace inline base64 with `file://uploads/<filename>` references
- [x] Move files from `SessionFileStore` temp dir into `sessions/<name>/uploads/`
- [x] Text-only sessions: keep existing `.json` format (no directory needed)
- [x] Multimodal sessions: create `<name>/` directory with `session.json` + `uploads/`

**Deserialization (load):**
- [x] Detect session format: `Path.is_dir()` → directory-based (multimodal), `.is_file()` → legacy JSON
- [x] `_deserialize_message()`: if `content` is `list[dict]`, resolve `file://uploads/...`
  references — re-register files in `SessionFileStore` so tools can access them by `file_id`
- [x] If referenced file is missing (deleted externally): replace with
  `{"type": "text", "text": "[Attachment missing: filename]"}` — never crash on missing files

**Migration / backward compat:**
- [x] Old `.json` sessions load unchanged — `content` is always `str`, no file references
- [x] New directory sessions auto-created only when message content contains binary data
- [x] Session list (`/sessions`): scan for both `*.json` files and `*/session.json` directories
- [x] Session delete: `shutil.rmtree()` for directory sessions, `Path.unlink()` for JSON sessions
- [x] Session rename: rename directory (or file), update `session.json` internal name field

### 0.7 Rich TUI Client — Fix str-Assuming Rendering (~5 locations)

- [x] `ppxai/tui/widgets/message_box.py` — 5 locations
  - Line 46: constructor `self.content = content` — reactive field typed as `str`; add type guard to accept list, store `text_content()` for display, keep original for serialization
  - Lines 72, 74, 77: `Markdown(self.content)` / `Static(self.content)` — Markdown/Static widgets require `str`; use text_content()
  - Line 104: `self.content += chunk` streaming append — only assistant streaming chunks are `str`, so this is safe for streaming; but initial multimodal user messages need text extraction before widget construction
  - Line 134: `copy_to_clipboard(self.content)` — use text_content() for clipboard
- [x] `ppxai/rendering/textual_renderer.py` — 1 location
  - Line 136: `content = msg.content` — use `text_content()` before rendering

### 0.8 Textual TUI Client — Fix str-Assuming Display (~3 locations)

- [x] `ppxai/tui/app.py` — 1 location
  - Line 749: `content = msg.content` passed to `chat_view.add_*_message()` — extract text before passing to widget; for image parts, show `[Image: filename]` placeholder in chat
- [x] `ppxai/tui/widgets/chat_view.py` — 1 location
  - Line 74: `{"content": msg.content}` in `get_messages()` — this is serialization for save, should preserve original multimodal content (no change needed)
- [x] `ppxai/tui/widgets/artifact_panel.py` — 1 location
  - Line 223: `content = result.content or result.message` — use text_content() if result wraps a Message

### 0.9 Web Client (JS) — Add Content Normalization (~8 locations)

- [x] Add `normalizeContent(content)` utility function in `app.js`
  ```javascript
  normalizeContent(content) {
      if (typeof content === 'string') return content;
      if (Array.isArray(content)) {
          return content
              .filter(b => b.type === 'text')
              .map(b => b.text || '')
              .join('\n');
      }
      return String(content);
  }
  ```
- [x] `app.js` — guard all content consumers:
  - Line 1102: `renderMarkdown(fullContent)` — fullContent is accumulated string from SSE chunks, safe for streaming (chunks are always strings); but session-restored messages may be multimodal → normalize before render
  - Line 1142: `fullContent += event.data` — SSE stream_chunk data is always string, safe
  - Line 1160: `event.data.trim()` — SSE stream_end data is always string, safe
  - Line 1367: `renderMarkdown(content)` in `addMessage()` — **CRITICAL**: when rendering loaded session messages, content may be array → `normalizeContent(content)` before render
  - Line 1401: clipboard copy `contentEl.innerText` — operates on DOM (already rendered text), safe
- [x] Session message rendering on load — the main break point: when the web client receives session history from `/api/sessions/:id`, messages may have list content → normalize before display
- [x] Image content display — for `image_url` parts, render `<img>` tags inline in the message bubble (future Phase 3 enhancement, for now show `[Image: name]` placeholder)

### 0.10 VSCode Client (TS) — Add Content Normalization (~15 locations)

- [x] Update type definition in `httpClient.ts`
  - Line 91: `content: string` → `content: string | ContentBlock[]`
  - Add type: `type ContentBlock = { type: string; text?: string; image_url?: { url: string } }`
  - Add helper: `function textContent(content: string | ContentBlock[]): string`
- [x] `httpClient.ts` — 4 locations
  - Line 701: `conversationHistory.push({content: message})` — user input is always string, safe
  - Line 731: `fullResponse += mappedEvent.content` — SSE chunks are strings, safe
  - Line 756: `conversationHistory.push({content: fullResponse})` — accumulated string, safe
  - Line 860: `streamCallback?.({content: fullResponse})` — accumulated string, safe
- [x] `chatPanel.ts` — 4 locations
  - Lines 87, 174: `msg.content` truthy check + log — use `textContent()` for logging
  - Line 364: `handleChat(message.content)` — message from webview is always string user input, safe
  - Line 603: `content.matchAll(refPattern)` — file ref extraction; this operates on user input string, safe
- [x] `handlers/stream.ts` — 6 locations
  - Lines 25-57: `eventBus.emit('stream:X', event.content)` — SSE event content is always string, safe
  - Line 86: `event.content` as file path — always string from server, safe
  - Lines 208, 238, 253: `JSON.parse(event.content)` — server sends JSON strings for consent/state events, safe
- [x] `handlers/agentStateMachine.ts` — 2 locations
  - Line 248: `response: input.content` — SSE chunk, always string, safe
  - Line 275: `response: state.response + input.content` — string accumulation, safe
- [x] **Webview JS** (`media/webview/main.js`) — session message rendering
  - When loading session history, messages may have array content → add `normalizeContent()` in webview JS
  - Line 1113: `parseMarkdown(content)` — normalize before parse
  - Line 1127: `contentEl.textContent = content` — normalize before display

**Key insight for Web/VSCode:** SSE streaming events (`stream_chunk`, `stream_end`) always carry string content from the server — they're safe. The break points are specifically when **rendering stored/loaded session messages** that may contain multimodal `list[dict]` content from a previous upload.

---

## Phase 1: Rich TUI — `/attach` + Multimodal Rendering

**Start here.** Rich TUI is the most constrained client — no drag-drop, no webview,
blocking REPL. If multimodal data works here, every other client is easier.
Rich TUI already has: inline image rendering (iTerm2/Sixel), `ImageResult` type +
renderer dispatch, `TableResult` + Rich Tables, `render_markdown_with_tables()`.

### 1.1 `/attach <path>` Slash Command

- [x] Add `/attach <path> [path2] ...` command in `ppxai/commands.py`
  - Read file(s), detect media type via `mimetypes.guess_type()`
  - Base64-encode, store in `_pending_files` list on CommandHandler
  - Show confirmation: `"report.pdf attached (2.4 MB, 12 pages) — will be sent with next message"`
  - For images: show inline preview via `ITerm2Image` if terminal supports it
  - For PDFs: show page count (via `pypdf` if available)
  - `/attach` with no args → list currently attached files
  - `/attach clear` → remove all pending files
- [x] File size guard: reject files > 10MB with clear error
- [x] On next chat send: call `preprocess_file()` per file, build multimodal `Message.content`,
  clear `_pending_files` after send

### 1.2 Multimodal Message Display in Rich Console

- [x] When rendering user messages that contain multimodal content:
  - Text parts → render as normal markdown via `Markdown()`
  - `image_url` parts → render inline via existing `ITerm2Image(base64_data)`
  - `<uploaded_file>` references → show badge: `[PDF: report.pdf, 12 pages]`
  - Fall back to `[Image: filename]` placeholder if terminal doesn't support images
- [x] When rendering assistant messages that reference tool results with images:
  - `get_pdf_page_image` returns base64 PNG → render inline
  - `render_excel_chart` returns base64 PNG → render inline
  - `render_pptx_slide` returns base64 PNG → render inline
  - Reuse existing `ImageResult` → `RichRenderer.render()` dispatch

### 1.3 Tabular Data Rendering Strategy

- [x] Excel sheet data → render via existing `TableResult` + `render_table()`
  - Rich Tables handle column alignment, word wrapping, styling automatically
  - For large sheets: truncate to first N rows with `[... 847 more rows]` footer
  - Add `/sheet <file_id> <sheet> [--rows N] [--sort col] [--filter col=val]` command
    for interactive exploration (low priority, nice-to-have)
- [x] Markdown tables from assistant responses → already rendered via `render_markdown_with_tables()`
- [x] Consider: numbered row references so user can say "expand row 3" or "show rows 10-20"

### 1.4 Visual Data Rendering Strategy

All visual content converts to PNG for inline terminal display:

| Source | Conversion | Tool |
|--------|-----------|------|
| **PDF page** | `pdf2image` (poppler) → PNG | `get_pdf_page_image` |
| **PPTX slide** | LibreOffice headless → PNG | `render_pptx_slide` |
| **Excel chart** | matplotlib re-render → PNG | `render_excel_chart` |
| **Image file** | Already PNG/JPEG | Direct `ITerm2Image` |

- [x] All image tool results return base64 PNG → Rich renderer shows inline via `ITerm2Image`
- [x] For terminals without image support: fall back to text description
  - PDF: show extracted text
  - Chart: show data table instead
  - PPTX: show slide text + "[slide image not available in this terminal]"

---

## Phase 2: Engine Foundation

Core backend — testable via Rich TUI's `/attach` command.

### 2.1 SessionFileStore

- [x] Create `ppxai/engine/session_store.py`
  - `SessionFileStore` class: `save(name, data) -> file_id`, `get(file_id) -> path`, `cleanup(file_id)`
  - Temp dir per session under `~/.ppxai/uploads/` (not system tmpdir — survives session restore)
  - File size guard: 10MB default, configurable via `ppxai-config.json`
  - Cleanup hook: wire into `EngineClient` session teardown to purge uploaded files
  - `move_to_session(session_dir)` — called by session save to move files from temp dir
    into `sessions/<name>/uploads/`, returns mapping of `file_id → relative_path` for
    serializing `file://uploads/...` references in message content
  - `restore_from_session(session_dir)` — called by session load to re-register files
    from `sessions/<name>/uploads/` back into the store's `file_id → path` mapping

### 2.1a `context_attachments` Schema Migration (new — AppState follow-up)

**Prerequisite:** Pattern 1 above (`AppState.context_attachments` already
lives in the engine as of Phase 1 follow-up). SessionFileStore landing
changes how entries are populated, not whether they exist.

Today each entry is `{name, kind, media_type, turn_index}` with data pulled
from `data:` URI parsing in `EngineClient._refresh_context_attachments()`.
Once binary content moves to SessionFileStore, the scanner needs to read
from file-reference content parts instead of inline base64, and clients
need a stable handle to fetch thumbnails through a future server endpoint.

- [x] Extend entry schema with `file_id: str` — nullable during transition,
  required once SessionFileStore is the sole storage backend
  - Update the schema doc comment in `AppState.FIELDS["context_attachments"]`
  - Bump the field-count sentinel test in `test_app_state.py` if needed
  - Bump the entry-shape assertions in `test_context_attachments_state.py`
- [x] Rewrite `_refresh_context_attachments()` in `ppxai/engine/client.py`
  - Current: parses `image_url.url` data URI for `media_type`
  - New: reads file reference from content part, looks up metadata via
    `SessionFileStore.get_metadata(file_id)` which returns
    `{name, media_type, size, kind}`
- [x] Add `SessionFileStore.get_metadata(file_id) -> dict` method for this
  read path (separate from `get(file_id) -> Path` which tools call)
- [x] Session round-trip test: save a session with an image attachment,
  load it back, assert `engine.get_context_attachments()` returns the
  same entries with correct `file_id` values
- [x] Backward compat: legacy sessions with inline base64 still parse
  correctly — `_refresh_context_attachments()` handles both formats for
  one release cycle, then the data-URI branch can be dropped

### 2.1b `/attach remove <name>` Command (new — closes the ticket on token billing)

**Motivation:** Once an image is in `session.messages`, every subsequent
turn re-sends (and re-bills) it. Phase 1 `/attach clear` only empties the
staging buffer — it has no way to evict already-committed attachments.
With `context_attachments` now carrying stable `name` and `turn_index`
values, targeted removal becomes a ~50-line change.

- [x] Add `/attach remove <name>` and `/attach remove all` subcommands in
  `ppxai/commands/attach.py`
- [x] Implement `EngineClient.remove_context_attachment(name: str) -> bool`
  - Walks `session.messages`, finds any user turn containing an
    `image_url` or file-reference content part with matching `name`
  - Rewrites the message's content list, dropping the matching parts
  - If all non-text parts are removed, leaves the text part intact so
    conversation alternation stays valid
  - Fires `session.on_messages_changed` — AppState refreshes automatically
  - Returns True if anything was removed
- [x] Unit tests: remove single, remove all, remove when absent (no-op),
  remove the only content part (message keeps text), remove across
  multiple turns (dedupes properly)
- [x] Help text + completion: `/attach remove <tab>` should complete the
  names of currently attached files — add a path-completion-style branch
  in `PPXAICompleter` that reads `handler.engine_client.get_context_attachments()`
- [x] Deferred until Phase 2 because the completion from stored file
  names requires SessionFileStore metadata to drive the display

### 2.2 File Preprocessing

- [x] Create `ppxai/engine/file_preprocessing.py`
  - `preprocess_file(name, media_type, data, model, engine) -> list[dict]`
  - **Images:** vision model → `image_url` content part; text-only model with VL fallback → auto-caption; no VL → placeholder
  - **PDFs:** save to SessionFileStore, inject `<uploaded_file>` reference with page count
    - Note: Perplexity sonar models accept PDF attachments natively via their API — future optimization
  - **Text/code:** base64-decode, inject inline as `<file name='...'>` block
  - **Office (xlsx/pptx):** save to SessionFileStore, inject `<uploaded_file>` reference with metadata

### 2.3 Gemini Models Consolidation + Gemma 4

Update model list, profiles, and pricing. Verified against official docs (April 2026):
- [Gemini models](https://ai.google.dev/gemini-api/docs/models)
- [Gemini deprecations](https://ai.google.dev/gemini-api/docs/deprecations)
- [Gemma 4 model card](https://ai.google.dev/gemma/docs/core/model_card_4)
- [Gemma on Gemini API](https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api)

**Models to add to `ppxai-config.example.json` (gemini provider):**
- [x] `gemini-3.1-flash-lite-preview` — cheapest Gemini 3 tier, text + image + video input
- [x] `gemini-3.1-flash-image-preview` — Nano Banana 2, image generation/editing + 4K output
- [x] `gemma-4-31b-it` — dense 31B, 256K context, text + vision (open weights, same API key)
- [x] `gemma-4-26b-a4b-it` — MoE 26B (3.8B active), 256K context, text + vision
- [x] `gemma-4-e4b-it` — edge 8B (4.5B effective), 128K context, text + vision + audio
- [x] `gemma-4-e2b-it` — edge 5.1B (2.3B effective), 128K context, text + vision + audio

**Models to remove (already shut down):**
- [x] `gemini-3-pro-preview` — **shut down March 9, 2026** → remove from models list, keep pricing for reference

**Models to flag as deprecated (add `__comment_deprecated` in config):**
- [x] `gemini-2.0-flash` — deprecated, shuts down **June 1, 2026**
- [x] `gemini-2.0-flash-lite` — deprecated, shuts down **June 1, 2026**
- [x] `gemini-2.5-pro` — GA but shuts down **June 17, 2026** (migrate to 3.x)
- [x] `gemini-2.5-flash` — GA but shuts down **June 17, 2026** (migrate to 3.x)
- [x] `gemini-2.5-flash-lite` — GA but shuts down **July 22, 2026**

**Deprecation timeline summary:**
```
June 1, 2026    gemini-2.0-flash, gemini-2.0-flash-lite (SHUTDOWN)
June 17, 2026   gemini-2.5-pro, gemini-2.5-flash (SHUTDOWN)
July 22, 2026   gemini-2.5-flash-lite (SHUTDOWN)
Oct 2, 2026     gemini-2.5-flash-image (SHUTDOWN)
Oct 16, 2026    gemini-2.5-pro, gemini-2.5-flash, gemini-2.5-flash-lite (extended?)
```

**Profiles to add in `model_profiles.py` `BUILTIN_PROFILES`:**
- [x] `gemma-4-31b*` — native tool calling (supports thinking), vision, 256K context, tier TBD
- [x] `gemma-4-26b*` — same as 31b (MoE variant, 3.8B active params)
- [x] `gemma-4-e*` — prompt-based tool calling (small edge models), vision + audio, 128K context
- [x] `gemini-3.1-flash-lite*` — native tool calling, fallback on empty/failure (like 2.5-flash-lite)
- [x] `gemini-3.1-flash-image*` — image generation model, no tool calling needed

**Pricing to add:**
- [x] `gemini-3.1-flash-lite-preview` — verify from Google AI Studio pricing page
- [x] `gemini-3.1-flash-image-preview` — verify from Google AI Studio pricing page
- [x] Gemma 4 models — free tier via Gemini API (same API key)

**Update default_model:**
- [x] Keep `gemini-3-flash-preview` as default (fast, cheap, 100% benchmark)
- [x] Add comment noting `gemini-3.1-pro-preview` for complex reasoning tasks
- [x] Recommend migration path: 2.0 → 2.5 → 3.x in deprecation comments

### 2.4 Config Doctor — `/doctor` Command

Read-only config advisor that scans user's `ppxai-config.json` against a known
deprecation table. **Does not modify user config** — prints actionable info only.

Not a migration tool — v1.17.4 data changes are backward compatible. This exists
because Gemini deprecations (outside v1.17.4) will strand users with dead models
in their config.

- [x] Add deprecation table in `ppxai/engine/model_deprecations.py`
  ```python
  GEMINI_DEPRECATIONS = {
      "gemini-3-pro-preview":    ("shutdown", "2026-03-09"),  # already dead
      "gemini-2.0-flash":        ("shutdown", "2026-06-01"),
      "gemini-2.0-flash-lite":   ("shutdown", "2026-06-01"),
      "gemini-2.5-pro":          ("shutdown", "2026-06-17"),
      "gemini-2.5-flash":        ("shutdown", "2026-06-17"),
      "gemini-2.5-flash-lite":   ("shutdown", "2026-07-22"),
      "gemini-2.5-flash-image":  ("shutdown", "2026-10-02"),
  }
  RECOMMENDED_NEW = [
      "gemini-3.1-flash-lite-preview",  # cheapest Gemini 3
      "gemma-4-31b-it",                 # open weights, free tier
      "gemma-4-26b-a4b-it",             # MoE variant
  ]
  ```

- [x] Add `/doctor` slash command in `ppxai/commands/doctor.py`
  - Scans user's `~/.ppxai/ppxai-config.json` (not the example file)
  - For each provider, checks models against deprecation table
  - Reports four categories:
    - **Dead models** (shutdown date in past) — must remove/replace
    - **Upcoming deprecations** (shutdown date in future) — days remaining countdown
    - **New models available** — present in example config but not in user config
    - **Recommended defaults** — flag if user's `default_model` is on deprecation list
  - Prints actionable info with exact JSON paths to edit
  - Returns exit code 0 (advisory only, never fails)
  - Read-only: never writes to user config file

- [x] Example output:
  ```
  ppxai config check
  ==================
  ⚠ Dead models in config (shutdown, remove):
     providers.gemini.models.gemini-3-pro-preview (shut down 2026-03-09)

  ⚠ Upcoming deprecations:
     providers.gemini.models.gemini-2.0-flash → 2026-06-01 (57 days)
     providers.gemini.models.gemini-2.5-flash → 2026-06-17 (73 days)

  ✓ New models available (add to your config):
     - gemini-3.1-flash-lite-preview (cheapest Gemini 3 tier)
     - gemma-4-31b-it (open weights, free tier)
     - gemma-4-26b-a4b-it (MoE variant, 3.8B active)

  Recommended default: gemini-3-flash-preview (100% benchmark, no deprecation)
  ```

- [x] Optional: one-time startup warning if config has dead models
  - Print a single-line notice on ppxai startup: `"⚠ Dead models in config. Run /doctor for details."`
  - Suppressed by env var `PPXAI_SKIP_CONFIG_CHECK=1` or after acknowledgment flag in config
  - Not blocking — user can still use ppxai normally

### 2.5 ModelProfile: Vision Capability Flag

- [x] Add `supports_vision: bool = False` to `ModelProfile` dataclass in `model_profiles.py`
  - Used by preprocessing to decide image handling strategy
  - No string-matching heuristics — use the existing profile registry
  - Set `True` for (verified against official docs April 2026):
    - **OpenAI:** `gpt-5.4*`, `gpt-5.3-codex*`, `gpt-5.2*` (all GPT-5.x have native vision)
    - **Gemini:** `gemini-3.1*`, `gemini-3-flash*`, `gemini-2.5*`, `gemini-2.0*` (all Gemini chat models)
    - **Gemma 4:** `gemma-4*` (all variants: 31B dense, 26B MoE, E4B, E2B — all have vision)
    - **Perplexity:** `sonar`, `sonar-pro` only (NOT `sonar-reasoning`, NOT `sonar-deep-research`)
    - **Local VL:** `qwen3-vl*`, `llava*`, `pixtral*`, `minicpm-v*`
  - Set `False` for: `sonar-reasoning`, `sonar-deep-research`, text-only local models (GPT-OSS, Qwen3.5-27B Dense)
  - Note: `gemini-3.1-flash-image*` and `gemini-3-pro-image*` are image **generation** models,
    not chat models — they don't need profiles (different API endpoint)

### 2.6 Provider-Level Image Capability

- [x] Add image format/size validation to preprocessing
  - Accepted formats: PNG, JPEG, WEBP, GIF (universal across all providers)
  - Default size limit: 10MB (conservative); Perplexity allows 50MB but most providers lower
  - Image token estimation: `(width × height) / 750` tokens (Perplexity formula, useful for cost warnings)
- [x] Preprocessing must check `supports_vision` before building `image_url` content parts
  - Vision model → `image_url` content part (native)
  - Text-only model + VL fallback configured → auto-caption via sidecar VL model
  - Text-only model + no VL fallback → reject with clear error: "model X does not support images"
  - Never silently drop image uploads — always inform the user

### 2.7 Vision Model Config

- [x] Add `vision_model` section to config schema (`config/providers.py` or `config/tools.py`)
  ```json
  "vision_model": {
    "endpoint": "http://dgx-node:8001/v1",
    "model": "qwen3-vl-8b",
    "auto_caption": true
  }
  ```
  - Wire `EngineClient.has_vision_model()` and `caption_image(name, media_type, data) -> str`
  - `caption_image` makes a one-shot `/chat/completions` call to the VL endpoint

### 2.8 PDF Tools

- [x] Create `ppxai/engine/tools/builtin/pdf_tools.py`
  - `ReadPdfTool(BaseTool)`: extract text from pages — params: `file_id`, `pages` ("all", "3", "2-5")
  - `GetPdfPageImageTool(BaseTool)`: rasterize page to PNG base64 — params: `file_id`, `page`, `dpi`
  - Both resolve `file_id` via `SessionFileStore.get()`
  - `register_tools(manager, engine)` — guarded by `try: import pypdf`
- [x] Register in `builtin/__init__.py` under a `try/except` block (like container tools)

**Design decision — tool-generated attachments are excluded from `context_attachments`:**

When `GetPdfPageImageTool` / `RenderExcelChartTool` / similar tools return
rasterized PNGs, those images become part of `session.messages` (so the
model sees them on subsequent turns) but must NOT appear in the user-facing
attachment badge.

**Rationale:** the badge represents "what the user attached to this
conversation." A user who asks the model to read 20 PDF pages via tools
should not see 20 entries in their badge — that would bury real user
uploads and conflate intent (deliberate attach) with side effects (tool
exploration).

**Implementation (already landed in Phase 1 follow-up, not deferred):**
`EngineClient._refresh_context_attachments()` filters by `msg.role == "user"`
before scanning content parts. Tool role and assistant role messages
with multimodal content are invisible to the scanner by design. System
messages are also excluded (defensive, for unusual provider-specific
system prompt injection shapes).

**Tests pinning the invariant:**
- `test_context_attachments_state.py::test_tool_generated_images_are_not_tracked` —
  conversation with user image + assistant image + tool image, asserts
  only the user image lands in `context_attachments`
- `test_context_attachments_state.py::test_system_messages_with_list_content_are_not_tracked` —
  system message with image content, asserts exclusion

**Revisit in Phase 4** (not Phase 2): if users request visibility into
tool artifacts (Excel charts are the likely trigger — they generate
several images per spreadsheet), add a second AppState field like
`tool_artifacts: list[dict]` with the same schema plus a `source` field
pointing at the tool call. Keep it a separate field so the two concepts
(user attachments vs tool output) stay distinct in every client UI.

### 2.9 Dependencies

- [x] Add `[data]` optional group to `pyproject.toml`
  ```toml
  [project.optional-dependencies]
  data = [
      "pypdf>=4.0",
      "pdf2image>=1.17",
  ]
  ```
  - Phase 2 ships with PDF only — Excel/PPTX deps added in Phase 4

---

## Phase 3: Server API

### 3.1 Extend Chat Request

- [ ] Update `ChatRequest` in `ppxai/server/models.py`
  ```python
  class FileAttachment(BaseModel):
      name: str
      media_type: str
      data: str  # base64

  class ChatRequest(BaseModel):
      message: str
      provider: Optional[str] = None
      model: Optional[str] = None
      files: list[FileAttachment] = []
  ```

### 3.2 Chat Route Integration

- [ ] In `ppxai/server/routes/chat.py`: if `request.files` is non-empty, call
  `preprocess_file()` for each, merge content parts into the message sent to engine
- [ ] Validate: reject files exceeding size limit before base64 decode

**Note:** Thanks to the AppState promotion in Phase 1 follow-up, the chat
route does NOT need to fire any per-client state updates. Calling
`engine.chat(content_list)` adds the message to `session.messages`, which
fires `on_messages_changed`, which fires `_refresh_context_attachments`,
which writes to `AppState.context_attachments`, which propagates to all
connected clients via the existing `state_sync` SSE stream. The route
becomes ~10 lines instead of ~30.

### 3.3 SSE `state_sync` for `context_attachments` (new — AppState follow-up)

**Prerequisite:** Phase 1 already installed `AppState.context_attachments`
as a canonical field with engine-side invalidation. Server needs to push
changes to connected clients so web/VSCode webviews can rerender their
attachment chip strips without polling.

- [ ] Verify that `context_attachments` is included in the list of fields
  broadcast by the existing `state_sync` SSE infrastructure (v1.17.1).
  Check `ppxai/server/streaming.py` and `ppxai/server/routes/chat.py`
  for the field whitelist, if any.
- [ ] If there's a whitelist, add `"context_attachments"` to it.
- [ ] Server-side test: open an SSE connection, fire a chat with an image,
  assert a `state_sync` event arrives with the new `context_attachments`
  value. Add to `tests/test_server_sse.py` or equivalent.
- [ ] Client subscription happens in Phases 5.4 and 6.3 (web/vscode).

---

## Phase 4: Excel + PPTX Tools

### 4.1 Excel Tools

- [ ] Create `ppxai/engine/tools/builtin/excel_tools.py`
  - `ListExcelSheetsTool`: sheet names + row/col dimensions
  - `ReadExcelSheetTool`: sheet data as markdown table or CSV — params: `file_id`, `sheet`, `rows`, `as_markdown`
  - `ListExcelChartsTool`: chart titles and types per sheet
  - `RenderExcelChartTool`: rasterize chart to PNG via matplotlib
  - Guarded by `try: import openpyxl`
- [ ] Register in `builtin/__init__.py`

### 4.2 PPTX Tools

- [ ] Create `ppxai/engine/tools/builtin/pptx_tools.py`
  - `ListPptxSlidesTool`: slide inventory with shape flags (TEXT, TABLE, CHART, IMAGE)
  - `ReadPptxSlideTextTool`: text + tables from a slide as markdown
  - `RenderPptxSlideTool`: rasterize full slide via LibreOffice headless
  - `ExtractPptxImagesTool`: extract embedded images as base64 PNGs
  - Guarded by `try: import pptx`
- [ ] Register in `builtin/__init__.py`

### 4.3 Dependencies Update

- [ ] Expand `[data]` optional group
  ```toml
  data = [
      "pypdf>=4.0",
      "pdf2image>=1.17",
      "openpyxl>=3.1",
      "python-pptx>=1.0",
      "matplotlib>=3.9",
  ]
  ```

---

## Phase 5: Web Client

Best UX for file upload — drag-drop is the natural interaction.

### 5.1 File Picker + Drag-Drop

- [ ] Add paperclip icon button next to chat input in `ppxai/web/index.html`
- [ ] Hidden `<input type="file" multiple accept=".pdf,.xlsx,.pptx,.png,.jpg,.txt,...">` triggered by button
- [ ] Drag-drop handler on chat input container (`dragover`, `drop` events)
- [ ] `fileToBase64()` utility — FileReader → base64 string
- [ ] Maintain `pendingFiles[]` array, cleared on send

### 5.2 Attachment Badges

- [ ] Render attachment badges (filename + type icon + X remove) below input area
- [ ] CSS for badge strip: horizontal scroll, max-height constrained

### 5.3 Send Integration

- [ ] On send: include `files: pendingFiles` in the POST body to `/api/chat`
- [ ] Clear `pendingFiles` and remove badges after successful send

### 5.4 `contextAttachments` AppState Mirror (new — AppState follow-up)

Phase 5.1-5.3 handle the *pre-send staging* chip strip (files the user has
selected via drag-drop, not yet uploaded). Phase 5.4 handles the
*post-send persistent* chip strip — files already committed to session
history that the model re-sees on every subsequent turn.

- [ ] Add `contextAttachments` field to `ppxai/web/shared/app-state.js`
  `FIELDS` dict (camelCase mirror of the Python
  `AppState.context_attachments`)
  - Entry schema: `{ name, kind, mediaType, turnIndex, fileId }` (after
    Phase 2.1a) — must match the Python schema 1:1
  - Default value: `[]`
- [ ] Subscribe to `state_sync` SSE events for `contextAttachments` —
  existing infrastructure handles delivery, just ensure the JS AppState
  writes the field when the event fires
- [ ] New DOM component: `ContextAttachmentChips` — renders one chip per
  entry in the persistent strip above the chat input
  - Visual distinction from pending (staged) chips: darker, smaller, with
    a "sent" indicator
  - Click chip → call `/api/command` with `/attach remove <name>`
    (requires Phase 2.1b)
  - Hover chip → fetch thumbnail via `/api/files/<file_id>` (requires
    Phase 2.1a + new server endpoint, see 5.4.1 below)
- [ ] (Optional 5.4.1) New server endpoint `GET /api/files/<file_id>` →
  returns the raw file bytes from SessionFileStore so the web client can
  render thumbnails. Serve with appropriate cache headers and session
  scoping (file_id is valid only within the authenticated session).

---

## Phase 6: VSCode Client

### 6.1 Webview File Picker

- [ ] Add file picker in chat webview (button + drag-drop, same pattern as web)
- [ ] `chatPanel.ts` — handle `{ type: 'chat', message, files }` from webview
- [ ] Forward files array to `httpClient.ts` POST `/api/chat`

### 6.2 Context Menu Integration

- [ ] Register "ppxai: Attach to Chat" command in `package.json` (`editor/context`)
- [ ] On invoke: read file, base64-encode, add to pending files in chat panel
- [ ] Works for any file in the explorer or open editor tab

### 6.3 `contextAttachments` AppState Mirror (new — AppState follow-up)

Same pattern as Phase 5.4, but for the VSCode extension. The webview
already uses the same HTML/JS stack as the web client, so most of this
step is importing the `ContextAttachmentChips` component from a shared
location or duplicating ~40 lines into the webview bundle.

- [ ] Add `contextAttachments` field to `vscode-extension/src/appState.ts`
  `FIELDS` (camelCase)
  - Type: `ContextAttachment[]` where
    `interface ContextAttachment { name: string; kind: string; mediaType: string; turnIndex: number; fileId: string }`
  - Default: `[]`
- [ ] Existing AppState sync bridge (SSE → TS AppState) already handles
  arbitrary fields — verify `contextAttachments` propagates without
  extra code
- [ ] Webview: add chip strip component, wire to AppState observer, render
  on state change
- [ ] Chip click → `vscode.commands.executeCommand('ppxai.removeAttachment', name)`
  or direct `/api/command` POST — same as web
- [ ] Consolidate chip component with web client into a shared
  `common/context-attachment-chips.js` module that both builds consume,
  so future schema changes happen in one place

---

## Phase 7: Textual TUI

### 7.1 File Tree Attach

- [ ] Add `a` key binding in `FileTree` widget — attach highlighted file as upload
- [ ] On attach: read file bytes, base64-encode, add to `_pending_files` on the app
- [ ] Show notification: "filename attached" (existing `self.notify()`)
- [ ] Display pending file count badge in status bar or input widget

### 7.2 Ctrl+U Shortcut

- [ ] Register `Ctrl+U` in `keys.py` as `attach_file`
- [ ] Opens a simple path input dialog (or focuses file tree if open)
- [ ] Alternative: `Ctrl+U` toggles file tree with attach mode active

### 7.3 Send Integration

- [ ] On submit: if `_pending_files` is non-empty, include in the engine call
- [ ] Clear pending files after send

### 7.4 Footer `context_attachments` Badge (new — AppState follow-up)

Textual TUI is in-process with the engine (no SSE, no HTTP), so it
subscribes directly to the AppState observer pattern — same as the Rich
TUI status bar does today.

- [ ] Add a `Static` widget in the ppxaide footer layout for the
  attachment badge. Initial text: `""` (hidden when empty).
- [ ] In `PPXAIDEApp.on_mount`, subscribe:
  ```python
  self._engine_client.state.on(
      "context_attachments",
      self._on_context_attachments_changed,
  )
  ```
- [ ] `_on_context_attachments_changed(entries: list[dict])` handler
  rebuilds the badge text using the same formatting helper as Rich's
  status bar (extract to `ppxai/common/attachment_badge.py` so both TUIs
  share the exact same label rendering — avoid drift between `📎 2 (1🖼 1📄)`
  in one client and a slightly different format in the other)
- [ ] Initial snapshot: call the handler once on mount with the current
  AppState value so a restored session shows the badge immediately
- [ ] Test: `tests/test_textual_context_attachments.py` — drive the app
  with a multimodal message, assert the footer widget updates
- [ ] Consider: click the badge to open a modal listing full filenames
  (nice-to-have, deferred if mount time bloats)

---

## Open Items (post v1.17.4)

- [ ] Scanned PDF support — rasterize + route pages through VL model
- [ ] DOCX support — `python-docx` text extraction
- [ ] `_render_chart_to_axes()` — matplotlib re-render from openpyxl chart data
- [ ] Native PDF passthrough for Perplexity sonar — skip tool extraction, send via API directly
- [ ] Audio/video input — Gemini Live API, OpenAI Realtime API (different integration path)
- [ ] Image generation output — Gemini Nano Banana models can generate images in responses
- [ ] Session migration tool — batch-convert old `.json` sessions if needed (likely not needed, old sessions have no multimodal content)

---

## Key Files (planned)

| File | Purpose |
|------|---------|
| `ppxai/engine/types.py` | Message.content Union type + text_content() helper |
| `ppxai/engine/providers/base.py` | BaseProvider._convert_messages() multimodal pass-through |
| `ppxai/engine/providers/gemini.py` | Gemini image_url → inline_data conversion |
| `ppxai/engine/session.py` | 6 sites: len(), export — use text_content() |
| `ppxai/engine/session_ops.py` | 3 sites: export, context calc, regex — use text_content() |
| `ppxai/engine/chat.py` | 2 sites: content extraction, truthy check |
| `ppxai/common/logger.py` | 2 sites: content preview slicing |
| `ppxai/server/streaming.py` | 2 sites: cleanup logging |
| `ppxai/tui/widgets/message_box.py` | 5 sites: Markdown/Static render, streaming, clipboard |
| `ppxai/tui/app.py` | Session load → extract text before widget |
| `ppxai/rendering/textual_renderer.py` | Content extraction for rendering |
| `ppxai/web/app.js` | normalizeContent() + session message rendering |
| `vscode-extension/src/httpClient.ts` | ContentBlock type, textContent() helper |
| `vscode-extension/media/webview/main.js` | normalizeContent() + session message rendering |
| `ppxai/commands.py` | /attach slash command (Phase 1, first deliverable) |
| `ppxai/rendering/rich_renderer.py` | Multimodal message + image result rendering |
| `ppxai/tui/renderable/iterm2.py` | ITerm2Image — reused for PDF/chart/slide PNGs |
| `ppxai/tui/terminal.py` | Terminal image protocol detection |
| `ppxai/engine/model_profiles.py` | Gemma 4 profiles, supports_vision flag, deprecation notes |
| `ppxai/engine/model_deprecations.py` | Deprecation table for /doctor command (read-only) |
| `ppxai-config.example.json` | Gemma 4 models, Gemini 3.1 Flash Lite, pricing, deprecations |
| `ppxai/engine/session.py` | Directory-based session format, file ref serialize/deserialize |
| `ppxai/engine/session_store.py` | Session file store (save/get/cleanup/move_to_session/restore) |
| `ppxai/engine/file_preprocessing.py` | Preprocessing dispatcher (images, PDFs, text, Office) |
| `ppxai/engine/tools/builtin/pdf_tools.py` | read_pdf, get_pdf_page_image |
| `ppxai/engine/tools/builtin/excel_tools.py` | list_sheets, read_sheet, list_charts, render_chart |
| `ppxai/engine/tools/builtin/pptx_tools.py` | list_slides, read_text, render_slide, extract_images |
| `ppxai/server/models.py` | FileAttachment model, ChatRequest.files field |
| `ppxai/server/routes/chat.py` | Preprocessing call in chat route |
| `ppxai/web/index.html` | File picker, drag-drop, attachment badges |
| `vscode-extension/src/chatPanel.ts` | Webview file picker relay |
| `ppxai/tui/widgets/file_tree.py` | `a` key attach binding |
| `ppxai/tui/keys.py` | Ctrl+U attach_file binding |
