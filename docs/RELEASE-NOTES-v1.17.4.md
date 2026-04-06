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
- **PPTX tools** — `list_pptx_slides` (slide inventory with shape type counts) and `read_pptx_slide_text` (text + tables as markdown)

### Model & Config Management (Phase 2.3-2.7)
- **`supports_vision` flag** on ModelProfile — set for GPT-5.x, GPT-4.x, Gemini 2.5/3/3.1, Gemma 4, Sonar/Sonar Pro, and local VL models (qwen3-vl, llava, pixtral, minicpm-v)
- **Gemma 4 family** added — 31B dense, 26B MoE, E4B edge, E2B edge. Free tier via Gemini API. Vision + audio capable.
- **Gemini 3.1 Flash Lite** added — cheapest Gemini 3 tier
- **Deprecation tracking** — gemini-3-pro-preview removed (shut down 2026-03-09), 2.0/2.5 models flagged with shutdown dates
- **`/doctor`** — read-only config advisor scanning for dead/deprecated/new models with days-remaining countdowns and migration recommendations
- **VL sidecar config** — `tools.vision_model` section for auto-captioning images on text-only models via an external VL endpoint

### Cross-Client Features (Phases 5-7)
- **Web app** — paperclip button, drag-drop zone, attachment badges strip, send with files via POST /chat
- **VSCode extension** — webview file picker, drag-drop, attachment badges, sends files through httpClient
- **Textual TUI** — file tree `a` key to attach, `Ctrl+U` shortcut, send integration with multimodal content, footer StatusBar badge
- **AppState `context_attachments`** — canonical cross-client field pushed via SSE state_sync. All 4 clients subscribe to it for their attachment badge/chip UI.

### Autocomplete (Phase 1 + Task #11)
- **Dynamic command discovery** — replaced hardcoded 27-entry COMMANDS list with live CommandFactory reader (56+ entries). New commands auto-appear in tab completion.
- **Shell-style path completion** — `/attach`, `/cd`, `/ls`, `/tree`, `/show`, `/preview` complete file/directory paths with per-command filters, alias resolution, sub-path navigation
- **CompletionProvider extraction** — `engine/completion.py` shared across all clients. `POST /complete` server endpoint for web/VSCode.

## Bug Fixes
- **`/save <name>` now honors the name argument** — was silently ignoring the user's chosen name
- **`/save` warns about unsent attachments** — staged files from `/attach` that haven't been sent yet are not included in the save; the user gets a clear warning
- **`/ls <file>` shows file entry** — matches shell `ls` semantics; was returning "Not a directory" error
- **Image validation rejects fake images** — a .png file containing non-image bytes is caught at attach time with a clear "Unrecognized image format" error

## Dependencies
- `pypdf>=4.0` — PDF text extraction
- `pdf2image>=1.17` — PDF page rasterization (+ poppler system dependency)
- `openpyxl>=3.1` — Excel reading
- `python-pptx>=1.0` — PowerPoint reading

All in the `[data]` optional extras group: `pip install 'ppxai[data]'`

## Test Coverage
- **Starting point:** 1,753 tests
- **Final count:** 2,218 tests
- **New tests:** 465
- **Regressions:** 0
- **Skipped:** 2 (poppler-dependent, platform-specific)
