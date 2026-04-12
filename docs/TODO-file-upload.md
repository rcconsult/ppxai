# TODO: File Upload & Data Processing

**Status:** Complete — All phases (0-7) + Task #11 + coder deployment + PPTX visual preview done, ready for release
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
| **Phase 3** — Server API | ✅ Complete | `ChatRequest.files[]` Pydantic model, chat route preprocessing, `context_attachments` in `state_sync` SSE whitelist, `POST /complete` endpoint, `GET /files/serve/{file_id}` |
| **Phase 4** — Excel + PPTX tools | ✅ Complete | `excel_tools.py` (4 tools), `pptx_tools.py` (4 tools), guarded by optional deps |
| **Phase 5** — Web client | ✅ Complete | Paperclip attach + drag-drop, attachment badges with thumbnails, inline clickable thumbnails in message bubbles, split panel lightbox (images) + PDF embed, `pendingFiles[]` staging |
| **Phase 6** — VSCode client | ✅ Complete | Webview file picker (`attachBtn` + `fileInput` + drag-drop), `pendingFiles` staging, `renderPendingBadges`, `chatPanel.ts` + `httpClient.ts` `files` forwarding |
| **Phase 7** — Textual TUI | ✅ Complete | FileTree `a` key → `FileAttach` message, `Ctrl+U` shortcut, `build_multimodal_content()` on send, public `pending_files` on `PPXAIDEApp` |
| **Task #11** — CompletionProvider | ✅ Complete | `engine/completion.py` with `complete()`, `POST /complete` server route, Rich `PPXAICompleter` delegates to engine |
| **Task #11 Follow-up** — Cross-client autocomplete parity | ✅ Complete | Engine now owns subcommands (`/tools`, `/usage`, `/checkpoint`, `/status`, `/theme`), dynamic `/model` + `/provider`, `/tools help <tool>`, and `@git`/`@tree`/`@clipboard`/`@url` context providers. Rich `PPXAICompleter` 594→85 lines, Textual `TextualCompleter` 238→100 lines. VSCode webview unifies `@` and `/` onto a single `POST /complete` flow (retires legacy `handleSearchFilesForAutocomplete` + `fileSuggestions`). Web picks up new sources for free via existing `replace_start`/`kind` dispatch. 18 new tests (39 total in `test_completion_provider.py`). Rich lazy imports hoisted per DAG rule. |

**Tests:** 2288 passing (was 1753 before Phase 0). **535 new tests** across
Phases 0-7 + Task #11 + autocomplete parity + schema-driven AppState DTO,
zero regressions. 2 poppler-dependent tests deliberately skipped.

### Post-Phase Work (coder.trad.int deployment, April 7)

| Item | Status | Notes |
|------|--------|-------|
| Dockerfile `[data]` extras + poppler + libreoffice-nogui | ✅ | System deps for PDF/PPTX rendering |
| `PPXAI_DATA_DIR` → workspace PVC | ✅ | Uploaded files survive session teardown |
| PV affinity (`SessionMeta.workspace_pv`) | ✅ | Prevents workspace data loss on namespace churn |
| deploy.sh resilience (secrets, namespace, labels) | ✅ | Auto-recovers Reflector secrets, API keys |
| `proxy-body-size: 50m` ingress annotation | ✅ | File uploads through nginx |
| Login wait 60s polling | ✅ | Cold pod starts without 503 |
| VL sidecar config (Qwen3-VL-8B) | ✅ | Auto-caption images on text-only models |
| `render_pptx_slide` tool (LibreOffice → PNG) | ✅ | Individual slide rasterization |
| `summarize_pptx_visual` tool (VL batch) | ✅ | All slides captioned in 1 tool call via VL sidecar |
| `GET /files/preview/{file_id}?slide=N` endpoint | ✅ | Server-side slide rendering for web preview |
| PDF preview — Blob URL + iframe | ✅ | Fixes blank preview for large PDFs |
| Excel preview — SheetJS + DataTableViewer | ✅ | Sort, filter, pagination, sheet tabs |
| PPTX preview — slide navigator | ✅ | Prev/next with LibreOffice-rendered images |
| Resizable split panel | ✅ | Drag handle sets flex-basis |
| Clickable attachment badge | ✅ | Cache-first file preview from status strip |
| `_refresh_context_attachments` for PDFs/Office | ✅ | Parses `<uploaded_file>` markers in text blocks |
| `ReadDocxTool` (read_docx) | ✅ | Stdlib zipfile + xml.etree, no python-docx dep |
| `ReadCsvTool` + `ListCsvColumnsTool` | ✅ | Large CSVs >50KB lazy-loaded via SessionFileStore |
| CSV preprocessing threshold (50KB) | ✅ | Small CSVs inline, large CSVs use tools |
| Word document preview (LibreOffice → PDF → iframe) | ✅ | Server-side conversion, cached |
| Type-specific tool hints in `<uploaded_file>` | ✅ | read_docx for Word, list_excel for Excel, etc. |
| Tests: PPTX render (15) + CSV (13) + Word (7) | ✅ | 35 new tests, full suite 2201 passed |

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
| 3 | Server | `ChatRequest.files[]`, preprocessing in chat route, **`context_attachments` in `state_sync` SSE (3.3)**, `POST /complete`, `GET /files/serve/{file_id}` ✅ |
| 4 | Engine | Excel + PPTX tools ✅ |
| 5 | Web | Drag-drop, file picker, staging chips, **`contextAttachments` AppState mirror + persistent chips (5.4)**, inline thumbnails, split panel lightbox/PDF embed ✅ |
| 6 | VSCode | Webview picker, context menu attach, **`contextAttachments` AppState mirror + webview chips (6.3)** ✅ |
| 7 | Textual TUI | File tree attach, Ctrl+U, staging badge, **footer `context_attachments` badge via observer (7.4)** ✅ |

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

