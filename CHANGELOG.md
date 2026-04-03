# Changelog

All notable changes to ppxai will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.17.3] - 2026-04-03

### Added

- **CodeMirror modular architecture** — replaced 5 monolithic bundles (6.3MB, each bundling full CM core) with shared `core.min.js` (411KB, loaded once) + 30 per-language addons; lazy-loaded on first use
- **30 editor languages** — native: Python, JavaScript, JSON, YAML, Markdown, HTML, CSS, SQL, Rust, Go, Java, C/C++, XML, PHP; legacy modes: Shell, TOML, Dockerfile, Ruby, Perl, Lua, Swift, R, Kotlin, Scala, PowerShell, Diff, Protobuf, Nginx, CMake, Properties
- **Verbose Tools toggle** — menu indicator in web app `⋮` menu with green-dot active state; SSE `state_sync` push for `tools_verbose` and `debug_log` fields
- **Benchmark K8s jobs** — `--agents-md` toggle, delta test results, in-cluster benchmark runs
- **New models benchmarked** — Qwen3.5-122B-A10B-NVFP4, Qwen3.5-27B-FP8, Qwen3-Coder-Next-NVFP4-GB10

### Fixed

- **DataFileView and MarkdownFileView** — updated to new modular `cm6.newEditor()` API with language parameter; edit mode now gets proper syntax highlighting for JSON, YAML, TOML, Markdown
- **CodeMirror per-language cache** — each language addon self-registers into `cm6.langs`; switching between files in different languages preserves correct syntax highlighting
- **Filename-based language detection** — `Makefile` → shell, `Dockerfile` → dockerfile, `CMakeLists.txt` → cmake
- **Heartbeat stream abort** — skip health failure counting while `isStreaming` is true (single-worker uvicorn can't serve `/health` during LLM streaming)
- **Helm ingress** — skip ingress on upgrade, re-add rule on existing session login, field manager conflict fix, raw REST API for server-side apply
- **Preview relative URLs** — poll and asset paths use relative URLs for K8s ingress compatibility

### Changed

- **TODO consolidation** — 11 files → 2 active (`TODO-appstate-codegen.md`, `TODO-routing.md`) + 4 archived; all open items retargeted to v1.18.x
- **ROADMAP** — added v1.17.0/v1.17.1/v1.17.2 completed sections, v1.18.x planned section
- **Tool failure hints** — improved AGENTS.md hints for tool calling reliability

## [1.17.2] - 2026-03-27

**Focus:** AppState alignment across all 5 clients, thread-safety, SSE state sync, iTerm2 image rendering

### Added

- **SSE state_sync push** — engine pushes `STATE_SYNC` events via SSE side-channel when key AppState fields change (provider, model, tools, agent_mode, working_dir, session_name); web app and VSCode extension update local state automatically
- **Event router pattern** — `EventHandler` and `TUIEventHandler` use strategy dispatch dicts for O(1) event lookup instead of if/elif chains

### Fixed

- **AppState thread-safety** — listeners dispatch outside the lock (was inside RLock); event queue protected by threading.Lock with `enqueue_event()`/`drain_events()` API; fixes race between SSE drain loop and AppState observers
- **Rich TUI AppState alignment** — `get_status_line()` reads all state through AppState; `restore_session_to_handler()` relies on atomic AppState update; `agent_mode` reads from state consistently across Rich and Textual TUI
- **HTTP server AppState alignment** — `GET /status` returns `state.snapshot()`; all provider/model/tools reads in routes use `state.get()`; `ServerCommandContext` reads from `engine.state`
- **ppxaide iTerm2 image rendering** — was incorrectly assigned Kitty Graphics Protocol (TGP); now uses native iTerm2 inline image protocol (OSC 1337) via `ITerm2ImageWidget`
- **ppxaide image display without PIL** — `ITerm2ImageWidget` reads PNG/JPEG/GIF dimensions from file headers via `struct` when Pillow isn't installed; `ImageHandlerFactory` accepts native widget without `textual-image` dependency
- **ppxaide file tree sync** — AppState `working_dir` observer now updates file tree widget; `/cd`, session restore, and engine tool changes all propagate to the file browser
- **Preview `--serve` venv detection** — auto-detect checks `venv/bin/python` and `.venv/bin/python` before falling back to bare `python3`
- **Preview single-quoted commands** — `/preview --serve 'python main.py'` now works alongside double-quoted syntax

### Changed

- **All 17 AppState fields wired** — session usage (tokens, cost, context%) synced via `session.on_usage_updated` callback; session_name via `on_name_changed`; debug_log via Textual toggle
- **Event queue renamed** — `_consent_event_queue` → `_event_queue` with thread-safe `enqueue_event()`/`drain_events()` API
- Removed 16 unused imports across engine, Rich TUI, and Textual TUI modules

## [1.17.1] - 2026-03-23

**Focus:** AppState convergence, web terminal, preview hardening, server dependency injection, client.py decomposition

### Added

- **AppState** (`ppxai/engine/app_state.py`) — canonical observable application state with `subscribe()`/`notify()` pattern; wired into EngineClient, CommandHandler, Textual TUI, Web app, and VSCode extension; 243 unit tests
- **Web terminal** — interactive xterm.js terminal with PTY WebSocket backend; `/terminal`, `/term`, `/sh` commands in web and VSCode clients
- **Preview `--serve` flag** — full-stack preview launches backend process alongside frontend; `ppxai-desktop` serves previews with live backend
- **Preview `--proxy` flag** — K8s full-stack preview via reverse proxy through ingress path prefix
- **Preview K8s ingress detection** — automatic reverse proxy path prefix for K8s ingress compatibility
- **80 new tests** — ops modules (`session_ops`, `provider_ops`, `tool_ops`, `context_ops`) and server routes; graph-analysis-driven coverage

### Fixed

- **Preview route collision** — previewing files in `static/` directories no longer collides with the static file mount
- **Preview absolute URLs** — poll and asset paths in subdirectories now use absolute URLs instead of broken relative ones
- **Preview helpful 404** — previewed HTML making API calls to the preview server now gets an actionable error instead of silent failure
- **Preview python→python3** — macOS compatibility fix; backend stderr surfaced on failure
- **SSE keepalive** — reduced from 15s to 5s to prevent false disconnect detection in browsers
- **Consent route crash** — undefined `x_session_id` variable in consent route handler
- **Sessions route** — variable collision in `get_sessions` route
- **Web preview iframe** — URL encoding and sandbox warning fixes
- **Terminal WebSocket 403** — event loop fd reader for PTY output; HTTP middleware now skips WebSocket upgrades
- **Lazy imports** — 3 + 2 remaining lazy imports moved to module level (DAG compliance)
- **Swallowed exceptions** — logging added to 8 previously silent exception handlers

### Changed

- **`client.py` decomposition** — monolith split into ops modules: `session_ops.py`, `provider_ops.py`, `tool_ops.py`, `context_ops.py`; client.py reduced to facade
- **FastAPI dependency injection** — session resolution extracted from route handlers into FastAPI `Depends()` dependencies
- **`reload_config` consolidation** — scattered reload calls consolidated into `get_or_create_session`
- **`stream_handler.py` extraction** — stream handling logic extracted from Textual `app.py`
- **`constants.Default` centralization** — magic numbers (keepalive interval, debounce delay, max retries, etc.) moved to `constants.Default` enum
- **`CommandContext.__getattr__` proxy** — adapter boilerplate in command handlers replaced with attribute proxy
- **Web command help** — updated for `/terminal`, `/preview --serve`/`--proxy`, `/config` commands

## [1.17.0] - 2026-03-19

**Focus:** Server/config modularization, K8s deployment POC, key bindings registry, Textual 8.1.1, import DAG cleanup

### Added

- **Server modularization** — `http.py` (2,936 lines) split into 13 route modules under `server/routes/` + shared `state.py`, `models.py`, `streaming.py`; facade reduced to 372 lines
- **Config modularization** — `config/__init__.py` (943 lines) split into `providers.py`, `tools.py`, `features.py`, `paths.py`, `prompts.py`, `context.py`; hub reduced to 262 lines
- **K8s deployment POC** (phases 1-5) — namespace, StorageClasses, in-cluster registry, Kaniko builds, session manager (FastAPI + k8s SDK), login service, LDAP auth, Helm chart
- **Key bindings registry** (`ppxai/tui/keys.py`) — single source of truth for all 32 keyboard shortcuts; widget BINDINGS generated via `get_widget_bindings()`; `/keys` and `/keys conflicts` commands
- **Protocol-based dependency inversion** — `ToolEngineProtocol` and `ToolManagerProtocol` in `engine/types.py`; all 9 tool modules use direct protocol imports instead of TYPE_CHECKING
- **Client log forwarding** — server-side log forwarding from web/VSCode clients
- **Web heartbeat watchdog** — stale connection detection
- **Benchmark: qwen2.5-coder-7b** — LM Studio eval (69.4% / 72.2% with AGENTS.md); multi-model routing plan
- **Shared deploy configs** — `deploy/shared/` with AGENTS.md and ppxai-config for k8s deployments
- **AppState architecture docs** — 6-part TODO series for cross-client state management

### Fixed

- **Web streaming layout thrashing** — RAF-based rendering prevents layout recalculation storms
- **Preview panel freeze on display_file** — concurrent file display requests handled properly
- **Preview URLs for reverse proxy** — all URLs now relative (works behind ingress path prefix)
- **Stale session detection** — verifies pod exists before returning "existing"
- **Tool fixes** — container.py and display.py error handling improvements

### Changed

- **Textual 8.1.1** — upgraded from 7.4.0 (DirectoryTree threading fixes, weak-ref DOM, GC improvements)
- **Lazy import cleanup** — ~70 imports moved to top-level across 30+ files; all 14 TYPE_CHECKING blocks eliminated
- **install.ps1** — Windows installer rewritten
- **VSCode extension** — chatPanel and httpClient improvements
- **display-only ctrl+enter** — replaced empty action string hack with explicit `action_noop()`

## [1.16.2] - 2026-03-07

**Focus:** Web app RightPanelFrame, file tree sidebar, inline images, web refactor, server fixes

### Added

- **Web app: RightPanelFrame** — view stack navigator with LRU eviction, dedup, back/forward navigation, pin, and position indicator; full Playwright coverage (34 tests)
- **Web app: view types** — `CodeEditorView` (unified view/edit with CodeMirror 6), `MarkdownFileView` (rendered/source/edit), `DataFileView` (table/tree for CSV/JSON/YAML/TOML/HCL), `ImageFileView` (click-to-zoom), `PdfFileView` (embedded iframe)
- **Web app: collapsible file tree sidebar** — VSCode-style browser; lazy-load via `/files/list`, drag-to-resize, left-click preview, right-click `@file` inject, `localStorage` state persistence; `..` parent entry at top, double-click dir to cd into it, right-click dir to cd here; `/files/list` response includes `at_fs_root` flag
- **Web app: inline image preview** — images in chat bubbles render inline; click to open lightbox zoom overlay
- **Web app refactor** — `ApiClient` for all fetch calls, `CommandDispatcher` (slash command routing), `StreamHandler` (proper buffer/RAF rendering), `AppState` (centralised state), virtual scroll (60-message window)

### Fixed

- **Web app: side panel saves to wrong path** — `/files/read` returned `path.name` (basename); now returns relative path from working dir; `app.js` prefers original `filepath` over `data.filename` in editor
- **Validator false positive on apology** — `_claims_success()` now returns `False` immediately when response contains apology phrases ("apologies", "you are right", "I missed", etc.)
- **Inline `<think>` block parsing** — Qwen3 via vLLM: inline thinking blocks now routed to `REASONING_CHUNK` events instead of leaking into response text
- **Three post-release bugs** — `Key.ctrl` binding removed (Textual deprecation), `initResizeHandle` null crash when sidebar element missing, stale file tree paths after working dir change
- **Stale session pointer** — last-session pointer now cleared if session file has been deleted
- **Absolute/home paths in file API** — `/files/list` and `/files/tree` accept absolute paths and `~`-prefixed paths
- **Default working dir** — engine working dir now initialised to `Path.home()` on session creation (fixes binary CWD being `/`)
- **Redundant `set_model` calls** — `/provider` switch no longer triggers 3–4 redundant `set_model` calls
- **File tree refresh storm** — `working_dir_changed` events debounced (300ms); session restore no longer triggers multiple `/files/list` calls
- **Validator false positive: success-after-retries** — `_check_success_after_failure` now only flags when the *most recent* tool call failed; earlier failures in a retry sequence no longer cause false `claim_contradicts_result` errors
- **Shell: configurable shell binary and login mode** — new `tools.shell.shell_bin` (e.g. `"/bin/zsh"`) and `tools.shell.login_shell` (bool) config keys; setting `login_shell: true` invokes the shell with `-l` so the full user environment (PATH, nvm, pyenv, etc.) is sourced, matching the user's interactive terminal
- **Inline image disappears after stream_end** — `stream_end` now appends inline image markdown to the server's text response rather than overwriting `fullContent`
- **Redundant display_file tool result bubble** — `showToolResult` now skips the bubble when `data.tool === 'display_file'`; image is already visible inline and non-image files open in RightPanelFrame
- **Stale expandedDirs after cd** — `FileTreeComponent.refresh(clearExpanded=true)` collapses old subpaths on working dir change, eliminating 404 storms and doubled path segments
- **File tree flickers on every chat send** — `working_dir_changed` debounce now skips refresh when path hasn't changed; session restore replays the same cwd causing needless `refresh(true)` calls
- **AI text inserted above inline image** — `stream_end` now renders inline images before the AI text response, matching the order shown during streaming

### Changed

- **Default models updated** — `ppxai-config.json`: sonar-pro (Perplexity), gemini-3-flash-preview (Gemini), gpt-4.1-mini (OpenAI default), gpt-5.1-codex-mini (OpenAI coding)
- **AGENTS.md** — Qwen3-4B model hints added; provider hints expanded for `local`, `asusai-vllm`, `openai`, `gemini`; global preferences reorganized

## [1.16.1] - 2026-03-01

**Focus:** FileTree browser, CommandFactory server pattern, unified session restore, pre-release tech debt

### Added

- **FileTree widget** (`ppxai/tui/widgets/file_tree.py`) — Norton Commander-style file browser in ppxaide; `Ctrl+B` toggle, `Enter` preview, `Ctrl+Enter` edit, `Space` injects `@file:path` into chat input; 28 unit tests
- **CommandFactory server pattern** — `POST /command` HTTP endpoint routes to same `CommandFactory` used by TUI/CLI; `/usage` unified across TUI, VSCode, and Web clients
- **`EngineClient.restore_session()`** — single authoritative session restore covering provider, model, tools, and working_dir; fixes JSON-RPC client never restoring provider/model

### Fixed

- `TypeError: 'bool' object is not iterable` in Codex Responses API (`_non_stream_responses` iterated `item.content` which can be `True`)
- SSE exception handlers now log full traceback unconditionally; `sse_coding_task_generator` had no exception logging at all
- Pre-flight `validate_and_fix_alternation()` before provider call — prevents recurring 400 errors from Perplexity and other strict providers on malformed session history
- `ppxai-server` binary crash on startup (`prompt_toolkit` was incorrectly excluded from PyInstaller spec)
- Side panel silently discarded unsaved edits on close — now prompts to save
- `Ctrl+Enter` in FileTree blocked by app-level priority submit binding
- Duplicate provider/model switch log entries
- `STREAM_START` event missing in some `chat_simple` code paths
- `GeminiProvider` deprecated `thinking_budget` → `thinking_level`

### Changed

- Lazy imports eliminated from `engine/context.py`, `engine/session.py`, `server/http.py`, `server/jsonrpc.py`, and Rich TUI client modules (DAG-style imports throughout)
- 6 regex patterns replaced with more robust alternatives: filename detection handles dotfiles + multi-dot names; markdown link parser uses bracket/paren depth counting; success-claim detection uses keyword set + proximity window; tool JSON detection uses `_find_json_objects()`; Rich markup stripping preserves citation markers `[1]`/`[2]`; inline formatter uses linear pass (code > bold > italic priority)
- `RichRenderer` gains `ConsentResult` and `PromptResult` renderers (were silently missing)

## [1.16.0] - 2026-02-26

**Focus:** Profile-driven tool loop, multi-tool support, agent UI improvements, benchmark v2

This release rewrites the core tool calling loop in `chat.py` with profile-driven routing,
proper `tool` role messages, multi-tool support, and grouped tool call UI across all 4 clients.
154 files changed, 30,400+ lines added. 1,536 tests passing.

### Added - Provider Hierarchy (Step 1)

- **`BaseProvider` ABC** — all providers inherit shared interface; `hasattr` guards eliminated
- **`get_capabilities_for_model()`** — guaranteed method on all providers
- **61 provider hierarchy tests** (`test_provider_hierarchy.py`)

### Added - Profile-Driven Tool Loop (Step 2)

- **Profile-driven mode routing** — `ToolCallingProfile.mode` ("native", "prompt_based", "auto") replaces binary `native_tool_calling` decision; provider capabilities gate native mode
- **Fallback on empty/failure** — configurable retry with prompt-based messages when native returns empty or unknown tool
- **Belt-and-suspenders** — models with fallback flags get tool descriptions injected into system prompt even in native mode
- **Truncation recovery** — raw JSON truncation detection, escalating recovery messages, `MAX_TRUNCATION_RETRIES=3` cap with `stuck_tool_loop` WARNING event
- **27 profile routing + truncation tests** (`test_chat_profile_routing.py`, `test_engine_tool_parsing.py`)

### Added - Proper Tool Messages (Step 3)

- **Native `tool` role messages** — `assistant` (with `tool_calls` field) + `tool` role result messages replace synthetic assistant/user pairs
- **`Message` type extended** — `tool_calls` and `tool_call_id` fields on `Message` dataclass
- **All 4 providers updated** — `_convert_messages()` handles `tool` role in base, openai_native, openai_compat, gemini
- **Session serialization** — save/load handles new fields; v1.15.x sessions load via `None`-safe `.get()`
- **28 tool message tests** (`test_tool_messages.py`)

### Added - Multi-Tool Support (Step 4)

- **All native tool calls processed** — `for tc in tool_calls_list` replaces `native_tool_calls[0]`
- **`parallel_tool_calls` gating** — profile flag controls whether all or only first tool call is processed
- **Sequential execution** — per-tool consent and loop detection for each call in a batch

### Added - Agent UI Noise Reduction (Step 5)

- **`TOOL_GROUP_START`/`TOOL_GROUP_END` events** — engine wraps each iteration's tool calls for client-side grouping
- **`AGENT_COMPLETE` event** — emitted after tool loop with iteration count and commit hash
- **Web app** — collapsible `.tool-group` containers, checkpoint bubble suppression, undo badge only on commits
- **VSCode extension** — tool group forwarding and CSS styling
- **ppxaide TUI** — non-verbose summary mode (one line per group); verbose mode unchanged
- **ppxai Rich CLI** — dim separator lines with iteration number and status
- **SSE event type dispatch fix** — side-channel events emit correct EventType (was all `consent_request`)
- **Consent deadlock fix** — SSE generator uses racing poll pattern instead of `async for`

### Added - Config Integration (Step 6)

- **Per-model `tool_calling` overrides** — 3-layer precedence: built-in profile → AGENTS.md → ppxai-config.json
- **AGENTS.md `tool_calling` YAML section** — glob-pattern matching for model-specific tool calling config
- **`/model info` command** — shows effective profile with source attribution per field
- **16 config + bootstrap + profile merging tests**

### Added - Benchmark v2 (Step 7)

- **36 tests across 9 categories** — hallucination_resistance, tool_calling, code_editing, format_compliance, instruction_following, reasoning, error_recovery, agentic_tool_loops, efficiency
- **8 new agentic tests** — `patch_apply_verify`, `search_then_edit`, `fix_verify`, `information_gathering`, `error_recovery_chain`, `multi_file_review`, `claim_without_action`, `consecutive_tool_loop`
- **Efficiency metrics** — `time_to_first_tool_call`, `tool_call_efficiency` scoring by redundant calls
- **Partial credit scoring** — `score` field (0.0-1.0) with per-test weighting
- **`_dedup_tool_call()` helper** — returns feedback for duplicate tool+args in multi-turn tests
- **AGENTS.md delta testing** — `--agents-md both` mode runs suite twice and reports per-category delta
- **Token/tool call tracking** — `total_tokens`, `total_tool_calls` in `BenchmarkResult.metadata`
- **29 models ranked** across 100+ benchmark runs

### Added - Commands

- **`/ls` command** — directory listing in all 3 clients (ppxaide TUI, Web, Rich CLI)
- **`/tree` command** — directory tree in all 3 clients
- **`GET /files/list`** and **`GET /files/tree`** HTTP endpoints for IDE integration

### Added - Session Management

- **Session context reset on model switch** — `session.reset_for_model_switch()`
- **Per-model iteration limits** — `ModelProfile.max_tool_iterations` field consulted by `chat.py`
- **Session pollution detection** — bigram similarity >90% triggers WARNING after iteration 1
- **SSE disconnect detection** — `request.is_disconnected()` in `sse_event_generator`

### Changed

- **Sonar model profiles** — all sonar profiles changed to `mode="prompt_based"` (matching Perplexity API capabilities)
- **Sonar/Perplexity AGENTS.md hints** — rewritten for prompt-based tool calling
- **Gemini 3.1 model profiles** — tier S→A, `max_tool_iterations` 25→20, `strip_json_from_text=True`
- **Default models** — optimized for cost and new-user experience
- **`contradiction_detection` test** — check acknowledgment patterns before contradictions (fixes negation false positives)

### Fixed

- **Tool usage tracking** — accumulated usage now includes tool call costs in final STREAM_END metadata
- **Provider pricing** — corrected pricing across all provider configs
- **ppxaide binary** — fixed missing tree-sitter syntax highlighting in PyInstaller build
- **Usage report** — fixed missing prompt/completion token breakdown

---

## [1.15.6] - 2026-02-19

### Added - Native OpenAI Provider

- **`OpenAINativeProvider`** (`ppxai/engine/providers/openai_native.py`) — Standalone provider for OpenAI API
  - Chat Completions API for GPT-4.1, GPT-5.x, o-series models
  - Responses API for Codex and Pro models (gpt-5.1-codex, gpt-5.2-pro)
  - Automatic `max_completion_tokens` handling for GPT-5.x and o-series
  - Restricted generation param stripping (temperature, top_p rejected by newer models)
  - Reasoning token extraction for o-series models
  - Native function calling with streaming tool call assembly
  - 404 auto-fallback: Chat Completions → Responses API when model isn't a chat model
  - Web search via `web_search_preview` tool (Responses API, opt-in)
- **46 unit tests** for native OpenAI provider (model classification, message conversion, streaming, error handling, prompt-based routing)
- **AGENTS.md hints** for OpenAI provider and model-specific hints (gpt-5.2, gpt-5, gpt-4.1, o4-mini, codex)

### Added - Model Profile System (Foundation for v1.16.0)

- **`model_profiles.py`** (`ppxai/engine/model_profiles.py`) — `ToolCallingProfile` and `ModelProfile` dataclasses encoding per-model tool calling strategy, API routing, max_tokens, and benchmark tier
- **`ModelProfileRegistry`** — Glob-pattern matching registry (case-insensitive, first match wins)
- **37 built-in profiles** covering all benchmarked models: OpenAI (14), Perplexity (5), Gemini (5), DGX/vLLM Qwen3 (5), Ollama Qwen (3), GPT-OSS (1), legacy GPT-4o (2), reasoning o-series (5)
- **`get_model_profile()`** method added to `BaseProvider`, `OpenAINativeProvider`, and `GeminiProvider` (scaffolding for v1.16.0 profile-driven tool loop)
- **41 model profile tests** — profile matching, glob patterns, shadowing prevention, tier validation, data integrity

### Added - Tool Call Parser Improvements

- **Brace-counting JSON parser** (`_find_json_objects()`) — Replaces regex-based extraction; correctly handles nested braces in `apply_patch` diffs containing code with `{` and `}` characters
- **`strip_tool_json_from_text()`** — Strips duplicate tool call JSON from response text when native `tool_calls` are present (Gap 4: tool_json_in_content anti-pattern), also strips surrounding markdown code fences
- **`detect_truncated_tool_call()`** — Detects "I'll use X tool" + incomplete JSON patterns for targeted retry feedback

### Added - Benchmark System Improvements

- **Benchmark results** for 27 model variants (54+ runs across 7 categories, 26 tests each)
- **Model behavior analysis** (`docs/MODEL-BEHAVIOR-ANALYSIS.md`) — 5 behavior tiers (S/A/B/C/D), per-category scores, 5 architectural gap findings
- **`--tool-calling-method`** CLI flag — Force `native`, `prompt_based`, or `auto` mode per benchmark run
- **`--debug`** flag — Saves per-request JSON to `debug/` with full AI response content, tool_calls, and errors
- **Profile-aware benchmark runner** — Consults `ModelProfile` for native vs prompt-based routing
- **Engine bypass** — Benchmark runner calls provider directly, avoiding engine tool conflicts
- **Prompt-based scoring fix** — `tool_json_in_content` penalty removed for prompt-based mode (expected behavior)

### Added - Packaging

- **Windows ZIP packager** (`scripts/package-windows-zip.ps1`) — Creates offline deployment ZIP with binaries + web UI for air-gapped environments

### Added - Response Validation & Debug Improvements

- **Read-claim validator** (`_check_read_claims_without_tools()` in `validator.py`) — Detects "I read each file" / "reviewed all files" claims when 0 `read_file` tool calls were made; 6 regex patterns + 5 tests
- **Truncation retry `[SYSTEM: ...]` framing** — Retry messages now use system framing instead of conversational text to prevent models from misinterpreting retries as conversation

### Changed

- **OpenAI provider registration** — `openai` provider now uses `OpenAINativeProvider` instead of `OpenAICompatibleProvider`; openrouter, local, custom providers unchanged
- **`PROMPT_BASED_MODEL_PREFIXES`** — Renamed from `PROMPT_BASED_MODELS`, changed from exact match (`in`) to prefix match (`.startswith()`) so dated model IDs like `o4-mini-2025-04-16` get correct prompt-based routing
- **Benchmark engine runner** — Loads AGENTS.md hints from all scopes (global, project, subdir) matching real client behavior
- **Retired Gemini 2.0 Flash models** — Removed from default config (expired preview models)
- **gpt-5-nano max_tokens** — Increased from 2048 to 8192 to prevent empty synthesis after tool iterations
- **codex-mini tuning** — Profile: added `strip_json_from_text`, `fallback_on_empty`, `restricted_params`, tier C→B; AGENTS.md: anti-hesitation hint; config: `max_tokens: 16384`
- **gemini-3-pro tier** — Changed S→A (best benchmark 73.1%, below S threshold of 80%)

### Fixed

- **AGENTS.md hints for native providers** — Bootstrap/AGENTS.md hints were only injected for prompt-based mode; now injected for ALL providers (P1)
- **`bootstrap_prompt` NameError** in benchmark debug logging — Variable was never defined in scope; replaced with `system_content`
- **ppxaide `/debug-log on`** — Was toggling in-memory flags only; now calls `Logger.enable_all()` / `Logger.disable_all()` to actually enable file logging
- **Codex native tool calling** — Removed `_is_responses_api_model()` from prompt-based override; added belt-and-suspenders tool hint injection for Responses API models

### Documentation

- **v1.15.6/v1.16.0 release plan** (`docs/archive/RELEASE-PLAN-v1.15.6-v1.16.0.md`) — Phased release strategy, P0-P4 backlog, v1.16.0 breaking changes roadmap
- **Debug session archive** (`docs/archive/ARCHIVE-v1.15.6-debug-sessions.md`) — 5 debug sessions, 23 items (A0-A14, C1-C9), key discoveries
- **DGX Spark setup guide** — Sanitized, removed sensitive info and Ollama references

---

## [1.15.5] - 2026-02-15

### Changed - Multi-Line Chat Input (Breaking UX Change)

- **Multi-line input in ppxaide** - Input box now uses TextArea widget instead of single-line Input
  - **Enter** inserts a newline (allows multi-line messages, code blocks, etc.)
  - **Ctrl+Enter** submits the message (shown in footer for discoverability)
  - Auto-expands from 1 line up to 18 lines as content grows, then shows scrollbar
  - All existing functionality preserved: command history (Up/Down), tab completion, focus management
  - Design rationale: Shift+Enter was tried first but many terminals cannot distinguish it from Enter

### Fixed - Escape Key Handling

- **Escape key properly dismisses UI elements** - Priority-based dismissal: help panel > modal screens > side panel
  - `action_cancel()` rewritten with clean priority chain
  - `on_key()` used instead of `_on_key()` in ChatTextArea — allows Escape to bubble up to app-level handlers
  - `q` key binding added to close help panel (common convention)
  - Command palette re-enabled (was temporarily disabled during debugging)

### Fixed - Build

- **PyInstaller `blinker` hiddenimport** - Added `blinker` to `ppxaide.spec` to fix `ModuleNotFoundError` when running ppxaide binary (required by EventBus)

### Changed - Benchmarks

- **`tool_calling_method` metadata** - Benchmark results now record whether native or prompt-based tool calling was used
- **Comprehensive BENCHMARKS.md guide** - 700+ line guide covering all 7 test categories (28 tests), scoring, analysis tools
- **Legacy benchmark files archived** - 15 old JSON files moved to `benchmarks/llm-eval/docs/archive/legacy/`

### Housekeeping

- **Removed 7 debug notifications** from `action_cancel()` that were added during Escape key development
- **15 new multi-line input tests** - ChatTextArea, Ctrl+Enter binding, submit handler, history preservation
- **`native_tool_calling: true`** added to OpenAI/OpenRouter in example config
- **`RELATED-PROJECTS.md`** added documenting ppxai ↔ ppxai-sre relationship
- **TODO-v1.15.3.md** marked as complete

---

## [1.15.4] - 2026-02-13

### Added - Live HTML Preview (`/preview` command)

- **`/preview` command** - Live-reloading HTML preview across all 3 clients
  - **TUI**: Stdlib `PreviewServer` (http.server + threading), auto-opens browser
  - **Web App**: Iframe with `/preview/{filepath}` endpoint, split panel UI
  - **VSCode**: `WebviewPanel` with `FileSystemWatcher` for live reload
- **`PreviewServer`** (`ppxai/preview_server.py`) - Standalone HTTP server with mtime polling at `/poll`
- **`rewrite_asset_paths()`** - Cache-buster support appending `?_t=<mtime>` for reliable CSS/JS/JSON live-reload
- **`inject_reload_script()`** - Auto-injects polling JavaScript into preview HTML
- **`resolve_preview_path()`** - Resolves preview file paths with security validation
- **FastAPI endpoints** - `/preview/poll/{path}`, `/preview/static/{path}`, `/preview/{path}` with session-scoped working directory
- **Non-HTML asset serving** - Preview iframe `fetch()` for JSON/CSS/JS files now served correctly via `FileResponse`
- **Session resolution from Referer** - JS `fetch()` calls from preview iframe resolve session from Referer header

### Added - VSCode Extension Improvements

- **Consent EventBus migration** - Consent dialog handling moved to EventBus pattern
- **Preview auto-refresh** - `FileSystemWatcher` monitors CSS/JS/JSON/SVG/PNG/JPG siblings for live reload
- **Autocomplete fixes** - Improved slash command autocomplete reliability
- **highlight.js rebuild** - Added PowerShell, Dockerfile, DOS, AppleScript language support

### Fixed - Web Tools & SSL

- **Corporate SSL support** - New `_create_ssl_context()` respects `SSL_VERIFY` and `SSL_CERT_FILE` env vars
- **`get_weather` HTTP fallback** - Tries HTTPS first, falls back to HTTP when corporate proxy stalls HTTPS
- **Configurable web tool timeouts** - `tools.<name>.timeout` in ppxai-config.json (default 15s)

### Fixed - Debug Logging

- **`/debug-log on` enables ALL logger instances** - Previously only enabled "tui" logger
- **`Logger.enable_all()` / `Logger.disable_all()`** - Class methods for centralized log control across all components

### Fixed - Session & Provider

- **Session restore** - Correctly restores provider/model from session metadata
- **Gemini provider** - Fixed content handling for tool responses with None content

### Added - Benchmarks & Testing

- **Qwen3-Coder-Next FP8 benchmarks** - 3 benchmark runs with per-category analysis
- **Model evaluation summary** - Comparative table across 7 tested models
- **34 new preview tests** - Covering utilities, server, cache-busting, and data file serving
- **16 new SSL tests** - Corporate proxy, timeout, and fallback scenarios
- **Total tests: 1,227 passing**

### Documentation

- **RELEASE-NOTES-v1.15.4.md** - Complete release documentation
- **archive/v1.15.4/PLAN-live-html-preview.md** - Implementation plan for preview feature
- **archive/v1.15.4/BUGFIX-WEB-TOOLS-CORPORATE-SSL.md** - Updated from planned to fixed status

---

## [1.15.3] - 2026-02-07

### Fixed - Config Hot-Reload & DAG-Based Initialization

- **Config hot-reload** - `/model` and `/provider` commands now auto-reload config from disk
  - All 3 clients (TUI, Rich, HTTP server) reload config before restoring sessions
  - HTTP + JSON-RPC endpoints reload before listing/switching providers/models
  - Fixes stale config cache when config file is edited externally
  - Root cause: ConfigStore singleton + EngineClient snapshot pattern caused stale references
- **DAG-based config initialization** - Replaced `__getattr__` lazy loading with explicit `initialize()`
  - Module-level PROVIDERS/MODELS dicts populated at startup
  - In-place mutation (`.clear()` + `.update()`) ensures all references stay fresh
  - EngineClient uses `@property providers_config` instead of snapshot
  - Removed 4 workarounds (deferred imports, manual re-fetches)
  - Added `reset_config_after_test` fixture for test isolation
  - All 1157 tests pass (100% pass rate)
- **New `EngineClient.reload_config()` method** - Single entry point to refresh all cached config data
  - Refreshes ConfigStore + shell/agent configs
  - Automatically called by `/config reload` command

### Fixed - Platform Alignment (Windows/macOS/Linux)

- **Signal handling** - SIGINT (Ctrl+C) and SIGTERM now work on all platforms including Windows
  - Removed Windows exclusion for signal handlers
  - TUI gracefully shuts down on both signals across all platforms
  - Uses `call_from_thread()` for thread-safe quit action
- **Binary search path filtering** - Platform-aware filtering for efficiency
  - Windows skips `/usr/*` paths (Unix-only)
  - Unix/macOS/Linux skip `AppData` paths (Windows-only)
  - Desktop app uses filtered paths from config
- **Path expansion standardization** - Standardized to `Path.home()` for internal paths
  - Intentional `os.path.expanduser()` kept only in tool handlers (supports `~username` syntax)
  - Consistent path handling across all platforms

### Fixed - TUI EventBus Stability

- **WARNING event handler** - Added ENGINE_WARNING event handler for hallucination detection alerts
  - Displays validation warnings in chat with yellow ⚠ indicator
  - Completes v1.15.2 response validation system integration with TUI
  - Fixes "Unhandled event type: EventType.WARNING" debug messages
- **EventBus handler resilience** - Added NoMatches guards to all event handlers
  - Prevents crashes when handlers fire before chat_view is mounted
  - Fixes "No nodes match '#chat-view'" errors during startup/shutdown
  - Protected handlers: `_on_tool_call`, `_on_tool_result`, `_on_tool_error`, `_on_engine_error`, `_on_engine_warning`, `_on_engine_info`
- **Shell consent dialog threading** - Verified correct implementation using `call_from_thread()` + callback pattern
  - No `wait_for_dismiss` usage (follows Textual best practices)

### Fixed - Engine & Performance

- **Model hints debug noise** - Removed verbose "no model hints matched" messages
  - Only logs when hints ARE matched, not when they aren't
  - Reduces duplicate log messages during session restoration and model switching
  - Available patterns still visible via `/context show` command
- **Working directory change deduplication** - Only emit WORKING_DIR_CHANGED event when directory actually changes
  - Compares resolved paths to prevent duplicate events
  - Fixes double events from temporary cwd switches during tool execution

### Added - Benchmarks & Testing

- **DGX Spark benchmarks** - Added benchmark results for local models
  - GPT-OSS-120B, Qwen3-30B-A3B, Qwen2.5-Coder-32B tested
  - Results tracked in `benchmarks/llm-eval/results/`
  - Hallucination resistance gate tests added

### Documentation

- **INSTALLATION.md** - Added platform-specific notes section
  - Clipboard support requirements per platform
  - Signal handling (Ctrl+C, SIGTERM) on all platforms (v1.15.3+)
  - Linux headless requirements (`xclip`/`xsel`)
- **MEMORY.md** - Added v1.15.3 critical patterns:
  - Pattern #8: TUI EventBus Handler Resilience
  - Pattern #9: WARNING Event Handling
  - Pattern #10: Working Directory Change Deduplication
- **RELEASE-NOTES-v1.15.3.md** - Complete release documentation with implementation details

---

## [1.15.2] - 2026-02-06

### Added - Gemini Native Tool Calling

- **Native function calling** - Gemini provider now uses `function_declarations` instead of prompt-based tool calling
  - Converts OpenAI tool format to Gemini format with `_convert_tools_to_gemini()`
  - Handles tool calls in streaming and non-streaming modes
  - Default capabilities include `native_tool_calling=True`
  - Backward compatible - prompt-based mode works with `native_tool_calling: false`
- **Gemini generation params** - Loads `temperature`, `top_p`, etc. from `ppxai-config.json`
- **Perplexity generation params** - Also loads generation params from config
- **Workaround for web search** - `web_search` tool now available for Gemini in agent mode
  - Uses premium search (Perplexity → Gemini grounding API → DuckDuckGo fallback)
  - Separate grounding-only API call when agent needs web data
- **Limitation:** Multi-tool use (GoogleSearch + function_declarations) requires Live API
  - Standard `generate_content` API cannot mix grounding with tools

### Added - LLM Benchmark Suite

- **Comprehensive benchmark suite** (`benchmarks/llm-eval/`) - 6 test categories, 21+ test cases
  - `hallucination_resistance` - Gate tests for basic reliability (must pass 100%)
  - `tool_calling` - Native tool execution accuracy
  - `file_editing` - apply_patch, replace_block, insert_text
  - `code_generation` - Generate working code from descriptions
  - `multi_step_tasks` - Complex multi-step agent workflows
  - `error_recovery` - Handle failures and retry
- **Generation params from config** - Benchmarks load `temperature`, `top_p` from `ppxai-config.json`
- **Engine runner** - Benchmark evaluation using ppxai Engine (not subprocess)
- **Test ordering** - `hallucination_resistance` runs first as gate tests

### Added - ppxaide TUI Improvements

- **Streaming cancellation** - Ctrl+C during streaming gracefully cancels the response
- **SIGINT handler** - Graceful shutdown on Ctrl+C for Linux/macOS
- **Trace logging mode** - `--trace` flag for verbose per-event logging (separate from `--debug`)
- **Performance optimization** - Network file crash fix (WinError 4350 on DFS paths)
- **StatusBar refactoring** - Extracted helpers (`_format_cwd_display`, `_update_checkpoint_badge`)

### Added - Response Validation & Hallucination Detection

- **ResponseValidator class** (`engine/tools/validator.py`) - Detects when LLM models:
  - Claim success after tool failures (e.g., "I've created the file" when write_file returned error)
  - Claim file operations without calling appropriate tools
  - Output tool call JSON as text instead of making actual calls
  - Fabricate output that looks like tool results (fake shell listings)
- **WARNING event type** - New SSE event for real-time validation warnings to clients
- **Web app warning display** - Styled warnings with severity, message, details, and suggested actions
- **Enhanced tool system prompt** - 5 new critical instructions for tool result validation:
  1. Always check tool results before claiming success
  2. Never claim file creation without tool confirmation
  3. Must call display_file when asked to display files
  4. Must use execute_shell_command for shell commands
  5. Call tools directly, never output JSON in response text

### Added - Terminal Features

- **`/terminal` command** - Shows terminal detection and image protocol config help
- **`PPXAI_TERMINAL` and `PPXAI_IMAGE_PROTOCOL`** - Environment variables for multi-terminal setups
- **Double Ctrl+C to quit** - Pattern in ppxaide prevents accidental exits

### Fixed - VSCode display_file Integration

- **EventBus architecture completion** - Fixed display_file tool in VSCode extension
  - Files now open in editor tab (ViewColumn.Beside) instead of chat window
  - Added missing `display_file` case in `httpClient.mapServerEvent()`
  - Completed incomplete EventBus refactoring - `handleStreamEvent()` now calls `processStreamEvent()`
  - Added `processDisplayFile()` in `stream.ts` and `stream:display_file` event type
  - Root cause: EventBus infrastructure existed but wasn't connected
- **Lesson learned:** Incomplete refactoring can leave both old and new code paths active

### Fixed - Unicode Whitespace & Tool Calling

- **Unicode whitespace normalization** in `apply_patch` - NBSP (`\xa0`), NNBSP (`\u202f`), Thin Space now match regular spaces
- **5-level fuzzy matching** in `_replace_hunk()`: exact → CRLF → Unicode normalize → strip+normalize → collapse
- **Truncated tool call detection** - Detects "I'll use X tool" with incomplete JSON and provides recovery feedback
- **GPT-OSS intermittent tool calling** - Auto-retry with targeted guidance when vLLM Harmony parser fails

### Fixed - Configuration & UI

- **Autocomplete** preserves command prefix for subcommands (`/provider ` + TAB works)
- **`/status`** shows terminal override indicators when env vars are set
- **Config loader** now includes all config sections (`server`, `session`, `tui`, `paths`, etc.)
- **`server.idle_timeout`** config now properly read (was always using 300s default)
- **Web app `/context reload`** shows correct message instead of false "not found"
- **Web app clipboard button** now uses correct global reference (`window.ppxai`)
- **Web app `display_file` event** now handled properly (opens split preview)

### Documentation

- Comprehensive terminal image display guide in INSTALLATION.md
- GPT-OSS "explain before calling" tool issue and `max_tokens` mitigation

### Technical

- **Gemini provider:** `_convert_tools_to_gemini()`, `_parse_function_call()`, generation params support
- **Benchmark suite:** 20+ test cases across 6 categories, engine runner integration
- **StatusBar helpers:** `_format_cwd_display()`, `_update_checkpoint_badge()` extracted
- **EventBus logging:** Now tied to `--trace` mode instead of `--debug`
- **Network file handling:** OSError exception handling for DFS/network paths (WinError 4350)
- **Validation system:** `ValidationResult` enum, `ValidationWarning` dataclass, 27 new tests
- **Test coverage:** 20 new tests for Unicode normalization, 20 for truncation detection
- **Total tests:** 1,105 passing tests

---

## [1.15.1] - 2026-01-29

### Added - AI Tool Integration

- **`display_file` tool** - AI can now proactively show files after generating/modifying them
  - Works across all clients: ppxaide (Textual TUI), ppxai (Rich TUI), VSCode, Web
  - Reuses existing `/show` command infrastructure - no parallel event systems
  - INFO event with `execute_command` metadata triggers client-side `/show` command
  - Graceful degradation: clients without interception just show the INFO message

### Fixed - ppxaide TUI Performance

- **UI responsiveness during streaming** - Worker threads with `call_from_thread()` prevent event loop blocking
  - UI stays responsive during 30+ second HTTP waits
  - Scrolling, history navigation work during streaming
  - Footer status widget shows live elapsed timer
- **CPU usage fix** - Timer cleanup safeguard prevents runaway processes
- **VSCode extension cleanup** - Removed 10 unused imports from chatPanel.ts
- **Copy button layout** - Moved to bottom of message bubble (matches VSCode)

### Technical

- Textual's `call_from_thread()` for thread-safe UI updates from worker threads
- Worker threads with isolated asyncio event loops
- Footer status widget with 100ms timer updates
- Input box disabled during streaming to prevent concurrent requests
- INFO events with metadata for client-agnostic command execution

---

## [1.15.0] - 2026-01-26

### Added - New TUI Engine Integration

- **Complete TUI rewrite with engine integration** - Full async streaming, event-driven architecture
- **Real-time token/cost tracking** - Display usage stats with smart formatting (K/M suffixes)
- **Tool execution display** - Show AI tool calls, results, and errors in chat with proper formatting
- **Bootstrap context loading** - Auto-load AGENTS.md/CLAUDE.md on TUI startup
- **Context badge** - Status bar shows context scope (global/project/subdir)
- **Command factory pattern** - All 30 commands using centralized factory with type-based dispatch
- **7 validation scripts** - Comprehensive validation for all Phase 6 features
- **Performance optimization** - 3.5M command lookups/sec, 6.1M event processing/sec

### Added - TUI Commands

- **`/context` command** - Show context usage info (KeyValueResult)
- **`/context show`** - Display bootstrap hierarchy (TreeResult)
- **`/context hints`** - Show active provider/model hints (KeyValueResult)
- **`/context reload`** - Reload bootstrap from disk (ConfirmationResult)
- **`/usage` command** - Show usage statistics with multiple display modes
- **`/usage show|session|provider|off`** - Control usage display format

### Changed

- **Removed alias conflict** - `/test` command no longer uses "t" alias (reserved for `/tools`)
- **Event-driven messaging** - STREAM_START, STREAM_CHUNK, STREAM_END, TOOL_CALL, TOOL_RESULT, TOOL_ERROR
- **Smart truncation** - Tool arguments capped at 100 chars, results at 500 chars
- **Usage auto-update** - Token/cost stats refresh after each STREAM_END event

### Fixed

- **ErrorResult status parameter** - Fixed 4 missing `status=ResultStatus.ERROR` parameters in session commands
- **Mock fixtures** - Enhanced test mocks with proper return values for all engine methods
- **Test assertions** - Updated to accept all valid result types (ListResult, ConfirmationResult, etc.)

### Testing

- **28/28 unit tests passing** - Complete command factory test suite
- **7/7 integration tests passing** - End-to-end TUI validation
- **5 validation scripts** - Bootstrap, token/cost, tool display, commands, integration
- **Performance benchmarks** - Established baseline metrics for command/event processing

### Architecture

- **Phase 6.1** - Engine connection with async streaming
- **Phase 6.1.1** - Command factory integration (removed 434 lines of legacy code)
- **Phase 6.2** - Command handler validation (30 commands, 9 categories)
- **Phase 6.3** - Bootstrap context loading
- **Phase 6.4** - Token/cost tracking with smart formatting
- **Phase 6.5** - Tool execution display with TOOL_* events
- **Phase 6.6** - Integration testing & validation

### Documentation

- **PHASE-6-PROGRESS.md** - Comprehensive progress tracking
- **PHASE-7-POLISH-RELEASE.md** - Release preparation guide
- **Validation scripts** - scripts/validate_tui_*.py (5 scripts)

## [1.14.2] - 2026-01-23

### Added - Hierarchical Context Scopes

- **Global context** - Load defaults from `~/.ppxai/AGENTS.md` across all projects
- **Project context** - Load from `{git_root}/AGENTS.md` for project-specific instructions
- **Subdirectory context** - Load from `{cwd}/AGENTS.md` for directory-specific overrides
- **Scope merge strategy** - Files from all scopes merge additively (global → project → subdir)
- **`/context show` command** - Display bootstrap context hierarchy with scope labels
- **`GET /context/bootstrap` endpoint** - HTTP API for scoped bootstrap status

### Added - Enhanced Context Providers (merged from v1.14.3)

- **`@clipboard` provider** - Inject clipboard text content with `@clipboard` in messages
- **`@url` provider** - Fetch and inject web content with `@https://example.com/file.md`
- **Include directive** - Compose AGENTS.md from multiple files: `<!-- include: ./docs/style.md -->`
- **Hint templates** - Define reusable hint sets in `~/.ppxai/hint-templates.yaml`, reference with `- template: name`

### Changed

- **Gemini default model** - Changed from `gemini-2.0-flash` to `gemini-2.5-flash` (2.0 deprecated March 2026)
- **Provider/model hints merging** - Hints from all scopes are combined (not replaced)
- **`/context reload`** - Now reloads from all scope levels with improved feedback
- **Bootstrap status API** - Returns `sources` array with path, scope, and size for each file

### Architecture

- **`find_git_root()`** - New helper to detect git repository root for project scope
- **`ContextScope` enum** - Scope labels (global, project, subdir)
- **`find_bootstrap_files_by_scope()`** - Hierarchical scope discovery
- **`ScopedBootstrapSource` dataclass** - Bootstrap file metadata with scope info
- **`load_bootstrap_context_merged()`** - Scope-aware context loading with merge
- **`inject_clipboard_context()`** - Clipboard content injection
- **`inject_url_context()`** - URL content fetching with HTML-to-text conversion
- **`_process_includes()`** - Recursive include directive processing with cycle detection
- **`load_hint_templates()`** - Template loading from ~/.ppxai/hint-templates.yaml

### Dependencies

- **pyperclip>=1.8.0** - Cross-platform clipboard access for `@clipboard` provider

## [1.14.1] - 2026-01-21

### Added - Editor Command Support

- **`/edit` command for VSCode** - Opens file in native VSCode editor with proper language mode, supports `file:line:col` syntax
- **`/edit` command for Web App** - Monaco-style editor with syntax highlighting, line numbers, Ctrl+S save
- **`/context reload` command** - Refresh AGENTS.md/CLAUDE.md from disk without restarting session (TUI, VSCode, Web)
- **`POST /files/write` endpoint** - Server-side file write support for VSCode/Web editors
- **Auto-reload on save** - Editing AGENTS.md or CLAUDE.md automatically offers to reload bootstrap context

### Fixed

- **Gemini provider error formatting** - Added missing `_format_error` and `_log_error_traceback` methods to GeminiProvider class

### Cancelled

- **TUI `/edit` command** - Cancelled for Rich TUI; ppxaide (Textual TUI) provides full file editing via CodeEditor widget with syntax highlighting

## [1.14.0] - 2026-01-19

### Added - Bootstrap Context System

- **AGENTS.md/CLAUDE.md support** - Load project-specific instructions from bootstrap files on startup
- **YAML front matter** - Provider and model-specific hints in structured header
- **Dynamic prompt assembly** - System prompt rebuilds automatically when switching provider/model
- **`local` provider inheritance** - ollama, vllm, lmstudio providers inherit from `local` hints
- **Model pattern matching** - Glob-style patterns match model IDs (e.g., `deepseek-r1*`)
- **Configurable file aliases** - User-defined fallback list via `bootstrap.files` config
- **Bootstrap enable/disable** - Toggle via `bootstrap.enabled` config option

### Added - Context Hints Debugging

- **`/context hints` command** - Shows active provider/model hints for current session
- **`/status` hints display** - Shows count of active hints with inheritance indicator (e.g., `3+ provider hints`)
- **Debug logging on switch** - Logs hint transitions when provider/model changes (with `/debug-log on`)
- **`/context/hints` HTTP endpoint** - VSCode extension can query active hints

### Fixed

- **VSCode/Web table rendering** - Markdown tables now use word-wrap instead of horizontal scrollbars
- **CSS table-layout** - Changed from `display: block` with `overflow-x` to `table-layout: fixed` with `word-wrap`
- **Perplexity "messages must alternate" error** - Fixed session corruption when restoring tool-use sessions that start with assistant messages
- **HTTP server session autosave** - Server now calls `save_dirty()` after each chat response (was only saving usage stats)
- **Session alternation validation** - New `validate_and_fix_alternation()` method sanitizes sessions on load/save, removing leading assistant messages
- **Error rollback in chat_with_tools** - User message rollback now only happens on first iteration, preventing session corruption during multi-turn tool calls
- **Session logger routing** - Changed session.py logger from "tui" to "session" for proper server-debug.log output

### Architecture

- **`ppxai/engine/bootstrap.py`** - New module with `BootstrapContext` class for parsing and prompt assembly
- **`EngineClient._bootstrap_context`** - Stores parsed bootstrap context for session
- **`get_active_hints()` method** - Returns detailed breakdown of active hints
- **`get_active_hints_for()` method** - `BootstrapContext` method for provider/model-specific hint retrieval

## [1.13.10] - 2026-01-16

### Added - Web App Enhancements

- **Image preview in /show command** - Web app now displays PNG, JPG, GIF, WebP, SVG, BMP, ICO files directly in the preview panel
- **PDF preview in /show command** - Web app now displays PDF files using the browser's native PDF viewer
- **YAML/TOML/HCL parsing for /show** - Web app now supports structure-aware previews for YAML, TOML, and HCL/Terraform files
- **Loop detection for tool calls** - Configurable `max_same_tool_calls` (default: 3) prevents models from calling the same tool repeatedly. Forces synthesis after threshold is reached.

### Added - Architecture Improvements

- **Command Factory pattern** - Migrated all slash commands to factory pattern in `ppxai/commands/` package with self-registration
- **SessionManager singleton** - Thread-safe session management for HTTP server with proper async locks
- **ConfigStore pattern** - Thread-safe configuration with explicit `initialize()` at entry points
- **Config seeding on first run** - Bundled `ppxai-config.example.json` is copied to `~/.ppxai/` on first run
- **Constants module** - New `ppxai/constants.py` centralizes magic strings and default values
- **Improved provider error formatting** - User-friendly error messages for connection, auth, and rate limit errors

### Fixed

- **Tool parameter aliasing with duplicates** - Fixed issue where models send both canonical and alias names in same call (e.g., both `file_path` AND `filepath`). Now removes duplicate aliases instead of passing them to tool execution.
- **Session restore working directory** - Fixed issue where status bar showed wrong working directory after session restore. Now `set_working_dir()` updates both `context_injector.working_dir` and `session.working_dir`.
- **Session restore tools state** - Session now saves and restores `tools_enabled` state. Tools are automatically re-enabled when restoring a session that had tools enabled.
- **Message alternation on errors** - User message is now rolled back when provider returns error or user interrupts, preventing "messages must alternate" errors on retry.
- **Relative /cd path resolution** - `/cd` command now correctly resolves relative paths.
- **apply_patch tool** - Now handles delete+recreate pattern and detects no-change errors.
- **Loop detection argument checking** - Loop detection now checks tool arguments, not just tool names.

### Changed

- **Removed BUILTIN_PROVIDERS** - JSON config is now the single source of truth for provider definitions
- **Explicit config initialization** - Entry points must call `initialize()` before using config (no import-time side effects)
- **HTTP error handling** - Standardized on `HTTPException` exclusively, removed unused `JSONResponse`

### Technical Debt Addressed

- Extracted `SessionManager` from `http.py` (467 lines)
- Extracted `BaseConsentManager` reducing consent.py by 14%
- Refactored container tools to `CLITool` hierarchy reducing boilerplate by 40%
- Replaced dangerous `eval()` with AST-based safe evaluation in calculator
- Added selective logging to 22 silent error handling instances
- Documented DAG import structure in `ARCHITECTURE.md`
- Replaced `os._exit()` with graceful shutdown via `asyncio.Event` for proper cleanup
- Refactored `client.py` via 5-phase extraction (2,037→1,311 lines, 36% reduction)
- Refactored `chatPanel.ts` with EventBus + State Machine architecture (5,123→2,773 lines, 46% reduction)
- Created `handlers/` module with 1,658 lines of extracted handler code

## [1.13.9] - 2026-01-12

### Added - Session Persistence & Auto-Recovery

- **Session state file** - New `~/.ppxai/session-state.json` tracks session dirty/clean state for crash recovery
- **Command history persistence** - User input history is saved per session and restored on reload
- **Working directory persistence** - Session remembers the working directory set via `cd` command
- **Auto-save after each roundtrip** - Sessions are automatically saved after each chat exchange (configurable interval)
- **Auto-restore on startup** - Configurable behavior: `"always"`, `"prompt"` (default), or `"never"`
- **Crash recovery** - Dirty sessions (from crashes/force-quit) are automatically detected and recovered
- **Graceful exit handling** - Sessions marked clean on `/quit`, Ctrl-C (double), or EOF

### Added - Configuration

- **Session config section** - New `"session"` key in `ppxai-config.json`:
  ```json
  {
    "session": {
      "auto_restore": "prompt",
      "auto_save_interval": 1
    }
  }
  ```

- **Context limits config section** - New `"context"` key for configurable truncation and model limits:
  ```json
  {
    "context": {
      "max_injection_size": 100000,
      "default_context_limit": 128000,
      "warn_at_percent": 80
    }
  }
  ```

- **Per-model context_limit** - Models can specify their context window size:
  ```json
  {
    "providers": {
      "vllm-gpt-oss": {
        "models": {
          "openai/gpt-oss-120b": {
            "context_limit": 131072
          }
        }
      }
    }
  }
  ```

- **Context usage warning** - Shows warning when approaching context limit (configurable threshold)
- **Tools enable notification** - Shows context limit and truncation info when enabling tools
- **`/context` command** - Show context usage, injected files, and visual progress bar (TUI, Web, VSCode)
- **`/context clear` command** - Remove injected @file/@git/@tree content from history to free context space
- **Context badge in TUI** - Status line shows `Ctx: X%` with color coding (green <80%, yellow 80-99%, red ≥100%)
- **Context badge in VSCode** - Header shows context usage percentage with click-to-clear functionality

### Fixed

- **Shell `cd` command updates engine working directory** - When AI calls `execute_shell_command` with `cd`, it now updates `engine.set_working_dir()` instead of running a subprocess (which only changed the subprocess directory). Fixes `list_directory` showing wrong directory after AI-issued `cd` command.
- **@tree context truncation** - `@tree` injection now truncates at 100KB limit (same as `@file` and `@git`) to prevent "too many tokens" errors with large codebases
- **TUI @file autocomplete after cd** - File completion now uses engine's working directory instead of process cwd, so @filename autocomplete correctly shows files from the current directory after using cd command
- **TUI /show command after cd** - `/show @filename` and `/show filename` now search in the engine's working directory (set by cd) instead of the process cwd
- **Desktop app missing data viewers** - Added `components/` and `styles/` directories to `ppxai-desktop.spec` so data viewer CSS/JS files are bundled and deployed to `~/.ppxai/web/`
- **Tool parameter aliasing** - Added dynamic parameter normalization in ToolManager to handle model variations. Different tools use different naming conventions (`read_file` expects `filepath`, `apply_patch` expects `file_path`), and models may use either. The new `_normalize_params()` method maps model-provided names to what each tool expects. Comprehensive alias groups cover: file paths, directories, commands, queries, diffs, URLs, locations, containers, pods, text content, and search/replace operations.
- **Context overflow prevention** - Added token estimation in OpenAI-compatible provider to prevent "max_tokens must be at least 1" errors from vLLM when injected `@file` context exceeds model's 128K context window. Now shows a friendly error message suggesting to remove file references or start a new conversation instead of cryptic API error.
- **Empty responses after tool calls** - Fixed issue where some models (e.g., GPT-OSS 120B via vLLM) would execute tools correctly but return empty text responses instead of summarizing the results. Now detects empty responses after tool iterations and prompts the model for a summary.
- **Reasoning model support** - Handle models that return content in `reasoning_content` instead of `content` field
- **Hash-based context deduplication** - Injecting same content twice (e.g., `@git` with unchanged diff) no longer duplicates. Uses MD5 hash to detect identical content and skip re-injection.
- **Gemini model context limits** - Added `context_limit: 1000000` for all Gemini models in example and project configs (was falling back to 128K default)

## [1.13.8] - 2026-01-11

### Added - Data Visualization

- **CSV/TSV Table Viewer** - Interactive table display with sorting, pagination, and filtering
  - TUI: Rich tables with pagination controls (`n`/`p` for next/prev, `s` for source view)
  - Web: Interactive DataTableViewer component with column sorting and search
- **JSON/YAML Tree Viewer** - Collapsible tree view for structured data
  - TUI: Rich tree with expand/collapse controls
  - Web: Interactive DataTreeViewer with expand all/collapse all
- **Format Detection** - Auto-detect CSV, TSV, JSON, YAML, TOML, HCL from extension and content
- **View Toggle** - Switch between rendered (table/tree) and source (syntax-highlighted) views
  - TUI: `/show file.csv --source` flag or `s` key during viewing
  - Web: "Rendered | Source" toggle button in preview panel
- **TOML/HCL Support** - Parse and display TOML and HCL/Terraform files as trees

### Added - Container Management Tools

- **Docker/Podman Tools** - Container lifecycle management with consent for destructive operations
  - `container_list` - List containers (running or all)
  - `container_logs` - Get container logs with tail/since options
  - `container_inspect` - Detailed container information
  - `container_start/stop/restart` - State management (requires consent)
  - `container_exec` - Execute commands in containers (requires consent)
  - `image_list` - List container images
- **Kubernetes Tools** - Pod and deployment management
  - `pod_list` - List pods across namespaces
  - `pod_logs` - Get pod logs with container selection
  - `pod_describe` - Detailed pod information
  - `deployment_list` - List deployments
  - `service_list` - List services
  - `kubectl_apply` - Apply manifests (requires consent)
  - `pod_exec` - Execute in pods (requires consent)
  - `namespace_list` - List namespaces
- **Runtime Detection** - Auto-detect Docker, Podman, and kubectl availability
- **Note**: Container tools are new and may require additional testing - please report issues

### Added - Configuration Options

- **Visualization Config** - New `visualization` section in ppxai-config.json
  - `max_rows` - Limit rows loaded for large CSV files (default: 10000)
  - `page_size` - Rows per page in TUI view (default: 50)
  - `tree_depth` - Initial tree expansion depth (default: 3)
  - `auto_detect` - Enable content-based format detection
  - `csv_delimiter` - Force delimiter or use 'auto'
- **Container Config** - New `tools.container` section
  - `enabled` - Enable/disable container tools
  - `require_consent` - Require consent for destructive operations
  - `timeout` - Command execution timeout

### Added - Dependencies

- **Optional `data` extras** - `pip install ppxai[data]` for YAML/HCL parsing
  - `pyyaml>=6.0` - YAML file parsing
  - `python-hcl2>=4.3` - HCL/Terraform file parsing

### Added - Testing

- **E2E Playwright tests** - 55 browser tests for DataTableViewer and DataTreeViewer components
- **CI Playwright integration** - GitHub Actions runs E2E tests with Chromium

### Fixed

- **`@filename` autocomplete in Web App** - Now uses `/files/search` server endpoint for real file suggestions
- **`@filename` autocomplete in VSCode** - `@git` and `@tree` now appear in autocomplete suggestions
- **Autocomplete popup persistence** - Popup now hides when sending a message (fixed async race condition)
- **`@git` truncation** - Git diff content now properly truncates at 100KB limit (was only setting flag, not truncating)

---

## [1.13.7] - 2026-01-09

### Added - Hot Reload Configuration

- **`/config reload` command** - Reload config without restarting TUI
- **`POST /config/reload` endpoint** - Server-side config reload for web clients
- **VSCode `ppxai.reloadConfig` command** - Reload config from VSCode command palette
- **Web app "Reload Config" menu** - Reload config from web app settings menu

### Added - TUI Improvements

- **`/status` toggles that save** - `/status datetime|version|cwd` now toggles and persists to config
- **TUI icon** - New bold `>_` symbol for better taskbar visibility

### Fixed

- **`provider_id` error** - Fixed `'EngineClient' object has no attribute 'provider_id'`
- **`get_total_usage()` error** - Fixed `'SessionManager' object has no attribute 'get_total_usage'`
- **Private function** - Renamed `_find_config_file()` to public `find_config_file()`

---

## [1.13.6] - 2026-01-08

### Added - Server Lifecycle & Configuration

- **Server idle auto-shutdown** - Server automatically shuts down after configurable inactivity period (default 5 minutes)
- **`/shutdown` endpoint** - Graceful server shutdown via HTTP POST request
- **Activity tracking middleware** - Resets idle timer on every client request
- **Server config section** - New `server.idle_timeout` and `server.port` in JSON config

### Added - System Prompt Configuration

- **Global system prompt** - Configure `system_prompt` at config root level
- **Per-provider system prompts** - Override system prompt per provider (e.g., reduce GPT-OSS chattiness)
- **Prompt modes** - `system_prompt_mode`: "prepend" (default), "append", or "replace"

### Added - TUI Enhancements

- **Status bar badges** - Version, current working directory, and date/time in TUI status bar
- **`/status` command** - Show provider, model, tools status, and working directory
- **`/tools on|off` aliases** - Shorter aliases for `/tools enable|disable`

### Added - Shell Tool Configuration

- **Configurable interactive commands** - `tools.shell.interactive_commands` list in JSON config
- **Non-interactive with args** - `tools.shell.non_interactive_with_args` for commands like `ssh host command`
- **SSH fix** - `ssh r1lx uptime` now works (previously blocked as "interactive")

### Added - Web App Server Control

- **Server badge click** - Click server badge to stop server (with confirmation)
- **Circuit breaker reconnection** - Exponential backoff retry pattern for server connection

### Fixed

- **TUI crash** - Fixed `'EngineClient' object has no attribute 'working_dir'` error

---

## [1.13.5] - 2026-01-08

### Fixed - Critical: Session Isolation

- **Multi-client session isolation** - VSCode extension and Desktop Web App now have isolated sessions when connected to the same server
- **Session ID via HTTP header** - All clients send `X-Session-Id` header; server routes requests to isolated EngineClient instances
- **Per-session state** - Each session maintains its own: conversation history, working directory, provider/model, tool consent state
- **Session lifecycle** - Sessions auto-expire after 1 hour of inactivity; usage saved on cleanup
- **Backward compatibility** - Clients without session ID use shared `default_engine` (existing behavior)

### Added - Session Management

- **`/sessions/list` endpoint** - Monitor active sessions for debugging (GET /sessions/list)
- **Session ID in responses** - `/status`, `/chat`, `/context/working_dir` return session ID
- **VSCode extension** - Generates unique `vscode-{uuid}` session ID per extension instance
- **Desktop Web App** - Generates unique `webapp-{uuid}` session ID per browser tab (via sessionStorage)

### Technical Details

- **Server**: New `get_or_create_session()` function routes requests to per-session EngineClient
- **Consent handling**: Consent requests keyed by `(session_id, file_path)` for proper isolation
- **Request serialization**: Each session has its own asyncio.Lock for chat request ordering

---

## [1.13.4] - 2026-01-08

### Fixed - Error Handling & LLM Guidance

- **SSL certificate support** - Added `SSL_CERT_FILE` environment variable support for corporate proxy certificates in all providers
- **Standardized error logging** - All providers now include full traceback in error events for better debugging
- **Windows shell guidance** - Added explicit warning in `execute_shell_command` that bash heredocs (`<<EOF`), `$()`, and bash builtins don't work on Windows
- **Tool parameter emphasis** - `apply_patch` description now emphasizes REQUIRED parameters to prevent missing argument errors
- **Actionable error tips** - File-not-found errors now suggest appropriate tools (`insert_text`, `list_directory`, `read_file`)
- **Line number validation tips** - `delete_lines` invalid range errors now suggest using `read_file` to check file length first

### Removed - Cleanup

- **docs/archive/** - Removed 39 obsolete documentation files (13KB) - preserved at v1.13.3 tag

---

## [1.13.3] - 2026-01-07

### Fixed - Session Management

- **TUI `/sessions` command** - Fixed KeyError 'saved_at' crash when listing sessions
- **Session data alignment** - All UIs (TUI, Web App, VSCode) now show consistent session info with Created and Last Saved timestamps
- **Robust session display** - `display_sessions()` now uses `.get()` for graceful handling of missing fields

### Changed - UI Consistency

- **Sessions table format** - All three UIs now display sessions in a markdown table with: Session, Messages, Provider/Model, Created, Last Saved columns
- **SessionInfo dataclass** - Added `saved_at` field to `SessionInfo` in engine types
- **HTTP endpoint** - `/sessions` endpoint now includes `saved_at` in response

### Fixed - File Editing Tools

- **Working directory resolution** - `apply_patch`, `replace_block`, `insert_text`, `delete_lines` now resolve relative paths against the engine's working directory instead of the process working directory
- **Critical fix** - Previously, when using file editing tools with a relative path like `task_analysis.ipynb`, the file would be created in `~/.ppxai/bin/` (where ppxai-server runs) instead of the project directory shown in the UI

### Fixed - Build/Release

- **validate-release.py** - Fixed UTF-8 encoding for Windows compatibility

## [1.13.2] - 2026-01-05

### Fixed - Desktop Web App & VSCode Extension

#### Markdown Rendering
- **Fixed bullet lists** - Changed from Unicode bullet (â€¢) to markdown dash (-) for proper rendering
- **Fixed `/usage` tables** - Both VSCode extension and Web App now show usage breakdown in table format
- **Updated marked.js** - Upgraded Web App from v9.1.6 to v11.1.1 (matching VSCode extension)

#### Desktop Web App
- **Auto-detect server URL** - Web UI now uses `window.location.origin` instead of hardcoded port
- **Favicon** - Added proper favicon (same icon as VSCode extension)
- **Markdown preview** - File preview panel now renders `.md` files with full markdown support
- **Preview link clicks** - Clicking relative links in markdown preview opens files instead of 404

#### Shared Modules
- **Command parity** - New shared JS/TS modules ensure identical commands across TUI, VSCode, and Web App
- **Formatter parity** - Consistent markdown formatting for all command responses

### Fixed - Cross-Platform Compatibility (Windows)

#### Tests
- **Path handling** - Tests now use `tempfile.gettempdir()` instead of hardcoded `/tmp`
- **Filename references** - Tests use filename only, not full paths with platform-specific separators
- **Rich console** - Added `legacy_windows=False` for OSC 8 hyperlink tests

#### Configuration
- **PEP 735** - Migrated from `[tool.uv].dev-dependencies` to `[dependency-groups].dev`

### Added - Enhanced Install Script

#### New Flags
- **`--with-config`** - Generate `ppxai-config.json` and `.env` template with all providers
- **`--with-macos-app`** - Download and install DMG to `/Applications/ppxai.app`
- **`--with-launchagent`** - Install LaunchAgent for server auto-start (macOS)
- **`--uninstall`** - Remove ppxai installation (preserves config files)

#### macOS Improvements
- **Quarantine removal** - Automatically runs `xattr -cr` on downloaded binaries
- **DMG installation** - Downloads, mounts, copies app, removes quarantine attribute

#### Documentation
- **INSTALLATION.md** - Comprehensive guide with all new options and platform-specific instructions

---

## [1.13.1] - 2026-01-04

### Added - Desktop Web App

#### ppxai-desktop Launcher
- **Standalone launcher** - Start server and open browser with one click
- **macOS app bundle** - Native `.app` with DMG installer for drag-and-drop install
- **Cross-platform binaries** - Linux, Windows, macOS (ARM + Intel)
- **Auto-install** - Web UI files auto-copied to `~/.ppxai/web/` on first run

#### Web UI
- **Full-featured chat** - Browser-based chat interface with SSE streaming
- **Feature parity** - All slash commands, autocomplete, tools, agent mode, themes
- **Project selector** - Quick switch between recent project directories
- **Provider/model switching** - Dropdown selectors in header
- **Usage tracking** - Token counts and cost display

#### UI Improvements
- **Tool call ordering** - Tool calls now appear before the answer (matching VSCode)
- **Visual badge states** - Tools and Agent badges turn green when enabled
- **Usage tables** - Formatted markdown tables for `/usage` reports

### Documentation
- Updated INSTALLATION.md with desktop app instructions for all platforms
- Added Linux and Windows platform-specific behavior notes
- Added troubleshooting guide for desktop app

---

## [1.13.0] - 2026-01-03

### Added - Custom Provider Parity

#### Premium Web Search Tool
- **Custom provider support** - vLLM, Ollama, and other custom providers can now use premium web search
- **Priority fallback chain** - Perplexity Sonar > Gemini Grounding > DuckDuckGo (free)
- **Automatic detection** - Tool checks available API keys and uses best available option
- **Citation integration** - Web search results formatted consistently across all providers

#### SSL Proxy Support
- **`SSL_VERIFY` environment variable** - Disable SSL verification for corporate proxies
- **Corporate network compatible** - Works behind SSL-inspecting firewalls

#### Tool Usage Tracking
- **`ToolUsage` dataclass** - New type for tracking per-tool usage (calls, tokens, cost)
- **`/usage` enhancement** - Shows tool usage breakdown with provider info
- **Cost attribution** - Separate tracking for model costs vs tool costs

#### Native Tool Calling for Custom Providers
- **`native_tool_calling` capability** - Enable OpenAI-style function calling for vLLM endpoints
- **vLLM integration** - Works with `--enable-auto-tool-choice` flag
- **Streaming tool calls** - Full support for streaming responses with tool calls

#### Enhanced Tool Parsing
- **vLLM inference** - Infer tool names from argument patterns
- **Dispatcher pattern** - Match JSON arguments against registered tool schemas
- **Robust error handling** - Better recovery from malformed tool responses

### Testing
- 525 tests passing (119 new tests)
- Custom provider tool calling tests
- Tool parsing test coverage (440+ lines)
- Premium web search integration tests

---

## [1.12.5] - 2026-01-03

### Added - Native Gemini Provider

#### Google Search Grounding
- **Native Gemini SDK** - Direct integration with `google-genai` package
- **Google Search Grounding** - Real-time web search with citations (like Perplexity)
- **Streaming support** - Full async streaming with usage tracking
- **Graceful fallback** - Uses OpenAI-compatible API if `google-genai` not installed

#### Installation
```bash
pip install ppxai[gemini]   # For enhanced Gemini support
```

### Technical
- New provider: `ppxai/engine/providers/gemini.py`
- Auto-detection in provider factory
- No performance regression (benchmarked)

## [1.12.4] - 2026-01-03

### Added - Checkpoint Management & Web Search Improvements

#### `/checkpoint` Command
- **`/checkpoint status`** - View current checkpoint configuration
- **`/checkpoint list`** - List recent checkpoints (up to 10)
- **`/checkpoint backend <git|file|auto|none>`** - Switch checkpoint backend (session-only)
- **`/checkpoint clear`** - Clear old file-based checkpoint snapshots
- **`/checkpoint info <id>`** - Show details about a specific checkpoint
- **`/checkpoint undo`** - Alias for `/undo` command
- **Tab autocomplete** - Subcommands and backend options autocomplete in TUI

#### Web Search Tool Upgrade
- **`ddgs` package** - Upgraded to use `ddgs>=9.0.0` for more reliable DuckDuckGo search
- **Fallback chain** - Uses ddgs â†’ duckduckgo-search â†’ HTML scraping
- **No API key needed** - Works out of the box for all providers

### New Endpoints
- `GET /checkpoint/list` - List recent checkpoints
- `POST /checkpoint/backend` - Set checkpoint backend
- `POST /checkpoint/clear` - Clear file-based checkpoints

### VSCode Extension
- Full `/checkpoint` command support with all subcommands
- HTTP client methods for checkpoint management

### Testing
- 400 tests passing

---

## [1.12.3] - 2026-01-03

### Added - Time-Based Usage Analytics

#### Persistent Usage Storage
- **`~/.ppxai/usage/usage.json`** - Usage data now persists across sessions
- **Auto-save** - Usage saved after each chat (VSCode) or on exit (TUI)
- **Shared storage** - Both TUI and VSCode contribute to the same usage history
- **No duplicates** - Same session updates existing entry instead of appending

#### Time-Based Usage Commands
- **`/usage 24h`** - Usage for last 24 hours
- **`/usage week`** - Usage for last 7 days
- **`/usage month`** - Usage for last 30 days
- **`/usage year`** - Usage for last 365 days
- **`/usage all`** - All-time usage history

#### HTTP Endpoints
- **`GET /usage/report?period=week`** - Aggregated usage report by time period
- **`GET /usage/sessions?limit=20`** - List recorded sessions with usage data

### New Files
- `ppxai/usage.py` - Persistent usage storage module
- `tests/test_usage_persistence.py` - 14 new tests

### Testing
- 414 tests passing (14 new usage persistence tests)

---

## [1.12.2] - 2026-01-02

### Added - TUI Polish & Bug Fixes

#### Emoji Toggle
- **`/theme emoji on|off`** - Toggle emoji display in panel badges
- Switch between emoji badges and text-only badges for better alignment

### Fixed

#### Tool Call Parsing
- **Single-quote JSON** - Fixed parsing of tool calls using single quotes instead of double quotes

#### Logging & Initialization
- **Unified logging** - TUI and engine now share common logger module
- **Logger initialization** - Fixed missing `self.logger` in CommandHandler
- **Removed obsolete** `tui_logger.py` (replaced by `ppxai/common/logger.py`)

#### TUI Display
- **Checkpoint status** - Shows `â†¶` symbol instead of full git hash for cleaner display
- **Panel alignment** - Text symbols instead of emojis for consistent column alignment

### Testing
- All 377 tests passing

---

## [1.12.1] - 2026-01-02

### Added - Enhanced TUI Experience

#### Themed TUI Panels
- **4 Distinctive Themes** - Standard, Tron Legacy, Matrix, and Nord color schemes
- **Rounded Panel Corners** - User, assistant, and system messages have rounded borders
- **`/theme` Command** - List themes or switch with `/theme <name>`
- **Theme Autocomplete** - Tab completion for theme names

#### Framed Status Panel
- **Badge Display** - Provider, model, tools status as colored badges
- **Visual Hierarchy** - Clear separation between header and chat
- **Theme-Aware Styling** - Badges adapt to current theme colors

#### Clickable File Links
- **OSC 8 Hyperlinks** - Markdown links clickable in supported terminals
- **File URI Support** - Local paths convert to `file://` URIs
- **VSCode Integration** - Click file links to open in editor
- **`/show` Command** - File references in rendered markdown are clickable

### Fixed
- File link resolution for relative paths in markdown
- Link detection regex to match all markdown links (not just http/https)
- Working directory passed correctly for relative link resolution

### New Files
- `ppxai/themes.py` - Theme dataclass and 4 built-in themes
- `ppxai/ui_components.py` - Reusable Rich UI components

---

## [1.12.0] - 2025-12-29

### Added - Checkpoint System & Usage Tracking ðŸ”’ðŸ“Š

This release introduces a checkpoint system for atomic multi-file rollback and real-time token usage tracking with cost estimation.

#### Checkpoint System
- **Git-based checkpoints** - Auto-commits changes before agent tasks for atomic rollback
- **`/undo` command** - Revert last agent task with single command (`git revert HEAD`)
- **File-based fallback** - Snapshots to `~/.ppxai/checkpoints/` when git unavailable
- **Auto-detection** - Automatically selects best backend (git â†’ file â†’ none)
- **Stale detection** - Checkpoints invalidated when new commits are made after them
- **VSCode Undo button** - One-click rollback with confirmation dialog

#### Token Usage & Cost Tracking
- **Real-time streaming usage** - Extract tokens from streaming responses
- **Cost estimation** - Automatic USD cost calculation based on per-model pricing
- **TUI status line** - Shows `1.2Kâ†“/0.5Kâ†‘ $0.0045` in status bar
- **VSCode usage badge** - Live-updating badge with tooltip breakdown
- **All providers supported** - OpenAI, Perplexity, Gemini streaming

#### New Configuration Options
- `tools.agent.checkpoint_backend` - `"auto"` | `"git"` | `"file"` | `"none"`
- `tools.agent.checkpoint_message` - Custom commit message format
- `tools.agent.max_tool_iterations` - Max inner tool loop iterations

#### Bug Fixes
- Fixed `@tree` and `@git` context injection in VSCode (was treated as file search)
- Fixed usage badge not updating after responses
- Fixed table horizontal overflow in VSCode webview
- Fixed concurrent request causing 400 message alternation errors
- Session cleanup on interrupted requests

#### Documentation
- [CHECKPOINT_GUIDE.md](docs/CHECKPOINT_GUIDE.md) - Comprehensive checkpoint system guide
- [RELEASE-NOTES-v1.12.0.md](docs/archive/release-notes/RELEASE-NOTES-v1.12.0.md) - Full release notes

#### Testing
- 377+ tests passing (40 new checkpoint tests)

---

## [1.11.9] - 2025-12-27

### Fixed - Critical Agent Mode Safety ðŸ”’

This release fixes a critical safety issue where `/agent on|off` commands were being interpreted as tasks instead of toggle commands.

#### Critical Fix
- **`/agent on|off` now correctly toggles agent mode** instead of being interpreted as tasks
  - Previously, typing `/agent off` would cause AI to search for things to turn "off" (including killing server processes!)
  - Now properly recognized as toggle commands in both TUI and VSCode extension

#### Security Improvements
- **Minimum word count validation** (default: 3 words) rejects vague single-word tasks
- **`kill`, `pkill`, `killall` added to built-in dangerous shell patterns**
- Built-in defaults ensure safety even without config file

#### New Features
- **Configurable agent settings** via `ppxai-config.json`:
  - `tools.agent.max_iterations` (default: 10) - Maximum agent loop iterations
  - `tools.agent.context_char_limit` (default: 2000) - Character limit for context display
  - `tools.agent.min_task_words` (default: 3) - Minimum words required for agent tasks
- **`/agent/config` API endpoint** for retrieving agent configuration
- **Full `/tools` command parity** between TUI and VSCode extension
  - Added `/tools agent`, `/tools set verbose on|off`, `/tools help <tool>` to extension

#### Documentation
- Updated [Agent Mode Guide](docs/AGENT_MODE_GUIDE.md) with configuration section

#### Testing
- 337 tests passing

---

## [1.11.8] - 2025-12-27

### Added - Agent Mode + Release Fixes ðŸ¤–

This release introduces Agent Mode for autonomous task execution in the VSCode extension.

#### Agent Mode
- **Agent Toggle Button** - New button in VSCode extension header to enable/disable agent mode
- **Agent Mode API** - New endpoints for agent control:
  - `GET /agent/status` - Check agent mode status
  - `POST /agent/enable` - Enable agent mode (auto-enables tools)
  - `POST /agent/disable` - Disable agent mode
- **EngineClient Support** - `agent_mode` property, `enable_agent_mode()`, `disable_agent_mode()` methods
- **Agent Mode Guide** - Comprehensive documentation at [docs/AGENT_MODE_GUIDE.md](docs/AGENT_MODE_GUIDE.md)

#### Release Process Fixes
- **GitHub "Latest" Release Tag** - Releases now correctly marked as latest
  - Added `make_latest: true` to GitHub Actions workflow
  - Release script now uses `--latest` flag when publishing notes
- **Documentation Links** - Fixed 12 broken internal links
  - `custom-tools-guide.md` â†’ `CUSTOM_TOOL_DEVELOPMENT_GUIDE.md`
  - Archived docs now properly reference `docs/archive/` paths

### Fixed
- GitHub releases not being marked as "Latest" on repository page
- Broken documentation links pointing to moved/renamed files

## [1.11.6] - 2025-12-26

### Fixed - /tools Commands After Provider Switch ðŸ”§

- **`/tools list` After Provider Switch** - Now correctly lists tools after `/provider gemini`
  - Root cause: `_list_tools()` checked `isinstance(self.client, PerplexityClientPromptTools)` which is False for non-Perplexity providers
  - Fix: Check `engine_client.tools_enabled` first, show engine tools for all providers

- **`/tools status` After Provider Switch** - Now correctly shows "Tools enabled" after switching providers
  - Same fix pattern applied

- **`/tools config` After Provider Switch** - Now works correctly after switching providers

### Testing
- 377 tests passing
- Manual TUI verification confirmed fix

---

## [1.11.5] - 2025-12-26

### Fixed - Ctrl-C and Tools Status Display ðŸ”§

- **Ctrl-C Message Alternation Error** - Fixed 400 error after interrupting streaming with Ctrl-C
  - Root cause: Ctrl-C cleanup only removed user message from legacy `client.conversation_history`, not from `engine_client.session.messages`
  - Fix: Added `SessionManager.remove_last_message()` method and cleanup logic for both legacy and engine session

- **Tools Status Display** - `/tools enable` now correctly shows "ON" in status line
  - Root cause: `get_status_line()` checked legacy `client.enable_tools` instead of `engine_client.tools_enabled`
  - Fix: Check `handler.engine_client.tools_enabled` first, fallback to legacy client check

### Testing
- 377 tests passing (2 new session cleanup tests)

---

## [1.11.4] - 2025-12-24

### Added - @git and @tree Context Injection ðŸ“‚

Automatic context injection for git changes and directory structure in AI messages.

#### New Features
- **@git injection**: Automatically includes `git diff` (staged + unstaged changes) when you type `@git` in messages
- **@tree injection**: Automatically includes directory tree structure when you type `@tree` in messages
- **Combined contexts**: Use `@file`, `@git`, and `@tree` together in the same message
- **Provider-agnostic**: Works with all providers (Perplexity, Gemini, OpenAI, custom)
- **TUI feedback**: Shows what was injected with size (e.g., "â†’ Injected context: @git (31 B)")

#### Architecture Changes
- **Unified TUI and VSCode**: Both now always use shared EngineClient (unified architecture)
- EngineClient now created at TUI startup (not just when tools enabled)
- Context injection works regardless of tools ON/OFF state

#### Testing
- 31 context injection tests passing (9 new @git/@tree tests)
- 70 command tests passing

---

## [1.11.7] - 2025-12-26

### Major - Legacy Code Removal + Clickable Citations ðŸŽ‰ðŸ”—

This release completes the migration to EngineClient and adds clickable citations/links across all interfaces.

#### Legacy Code Removed
- **Deleted ~2,100 lines of legacy code**
  - `ppxai/client.py` (447 lines - AIClient)
  - `perplexity_tools_prompt_based.py` (1,342 lines - legacy tools client)
  - `tool_manager.py` (299 lines - legacy MCP loader)
- **EngineClient is now the only client interface**
- **337 tests passing** (migrated from legacy tests)

#### New Features
- **`/tools help <tool-name>`** - Detailed documentation for any tool
- **Autocomplete for `/tools`** - Tab completion for subcommands and tool names
- **Custom Tool Development Guide** - [docs/CUSTOM_TOOL_DEVELOPMENT_GUIDE.md](docs/CUSTOM_TOOL_DEVELOPMENT_GUIDE.md)

### Fixed - Clickable Citations ðŸ”—

- **Perplexity Citations Clickable** - `inject_citation_urls()` converts `[1]` to `[1](url)` format
  - Perplexity API returns citations as separate metadata array
  - New function injects URLs into response text for clickable links
- **TUI Links Clickable** - OSC 8 hyperlinks via `convert_markdown_links_to_rich()`
  - Works in Ghostty, iTerm2, Kitty, Windows Terminal, GNOME Terminal 3.26+
  - Cross-platform support (macOS, Linux, Windows)
- **VSCode Tool Responses** - Added `fullResponse` message type for tool-using responses
- **`/tools list` After Provider Switch** - Now correctly lists tools after `/provider gemini`
- **Tool JSON Leak** - No longer leaks to VSCode during streaming

### Documentation
- Archived legacy documentation to `docs/archive/legacy-tools-docs/`
- Updated all guides for EngineClient architecture
- Autocomplete documentation across all relevant guides

## [1.11.3] - 2025-12-24

### Added - Foundation Refactoring + Critical Bugfixes âš™ï¸ðŸ”§

**Note:** This release consolidates v1.11.2.1 and v1.11.2.2 into v1.11.3 due to VSCode extension versioning constraints (only supports 3-part semantic versioning: major.minor.patch).

This release combines two critical patches: provider abstraction improvements and autorouter fixes, providing a solid foundation for adding new AI providers.

#### Autorouter Fix (from v1.11.2.1)

- **Fixed Provider Mismatch in Autorouter** - Coding commands now work with all providers
  - **Problem**: Using `/convert`, `/generate`, etc. with Gemini/OpenAI caused 404 errors
  - **Root Cause**: 7 coding command handlers didn't pass `self.provider` to `send_coding_task()`
  - **Fix**: All 7 handlers now pass current provider parameter
  - **Impact**: Autorouting now respects provider (Perplexityâ†’sonar-pro, Geminiâ†’gemini-2.5-pro, OpenAIâ†’gpt-4o, etc.)

#### Provider Abstraction Improvements (from v1.11.2.2)

- **Configurable Default Provider** - No more hardcoded "perplexity"
  - New `get_default_provider()` function with smart fallback chain
  - `DEFAULT_PROVIDER` environment variable support (`.env`)
  - Fallback order: env var â†’ first available provider â†’ perplexity
  - Documented in `.env.example`

- **Provider-Specific Pricing** - Each provider can have its own pricing model
  - New `get_model_pricing(provider)` function for any provider
  - Backward compatible: Legacy `MODEL_PRICING` global still exists

- **AIClientWithTools Alias** - Better naming for provider-agnostic tool client
  - `AIClientWithTools` = `PerplexityClientPromptTools` (same class, clearer name)
  - Updated docstring: "works with ALL providers (not just Perplexity)"
  - Both names supported for backward compatibility

### Fixed - Critical TUI Bugs ðŸ”§

**From branch `bugfix/gemini-tool-calling`**

- **Bug #1: Tools Status Not Persisting** - Tools now stay ON when switching providers
  - **Before**: Enable tools on Perplexity â†’ switch to Gemini â†’ Tools show OFF âŒ
  - **After**: Tools remain ON across provider switches âœ…
  - **Root Cause**: `handle_provider()` didn't check if tools were enabled before switching
  - **Fix**: Added tools persistence logic in `ppxai/commands.py` (lines 388-420)
  - **Testing**: Manual TUI testing confirms fix works

- **Bug #2: Gemini Tool Call Parsing Failure** - Fixed nested JSON parsing
  - **Before**: Gemini showed raw JSON instead of executing tools âŒ
  - **After**: Gemini tool calls execute correctly âœ…
  - **Root Cause**: Regex pattern `r'\{\s*"tool"\s*:\s*"[^"]+"\s*[^}]*\}'` broke on nested `arguments` object
  - **Fix**: Extract JSON using first/last brace positions instead of regex (`perplexity_tools_prompt_based.py` lines 1054-1083)
  - **Testing**: 4/4 new regression tests passing

### Documentation

- **docs/BUGFIX-gemini-tool-calling.md** - NEW: Comprehensive analysis of both bugs with root causes and fixes
- **docs/PROVIDER-TOOLS-COMPATIBILITY.md** - NEW: Guide explaining how tools work across different providers
- **docs/PROVIDER-ABSTRACTION-REFACTORING.md** - NEW: Detailed refactoring analysis and v1.12.0 recommendations
- **docs/RELEASE-NOTES-v1.11.2.2.md** - NEW: Complete release notes with migration guide

### Testing

- **4 new regression tests** in `tests/test_provider_tools_bugfixes.py`
  - `test_provider_switching_fix_documented()` - Documents Bug #1 fix
  - `test_parse_gemini_nested_json_tool_call()` - Tests Gemini nested JSON parsing
  - `test_parse_tool_call_in_code_block()` - Tests code block tool calls
  - `test_parse_tool_call_simple_no_nested_args()` - Tests simple tool calls
- All 4 tests passing (100%)
- Manual TUI testing confirms both bugs fixed

### Changed

- `ppxai/config.py` - Added `get_default_provider()` and `get_model_pricing(provider)` functions
- `ppxai/commands.py` - Use configurable default provider, tools persistence fix
- `perplexity_tools_prompt_based.py` - Gemini JSON parsing fix, added AIClientWithTools alias
- `.env.example` - Document `DEFAULT_PROVIDER` option

### Impact

- âœ… **Adding new providers now requires ZERO code changes** (config-only)
- âœ… Tools work correctly with all providers (Perplexity, Gemini, OpenAI, OpenRouter, Ollama)
- âœ… Solid foundation for v1.12.0+ features (deprecation warnings, code cleanup)

### Migration Guide

**For Users**: No breaking changes! Everything works as before.
- Optional: Set custom default provider via `DEFAULT_PROVIDER=gemini` in `.env`

**For Developers**: Recommended but not required:
- Use `get_default_provider()` instead of hardcoded "perplexity"
- Use `get_model_pricing(provider)` instead of global `MODEL_PRICING`
- Use `AIClientWithTools` alias for new code (clearer name)

### VSCode Extension Versioning Note

âš ï¸ **Important**: VSCode extensions only support 3-part semantic versioning (`major.minor.patch`). This is why v1.11.2.1 and v1.11.2.2 were consolidated into v1.11.3. Future releases will use 3-part versions only (e.g., 1.11.3 â†’ 1.11.4 â†’ 1.12.0).

## [1.11.2] - 2025-12-22

### Added - Shell Command Consent Security + Shared Modules Refactoring ðŸ”’

This release introduces two major improvements: a comprehensive shell command consent system for secure AI command execution, and complete shared modules architecture refactoring.

#### Shell Command Consent System

- **Regex-Based Command Classification** - Three-tier security model:
  - **Safe Commands** - Auto-approved read-only operations (ls, cat, grep, pwd, which, whoami, date, uname)
  - **Dangerous Commands** - Require user consent (rm, mv, chmod, sudo, curl | bash, kill, pkill)
  - **Never-Allow Commands** - Always blocked (rm -rf /, dd of=/dev/, fork bombs, mkfs)

- **Session-Scoped Consent** - Flexible approval options:
  - **y (yes, once)** - Approve this command execution
  - **n (no, once)** - Deny this command execution
  - **always** - Auto-approve all matching commands (this session)
  - **never** - Block all matching commands (this session)
  - Consent decisions persist for entire session
  - No persistence to disk (security feature)

- **TUI Consent Interface** - Terminal prompt with command details:
  - Shows command, working directory, risk level
  - Keyboard-friendly y/n/always/never input
  - Clear classification feedback

- **VSCode QuickPick Consent** - Native VSCode consent UI:
  - Keyboard navigation (no mouse required)
  - Four clear options: "Yes, Once", "Yes, Always", "No, Once", "No, Never"
  - Command context and risk level display
  - Dismissible (ESC to cancel)

- **Configuration System** - Customizable patterns in ppxai-config.json:
  - `tools.shell.allowed_commands` - Safe command patterns
  - `tools.shell.dangerous_commands` - Require consent patterns
  - `tools.shell.never_allow` - Forbidden command patterns
  - Uses Python regex with negative lookaheads for security

- **Critical Security Fix** - Commands with redirections now require consent:
  - `cat > file.txt` classified as dangerous (not safe)
  - `echo data > file.txt` classified as dangerous (not safe)
  - Uses `(?!.*[><])` negative lookahead in patterns

#### Shared Modules Architecture Refactoring

- **ppxai/common/ Directory** - Centralized shared code (55KB total):
  - `consent.py` (21KB) - Unified consent system for file editing and shell commands
  - `logger.py` (8KB) - Shared logging system replacing TUI-specific logger
  - `event_handler.py` (9KB) - Common event processing for both TUI and VSCode
  - `commands.py` (14KB) - Shared command handlers

- **TUI Adapter** - TUI now uses shared modules:
  - Migrated from `tui_logger.py` to `ppxai.common.logger`
  - Uses shared consent manager
  - Event handler integration
  - Eliminates duplicate code

- **HTTP Server Adapter** - VSCode backend uses shared modules:
  - Shared logger for consistent logging
  - Shared consent manager
  - Event processing via shared handler
  - Unified architecture with TUI

- **Backward Compatibility** - No breaking changes:
  - Existing ppxai-config.json files work unchanged
  - API remains compatible
  - All existing tests pass

#### Files Changed

**Shell Consent:**
- `ppxai/engine/client.py` - Added request_shell_consent() and command classification
- `ppxai/engine/session.py` - Shell consent state tracking (shell_consent_mode, allowed_shell_patterns, denied_shell_patterns)
- `ppxai/engine/tools/builtin/shell.py` - Integrated consent system into execute_shell_command
- `ppxai/server/http.py` - Added POST /shell-consent endpoint for VSCode
- `ppxai/commands.py` - TUI shell consent handler
- `vscode-extension/src/chatPanel.ts` - QuickPick consent UI implementation
- `ppxai-config.json` - Added tools.shell configuration section
- `docs/SHELL_CONSENT_GUIDE.md` - NEW: Comprehensive 642-line security guide
- `docs/RELEASE-NOTES-v1.11.2.md` - NEW: Detailed release notes

**Shared Modules:**
- `ppxai/common/__init__.py` - NEW: Public exports for shared modules
- `ppxai/common/consent.py` - NEW: Unified consent system
- `ppxai/common/logger.py` - NEW: Shared logging (replaces tui_logger.py)
- `ppxai/common/event_handler.py` - NEW: Common event processing
- `ppxai/common/commands.py` - NEW: Shared command handlers
- `ppxai/main.py` - Integrated shared modules into TUI
- `ppxai/server/http.py` - Integrated shared logger into HTTP server
- `tests/test_consent.py` - Updated for file_mode/shell_mode keys
- `tests/test_common_*.py` - NEW: Comprehensive tests for shared modules

#### Testing
- **308/308 tests passing (100%)** - All tests green
- Shell consent integration tests with edge cases
- Shared modules comprehensive test coverage
- Pattern matching validation (safe/dangerous/never)
- TUI and VSCode consent flow end-to-end tested

#### Documentation
- [docs/SHELL_CONSENT_GUIDE.md](docs/SHELL_CONSENT_GUIDE.md) - Complete security guide
- [docs/RELEASE-NOTES-v1.11.2.md](docs/archive/release-notes/RELEASE-NOTES-v1.11.2.md) - Full release notes
- Updated README.md with shell consent features
- Updated CLAUDE.md with v1.11.2 summary

### Changed
- Version bumped to 1.11.2 in all package files (pyproject.toml, vscode-extension/package.json)
- TUI and HTTP server now share common modules (no duplicate code)
- Architecture unified between all clients (TUI, VSCode, future web UI)

## [1.11.1] - 2025-12-22

### Fixed - Critical TUI Regression âš ï¸

This release fixes a critical regression in v1.11.0 where the TUI failed to display AI responses when tools were enabled.

#### Root Cause
- v1.11.0 switched TUI to use `EngineClient.chat_sync()` to enable file editing tools
- However, `chat_sync()` returns a plain string without rendering (pure function)
- Legacy `AIClient.chat()` had built-in console printing (side effect)
- Result: Response was set but never displayed to user

#### Solution
- **Unified Architecture:** Refactored TUI to use async event stream (like VSCode extension)
- **Event Handling:** TUI now properly handles all event types:
  - `STREAM_CHUNK` - Streaming response chunks
  - `TOOL_CALL` - Tool execution notifications
  - `TOOL_RESULT` - Tool results
  - `CONSENT_REQUEST` - File edit consent prompts
  - `ERROR` - Error messages
- **Real-time UX:** TUI now shows streaming chunks, tool calls, and consent prompts in real-time
- **Code Quality:** Eliminates architectural divergence between TUI and VSCode extension

#### Performance
- **No regression:** EngineClient is actually **16.5% faster** than legacy (2446ms vs 2929ms total time)
- TTFT: 1453ms, Total: 2446ms, Throughput: 64.0 tok/s
- Benchmarked against v1.10.5 baseline

#### Files Changed
- `ppxai/main.py` - Added event-based streaming loop (lines 268-325)
- `pyproject.toml` - Version 1.11.0 â†’ 1.11.1
- `vscode-extension/package.json` - Version 1.11.0 â†’ 1.11.1
- `README.md` - Updated version references and installation instructions
- `vscode-extension/README.md` - Updated version references
- `docs/README.md` - Updated version references
- `CLAUDE.md` - Documented v1.11.1 changes

#### Additional Fixes
- **Conversation History Sync:** Fixed 400 error when using tools with conversation history
  - Engine client and legacy client now properly sync conversation history
  - Fixes message alternation errors ("user or tool message(s) should alternate with assistant message(s)")
  - Syncs history when enabling tools and after each response
- **Inline Markdown in Tables:** File names and inline code now render properly in markdown tables
  - Added `parse_inline_markdown()` to handle backticks, bold, italic in table cells
  - Inline code (`` `text` ``) renders with cyan monospace on grey background (GitHub-like)
  - Bold (`**text**`) and italic (`*text*`) also supported
  - Files: `ppxai/markdown_tables.py` (lines 16-64, 135)

#### New Features
- **Verbose Tool Logging:** Added `/tools set verbose` command to inspect tool inputs/outputs
  - `/tools set verbose on` - Show tool arguments and results during execution
  - `/tools set verbose off` - Hide detailed tool information (default)
  - Useful for debugging and understanding AI tool calls
  - Files: `ppxai/commands.py` (lines 134, 495, 665-698), `ppxai/main.py` (lines 295-302)

#### Testing
- **296/301 tests passing** (same as v1.11.0)
- 5 failures are pre-existing custom endpoint config issues (unrelated)
- Syntax validated, imports verified
- Manually tested: verbose mode, conversation history sync, inline code rendering

### Changed
- Version bumped to 1.11.1 in all package files
- Updated all installation instructions to reference v1.11.1
- Updated documentation to reflect unified event-based architecture
- Enhanced markdown table rendering with inline formatting support

## [1.11.0] - 2025-12-21

### Added - File Editing Tools with User Consent ðŸŽ¯

This release introduces **autonomous file editing** capabilities with a comprehensive consent system, transforming ppxai into the first phase of an agentic developer assistant.

#### Core Features
- **4 File Editing Tools** - AI can now modify files with user permission:
  - `apply_patch` - Apply unified diff patches (git-style)
  - `replace_block` - Search and replace exact text blocks
  - `insert_text` - Insert text at specific line numbers
  - `delete_lines` - Delete line ranges from files

- **Per-File Session Consent System** - Safety-first approach:
  - **y (yes)** - Allow editing this file (this session)
  - **n (no)** - Deny this edit
  - **always** - Auto-approve all files (this session)
  - **never** - Block all edits (this session)
  - Consent persists only for current session
  - Separate consent tracking per file path

- **TUI Consent Prompts** - Interactive validation using prompt_toolkit:
  - Clear file path display
  - Validated input (only y/n/always/never accepted)
  - Persistent consent state tracking

- **VSCode Consent Dialogs** - Event-driven SSE integration:
  - Modal dialogs with 4 consent options
  - Server-Sent Events for real-time communication
  - Non-blocking async consent flow

- **Atomic File Operations** - Robust and safe:
  - Write-to-temp + rename pattern
  - Automatic rollback on failure
  - File existence validation
  - Permission checks before edit

- **In-App Help System** - `/tools help editing` command:
  - Comprehensive markdown guide
  - Practical examples with chat flows
  - Consent system explanation
  - Troubleshooting tips
  - Available in both TUI and VSCode extension

#### Documentation
- **NEW:** [docs/FILE_EDITING_GUIDE.md](docs/FILE_EDITING_GUIDE.md) - 400+ lines comprehensive user guide
- **NEW:** [vscode-extension/TESTING.md](vscode-extension/TESTING.md) - Testing documentation for VSCode extension
- **Updated:** README.md with File Editing Tools section
- **Updated:** CLAUDE.md with v1.11.0 feature summary and version alignment

#### Testing
- **NEW:** 36 comprehensive tests for file editing features:
  - 25 tests for file editing tools ([tests/test_file_editing_tools.py](tests/test_file_editing_tools.py))
  - 11 tests for help commands and UI ([tests/test_ui.py](tests/test_ui.py), [tests/test_commands.py](tests/test_commands.py))
- **Total:** 273/278 tests passing (98.2%)
- 5 pre-existing custom endpoint integration test failures (unrelated)

#### Technical Implementation
- `ppxai/engine/tools/builtin/editor.py` - NEW, implements all 4 file editing tools
- `ppxai/engine/client.py` - Added `request_file_edit_consent()` async method
- `ppxai/engine/session.py` - Added consent state (`allowed_files`, `edit_consent_mode`)
- `ppxai/commands.py` - TUI consent handler with prompt_toolkit validation + `/tools help editing`
- `ppxai/ui.py` - Added `display_file_editing_help()` function and updated welcome message
- `vscode-extension/src/chatPanel.ts` - Added `getFileEditingHelp()` + help command handler

### Changed
- Version bumped to 1.11.0 in `pyproject.toml` and `vscode-extension/package.json`
- Updated ROADMAP.md to reflect Phase 1 completion
- Updated all version references throughout documentation

### Fixed
- VSCode extension `/tools help editing` command now displays formatted help content

---

## [1.10.8] - 2025-12-21

### Added
- Unified `/save` and `/export` commands across TUI and VSCode extension
- New `/export [filename]` command exports last answer to markdown (`~/.ppxai/exports/`)
- Clear separation between session persistence (JSON) and answer export (markdown)

### Changed
- `/save` now saves session to JSON (`~/.ppxai/sessions/`) for persistence
- VSCode extension "Save Answer" button now saves to exports folder with auto-generated filenames

### Improved
- VSCode extension interrupt UX - orange pulsing "â¹ Streaming..." badge in header
- Streaming interrupt no longer shows red error message on user-initiated stop

---

## [1.10.7] - 2025-12-20

### Fixed
- Perplexity API compatibility - removed deprecated `sonar-reasoning` model
- Model documentation updated to reflect current Perplexity API

### Changed
- Supported Perplexity models: sonar, sonar-pro, sonar-reasoning-pro, sonar-deep-research

---

## [1.10.6] - 2025-12-20

### Added
- Gemini 3 Flash Preview - Speed-optimized with frontier intelligence and 1M context
- Gemini 3 Pro Preview - Most powerful agentic model with code execution and search grounding
- Enhanced model descriptions with detailed capabilities
- Preview pricing estimates for Gemini 3 models

---

## [1.10.5] - 2025-12-20

### Added
- Status bar showing provider, model, and tools status
- VSCode extension interrupt support via Esc key and Command Palette
- TUI Ctrl-C double-press pattern (2s timeout) - first press warns, second exits
- 7 new interrupt handling tests

### Fixed
- Ctrl-C during streaming no longer causes message alternation errors
- Conversation history cleanup on interrupt maintains LLM message alternation
- Gemini tools None content handling
- FastAPI deprecation warnings (migrated to lifespan pattern)

### Testing
- 235/241 tests passing

---

## [1.10.4] - 2025-12-19

### Fixed
- Markdown tables now render properly in TUI (no more raw `|:---|:---|` syntax)
- Tables support left/center/right alignment (`:---`, `:---:`, `---:`)
- `/show` command renders markdown files with formatted tables
- All AI responses render tables correctly

### Added
- 27 new regression tests for table rendering

---

## [1.10.3] - 2025-12-18

### Added
- Standalone `ppxai-server` executables for all platforms (no Python required)
- Automated GitHub Actions CI/CD for multi-platform builds:
  - macOS ARM64 & Intel
  - Linux AMD64
  - Windows

---

## Earlier Versions

See [ROADMAP.md](ROADMAP.md) for historical release information.

---

## Versioning

ppxai follows [Semantic Versioning](https://semver.org/):
- **MAJOR** version for incompatible API changes
- **MINOR** version for new functionality in a backwards compatible manner
- **PATCH** version for backwards compatible bug fixes

## Release Process

1. Update version in `pyproject.toml` and `vscode-extension/package.json`
2. Update CHANGELOG.md with release notes
3. Update ROADMAP.md to move release from "Next" to "Current"
4. Create git tag: `git tag -a v1.x.x -m "Release v1.x.x"`
5. Push tag: `git push origin v1.x.x`
6. GitHub Actions automatically builds and creates release

[1.15.5]: https://github.com/rcconsult/ppxai/releases/tag/v1.15.5
[1.15.4]: https://github.com/rcconsult/ppxai/releases/tag/v1.15.4
[1.15.3]: https://github.com/rcconsult/ppxai/releases/tag/v1.15.3
[1.15.2]: https://github.com/rcconsult/ppxai/releases/tag/v1.15.2
[1.15.1]: https://github.com/rcconsult/ppxai/releases/tag/v1.15.1
[1.15.0]: https://github.com/rcconsult/ppxai/releases/tag/v1.15.0
[1.14.2]: https://github.com/rcconsult/ppxai/releases/tag/v1.14.2
[1.14.1]: https://github.com/rcconsult/ppxai/releases/tag/v1.14.1
[1.14.0]: https://github.com/rcconsult/ppxai/releases/tag/v1.14.0
[1.13.10]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.10
[1.13.9]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.9
[1.13.8]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.8
[1.13.7]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.7
[1.13.6]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.6
[1.13.5]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.5
[1.13.4]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.4
[1.13.3]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.3
[1.13.2]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.2
[1.13.1]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.1
[1.13.0]: https://github.com/rcconsult/ppxai/releases/tag/v1.13.0
[1.12.5]: https://github.com/rcconsult/ppxai/releases/tag/v1.12.5
[1.12.4]: https://github.com/rcconsult/ppxai/releases/tag/v1.12.4
[1.12.3]: https://github.com/rcconsult/ppxai/releases/tag/v1.12.3
[1.12.2]: https://github.com/rcconsult/ppxai/releases/tag/v1.12.2
[1.12.1]: https://github.com/rcconsult/ppxai/releases/tag/v1.12.1
[1.12.0]: https://github.com/rcconsult/ppxai/releases/tag/v1.12.0
[1.11.9]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.9
[1.11.8]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.8
[1.11.7]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.7
[1.11.6]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.6
[1.11.5]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.5
[1.11.4]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.4
[1.11.3]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.3
[1.11.2]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.2
[1.11.1]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.1
[1.11.0]: https://github.com/rcconsult/ppxai/releases/tag/v1.11.0
[1.10.8]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.8
[1.10.7]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.7
[1.10.6]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.6
[1.10.5]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.5
[1.10.4]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.4
[1.10.3]: https://github.com/rcconsult/ppxai/releases/tag/v1.10.3
