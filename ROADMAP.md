# ppxai Development Roadmap

> **Current version:** see [latest release](https://github.com/rcconsult/ppxai/releases/latest) (`pyproject.toml` is the single source of truth).
> **Focus**: Multi-LLM interface for developers—terminal + VSCode, zero vendor lock-in

---

## Core Value Proposition

ppxai provides:
1. **Multi-Provider Support** - Switch between Perplexity, Gemini, OpenAI, OpenRouter, Ollama anytime
2. **Dual Interface** - Same experience in TUI and VSCode extension
3. **Agent Mode** - Iterative tool execution with consent-based safety
4. **Open Source** - Inspect, modify, self-host, no telemetry

---

## Completed (v1.11.x)

### Agentic Workflow ✅
- File editing tools with consent (`apply_patch`, `replace_block`, `insert_text`, `delete_lines`)
- Context injection (`@file`, `@git`, `@tree`)
- `/agent` command for autonomous multi-step execution
- Safety: dangerous command patterns, minimum word validation
- Configurable via `ppxai-config.json`

### Multi-Provider ✅
- Perplexity AI (with citations)
- Google Gemini (2.0 Flash, 2.5 Flash, 2.5 Pro)
- OpenAI (GPT-4o, o1)
- OpenRouter (Claude, 100+ models)
- Local models (Ollama, vLLM)

### Developer Experience ✅
- TUI with Rich markdown, tables, OSC 8 hyperlinks
- VSCode extension with webview chat, context menu commands
- Coding commands (`/generate`, `/test`, `/docs`, `/explain`, `/debug`, `/convert`)
- Session management, token tracking, cost estimation

---

## Completed (v1.12.x)

### Safety & Reproducibility ✅ (v1.12.0)
- Git-based checkpoints: Auto-commit before `/agent` tasks
- `/undo` command: Revert last agent task atomically
- Stale checkpoint detection
- File-based fallback for non-git directories

### TUI Themes ✅ (v1.12.1)
- 4 themes: Standard, Tron Legacy, Matrix, Nord
- Framed status panel with colored badges
- Clickable file links via OSC 8 hyperlinks
- `/theme` command with autocomplete

### Tool Call Parsing ✅ (v1.12.2)
- Fixed single-quote JSON parsing in tool calls
- Improved error handling for malformed tool responses

### Usage Analytics ✅ (v1.12.3)
- Persistent usage storage in `~/.ppxai/usage/usage.json`
- Time-based usage reports: `/usage 24h|week|month|year|all`
- HTTP endpoints: `/usage/report`, `/usage/sessions`
- Auto-save after each chat (VSCode), on quit (TUI)

### Checkpoint Management ✅ (v1.12.4)
- `/checkpoint` command with 6 subcommands
- Status, list, backend switching, clear, info, undo alias
- Tab autocomplete for subcommands and backends
- VSCode extension full support
- HTTP endpoints for remote control

### Native Gemini Provider ✅ (v1.12.5)
- Native `google-genai` SDK integration
- Google Search Grounding with citations (like Perplexity)
- Streaming support with usage tracking
- Graceful fallback to OpenAI-compatible API
- Install: `pip install ppxai[gemini]`

---

## Completed (v1.13.x)

### Premium Web Search ✅ (v1.13.0)
- Premium web search tool for custom providers (vLLM, Ollama)
- Priority fallback: Perplexity Sonar → Gemini Grounding → DuckDuckGo (free)
- SSL_VERIFY environment variable for corporate proxy support
- Custom provider tool calling tests
- Install: `pip install ppxai[gemini]` for Gemini Grounding support

### Desktop Web App ✅ (v1.13.1)
- Standalone `ppxai-desktop` launcher for all platforms
- macOS `.app` bundle with DMG installer
- Full-featured browser-based chat interface
- Feature parity: commands, tools, agent mode, themes
- Working directory context with folder badge

### Bugfix Release ✅ (v1.13.2)
- Fixed markdown rendering (bullet lists, `/usage` tables)
- Updated marked.js to v11.1.1 in Web App
- Desktop Web App: auto-detect server URL, proper favicon
- Shared modules for command/formatter parity
- Windows compatibility fixes (tests, PEP 735 config)

### Gemini Tools + Grounding ✅ (v1.13.3)
- **Gemini system instruction fix** - System messages now passed via `system_instruction` config
- **Tools + grounding together** - Both work simultaneously (not mutually exclusive)
- **Native web search guidance** - Tool prompt tells providers with native search to use it
- **Provider options** - New `options` section in JSON config for provider-specific settings
- **Detailed error tracebacks** - Full stack traces for Gemini API errors
- **UTF-8 BOM handling** - Windows config file compatibility
- **Windows PowerShell installer** - `scripts/install.ps1` for one-line Windows install

### Error Handling & LLM Guidance ✅ (v1.13.4)
- **SSL certificate support** - `SSL_CERT_FILE` environment variable for corporate proxies
- **Windows shell guidance** - Explicit warnings that bash heredocs don't work on Windows
- **Tool parameter emphasis** - Better error messages for missing arguments
- **Actionable error tips** - Suggestions for appropriate tools on file-not-found errors

### Session Isolation ✅ (v1.13.5)
- **Multi-client isolation** - VSCode and Web App get isolated sessions on same server
- **Session ID header** - `X-Session-Id` HTTP header routes requests to per-session EngineClient
- **Per-session state** - Conversation history, working directory, provider/model, consent state
- **Session lifecycle** - Auto-expire after 1 hour, usage saved on cleanup
- **Monitoring endpoint** - `GET /sessions/list` for debugging active sessions

### Release Script Fixes ✅ (v1.13.6)
- **Windows `gh` CLI compatibility** - Release script works on Windows PowerShell
- **UTF-8 encoding** - Release scripts use proper encoding on all platforms

### Config & Status Fixes ✅ (v1.13.7)
- **`/config reload` command** - Hot-reload `ppxai-config.json` without restart
- **`/status` command fixes** - Fixed session methods and working directory display
- **Gemini grounding pricing** - Corrected pricing in example config ($35/1K requests)

### Data Visualization & Container Tools ✅ (v1.13.8)
- **CSV/TSV table viewer** - Rich tables in TUI, interactive DataTableViewer in Web App
- **JSON/YAML/TOML/HCL tree viewer** - Collapsible trees with syntax highlighting
- **Rendered/Source toggle** - Switch between formatted view and raw source (TUI + Web)
- **Container management tools** - 16 tools for Docker, Podman, Kubernetes CLI
- **Format auto-detection** - Extension-based and content sniffing for data files
- **Visualization config** - `max_rows`, `page_size`, `tree_depth`, `csv_delimiter` options
- **Optional dependencies** - `pip install ppxai[data]` for YAML/HCL parsing
- **`@filename` autocomplete fix** - Web App and VSCode now show real file suggestions via `/files/search`
- **E2E Playwright tests** - 55 browser tests for data viewer components

### Session Persistence & Windows Fixes ✅ (v1.13.9)
- **Session auto-save** - Sessions saved after each chat exchange with crash recovery
- **Command history persistence** - User input history saved per session
- **Working directory persistence** - `cd` command changes remembered across restarts
- **Auto-restore on startup** - Configurable: `"always"`, `"prompt"`, `"never"`
- **Tool parameter aliasing** - Handle model variations (`filepath` vs `file_path`)
- **Context overflow prevention** - Friendly error when `@file` exceeds 128K limit
- **Empty responses after tools** - Prompt model for summary when response is empty
- **Reasoning model support** - Handle `reasoning_content` field from DeepSeek R1
- **`/context` command** - Show context usage vs model limit, injected files list (TUI, Web, VSCode)
- **`/context clear`** - Remove all injected @file/@git/@tree content from current session
- **Context badge** - TUI status line and VSCode header show context usage percentage
- **Hash-based deduplication** - Prevents duplicate @git/@tree injections (MD5 content hash)
- **Per-model context limits** - Configure `context_limit` per model (Gemini: 1M tokens)

### Stabilization & Architecture ✅ (v1.13.10)
- **Tool loop detection** - Configurable `max_same_tool_calls` prevents infinite loops with Ollama models
- **Image/PDF preview** - Web app `/show` command supports image and PDF preview
- **VSCode chatPanel.ts refactoring** - Reduced 5,123 to 2,773 lines with EventBus + State Machine architecture
- **EventBus pub/sub** - Decoupled stream handlers, consent handlers, and UI updates
- **Agent state machine** - Explicit state transitions replace implicit local variables
- **handlers/ module** - 1,658 lines of extracted handler code with IoC pattern
- **client.py refactoring** - 36% reduction (2,037→1,311 lines) via 5-phase extraction
- **Technical debt cleared** - All 16 critical/high priority items addressed

---

## Infrastructure

### CI/CD ✅
- GitHub Actions workflow for releases (`.github/workflows/release.yml`)
- Automated builds for Linux, Windows, macOS (ARM + Intel)
- VSCode extension VSIX packaging
- PyPI publishing via CI

---

## v1.14.x Series - Session Bootstrap & Context ✅ Complete

**Theme**: Reproducible starting point for every session

**User value**: Teams share project context. Consistent AI behavior across sessions.

**Status**: v1.14.2 released. Series complete. Future v1.14.x releases will be bug fixes only (stabilization).

**Detailed Plan**: [docs/RELEASE-PLAN-v1.14.x.md](docs/archive/v1.15.1-completed/RELEASE-PLAN-v1.14.x.md)

**Rich-based TUI**: Feature complete. The current TUI (`ppxai`) has reached its feature ceiling due to Rich framework limitations (no proper editor workflows, limited keyboard handling). New TUI features will be developed in ppxaide (v1.15.x).

**Prerequisite (v1.13.6):** System prompts are already supported via `ppxai-config.json`:
- Global: `system_prompt` at root level
- Per-provider: `providers.<name>.system_prompt`
- Modes: `system_prompt_mode` = "prepend" | "append" | "replace"
- Location: `ppxai/config.py:get_system_prompt()`, `ppxai/engine/client.py:1171-1186`

### v1.14.0 - AGENTS.md Support with Provider Hints ✅

| Feature | Description | Status |
|---------|-------------|--------|
| **AGENTS.md loading** | Load project instructions from AGENTS.md on startup | ✅ Done |
| **Configurable file aliases** | User-defined fallback list: `bootstrap_files: ["AGENTS.md", "CLAUDE.md", ...]` | ✅ Done |
| **YAML front matter** | Provider/model-specific hints in structured header | ✅ Done |
| **Dynamic prompt assembly** | Rebuild system prompt on provider/model switch | ✅ Done |
| **TUI + VSCode + Web support** | All interfaces load context via EngineClient | ✅ Done |
| **`/context hints` command** | Show active provider/model hints for debugging | ✅ Done |
| **`/status` hints display** | Show active hints count in status output | ✅ Done |
| **Debug logging on switch** | Log hint transitions when provider/model changes | ✅ Done |
| **CSS table word-wrap** | VSCode/Web tables use word-wrap instead of horizontal scroll | ✅ Done |

**Design Decision: YAML Front Matter Format**

The problem: When switching from Gemini to Ollama mid-session, the system prompt needs to adapt because:
- **Ollama/local models** need: "Complete tasks fully, don't stop on empty responses"
- **Gemini** needs: "Use Google Search grounding for current information"
- **DeepSeek R1** needs: "Show reasoning before taking actions"

**File Format:**

```markdown
---
# Provider-specific hints (appended when provider is active)
provider_hints:
  ollama:
    - "Complete tasks fully. Don't stop after tool calls - synthesize results."
    - "If a tool returns empty output, explain what you tried and continue."
  local:  # Applies to all local providers (ollama, vllm, lmstudio)
    - "Use tools proactively. Don't ask for permission - just execute."
  gemini:
    - "Use your built-in web search for current information."

# Pattern-matched against model ID (regex)
model_hints:
  "deepseek-r1*":
    - "Show <think> reasoning before actions."
  "qwen2.5-coder*":
    - "Prefer edit_file over apply_patch for modifications."
  "llama*":
    - "Always provide complete file contents, not diffs."
---

# MyProject Development Guide

## Code Standards
- Python 3.11+, type hints required
- pytest for testing, 80% coverage minimum
```

**Architecture:**

```
ppxai/engine/bootstrap.py (new)
├── BootstrapContext class
│   ├── base_instructions: str      # Content below ---
│   ├── provider_hints: dict        # provider_id → list[str]
│   ├── model_hints: dict           # regex pattern → list[str]
│   └── get_prompt_for(provider, model) → str
│
└── Integration points:
    ├── EngineClient._bootstrap_context: BootstrapContext
    ├── EngineClient.set_provider() → triggers prompt rebuild
    └── EngineClient.set_model() → triggers prompt rebuild
```

**Prompt Assembly Order:**
1. `[bootstrap base_instructions]`
2. `[matching provider_hints]` (if provider matches)
3. `[matching model_hints]` (if model regex matches)
4. `[config system_prompt]` (from ppxai-config.json)
5. `[tool_prompt]` (if tools enabled)

**Behavior Rules:**
- `local` provider hints apply to: ollama, vllm, lmstudio (inheritance)
- Both provider AND model hints concatenate (additive, not override)
- On `/provider` or `/model` switch: immediate prompt rebuild
- On `/context reload`: re-parse AGENTS.md and rebuild

**No conflicts:** Bootstrap context extends the existing system prompt pipeline, doesn't replace it.

### v1.14.1 - `/edit` Command & Context Reload ✅

**Theme**: Edit-test-save workflow for bootstrap context tuning

| Feature | Description | Status |
|---------|-------------|--------|
| **`/edit` command (VSCode)** | Opens file in native VSCode editor | ✅ Done |
| **`/edit` command (Web App)** | Monaco-style editor with syntax highlighting | ✅ Done |
| **`/edit` command (TUI)** | Simple line editor | ❌ Cancelled (Rich TUI deprecated in favor of ppxaide) |
| **`/context reload`** | Refresh AGENTS.md from disk | ✅ Done |
| **Auto-reload on save** | `/edit AGENTS.md` + save triggers context reload | ✅ Done |
| **`POST /files/write`** | Server endpoint for file writes | ✅ Done |
| **Gemini error handling** | Added `_format_error` method to GeminiProvider | ✅ Done |

**Implementation by Interface:**

| Interface | `/edit` Implementation | Status |
|-----------|------------------------|--------|
| **VSCode** | Delegate to `vscode.window.showTextDocument()` | ✅ Done |
| **Web App** | CodeMirror 6 split-pane editor | ✅ Done |
| **TUI (Rich)** | Deferred to v1.15.x (ppxaide with Textual) | ⏳ |

**Web App CodeMirror Editor:**

Split-pane design with syntax highlighting:
```
┌────────────────────────────┬─────────────────────────────────┐
│  Chat messages...          │  AGENTS.md                [×]   │
│                            │─────────────────────────────────│
│  You: /edit AGENTS.md      │  ---                            │
│                            │  provider_hints:                │
│  System: Opened in editor  │    ollama:                      │
│                            │      - "Complete tasks fully."  │
│                            │  ---                            │
│                            │  # Project Rules                │
│                            │                                 │
│  [input field]             │  [Save] [Save As...] [Discard]  │
└────────────────────────────┴─────────────────────────────────┘
```

**CodeMirror 6 Language Support:**
- Config files: Markdown, YAML, TOML, JSON, HCL
- Programming: Python, Go, C/C++, JavaScript, TypeScript
- Shell: Bash/Zsh/Csh, Perl

**Bundle size:** ~200KB (core + languages, loaded on demand)

### v1.14.2 - Hierarchical Scopes & Enhanced Context ✅

**Note:** v1.14.3 features merged into v1.14.2.

| Feature | Description | Status |
|---------|-------------|--------|
| **Global context** | Load from `~/.ppxai/AGENTS.md` | ✅ Done |
| **Project context** | Load from project root AGENTS.md | ✅ Done |
| **Subdirectory context** | Load from current working directory | ✅ Done |
| **Merge strategy** | Global → Project → Subdir (concatenate) | ✅ Done |
| **`/context show`** | Display AGENTS.md sources with hierarchy | ✅ Done |
| **`@url` provider** | Fetch and inject web content | ✅ Done |
| **`@clipboard`** | Inject clipboard contents | ✅ Done |
| **Include directive** | `<!-- include: ./docs/style.md -->` in AGENTS.md | ✅ Done |
| **Hint templates** | Reusable hint sets in `~/.ppxai/hint-templates.yaml` | ✅ Done |

### Documentation Site (Post v1.14.2 - Master) ✅

**Note:** Added to master after v1.14.2 release. Not a versioned release.

| Feature | Description | Status |
|---------|-------------|--------|
| **MkDocs setup** | `mkdocs.yml` with Material theme | ✅ Done |
| **Auto-deploy workflow** | GitHub Actions deploys on release tag | ✅ Done |
| **Versioned docs** | `mike` plugin for version selector | ✅ Done |
| **Search** | Built-in full-text search | ✅ Done |
| **Release integration** | Docs deploy as part of release process | ✅ Done |

**Technology Stack:**
- **MkDocs** - Static site generator from markdown
- **Material for MkDocs** - Theme with dark mode, search, code highlighting
- **mike** - Versioning plugin (each release gets archived docs)
- **GitHub Pages** - Hosting at `rcconsult.github.io/ppxai`

**URL Structure:**
```
https://rcconsult.github.io/ppxai/
├── /dev/                  # Dev version (master branch)
├── /latest/              # Latest release (alias)
├── /1.14.2/              # Specific version
└── /getting-started/     # Navigation sections
```

**Automation:**
- Push to master → Deploys as `/dev/`
- Release tag (`v*`) → Deploys as versioned `/X.Y.Z/` + `latest` alias
- Manual trigger supported via workflow_dispatch

---

## v1.15.x Series - Next Generation TUI (ppxaide)

**Theme**: Textual-based TUI replacing Rich-based TUI as the primary terminal interface

**User value**: Visual-focused TUI with mouse support, CSS theming, proper editor workflows, and widget-based UI

**Approach**: Incremental development. ppxaide starts minimal and catches up with current TUI and Desktop Web App features over multiple v1.15.x releases.

**Migration path**:
- v1.15.0: ppxaide launches as separate command (`ppxaide` vs `ppxai`)
- v1.15.x: Feature parity achieved incrementally
- v1.16.x: ppxaide becomes `ppxai`, old TUI deprecated

### v1.15.0 - ppxaide Core TUI ✅

| Feature | Description | Status |
|---------|-------------|--------|
| **Textual SDK integration** | Build on current `ppxai/engine/` architecture | ✅ Done |
| **New entry point** | `ppxaide` command (separate from `ppxai`) | ✅ Done |
| **Core chat UI** | Streaming responses with Markdown rendering | ✅ Done |
| **Markdown in chat bubbles** | Full markdown with clickable URLs, headers, code blocks | ✅ Done |
| **Status badges** | Provider, model, tools, context, CWD in header | ✅ Done |
| **Mouse support** | Click-to-scroll, selectable text | ✅ Done |
| **CSS themes** | 17+ themes (catppuccin-mocha, dracula, tokyo-night, etc.) | ✅ Done |
| **Type-based renderer** | 17 CommandResult types with mechanical UI dispatch | ✅ Done |
| **Blinker event bus** | Decoupled component communication | ✅ Done |
| **Thinking indicators** | "Thinking..." animation while waiting for response | ✅ Done |
| **Reasoning token support** | DeepSeek R1, GPT-OSS thinking visualization | ✅ Done |
| **Generation params** | temperature, top_p, frequency_penalty configuration | ✅ Done |
| **Tools verbose setting** | `/tools set verbose on/off` for detailed tool output | ✅ Done |
| **Command history** | Arrow key history navigation with session persistence | ✅ Done |
| **WORKING_DIR_CHANGED** | Status bar updates on `cd` command | ✅ Done |
| **1105 tests passing** | Comprehensive test coverage | ✅ Done |

**Architecture:**

```
ppxai/tui/                     # New module (Textual-based)
├── __init__.py                # Entry point: ppxaide command
├── app.py                     # PPXAIDEApp(textual.App)
├── widgets/                   # Custom widgets
│   ├── message_box.py         # Chat message display
│   ├── streaming.py           # Streaming response widget
│   ├── tool_call.py           # Collapsible tool call display
│   └── status.py              # Status badges
└── themes/                    # CSS theme files
    ├── standard.tcss
    ├── tron-legacy.tcss
    ├── matrix.tcss
    └── nord.tcss
```

**Key design decisions:**
- **Separate command** - `ppxaide` coexists with `ppxai` (not a replacement)
- **Shared engine** - Uses existing `EngineClient` via composition
- **Feature parity target** - Match current TUI commands over v1.15.x releases
- **CSS-first theming** - Leverage Textual's CSS for consistent styling

### v1.15.1 - AI Tool Integration & Performance ✅

| Feature | Description | Status |
|---------|-------------|--------|
| **`display_file` tool** | AI proactively shows files after generating/modifying them | ✅ Done |
| **UI responsiveness** | Worker threads with `call_from_thread()` prevent event loop blocking | ✅ Done |
| **Footer status widget** | Live elapsed timer during streaming | ✅ Done |
| **Copy button layout** | Moved to bottom of message bubble (matches VSCode) | ✅ Done |

### v1.15.2 - Validation, Robustness & Benchmarks

| Feature | Description | Status |
|---------|-------------|--------|
| **Response validation** | Detects LLM hallucinations and tool result contradictions | ✅ Done |
| **`ResponseValidator`** | Tracks tool calls, validates claims against results | ✅ Done |
| **WARNING SSE events** | Real-time alerts when model claims contradict tool results | ✅ Done |
| **Unicode whitespace** | 5-level fuzzy matching in `apply_patch` for NBSP, NNBSP, thin spaces | ✅ Done |
| **Truncated tool call detection** | Detects "I'll use X tool" with incomplete JSON, auto-retries | ✅ Done |
| **`/terminal` command** | Terminal detection and image protocol config help | ✅ Done |
| **iTerm2 image protocol** | Native inline image support for WezTerm | ✅ Done |
| **LLM benchmark suite** | 6 categories, 21+ test cases for agentic coding evaluation | ✅ Done |
| **Generation params** | Gemini and Perplexity load temperature/top_p from config | ✅ Done |
| **Streaming cancellation** | Graceful Ctrl+C during streaming in ppxaide | ✅ Done |
| **Double Ctrl+C to quit** | Prevents accidental exits in ppxaide | ✅ Done |

**Dependencies:**
- `textual>=0.47.0` (added to optional extras: `pip install ppxai[tui]`)

### v1.15.3 - Config Hot-Reload Fix ✅

| Feature | Description | Status |
|---------|-------------|--------|
| **Config auto-reload** | `/model` and `/provider` commands reload config from disk before listing | ✅ Done |
| **`EngineClient.reload_config()`** | Single entry point to refresh all cached config data | ✅ Done |
| **Session restore reload** | All 3 clients (Textual, Rich, HTTP) reload config before restore | ✅ Done |
| **Platform alignment** | Signal handling (SIGINT/SIGTERM) on all platforms | ✅ Done |
| **TUI EventBus stability** | NoMatches guards, WARNING event handler | ✅ Done |

### v1.15.4 - Live HTML Preview & SSL Fixes

| Feature | Description | Status |
|---------|-------------|--------|
| **`/preview` command** | Live-reloading HTML preview across all 3 clients (TUI, Web, VSCode) | ✅ Done |
| **PreviewServer** | Stdlib HTTP server with mtime polling, auto-opens browser | ✅ Done |
| **Cache busting** | `rewrite_asset_paths()` appends `?_t=<mtime>` to asset URLs | ✅ Done |
| **Corporate SSL** | `_create_ssl_context()`, HTTP fallback, configurable timeouts | ✅ Done |
| **Debug logging** | `Logger.enable_all()` / `disable_all()` for all logger instances | ✅ Done |
| **VSCode consent EventBus** | Consent dialogs migrated to EventBus pattern | ✅ Done |
| **highlight.js rebuild** | Added PowerShell, Dockerfile, DOS, AppleScript | ✅ Done |
| **1,227 tests passing** | 34 preview + 16 SSL tests added | ✅ Done |

**File Navigation:** Deferred to v1.16.0. See [docs/TODO-v1.16.0.md](docs/TODO-v1.16.0.md) for detailed spec.

### v1.15.5 - Multi-Line Input & Escape Key Fix

| Feature | Description | Status |
|---------|-------------|--------|
| **Multi-line input** | TextArea replaces Input widget; Enter=newline, Ctrl+Enter=submit | ✅ Done |
| **Escape key fix** | Priority-based dismissal: help panel > modals > side panel | ✅ Done |
| **PyInstaller blinker fix** | Added `blinker` to ppxaide.spec hiddenimports | ✅ Done |
| **Benchmark metadata** | `tool_calling_method` field (native vs prompt_based) in results | ✅ Done |
| **BENCHMARKS.md guide** | 700+ line guide for benchmark system | ✅ Done |
| **Debug cleanup** | Removed development debug notifications from action_cancel | ✅ Done |
| **1,237 tests passing** | 15 new multi-line input tests added | ✅ Done |

### v1.15.6 - Model Profile System & Native OpenAI Provider

**Status:** ✅ All items done, pre-release (pending merge)
**Branch:** feature/benchmark-openai-models
**Release Notes:** [docs/RELEASE-NOTES-v1.15.6.md](docs/RELEASE-NOTES-v1.15.6.md)
**Debug Sessions:** [docs/ARCHIVE-v1.15.6-debug-sessions.md](docs/archive/ARCHIVE-v1.15.6-debug-sessions.md)

| Feature | Description | Status |
|---------|-------------|--------|
| **`OpenAINativeProvider`** | Native OpenAI API: Chat Completions + Responses API, 404 auto-fallback | ✅ Done |
| **Benchmark results** | 54+ runs across 27 model variants, behavior analysis | ✅ Done |
| **o4-mini/gpt-4.1-mini → prompt-based** | Prefix-based routing: up to 80.8% / 100% prompt-based | ✅ Done |
| **JSON stripping** | Strip tool JSON from response text when native tool_calls present | ✅ Done |
| **Brace-counting JSON parser** | `_find_json_objects()` handles nested braces in apply_patch diffs | ✅ Done |
| **`model_profiles.py`** | 37 built-in profiles + `ModelProfileRegistry` with glob matching | ✅ Done |
| **Codex native tool calling** | Both codex models work via Responses API with native function calls | ✅ Done |
| **Read-claim validator** | Catches "I read each file" with 0 `read_file` calls | ✅ Done |
| **ppxaide `/debug-log on` fix** | `Logger.enable_all()` now called when debug logging enabled | ✅ Done |
| **AGENTS.md hints** | OpenAI model hints, anti-hesitation, anti-chaining | ✅ Done |
| **1,349 tests passing** | 46 OpenAI provider + 41 model profile + others | ✅ Done |

---

## Completed (v1.16.x)

### v1.16.0 - Profile-Driven Tool Loop

**Status:** ✅ Released (2026-02-26)
**Branch:** feature/v1.16.0
**Release Notes:** [docs/RELEASE-NOTES-v1.16.0.md](docs/RELEASE-NOTES-v1.16.0.md)

**Why major version bump:** Changes to `chat.py` tool loop affect every provider and every client.

| Feature | Description | Status |
|---------|-------------|--------|
| **Provider hierarchy** | `BaseProvider` ABC for OpenAINative/Gemini, remove `hasattr` guards | ✅ Done |
| **Profile-driven routing** | Replace binary `use_native_tools` with `ModelProfile` lookup in `chat.py` | ✅ Done |
| **`fallback_on_empty`** | Adaptive fallback: native → prompt-based mid-conversation | ✅ Done |
| **Proper `tool` role messages** | Replace synthetic assistant/user pairs with `tool` role + `tool_call_id` | ✅ Done |
| **Multi-tool support** | Process all native tool calls (not just first) when profile allows | ✅ Done |
| **Grouped tool call UI** | `TOOL_GROUP_START/END` events, collapsible bubbles in all clients | ✅ Done |
| **Config overrides** | `tool_calling` settings per model in ppxai-config.json + AGENTS.md | ✅ Done |
| **`/model info`** | Show active profile for current model with source attribution | ✅ Done |
| **Session migration** | v1.15.x sessions load in v1.16.0 without data loss | ✅ Done |
| **Session context reset** | Strip assistant/tool messages on model switch | ✅ Done |
| **Per-model iteration limits** | `ModelProfile.max_tool_iterations` | ✅ Done |
| **Belt-and-suspenders** | Tool hints injected for fallback-enabled native profiles | ✅ Done |
| **Session pollution detection** | Bigram similarity check after model switch | ✅ Done |
| **SSE disconnect detection** | Cancel background tasks on client disconnect | ✅ Done |
| **`/ls` and `/tree` commands** | Directory listing and tree in all 3 clients + HTTP | ✅ Done |
| **Benchmark v2** | 36 tests/9 categories, AGENTS.md delta testing, partial credit | ✅ Done |
| **1,536 tests passing** | 187 new tests (provider hierarchy, routing, tool messages, config) | ✅ Done |

**Gaps addressed (from MODEL-BEHAVIOR-ANALYSIS.md):**
1. Binary decision at wrong layer → Profile-driven routing
2. Tool results as synthetic messages → Proper `tool` role messages
3. Single tool call per iteration → Multi-tool support
4. No response deduplication → JSON stripping
5. Static provider capabilities → Adaptive profiles with fallback

---

## Completed (v1.16.1)

### v1.16.1 - Gemini 3 Model Updates + File Tree + CommandFactory Server Pattern

**Status:** ✅ Complete (2026-03-01)
**Branch:** feature/v1.16.1
**Release Notes:** [docs/RELEASE-NOTES-v1.16.1.md](docs/RELEASE-NOTES-v1.16.1.md)

#### Gemini 3 Model Updates (Priority: High)

**Reference:** https://ai.google.dev/gemini-api/docs/gemini-3

| Task | Description | Status |
|------|-------------|--------|
| **Add gemini-3.1-pro-preview to config** | Model entry + pricing ($2/$12 per 1M, <200K ctx) in `ppxai-config.json` | ✅ Done |
| **Remove deprecated gemini-2.0-flash** | Shutting down June 1, 2026 | ✅ Done |
| **thinking_level param** | Replace deprecated `thinking_budget` with `thinking_level` in GeminiProvider | ✅ Done |
| **model_profiles.py context limits** | 1M input / 64K output for all gemini-3.x profiles | ✅ Done |
| **google-genai SDK pin** | `<1.57.0` due to code editing regression (KI-001) | ✅ Done |

#### ppxaide Interactive File Tree

| Feature | Description | Status |
|---------|-------------|--------|
| **FileTree widget** | Norton Commander style left sidebar (DirectoryTree extension) | ✅ Done |
| **Layout integration** | 3-pane layout, Ctrl+B toggle, CSS split ratios | ✅ Done |
| **Key bindings** | Enter=preview, Ctrl+Enter=edit, Space=@file inject, Escape=dismiss | ✅ Done |
| **Resize keys** | `-`/`=` resize file tree and side panel | ✅ Done |

#### CommandFactory Server Pattern (POC: /usage)

| Feature | Description | Status |
|---------|-------------|--------|
| **`to_dict()` serialization** | CommandResult types serialize to JSON for HTTP transport | ✅ Done |
| **`ServerCommandContext`** | Adapter wrapping EngineClient for server-side commands | ✅ Done |
| **`POST /command/{name}`** | Generic 10-line endpoint dispatching any command via CommandFactory | ✅ Done |
| **Web app migration** | `handleUsageCommand()` → server call + `renderCommandResult()` | ✅ Done |
| **VSCode migration** | `handleUsageCommand()` → `executeCommand()` + `renderCommandResult()` | ✅ Done |
| **Shared formatters** | `formatTableResult()` with usage-aware bullet summary + table | ✅ Done |
| **Integration tests** | 18 tests validating counter values across 3 real providers | ✅ Done |

#### Session Restore Refactor

| Feature | Description | Status |
|---------|-------------|--------|
| **`EngineClient.restore_session()`** | Single entry point for all session restoration | ✅ Done |
| **All clients migrated** | Rich, Textual, HTTP, JSON-RPC delegate to centralized method | ✅ Done |

| **1,624 tests passing** | 88 new tests (+28 FileTree, +20 regex/parsing, +40 other) | ✅ Done |

---

## Completed (v1.16.2)

### v1.16.2 - Web App Refactor + RightPanelFrame + File Tree + Inline Images

**Status:** ✅ Complete (2026-03-07)
**Branch:** bugfix/1.16.2
**Release Notes:** [docs/RELEASE-NOTES-v1.16.2.md](docs/RELEASE-NOTES-v1.16.2.md)

| Feature | Description | Status |
|---------|-------------|--------|
| **Bug fixes** | Wrong save path, validator false positive, redundant set_model, server stale session | ✅ Done |
| **Web app file tree** | Collapsible sidebar with @file injection, drag-resize, `..` parent nav, `at_fs_root` | ✅ Done |
| **Web app refactor** | app.js 4,264→~2,100 lines: ApiClient, CommandDispatcher, StreamHandler, AppState | ✅ Done |
| **RightPanelFrame** | View stack navigator with 5 view types, LRU eviction, back/forward nav, pin | ✅ Done |
| **Virtual scroll** | Buffer-based message virtualization (60-message DOM window) | ✅ Done |
| **Inline `<think>` routing** | Qwen3/vLLM reasoning blocks routed as REASONING_CHUNK | ✅ Done |
| **AGENTS.md tuning** | Qwen3-4B model hints, benchmark runs (76-82%), anti-pattern fix | ✅ Done |
| **Inline chat images** | Web app: images from `display_file` render inline in chat; lightbox zoom | ✅ Done |
| **Shell config** | `tools.shell.shell_bin` + `login_shell` — configurable shell and login mode | ✅ Done |
| **Server fixes** | Stale session pointer, absolute/home paths in file API, default working dir | ✅ Done |
| **Web app UX fixes** | File tree flicker on chat send, image ordering, stale expandedDirs after cd | ✅ Done |
| **1,639 unit tests** | 200 Playwright E2E tests (up from ~115); +85 new web tests | ✅ Done |

---

## Completed (v1.17.x)

### v1.17.0 - Server + Config Modularization, K8s POC ✅

**Status:** ✅ Complete (2026-03-15)
**Release Notes:** [docs/RELEASE-NOTES-v1.17.0.md](docs/RELEASE-NOTES-v1.17.0.md)

| Feature | Description | Status |
|---------|-------------|--------|
| **Server modularization** | `server/http.py` 2,936→372 lines: `models.py`, `state.py`, `streaming.py` + `routes/` (13 modules) | ✅ Done |
| **Config submodules** | `config/__init__.py` 943→262 lines: `providers.py`, `tools.py`, `features.py`, `paths.py`, `context.py`, `prompts.py` | ✅ Done |
| **Centralized key registry** | `ppxai/tui/keys.py` — single source of truth, all BINDINGS generated | ✅ Done |
| **Textual upgrade** | 7.4.0 → 8.1.1 (DirectoryTree fixes, GC improvements) | ✅ Done |
| **K8s POC** | 5 phases: namespace, Dockerfile.server, session manager, login service, LDAP auth | ✅ Done |
| **Client log forwarding** | Web/VSCode forward client logs to server debug log | ✅ Done |
| **Web heartbeat watchdog** | Detect disconnects, auto-reconnect SSE | ✅ Done |
| **Deploy structure** | `deploy/{compose,docker,images,k8s}/` + shared configs | ✅ Done |
| **AppState architecture docs** | `docs/TODO-appstate-{0..5}.md` + refactoring tracker | ✅ Done |

### v1.17.1 - AppState Wiring + EngineClient Decomposition ✅

**Status:** ✅ Complete (2026-03-26)
**Release Notes:** [docs/RELEASE-NOTES-v1.17.1.md](docs/RELEASE-NOTES-v1.17.1.md)

| Feature | Description | Status |
|---------|-------------|--------|
| **AppState (hand-crafted)** | Python, JS, TS implementations wired across all 4 clients | ✅ Done |
| **EngineClient decomposition** | 1,588→955 lines: `checkpoint_ops.py`, `consent_ops.py`, `bootstrap_ops.py` | ✅ Done |
| **CommandContext proxy** | `__getattr__` base class, Rich/Textual are 2-3 line stubs | ✅ Done |
| **Constants centralized** | `ppxai/constants.py` — single source for magic values | ✅ Done |
| **Server DI** | `Depends(get_session)` across all 13 route modules | ✅ Done |
| **`/preview --serve`** | Full-stack preview with live reload | ✅ Done |
| **`/terminal`** | xterm.js + PTY WebSocket terminal | ✅ Done |
| **Stream handler extraction** | `tui/stream_handler.py` — 2,303→1,718 lines in `app.py` | ✅ Done |
| **Event router pattern** | Strategy dispatch dicts in `EventHandler` + `TUIEventHandler` | ✅ Done |
| **Session → AppState sync** | `on_usage_updated`, `on_name_changed` callbacks | ✅ Done |

### v1.17.2 - SSE State Sync + Benchmark Infra ✅

**Status:** ✅ Complete (2026-03-28)
**Release Notes:** [docs/RELEASE-NOTES-v1.17.2.md](docs/RELEASE-NOTES-v1.17.2.md)

| Feature | Description | Status |
|---------|-------------|--------|
| **SSE `state_sync` push** | Cross-client AppState alignment via server-sent events | ✅ Done |
| **Thread-safe AppState** | Lock-protected dispatch and event queue | ✅ Done |
| **Heartbeat streaming fix** | Skip health failures during active LLM streaming (single-worker) | ✅ Done |
| **ppxaide iTerm2 images** | Native image protocol, file tree syncs with AppState | ✅ Done |
| **Preview auto-detect** | Venv python detection + single-quoted command support | ✅ Done |
| **Helm chart 0.3.0** | Ingress field manager conflict fix, preview route prefix detection | ✅ Done |
| **K8s benchmark jobs** | `--agents-md` toggle, delta test results, in-cluster runs | ✅ Done |
| **New models benchmarked** | Qwen3.5-122B-A10B, Qwen3.5-27B-FP8, Qwen3-Coder-Next-NVFP4-GB10 | ✅ Done |
| **Web verbose tools toggle** | Menu indicator + SSE state_sync for tools_verbose, debug_log | ✅ Done |

### v1.17.4 - File Upload & Data Processing

**Status:** All phases complete + coder deployed + PPTX visual preview, ready for release
**Branch:** `feat/file-upload`
**Plan:** [docs/TODO-file-upload.md](docs/TODO-file-upload.md)

| Feature | Description | Status |
|---------|-------------|--------|
| **Phase 0 — Multimodal plumbing** | `Message.content: Union[str, list[dict]]`, `text_content()` helper, all providers + clients updated | ✅ Done |
| **Phase 1 — Rich TUI `/attach`** | `/attach <path>` slash cmd, inline image preview, `EngineClient.chat(MessageContent)`, AppState `context_attachments`, dynamic autocomplete | ✅ Done |
| **Phase 2 — Engine foundation** | SessionFileStore, file preprocessing, image validation, VL sidecar, PDF tools, `/doctor`, `/attach remove`, `supports_vision`, Gemini 3.1 + Gemma 4 models | ✅ Done |
| **Phase 3 — Server API** | `ChatRequest.files[]`, preprocessing in chat route, `state_sync` SSE, `POST /complete`, `GET /files/serve/{file_id}`, `GET /files/preview/{file_id}` | ✅ Done |
| **Phase 4 — File tools** | Excel (openpyxl), PPTX (python-pptx + LibreOffice + VL), Word (read_docx, stdlib), CSV (lazy >50KB) | ✅ Done |
| **Phase 5 — Web client** | Drag-drop, file picker, attachment badges, SheetJS Excel preview (DataTableViewer), PPTX slide navigator, PDF Blob URL, resizable split panel | ✅ Done |
| **Phase 6 — VSCode client** | Webview picker, drag-drop, pendingFiles staging, extension host forwarding | ✅ Done |
| **Phase 7 — Textual TUI** | FileTree `a` key attach, Ctrl+U shortcut, `build_multimodal_content()`, `pending_files` attribute | ✅ Done |
| **Task #11 — CompletionProvider** | `engine/completion.py`, `POST /complete` server route, Rich completer delegating to engine | ✅ Done |
| **Task #11 Follow-up — Cross-client parity** | Engine owns all sources (commands, path args, subcommands `/tools`/`/usage`/`/checkpoint`/`/status`/`/theme`, dynamic `/model`+`/provider`, `/tools help <tool>`, `@git`/`@tree`/`@clipboard`/`@url`). Rich completer 594→85 lines; Textual 238→100 lines; VSCode unifies `@` + `/` onto one `POST /complete` flow. Web picks up all new sources for free. | ✅ Done |
| **AppState schema DTO** | `ppxai/engine/app_state_schema.json` is the canonical golden source of truth. Python loads via `importlib.resources`, Web via `window.APP_STATE_SCHEMA` injected by FastAPI, VSCode via bundled copy kept in sync by `scripts/sync-schema.js` (precompile hook). `GET /schema/app-state` exposes the schema as a diagnostic endpoint. Zero hand-maintained parallel schemas. | ✅ Done |
| **K8s deployment** | Dockerfile `[data]+libreoffice`, PV affinity, deploy.sh resilience, VL sidecar, ingress body-size, login wait | ✅ Done |

**Tests:** 2288 total (was 1753 before Phase 0). 535 new tests, zero regressions.
**System deps (K8s):** poppler-utils, libreoffice-nogui. **JS libs (web):** SheetJS (xlsx.full.min.js).

---

## In Progress (v1.18.0)

**Branch:** `feature/v1.18.0` | **Theme:** Agent heartbeat primitives + stabilization pass

### v1.18.0 - Agent Heartbeat Primitives (P0 — landed on branch)

| Feature | Description | Status |
|---------|-------------|--------|
| **`AgentBeatState` + lifecycle events** | `EventType.AGENT_BEAT` + `AGENT_RUN_START` / `_COMPLETE` / `_ERROR` + `AGENT_ZOMBIE`, emitted by `chat_with_tools`. Serializable `as_event_data()` payload. | ✅ Landed |
| **`AppState.agent_beat` field** | Schema-driven across Python/JS/TS; pushed via `state_sync` SSE; cleared on run end. | ✅ Landed |
| **Zombie circuit-breaker** | `tools.agent.zombie_threshold` (default 3, 0 disables) stops the tool loop after N consecutive failed iterations. | ✅ Landed |
| **Client renderers** | Rich dim line, ppxaide status badge (success/warning/error variants), Web + VSCode header badge. | ✅ Landed |
| **Architecture doc** | [ARCHITECTURE.md §"Agent Heartbeat Primitives"](docs/ARCHITECTURE.md) + [RELEASE-NOTES-v1.18.0.md](docs/RELEASE-NOTES-v1.18.0.md). | ✅ Landed |

### v1.18.0 - Stabilization Pass (Phases 1–5 — landed on branch)

Targeted cleanup pass between heartbeat P0 and the next feature
workstream. Pays down architectural drift accumulated across v1.16.x
/ v1.17.x. See [STABILIZATION-v1.18.0.md](docs/STABILIZATION-v1.18.0.md)
for the full pass summary.

| Phase | Feature | Status |
|-------|---------|--------|
| **1** | AGENT_BEAT cross-client rendering parity test (4 clients, 5 fixtures, 20 assertions) | ✅ Landed |
| **2** | `GET /state` endpoint for SSE reconnect catch-up; `SSE_SYNC_FIELDS` hoisted to module-level constant | ✅ Landed |
| **2.5** | 19 pre-existing test failures cleared on Windows; 2 real prod bugs fixed (`/attach` CRLF, CSV mimetype routing) | ✅ Landed |
| **3** | `AppState.last_message_role` field; Rich interrupt handler off direct `session.messages` scanning | ✅ Landed |
| **4** | `ppxai/common/format.py` canonical + JS/TS mirrors with byte-identical parity tests | ✅ Landed |
| **5a-c** | Trivial cleanup, `has_vision_model` alias removed, PyInstaller spec full route listing | ✅ Landed |
| **5d** | Zero-cost badge suppression unified across all four clients | ✅ Landed |
| **5e** | AppState listener contract + error routing conventions documented | ✅ Landed |
| **5f** | `AutosaveFailureGuard` surfaces sustained auto-save failures; Textual `query_one` excepts narrowed to `NoMatches` | ✅ Landed |
| **5g** | 6 pure helpers promoted to public API; 2 I/O helpers extracted to `ppxai/common/atomic_file.py` and `ppxai/common/docx_to_pdf.py` | ✅ Landed |

**Cumulative impact:** 2,410 → 2,591 passing tests, 0 failing, 4 real
production bugs fixed as side-effects, 1 deprecated alias removed,
8 former private helpers given documented public contracts.

### v1.18.1 - AppState Codegen + Routing Infrastructure (deferred from v1.18.0)

Originally planned to ship alongside heartbeat in v1.18.0; moved to
v1.18.1 because they're each substantial enough to deserve dedicated
release notes — bundling four workstreams in one release made review
impractical.

| Feature | Description | Plan |
|---------|-------------|------|
| **AppState schema + generator** | YAML → Python/JS/TS codegen, CI `--check` mode | [TODO-appstate-codegen.md](docs/TODO-appstate-codegen.md) |
| **AppState client wiring** | Replace hand-crafted with generated across Rich, Textual, Web, VSCode, k8s | [TODO-appstate-codegen.md](docs/TODO-appstate-codegen.md) |
| **Routing infrastructure** | `RoutingRole`, `ProviderPool`, `ModelRouter` classes | [TODO-routing.md](docs/TODO-routing.md) Phase 1 |
| **Coding command routing** | Replace `coding_model` with `router.resolve(RoutingRole.CODER)` | [TODO-routing.md](docs/TODO-routing.md) Phase 2 |

### v1.18.2 - Agent + Chat Mode Routing

| Feature | Description | Plan |
|---------|-------------|------|
| **Agent mode routing** | Planner role on first turn, tools role on iterations 2+ | [TODO-routing.md](docs/TODO-routing.md) Phase 3 |
| **Chat mode routing** | Route regular chat to `chat` role, mode presets | [TODO-routing.md](docs/TODO-routing.md) Phase 4 |

### v1.18.3+ - Preset Commands + TUI Integration

| Feature | Description | Plan |
|---------|-------------|------|
| **`/preset` command** | List, switch, show preset bindings | [TODO-routing.md](docs/TODO-routing.md) Phase 5 |
| **Status bar preset badge** | Show active preset name in TUI/Web | [TODO-routing.md](docs/TODO-routing.md) Phase 5 |

### v1.19.x - Anthropic Provider (planned)

Moved from `docs/DEBT-INVENTORY-v1.18.3.md` Item 14 on 2026-05-05 — feature
work, not a fix, so it belongs on the roadmap rather than the debt list.
Pairs well with the multi-model routing work below: Claude as a coding-model
option in the routing layer is one of the listed motivations.

| Phase | Description | Effort |
|---|---|---|
| **Phase 1: API key (mainline)** | New `ppxai/engine/providers/anthropic.py` using the official `anthropic` Python SDK. Same shape as `openai_native.py` / `gemini.py`. `ModelProfile` entries for `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`. Auth via `ANTHROPIC_API_KEY`. Ships behind a `[anthropic]` extra in `pyproject.toml` so users opt into the dependency. | ~2-3 days |
| **Phase 2: TOS-aware OAuth fallback (opt-in)** | When `ANTHROPIC_API_KEY` is unset AND `ANTHROPIC_AUTH_TOKEN` is set (or detectable from `~/.claude/.credentials.json`), allow auth-token path. **Must:** (1) emit runtime WARNING the first time the fallback is invoked stating that reusing Claude Code credentials from non-Claude-Code clients may violate Anthropic TOS; (2) NOT auto-read `~/.claude/.credentials.json` without explicit `providers.anthropic.allow_claude_code_oauth: true` config flag; (3) implement token-refresh awareness — re-read credentials per request when opted in, fail loudly with "run `claude /login` and retry" on 401. | ~1 day |
| **Documentation** | New `docs/ANTHROPIC-PROVIDER.md` covering API-key setup (mainline, recommended), opt-in OAuth-reuse with the full TOS warning quoted verbatim, troubleshooting expired tokens. README provider table gets an Anthropic row. | ~half day |

**Why this matters:** Claude is currently the strongest coding model in the
v4.x generation; first-class support unlocks `/explain`, `/test`, `/docs`,
`/agent` against Claude with the same UX as the other providers.

**Caveats pinned so they don't get re-litigated:**
- The project does NOT endorse / guarantee / take legal responsibility for
  users using their Claude Code subscription credentials with ppxai. The
  runtime warning is the project's due-diligence boundary.
- The mainline (API-key) path has no TOS concerns and is the recommended
  setup. Phase 2 exists for users who explicitly choose the experimentation
  path.
- Auto-reading `~/.claude/.credentials.json` without opt-in is the project
  taking the user's TOS decision for them — not acceptable.

**Branch when ready:** `feat/anthropic-provider`. Phase 2 can be a follow-up
commit on the same branch or split into `feat/anthropic-oauth-fallback` if
the TOS-warning UX needs review independently.

---

### v1.19.x - Prompt Analyzer + Adaptive Routing (Future)

| Feature | Description | Plan |
|---------|-------------|------|
| **Rule-based classifier** | Tier 1: regex patterns for role classification | [TODO-routing.md](docs/TODO-routing.md) Phase 6a |
| **Decision logging** | `decisions.jsonl` with outcome signals | [TODO-routing.md](docs/TODO-routing.md) Phase 6b |
| **Embedding similarity** | TF-IDF cache for past prompt classification | [TODO-routing.md](docs/TODO-routing.md) Phase 6c |
| **Silent AI classifier** | Fast model fallback for ambiguous prompts | [TODO-routing.md](docs/TODO-routing.md) Phase 6d |
| **Adaptive learning** | Self-improving routing from decision logs | [TODO-routing.md](docs/TODO-routing.md) Phase 7 |

---

## Future Considerations

These are tracked but not prioritized:
- **libghostty SDK** — `libghostty-vt` is a zero-dep library (not even libc) extracted from Ghostty's core (1M+ daily macOS users since 1.0 in late 2024). Provides VT sequence parsing + full terminal state (cursor, styles, wrapping, scrollback, reflow). **Zig API complete**, **C API functional** (proven by [ghostling](https://github.com/ghostty-org/ghostling) — complete terminal in single C file). Features: SIMD-accelerated parsing (>100 MB/s), DFA parser (14 states, O(1) transitions), Kitty Keyboard Protocol key encoder, Kitty Graphics Protocol, mouse encoding (SGR/X10/URxvt), terminal-to-HTML encoding, render state API with row/cell iterators. Platforms: macOS, Linux, Windows, WebAssembly, Android (x86_64 + aarch64 + 32-bit). Growing ecosystem: Rust wrappers, C# experiments, Windows ports, browser embeds. **ppxai integration:** CI pipeline ready (`.github/workflows/build-ghostty-vt.yml`), prebuilt libs at `libghostty-20260319` release, Python ctypes wrapper scaffolded (`ppxai/terminal/ghostty.py`). See [TODO](docs/TODO-libghostty-integration.md), [ghostling](https://github.com/ghostty-org/ghostling), [mitchellh.com/writing/libghostty-is-coming](https://mitchellh.com/writing/libghostty-is-coming)
- ~~**Per-provider tool config**~~ - ⏳ Partially addressed by Model Profile System (v1.15.6/v1.16.0)
- **Custom tools** - User-defined tools in `~/.ppxai/tools/`
- ~~**Provider-aware tool guidance**~~ - ✅ Implemented in v1.13.3
- ~~**Cost display in `/usage`**~~ - ✅ Implemented (shows $ cost in session and reports)
- ~~**Per-provider cost rates**~~ - ✅ Implemented in `config.py` (pricing per model)
- ~~**Standardized error handling**~~ - ✅ All providers now have detailed traceback logging
- **`/rewind` browser** - Interactive checkpoint history viewer
- **`/agent --dry-run`** - Preview changes without applying
- **Cross-session search** - Semantic search over `~/.ppxai/sessions/`. Watch: [microsoft/typeagent-py](https://github.com/microsoft/typeagent-py) (MIT, v0.4.0-dev) — Structured RAG with 6 parallel indexes (semantic, property, temporal, thread-scoped). Interesting architecture but too heavy today (azure-identity, numpy, pydantic-ai, Python 3.12+). Revisit when ppxai needs session search or typeagent reaches 1.0 with lighter deps

### Multi-Model Orchestration (Research)

**Reference:** [docs/2512.15943v1.pdf](docs/archive/2512.15943v1.pdf) - "Small Language Models for Efficient Agentic Tool Calling" (AWS, Dec 2025)

**Paper Summary:**
- Fine-tuned `facebook/opt-350m` (350M params) on ToolBench dataset (187,542 examples, 16,000+ APIs)
- Single epoch training with SFT (Supervised Fine-Tuning) using HuggingFace TRL
- Hyperparameters: lr=5×10⁻⁵, batch=32, gradient clipping=0.3, FP16, AdamW

**Benchmark Results (ToolBench - 1,100 test queries across 6 categories):**

| Model | Params | Pass Rate | Gap |
|-------|--------|-----------|-----|
| **Fine-tuned SLM** | **350M** | **77.55%** | – |
| ToolLLaMA-DFS | 7B | 30.18% | -47% |
| ChatGPT-CoT | 175B | 26.00% | -52% |
| ToolLLaMA-CoT | 7B | 16.27% | -61% |
| Claude-CoT | 52B | 2.73% | -75% |

**Why Small Models Win at Tool Calling:**
1. **Parameter efficiency** - All capacity focused on tool patterns, not general language
2. **Behavioral focus** - Learns structured Thought-Action-Observation patterns
3. **No overgeneralization** - Precise API calls vs verbose explanations

**Implication for ppxai:** Specialized small models can dramatically outperform general-purpose LLMs at specific tasks like tool selection. A 350M router could achieve 77% accuracy while ChatGPT achieves only 26%.

**Proposed Architecture - Dual Model Orchestration:**

```
User Query → Tool Router (small, fast) → Decision
                                            ↓
                            [tool_needed?] ─┬─ Yes → Execute Tool → Response Generator (larger)
                                            └─ No  → Response Generator (larger)
```

| Component | Model Size | Role | Latency |
|-----------|------------|------|---------|
| Tool Router | 350M-1.3B | Decide if/which tool to call | <50ms |
| Response Generator | 3B-7B | Generate code, explanations | ~60 tok/s |

**Benefits:**
- Faster tool decisions (small model = instant routing)
- Better tool selection accuracy (specialized > general)
- Reduced load on main model (only generates, doesn't decide)
- Fits 6GB VRAM: router (500MB) + generator (1.9GB-4.7GB)

**Implementation Path:**

| Phase | Task | Effort |
|-------|------|--------|
| 1 | Add tool-calling benchmark to test suite | Low |
| 2 | Test existing small models (Qwen2.5-0.5B, DeepSeek-Coder 1.3B) on ppxai tools | Medium |
| 3 | Config option: `tool_router_model` separate from `default_model` | Medium |
| 4 | Fine-tune ppxai-specific tool router on our schema (follow paper's SFT approach) | High |

**Ollama Multi-Model Setup:**
```bash
# Router model (stays loaded, instant)
ollama pull qwen2.5-coder:0.5b  # 398MB

# Generator model (loaded on demand)
ollama pull qwen2.5-coder:3b    # 1.9GB

# Run both with OLLAMA_NUM_PARALLEL=2
OLLAMA_NUM_PARALLEL=2 ollama serve
```

**Config example:**
```json
{
  "ollama": {
    "tool_router_model": "qwen2.5-coder:0.5b",
    "default_model": "qwen2.5-coder:3b",
    "orchestration": "router_generator"
  }
}
```

**Paper Limitations to Consider:**
- Model optimized for ToolBench format - may not generalize to ppxai's tool schema
- 350M limit may struggle with complex contextual nuances
- Requires retraining as tools evolve

**Status:** Research phase. PDF saved to `docs/`. Next: benchmark existing small models on ppxai tool schema before implementation.

### Voice Input / Speech-to-Text (Research)

**Reference:** [cjpais/Handy](https://github.com/cjpais/Handy) — MIT, Tauri desktop app, offline, macOS/Windows/Linux. Whisper via `whisper-rs`, Parakeet V3 via `transcribe-rs`, Silero VAD, global hotkey → synthetic keystrokes into focused window.

**Problem:** ppxai has four clients (Rich TUI, Textual TUI, Web, VSCode) and none accept voice input today. Users wanting dictation have to copy-paste from an external transcription app.

**Constraint:** Handy has **no programmatic integration surface** — no HTTP/WebSocket server, no file/stdout mode, no plugin API. Its only output is OS-level synthetic keystrokes. That works for GUI text fields (VSCode webview, browser) but not reliably for terminal UIs.

**Three integration options:**

| Option | Effort | Fit | Notes |
|--------|:-:|:-:|-------|
| **A.** Run Handy alongside ppxai, use its hotkey | None | Poor | Works in VSCode webview + browser, likely broken in TUIs. No start/stop signal, no partials, no mic indicator in-chat. |
| **B.** Fork Handy, add `--serve` WebSocket output mode | Medium | OK | Small Rust PR on a fast-moving upstream (releases every 3–10 days). Fork maintenance burden. |
| **C.** Build `ppxai-voice` sidecar from Handy's ingredients | High | Best | Take `whisper-rs` or `transcribe-rs` + Silero VAD + `cpal`. Ship as small Rust binary alongside `ppxai-server`. Expose WebSocket to all clients. Mic button in chat UI, partial transcripts, per-provider routing. Model cache under `~/.ppxai/models/`. No fork. |

**Recommended path:** Option A confirmed working in VSCode webview (tested 2026-04-24). Ship a docs entry now; defer B/C unless users ask for in-chat mic button, partials, or TUI dictation.

**Near-term actions (Option A productization):**
- Add "Voice input" section to `docs/` and `README.md` — install Handy, recommended hotkey, focus-the-input workflow
- Note known limitations: no start/stop signal in chat UI, no partials, TUI reliability untested
- Link from VSCode extension README (most likely to work since webview accepts synthetic keystrokes)

**If Option C becomes necessary later, decisions to make up front:**
- Backend: `whisper-rs` (GPU, multi-lang) vs `transcribe-rs`/Parakeet (CPU, faster)
- Transport: WebSocket (SSE can't push binary audio for round-trip) or Unix socket
- Where hotkey lives: each client owns its own binding, sidecar only does audio→text
- Model distribution: download-on-first-use, progress in `state_sync`, cached in `~/.ppxai/models/voice/`

**Status:** Option A validated. Next: docs entry. Revisit C if user demand materializes or Handy upstream adds a structured output mode (tracked in [Handy#933](https://github.com/cjpais/Handy/discussions/933)).

### Data Visualization Library Upgrade (Web App)

Current: Vanilla JavaScript (`DataTableViewer`, `DataTreeViewer`) - lightweight, no dependencies.

**Alternative libraries to consider if advanced features needed:**

| Library | Size | Use Case |
|---------|------|----------|
| **Tabulator** | ~100KB | Virtual scrolling, column resize, export (10K+ rows) |
| **AG Grid** (Free) | ~500KB | Professional tables, filtering, grouping |
| **json-viewer** | ~10KB | Focused JSON tree visualization |
| **JSONEditor** | ~200KB | Tree + code view with editing |

**Criteria for upgrade:**
- User requests column resizing or virtual scrolling for large files
- Performance issues with current implementation (>5000 rows)
- Need for data export (CSV, Excel) from preview

**Current vanilla JS is sufficient for v1.13.x preview use case.**

### Gemini 3 API Features (Research)

**Reference:** https://ai.google.dev/gemini-api/docs/gemini-3

#### New Models
| Model | Context | Pricing (input/output) |
|-------|---------|------------------------|
| **Gemini 3.1 Pro Preview** | 1M / 64K tokens | $2/$12 per 1M (<200K ctx); $4/$18 (>200K) |
| **Gemini 3 Flash Preview** | 1M / 64K tokens | $0.50/$3 per 1M |
| **Gemini 3.1 Flash Image** | — | $0.25 text in / $0.067 image out |
| **Gemini 3 Pro Image** | — | $2 text in / $0.134 image out |

#### Key New Capabilities to Evaluate

- **Thinking level parameter** — `minimal/low/medium/high`; default `high`. Consider exposing in ppxai config or via `/model` hints
- **Thought signatures** — encrypted reasoning context maintained across calls; critical for function calling chains; may affect session serialization
- **Multimodal function responses** — tool results can include images (extends existing tool system)
- **Structured outputs + tools** — native combo of schema-constrained responses with Google Search / Code Execution / Function Calling
- **Image generation** — 4K images with text rendering, grounded via Google Search, conversational editing across turns

#### Migration Notes
- Temperature: keep at default `1.0`; changing may degrade complex reasoning
- Image segmentation **not supported** in Gemini 3 series
- Model profiles for gemini-3.1-pro-preview and gemini-3-flash-preview already in `model_profiles.py`

#### Action Items
- [x] Add gemini-3.1-pro-preview and gemini-3-flash-preview pricing to `ppxai-config.json` (v1.16.1)
- [x] Replace deprecated `thinking_budget` with `thinking_level` parameter in GeminiProvider (v1.16.1)
- [x] Update model profiles with correct context limits (1M/64K) and tier assignments (v1.16.1)
- [x] Remove deprecated gemini-2.0-flash and gemini-3-pro-preview models (v1.16.1)
- [x] Pin google-genai SDK `<1.57.0` due to code editing regression KI-001 (v1.16.1)
- [ ] Evaluate thought signatures impact on session serialization — currently transparent; google-genai SDK handles signature propagation automatically in multi-turn. No ppxai changes needed unless custom session serialization strips opaque fields.
- [ ] Multimodal tool responses — ppxai's tool result pipeline is text-only (`str` results). Supporting image bytes requires extending `ToolResult` type + base64 encoding. Deferred to v1.17.0+ when a concrete use case arises.

**Status:** Core integration done (v1.16.1). Thought signatures and multimodal responses are future items.

### Jupyter Kernel Tool (Data Science Workflow)

Enable AI to execute cells in a running JupyterLab kernel with real-time output streaming:

| Package | Purpose |
|---------|---------|
| `jupyter_client` | Connect to running kernels via connection file |
| `nbclient` | Higher-level cell execution with callbacks |
| `websockets` | Real-time output streaming via Jupyter wire protocol |
| `nbformat` | Read/write .ipynb files |

**Use case:** Data developer asks AI to "run this notebook cell by cell" and watches output appear in JupyterLab UI in real-time.

### Inline Image Preview in Chat Bubbles

**Current state:** Images render in side panels only (ppxaide ImageViewer, web app ImageFileView in RightPanelFrame). ppxai Rich TUI already renders images inline via terminal escape sequences (iTerm2/Sixel/Kitty).

**Goal:** Show images directly inside chat message bubbles when AI calls `display_file` on an image.

**Web app (cheapest win):**
1. Add `GET /files/image/{path}` endpoint to `http.py` — serves raw binary with correct `Content-Type`
2. Stream handler rewrites `display_file` events for image files to inject `![filename](/files/image/path)` into the assistant message markdown
3. `marked.parse()` renders it as an inline `<img>` automatically — no new rendering code needed

**ppxaide:** Textual's `Markdown` widget can't render pixel images inline (only shows clickable placeholder). Would require a custom widget that embeds terminal image escape sequences inside the chat scroll. Deferred until Textual adds image support or libghostty provides embeddable rendering.

**VSCode:** Could inject `<img src="data:...;base64,...">` into webview HTML. Medium effort — needs base64 fetch + webview content security policy update.

| Client | Inline today | Effort to add |
|--------|-------------|---------------|
| ppxai (Rich) | ✅ Yes | — |
| Web app | ✅ Yes (v1.16.2) | — |
| ppxaide | ❌ Side panel | High — Textual limitation |
| VSCode | ❌ Native editor | Medium — CSP + base64 |

---

## Known Issues

| Issue | Description | Status |
|-------|-------------|--------|
| ~~**`@filename` injection broken**~~ | ~~Web app file injection via `@filename` stopped working after agent context fix.~~ | ✅ Fixed in v1.13.8 |

---

## Non-Goals

ppxai is **not** trying to be:
- An autonomous coding agent (it's an interface, not an AI)
- A replacement for Claude Code or Cursor (use those for full autonomy)
- A one-size-fits-all solution (flexibility over magic)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
uv run pytest tests/ -v       # Run tests
uv run ppxai-server           # Start server for VSCode dev
```

---

## Historical Notes

For detailed release history, see [CHANGELOG.md](CHANGELOG.md).

For archived planning documents:
- [Agentic workflow design](docs/archive/v1.15.1-completed/v1.11.0-agentic-workflow-plan.md)
- [Archived release notes](docs/archive/release-notes/) (v1.11.x through v1.14.x)
- [Benchmark reports](docs/archive/benchmarks/) (Gemini, Perplexity, GPT-OSS tuning)

---

**Last Updated**: April 2, 2026