- [x] Update `ChatRequest` in `ppxai/server/models.py`
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

- [x] In `ppxai/server/routes/chat.py`: if `request.files` is non-empty, call
  `preprocess_file()` for each, merge content parts into the message sent to engine
- [x] Validate: reject files exceeding size limit before base64 decode

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

- [x] Verify that `context_attachments` is included in the list of fields
  broadcast by the existing `state_sync` SSE infrastructure (v1.17.1).
  Check `ppxai/server/streaming.py` and `ppxai/server/routes/chat.py`
  for the field whitelist, if any.
- [x] If there's a whitelist, add `"context_attachments"` to it.
- [x] Server-side test: open an SSE connection, fire a chat with an image,
  assert a `state_sync` event arrives with the new `context_attachments`
  value. Add to `tests/test_server_sse.py` or equivalent.
- [x] Client subscription happens in Phases 5.4 and 6.3 (web/vscode).

---

## Phase 4: Excel + PPTX Tools

### 4.1 Excel Tools

- [x] Create `ppxai/engine/tools/builtin/excel_tools.py`
  - `ListExcelSheetsTool`: sheet names + row/col dimensions
  - `ReadExcelSheetTool`: sheet data as markdown table or CSV — params: `file_id`, `sheet`, `rows`, `as_markdown`
  - `ListExcelChartsTool`: chart titles and types per sheet
  - `RenderExcelChartTool`: rasterize chart to PNG via matplotlib
  - Guarded by `try: import openpyxl`
- [x] Register in `builtin/__init__.py`

### 4.2 PPTX Tools

- [x] Create `ppxai/engine/tools/builtin/pptx_tools.py`
  - `ListPptxSlidesTool`: slide inventory with shape flags (TEXT, TABLE, CHART, IMAGE)
  - `ReadPptxSlideTextTool`: text + tables from a slide as markdown
  - `RenderPptxSlideTool`: rasterize full slide via LibreOffice headless
  - `ExtractPptxImagesTool`: extract embedded images as base64 PNGs
  - Guarded by `try: import pptx`
- [x] Register in `builtin/__init__.py`

### 4.3 Dependencies Update

- [x] Expand `[data]` optional group
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

- [x] Add paperclip icon button next to chat input in `ppxai/web/index.html`
- [x] Hidden `<input type="file" multiple accept=".pdf,.xlsx,.pptx,.png,.jpg,.txt,...">` triggered by button
- [x] Drag-drop handler on chat input container (`dragover`, `drop` events)
- [x] `fileToBase64()` utility — FileReader → base64 string
- [x] Maintain `pendingFiles[]` array, cleared on send

### 5.2 Attachment Badges

- [x] Render attachment badges (filename + type icon + X remove) below input area
- [x] CSS for badge strip: horizontal scroll, max-height constrained

### 5.3 Send Integration

- [x] On send: include `files: pendingFiles` in the POST body to `/api/chat`
- [x] Clear `pendingFiles` and remove badges after successful send

### 5.4 `contextAttachments` AppState Mirror (new — AppState follow-up)

Phase 5.1-5.3 handle the *pre-send staging* chip strip (files the user has
selected via drag-drop, not yet uploaded). Phase 5.4 handles the
*post-send persistent* chip strip — files already committed to session
history that the model re-sees on every subsequent turn.

- [x] Add `contextAttachments` field to `ppxai/web/shared/app-state.js`
  `FIELDS` dict (camelCase mirror of the Python
  `AppState.context_attachments`)
  - Entry schema: `{ name, kind, mediaType, turnIndex, fileId }` (after
    Phase 2.1a) — must match the Python schema 1:1
  - Default value: `[]`
- [x] Subscribe to `state_sync` SSE events for `contextAttachments` —
  existing infrastructure handles delivery, just ensure the JS AppState
  writes the field when the event fires
- [x] New DOM component: `ContextAttachmentChips` — renders one chip per
  entry in the persistent strip above the chat input
  - Visual distinction from pending (staged) chips: darker, smaller, with
    a "sent" indicator
  - Click chip → call `/api/command` with `/attach remove <name>`
    (requires Phase 2.1b)
  - Hover chip → fetch thumbnail via `/api/files/<file_id>` (requires
    Phase 2.1a + new server endpoint, see 5.4.1 below)
- [x] (5.4.1) Server endpoint `GET /files/serve/{file_id}` →
  returns the raw file bytes from SessionFileStore so the web client can
  render thumbnails. Serve with appropriate cache headers and session
  scoping (file_id is valid only within the authenticated session).

---

## Phase 6: VSCode Client

### 6.1 Webview File Picker

- [x] Add file picker in chat webview (button + drag-drop, same pattern as web)
- [x] `chatPanel.ts` — handle `{ type: 'chat', message, files }` from webview
- [x] Forward files array to `httpClient.ts` POST `/api/chat`

### 6.2 Context Menu Integration

- [x] Register "ppxai: Attach to Chat" command in `package.json` (`editor/context`)
- [x] On invoke: read file, base64-encode, add to pending files in chat panel
- [x] Works for any file in the explorer or open editor tab

### 6.3 `contextAttachments` AppState Mirror (new — AppState follow-up)

Same pattern as Phase 5.4, but for the VSCode extension. The webview
already uses the same HTML/JS stack as the web client, so most of this
step is importing the `ContextAttachmentChips` component from a shared
location or duplicating ~40 lines into the webview bundle.

- [x] Add `contextAttachments` field to `vscode-extension/src/appState.ts`
  `FIELDS` (camelCase)
  - Type: `ContextAttachment[]` where
    `interface ContextAttachment { name: string; kind: string; mediaType: string; turnIndex: number; fileId: string }`
  - Default: `[]`
- [x] Existing AppState sync bridge (SSE → TS AppState) already handles
  arbitrary fields — verify `contextAttachments` propagates without
  extra code
- [x] Webview: add chip strip component, wire to AppState observer, render
  on state change
- [x] Chip click → `vscode.commands.executeCommand('ppxai.removeAttachment', name)`
  or direct `/api/command` POST — same as web
- [x] Consolidate chip component with web client into a shared
  `common/context-attachment-chips.js` module that both builds consume,
  so future schema changes happen in one place

---

## Phase 7: Textual TUI

### 7.1 File Tree Attach

- [x] Add `a` key binding in `FileTree` widget — attach highlighted file as upload
- [x] On attach: read file bytes, base64-encode, add to `_pending_files` on the app
- [x] Show notification: "filename attached" (existing `self.notify()`)
- [x] Display pending file count badge in status bar or input widget

### 7.2 Ctrl+U Shortcut

- [x] Register `Ctrl+U` in `keys.py` as `attach_file`
- [x] Opens a simple path input dialog (or focuses file tree if open)
- [x] Alternative: `Ctrl+U` toggles file tree with attach mode active

### 7.3 Send Integration

- [x] On submit: if `_pending_files` is non-empty, include in the engine call
- [x] Clear pending files after send

### 7.4 Footer `context_attachments` Badge (new — AppState follow-up)

Textual TUI is in-process with the engine (no SSE, no HTTP), so it
subscribes directly to the AppState observer pattern — same as the Rich
TUI status bar does today.

- [x] Add a `Static` widget in the ppxaide footer layout for the
  attachment badge. Initial text: `""` (hidden when empty).
- [x] In `PPXAIDEApp.on_mount`, subscribe:
  ```python
  self._engine_client.state.on(
      "context_attachments",
      self._on_context_attachments_changed,
  )
  ```
- [x] `_on_context_attachments_changed(entries: list[dict])` handler
  rebuilds the badge text using the same formatting helper as Rich's
  status bar (extract to `ppxai/common/attachment_badge.py` so both TUIs
  share the exact same label rendering — avoid drift between `📎 2 (1🖼 1📄)`
  in one client and a slightly different format in the other)
- [x] Initial snapshot: call the handler once on mount with the current
  AppState value so a restored session shows the badge immediately
- [x] Test: `tests/test_textual_context_attachments.py` — drive the app
  with a multimodal message, assert the footer widget updates
- [x] Consider: click the badge to open a modal listing full filenames
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

## Pre-merge Review Findings (gpt-5.4, session_20260412_192249)

External review on `feat/file-upload` by gpt-5.4 surfaced these issues.
Each was verified against the branch; ranked by user-visible impact.

**Status (v1.17.4):** R1, R2, R3, R4, R6, R7 all fixed in commit `d2d1fd6`
with 9 new regression tests in `test_attach_remove.py` and updated
semantics tests in `test_context_attachments_state.py`. All 2308
tests pass. R5 deferred to v1.18.x per the merge-order plan — it's a
structural schema change that retires R7's workaround.

### R1. `/attach remove` doesn't handle PDF/Office attachments — **correctness gap** 🔴

**Symptom.** User uploads a PDF → badge appears in status bar. User runs
`/attach remove myfile.pdf` → command reports success but badge stays,
the marker remains in context, and the model continues to see the file
on the next turn.

**Root cause.** Tracking and removal use different rules.
[`refresh_context_attachments()`](../ppxai/engine/multimodal_ops.py#L141-L169)
at lines 141-169 scans **both** structured blocks (`image_url`,
`input_file`, `file`) **and** `<uploaded_file>` XML markers embedded
inside `text` blocks. But
[`remove_context_attachment()`](../ppxai/engine/multimodal_ops.py#L244)
at line 244 filters only the structured types:

```python
if btype not in ("image_url", "input_file", "file"):
    kept.append(block)
    continue
```

PDFs and Office files are surfaced as `<uploaded_file name="..." type="..." file_id="..." />`
tags inside text blocks (the "Phase 2.8+" marker convention), so they
silently slip through the `continue` and survive removal.

**Proposed fix.**
1. In `remove_context_attachment()`, add a second pass for `text` blocks
   that contain `<uploaded_file>` markers. Use the same regex as the
   tracker (ideally factored into a shared helper — see R6 below).
2. When a marker matches, either:
   - strip only the marker substring from the text block (preserves any
     user-authored text around it), or
   - if the text block is *only* the marker (+ whitespace), drop the
     entire block.
3. Increment `removed_count` and set `mutated = True` so the
   `on_messages_changed` callback fires and the badge clears.

**Test.** Add a regression test to `tests/test_attach_remove.py` (or
equivalent) with a user turn containing a mix of: text, image_url block,
`<uploaded_file pdf>` marker embedded in text, another text block. Call
`remove_context_attachment(engine, "myfile.pdf")` and assert only the
marker is stripped.

---

### R2. `files: List[FileAttachment] = []` mutable default — **fragile** 🟡

**Location.** [`ppxai/server/models.py:45`](../ppxai/server/models.py#L45)

**Risk.** Pydantic v2 copies the default for each instance so this
doesn't cross-contaminate in practice, but the pattern is easy to
regress when the model is copied, inherited, or ported — and it fails
static-analysis rules the project has been tightening elsewhere.

**Proposed fix.**
```python
from pydantic import BaseModel, Field
# ...
files: List[FileAttachment] = Field(default_factory=list)
```

**Scope.** One line. No behavior change. Add a quick test asserting
`ChatRequest().files is not ChatRequest().files` (different identity).

---

### R3. `_count_csv_rows_cols()` materializes entire CSV in memory — **performance** 🟡

**Location.** [`ppxai/engine/file_preprocessing.py:359`](../ppxai/engine/file_preprocessing.py#L359)

```python
reader = _csv.reader(_io.StringIO(text), delimiter=delimiter)
rows = list(reader)        # ← materializes every row
```

**Risk.** For the exact use case this function exists for (metadata for
*large* CSVs that are persisted rather than inlined), loading every row
into a Python list is the opposite of what we want. A 500 MB CSV
becomes a multi-GB object graph.

**Proposed fix — streaming count:**
```python
reader = _csv.reader(_io.StringIO(text), delimiter=delimiter)
try:
    first = next(reader)
except StopIteration:
    return 0, 0
columns = len(first)
data_rows = sum(1 for _ in reader)   # streaming
return data_rows, columns
```

Same semantics, O(1) memory instead of O(n).

**Test.** Existing tests should pass unchanged. Add a test that counts
rows/cols on a 10 MB synthetic CSV and asserts peak memory stays below
~50 MB (or just asserts the function returns correctly — the memory
assertion is nice-to-have).

---

### R4. `has_vision_model()` naming hides sidecar-vs-model distinction — **clarity** 🟡

**Location.** [`ppxai/engine/multimodal_ops.py:285`](../ppxai/engine/multimodal_ops.py#L285)
+ caller at [`ppxai/server/routes/chat.py::_build_chat_payload`](../ppxai/server/routes/chat.py)

**Risk.** The name reads as "is the active model vision-capable?" but
the implementation checks the VL **sidecar** configuration
(`tools.vision_model` block). When the active model is vision-capable
but no sidecar is configured, the function returns False — which reads
wrong to anyone calling the method by name.

**Proposed fix.** Rename to `has_vision_sidecar()` and update callers:
- `ppxai/engine/multimodal_ops.py` — the definition
- `ppxai/engine/client.py:318` — `EngineClient.has_vision_model` facade
- `ppxai/server/routes/chat.py` — `_build_chat_payload` call site
- any tests

Add a one-line docstring pointer so future readers who grep for the
old name land on the new one.

**Alternative (cheaper).** Keep the name, add an explicit note to the
docstring: *"`has_vision_model` = "is the VL sidecar available?", NOT
"is the active model vision-capable?" For the latter, check
`model_profiles.get_profile(model).supports_vision`."* Lower-effort
but preserves the ambiguity for the next reader.

---

### R5. Uploaded-file metadata lives in free-form text blocks — **design debt** 🟢

**Symptom.** PDFs/Office files are represented as `<uploaded_file>`
XML markers *inside* text blocks rather than as first-class content
types. Tracking, removal, rendering, and serialization all need to
parse the same regex, and any client that forgets to parse it shows
raw XML to the user.

**Proposed fix (medium-term).** Promote uploaded files to a dedicated
content-part type:

```json
{
  "type": "uploaded_file",
  "name": "report.pdf",
  "media_type": "application/pdf",
  "file_id": "sha256:..."
}
```

All four clients (Python engine, Rich, Textual, Web, VSCode) already
normalize content blocks, so adding a type is a schema change + four
rendering updates. Session serialization becomes trivial (no regex).
R1 and R6 collapse into "handle the new type."

**Decision.** Defer to a v1.18.x structural change. Too invasive for
v1.17.4. Track here so we don't forget.

---

### R6. Shared uploaded-file marker helpers — **small refactor, enables R1** 🟢

**Symptom.** The `<uploaded_file ... />` marker regex and format
string live in at least three places: the tracker, the generator in
`file_preprocessing.py`, and (soon) the R1 removal path.

**Proposed fix.** Add to `ppxai/engine/multimodal_ops.py` (or a new
`ppxai/engine/uploaded_file_marker.py`):

```python
UPLOADED_FILE_MARKER_RE = re.compile(
    r'<uploaded_file\s+name="([^"]*)"[^>]*'
    r'type="([^"]*)"[^>]*'
    r'file_id="([^"]*)"[^/]*/>'
)

def format_uploaded_file_marker(name: str, media_type: str, file_id: str) -> str:
    return f'<uploaded_file name="{name}" type="{media_type}" file_id="{file_id}" />'

def parse_uploaded_file_markers(text: str) -> list[tuple[str, str, str]]:
    return [(m.group(1), m.group(2), m.group(3))
            for m in UPLOADED_FILE_MARKER_RE.finditer(text)]
```

Replace the inline regex in `refresh_context_attachments()` and the
inline f-string in whichever preprocessor generates the marker. R1's
removal path consumes the same helpers.

---

### R7. Name-based attachment identity — **non-determinism + false positives** 🔴

**Symptom.**
- User attaches two files that happen to share a display name — e.g.,
  `src/report.pdf` and `archive/report.pdf`, or two `screenshot.png`
  from different folders / browser downloads. Or pastes the same file
  twice in a session before we content-addressed things.
- `/attach remove report.pdf` removes **both** — no way to target one.
- Context-attachment badge shows 1 when there are 2 (dedup collapses
  same-name entries when `file_id` is absent).
- Model sees the "other" file that the user thought they removed.

**Evidence from sessions.** Of the 5 most recent sessions on disk,
only one has any attachment at all (`session_20260405_214711.json`) —
a single `image_url` block with **empty `file_id`**. So the
name-only identity path is exercised in the wild, not hypothetical.
Multi-attachment scenarios haven't been tested enough yet for
collisions to show up empirically, but the code paths make them
inevitable as soon as a user attaches two files with the same name.

**Root cause — three sites, same bug.**

1. **Removal is name-only**
   [`multimodal_ops.py:247-253`](../ppxai/engine/multimodal_ops.py#L247):
   ```python
   block_name = (
       block.get("name")
       or block.get("filename")
       or block.get("file_id")
       or ""
   )
   if remove_all or block_name == name:
       removed_count += 1
       ...
   ```
   `name` arrives as a plain string from the user. No way to pass a
   `file_id` to disambiguate. Same-name collisions remove every match.

2. **Dedup falls back to name when `file_id` missing**
   [`multimodal_ops.py:96`](../ppxai/engine/multimodal_ops.py#L96),
   [`:130`](../ppxai/engine/multimodal_ops.py#L130),
   [`:159`](../ppxai/engine/multimodal_ops.py#L159):
   ```python
   dedup_key = file_id or name
   ```
   Good intent (stable content-addressed identity when we have it),
   but two legacy / pasted blocks that both have empty `file_id` and
   matching `name` collapse into one badge.

3. **Uploaded-file markers have the same weakness**
   (line 159) — `dedup_key = uf_fid or uf_name`. If a PDF is re-generated
   without its file_id surviving (e.g., a session-migration path), two
   `<uploaded_file name="report.pdf" ... file_id="">` markers collapse.

**Proposed fix.**

**Short-term (v1.17.4) — make `/attach remove` file_id-aware:**

1. Extend `remove_context_attachment(engine, name_or_id: str)` to accept
   either a display name or a `file_id`. Match in this order:
   - exact `file_id` match (most specific, unambiguous)
   - if name matches exactly ONE attachment → remove that one
   - if name matches multiple → return a `CommandResult` with status
     `AMBIGUOUS` listing all matches with their file_ids, asking the
     user to re-run with the ID. Do NOT silently remove all.
   - `"all"` keeps current blast-radius behavior.

2. Extend `context_attachments` schema (already a dict) to include a
   short display form of the file_id (first 8 chars is enough for
   human disambiguation):
   ```python
   {"name": "report.pdf", "file_id": "sha256:abc123...", "short_id": "abc123"}
   ```
   So clients can render `report.pdf (abc123)` when there's a collision
   and the user can type `/attach remove abc123` to target one.

3. `/attach` completer (engine/completion.py) should offer both `name`
   and `short_id` tokens when multiple same-name attachments exist.

**Medium-term — guarantee `file_id` presence:**

4. Every block produced by our file pipeline MUST carry a non-empty
   `file_id`. Trace every code path that emits an `image_url` /
   `input_file` / `<uploaded_file>` block and assert it hit `SessionFileStore.save()`
   first. Add a test that fails if any producer emits blocks without
   `file_id`.

5. Once `file_id` presence is guaranteed, flip dedup_key logic from
   `file_id or name` to just `file_id` — and log a warning for any
   legacy block that arrives without one (likely a session restored
   from pre-`file_id` data).

**Test coverage.**

- Unit test: `remove_context_attachment` with two blocks sharing
  `name="report.pdf"` but different `file_id` — assert calling with
  `name` returns `AMBIGUOUS`, calling with either `file_id` removes
  exactly one.
- Unit test: `refresh_context_attachments` with two empty-`file_id`
  blocks sharing `name` — assert **two** badges appear (not
  silently deduped). Or: assert a warning is logged.
- Regression: replay `session_20260405_214711.json` and verify the
  single empty-`file_id` image_url block still renders correctly
  after the dedup policy change.

**Relation to other findings.**
- R1 (PDF/Office removal) and R7 (name identity) compound: fixing R1
  without R7 means `/attach remove report.pdf` works for PDFs AND
  wipes every same-named file.
- R5 (first-class `uploaded_file` content type) naturally carries
  `file_id` as a required field and retires this whole class of bug.

---

### Proposed merge order

Do R2 + R3 + R6 first — small, atomic, low-risk. Then R1 **+ R7**
together on top of R6, because fixing removal for PDFs without also
fixing name-identity creates a bigger footgun than either alone.
R4 and R5 are follow-ups that don't need to land for v1.17.4.

1. **R2** — `Field(default_factory=list)` [trivial]
2. **R3** — streaming CSV count [small, pure function]
3. **R6** — extract marker helpers [refactor, no behavior change]
4. **R1 + R7 together** — fix `/attach remove` parity for PDF/Office
   AND make it file_id-aware with AMBIGUOUS status on name collisions
   [uses R6; add tests for both correctness gaps]
5. **R4** — `has_vision_sidecar` rename OR docstring note [optional]
6. **R5** — first-class `uploaded_file` content type [v1.18.x, retires R7]

---

## Second-pass Review Findings (gemini-3-flash, session_20260412_192249, 21:03)

Re-reviewed after R1–R7 landed. Confirmed R3's streaming goal isn't
fully met yet, plus three smaller risks in session handling. Each
is verified against the branch; none are v1.17.4 release-blockers.

### R8. `_count_csv_rows_cols` still materializes via `_decode_text` — **polish R3** 🟡

**Location.** [`ppxai/engine/file_preprocessing.py`](../ppxai/engine/file_preprocessing.py#L342)

**Symptom.** R3 streamed the row count (O(1) memory for the counting
step), but the function still calls `text = _decode_text(data)` on
the full byte buffer before sniffing the delimiter. For a 10 MB CSV
the decode produces a multi-MB Python string plus whatever intermediate
allocations the codec needs. The memory win is partial.

**Proposed fix.**
```python
def _count_csv_rows_cols(data: bytes) -> tuple[int, int]:
    import csv as _csv, io as _io

    # Sniff on the first 8 KB only — enough for the delimiter heuristic,
    # avoids materializing a full-file string just to peek at it.
    sample = _decode_text(data[:8192])
    try:
        dialect = _csv.Sniffer().sniff(sample)
        delimiter = dialect.delimiter
    except _csv.Error:
        delimiter = ","

    # Stream the actual bytes through TextIOWrapper — csv.reader
    # iterates row-by-row and we never hold the full decoded string.
    stream = _io.TextIOWrapper(
        _io.BytesIO(data), encoding="utf-8", errors="replace"
    )
    reader = _csv.reader(stream, delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        return 0, 0
    columns = len(header)
    data_rows = sum(1 for _ in reader)
    return data_rows, columns
```

**Test.** Count rows on a synthetic 10 MB CSV and assert peak RSS
growth stays under ~15 MB (one buffer, not two). Existing metadata
correctness tests should pass unchanged.

---

### R9. `validate_and_fix_alternation` "longer wins" heuristic can drop tool_calls — **correctness edge** 🟡

**Location.** [`ppxai/engine/session.py`](../ppxai/engine/session.py) — `validate_and_fix_alternation`

**Symptom.** When two consecutive assistant messages are found, the
"longer is better" heuristic picks the one with more text content
and drops the other. But an assistant message carrying structured
`tool_calls[]` may have **empty `content`** (native tool-calling
pattern for several providers) — so a trailing explanatory text
message will always win, and the tool_calls silently disappear.
After serialize/deserialize or alternation repair, a session can
lose pending tool invocations without any warning.

Also: `validate_and_fix_alternation` removes trailing `user`
messages. If a user saves a session right after typing a prompt but
before the assistant responds, the prompt is lost on reload. Rare
but reproducible via `/save` immediately after pressing Enter.

**Proposed fix.**
1. Before picking "longer wins," check each candidate for non-empty
   `tool_calls`. A message with tool_calls is load-bearing regardless
   of text length — prefer it over a plain-text sibling, or better,
   merge them (structured + narrative).
2. For the trailing-user case: either preserve it as a pending prompt
   (and let the next session load auto-send it) or at least log a
   WARNING before dropping, so the regression is visible.

**Test.** Build a session with
`[user, assistant(tool_calls=[...], content=""), assistant("short"), ...]`
— a synthetic alternation violation — and assert the tool_calls
message survives the repair. A second test for the trailing-user
case: save immediately after appending a user message with no
assistant response, reload, assert user turn still present.

---

### R10. `_has_multimodal_attachments` O(N) scan on every save — **micro-perf** 🟢

**Location.** [`ppxai/engine/session.py`](../ppxai/engine/session.py) — `_has_multimodal_attachments`

**Symptom.** Called from `save()` / `save_dirty()` to decide flat vs
directory session format. Walks every content block of every message
on every save. Long conversations (200+ messages, tool-heavy) add
measurable latency to every auto-save, compounding UI stutter in
the TUI and slow roundtrips in web/VSCode.

**Proposed fix.**
Cache the result on `Session`, invalidate in exactly two mutation
paths:
- `add_message` — if the new message contains multimodal parts,
  flip the cache to True (never scans)
- `remove_last_message` / `clear` — invalidate to `None` (recompute
  lazily on next save)

The cache defaults to `None` on load so existing sessions get one
scan on first save and then O(1) forever.

**Test.** Monkeypatch `_has_multimodal_attachments` with a call
counter, build a 500-message session with one image attachment
early on, call `save()` 20 times, assert the underlying scan ran
at most twice (once on first save, once if attachments were
removed in between).

---

### R11. Session format transition is not atomic — **crash-edge** 🟢

**Location.** [`ppxai/engine/session.py`](../ppxai/engine/session.py) — `_write_session_json`

**Symptom.** When a session gains its first multimodal attachment
mid-conversation, the writer transitions from flat `sessions/<name>.json`
to directory `sessions/<name>/session.json`. The current sequence is
roughly:

1. Create `sessions/<name>/` directory
2. Write `sessions/<name>/session.json`
3. Write attachment files into `sessions/<name>/uploads/`
4. Unlink old `sessions/<name>.json`

A crash (power loss, SIGKILL, filesystem issue) between any two
steps leaves the user with **both** a flat session and a directory
session sharing the same name. The session list UI then shows two
entries, and it's ambiguous which one `/load <name>` picks.

**Proposed fix.**
Two options:

1. **Atomic move.** Write to `sessions/<name>.tmp/`, then `os.rename`
   to `sessions/<name>/` (atomic on POSIX for same-filesystem renames),
   then unlink the flat file. Reorders the sequence so the only
   observable intermediate state is "old flat still present, new
   dir not yet visible" — which the load path already handles by
   preferring the flat file when both exist (confirm this is true).

2. **Reject duplicates on load.** If both formats exist for the same
   name, log a WARNING and pick the newer one by mtime. Cheap belt
   even if (1) lands — protects against prior corruption from existing
   installations.

Ship (2) first (one-line safety net), then (1) as the proper fix.

**Test.** Mock out `Path.unlink` to raise after the directory write
succeeds, call save on a session transitioning formats, assert the
next load picks the directory version and logs a warning about the
orphan flat file.

---

### R12. Silent gaps during agentic tool loops — **architectural UX** 🟢

**Location.** [`ppxai/engine/chat.py:584`](../ppxai/engine/chat.py#L584),
inside `while iteration < max_iterations`:

```python
async for event in ctx.provider.chat(messages, ctx.model, stream=False, tools=openai_tools):
```

**Symptom.** During a multi-step tool-calling loop (gemini-3-flash,
gpt-5.4-mini, long refactor tasks) the UI shows tool_call / tool_result
events executing but **no model prose** between iterations. The user
sees 5–15 second silent waits between tool bubbles. Model IS producing
explanatory text ("I'll now examine the config file..."), but the
engine captures it as part of `full_response`, parses the tool JSON
out of it, and discards the rest before looping. Nothing reaches the
UI's stream-chunk renderer.

After R1–R11 land, this is the single biggest remaining UX complaint
for long agent sessions.

**Why the engine does this.** At the end of each iteration the engine
needs to decide:
1. Did the model emit any `tool_calls`? → execute, loop again.
2. Or is this the final answer? → exit loop, yield to UI.

That decision needs the **complete response** + **complete tool_calls
array**. With `stream=False` the provider buffers internally and hands
the engine one atomic `STREAM_END` — branching is trivial. With
`stream=True` the engine would have to accumulate chunks, watch for
interleaved tool_call fragments (OpenAI streams tool call arguments
as JSON fragments), distinguish prose from tool-call JSON,
and route text upstream while holding tool_calls until iteration
end. That's 60–100 lines of state machine per provider adapter.

**Three fix options, increasing effort.**

**Option 1 — Forward intermediate prose via an event.**
After each iteration the engine already has `full_response` with tool
JSON stripped. Emit it as `STREAM_INTERMEDIATE_TEXT` (or reuse
`STREAM_CHUNK` with the whole chunk). UI renders it as a preamble
message or appends to a running assistant bubble. Engine stays
`stream=False` — no provider changes.
*Effort:* ~50 lines in `chat.py`, ~20 in `stream_handler.py`.
*Trade-off:* still silent DURING the iteration (15s wait), but
prose appears right after each tool completes.

**Option 2 — Stream the final iteration only.**
Engine detects "this iteration emitted no tool_calls" and re-runs
with `stream=True` for the user-visible part. But the engine doesn't
know an iteration is final until after the call — requires a
two-pass or speculative approach.
*Effort:* ~100 lines, tricky edge cases around re-entering provider
calls.
*Trade-off:* full answer streams char-by-char (good), tool-iteration
prose still missed (same as Option 1).

**Option 3 — Full streaming tool loop.**
Provider adapters emit interleaved `STREAM_CHUNK` +
`TOOL_CALL_DELTA` + `TOOL_CALL_COMPLETE` events. Engine consumes a
stream, keeps a per-tool-call accumulator, fires `TOOL_CALL` when one
completes. UI gets real-time text throughout.
*Effort:* ~60–100 lines per provider × 5 (OpenAI, OpenAI native,
Gemini, Perplexity, OpenAI-compat). Plus end-to-end multi-turn
tool-loop tests per provider.
*Trade-off:* right fix, highest risk, needs a test harness we don't
yet have for interleaved streaming.

**Proposed.**
Ship **Option 1 in v1.17.5 or v1.17.6** — cheap, high-ratio UX win,
zero provider changes. Plan **Option 3 for v1.18.x** as a dedicated
provider-adapter sweep with a new multi-turn test harness. Option 2
skipped — halfway solution that doesn't justify the complexity.

**Test for Option 1.**
Build a session that triggers 2 tool iterations where the model
produces both tool_calls AND intermediate prose on the first
iteration. Assert the UI (or mock event recorder) receives a text
event between `TOOL_GROUP_END` of iteration 1 and `TOOL_GROUP_START`
of iteration 2.

---

### Proposed merge order (updated)

R1 + R7 already landed. R2, R3, R4, R6 already landed. Remaining
items targeted for v1.17.5 at the user's request:

| # | Priority | Effort | Target |
|---|---|---|---|
| **R8** | 🟡 polish R3 | ~30 min + test | v1.17.5 |
| **R9** | 🟡 correctness edge | ~1 hr + 2 tests | v1.17.5 |
| **R10** | 🟢 micro-perf | ~30 min + test | v1.17.5 |
| **R11** | 🟢 crash-edge | ~1 hr (option 2 then 1) | v1.17.5 |
| **R5** | 🟢 schema change, retires R7 | ~3 hr + cross-client sweep | v1.17.5 |
| **R12** (Opt 1) | 🟢 UX progress signal | ~1 hr + test | v1.17.5 or v1.17.6 |
| **R12** (Opt 3) | 🟢 full streaming tool loop | ~1 day + test harness | v1.18.x |

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
