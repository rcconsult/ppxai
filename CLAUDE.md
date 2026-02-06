# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ppxai is a terminal-based UI application for interacting with multiple AI providers (Perplexity AI, OpenAI, OpenRouter, local models). It provides an interactive chat interface with model selection, conversation history, streaming responses, and AI-powered tools.

**Current Version:** v1.15.2

**v1.15.2 highlights:**
- **NEW:** Response validation system - detects LLM hallucinations and tool result contradictions
- **NEW:** `ResponseValidator` class in `engine/tools/validator.py` - tracks tool calls and validates claims
- **NEW:** WARNING SSE events - real-time alerts when model claims contradict tool results
- **NEW:** Web app warning display - styled warnings show detected issues with suggested actions
- **NEW:** Enhanced system prompt - instructs models to verify tool results before claiming success
- **NEW:** `/terminal` command - shows terminal detection and image protocol config help
- **NEW:** `PPXAI_TERMINAL` and `PPXAI_IMAGE_PROTOCOL` env vars for multi-terminal setups
- **NEW:** Double Ctrl+C to quit pattern in ppxaide (prevents accidental exits)
- **FIX:** Unicode whitespace normalization in `apply_patch` - NBSP (`\xa0`), NNBSP (`\u202f`), Thin Space now match regular spaces
- **FIX:** 5-level fuzzy matching in `_replace_hunk()`: exact → CRLF → Unicode normalize → strip+normalize → collapse
- **FIX:** Truncated tool call detection - detects "I'll use X tool" with incomplete JSON and provides recovery feedback
- **FIX:** GPT-OSS intermittent tool calling issue - auto-retry with targeted guidance when vLLM Harmony parser fails
- **FIX:** Autocomplete preserves command prefix for subcommands (`/provider ` + TAB works)
- **FIX:** `/status` shows terminal override indicators when env vars are set
- **FIX:** Config loader now includes all config sections (`server`, `session`, `tui`, `paths`, etc.)
- **FIX:** `server.idle_timeout` config now properly read (was always using 300s default)
- **FIX:** Web app `/context reload` shows correct message instead of false "not found"
- **FIX:** Web app clipboard button now uses correct global reference (`window.ppxai`)
- **FIX:** Web app `display_file` event now handled properly (opens split preview)
- **TESTS:** 20 new tests for Unicode whitespace normalization and truncated tool call detection
- **DOCS:** Comprehensive terminal image display guide in INSTALLATION.md
- **DOCS:** GPT-OSS "explain before calling" tool issue and `max_tokens` mitigation

**v1.15.0 highlights:**
- **NEW:** Type-based renderer dispatch - commands return typed result objects
- **NEW:** 17 CommandResult types for UI-agnostic command architecture
- **NEW:** RichRenderer and TextualRenderer with mechanical type dispatch
- **CHANGE:** All 32 Rich TUI commands migrated to return typed results
- **CHANGE:** Commands are now testable without UI framework dependencies
- **CLEANUP:** Removed all v2 naming artifacts (~1,698 lines of legacy code)

**v1.14.2 highlights:**
- **NEW:** Hierarchical context scopes - global (`~/.ppxai/`), project (git root), subdir (cwd)
- **NEW:** `/context show` command - displays bootstrap sources with scope labels
- **NEW:** `@clipboard` and `@url` context providers - inject clipboard text or web content
- **NEW:** Include directive - `<!-- include: ./file.md -->` for modular AGENTS.md
- **NEW:** Hint templates - reusable hints in `~/.ppxai/hint-templates.yaml`
- **CHANGE:** Gemini default model updated to `gemini-2.5-flash` (2.0 deprecated March 2026)
- **CHANGE:** Provider/model hints from all scopes merge additively

**v1.14.1 highlights:**
- `/edit` command for VSCode - opens files in native editor with line:col support
- `/edit` command for Web App - Monaco-style editor with syntax highlighting
- `/context reload` command - refresh AGENTS.md without restarting session

**v1.14.0 highlights:**
- AGENTS.md/CLAUDE.md bootstrap context support - project-specific instructions loaded on startup
- YAML front matter for provider/model-specific hints (dynamic prompt assembly)
- `local` provider inheritance - ollama, vllm, lmstudio inherit from `local` hints

**Version Alignment:**
- Python package (pyproject.toml): v1.15.2
- VSCode extension (package.json): v1.15.2
- Git tag: v1.15.2

For detailed release history, see [CHANGELOG.md](CHANGELOG.md) and `docs/RELEASE-NOTES-v*.md`.

## Codebase Statistics (v1.14.0)

| Language | Files | Lines |
|----------|------:|------:|
| Python (core) | 66 | ~24,100 |
| Python (tests) | 30 | ~11,800 |
| TypeScript (VSCode) | 17 | ~8,300 |
| JavaScript (Web) | 7 | ~5,200 |
| CSS | 3 | ~2,000 |
| **Total** | **~123** | **~51,400** |

Breakdown: ~70% Python, ~16% TypeScript, ~10% JavaScript, ~4% CSS/HTML

## Installation Locations (CRITICAL)

**IMPORTANT: Follow these exact paths. NEVER use `AppData\Local\ppxai` on Windows.**

| Item | Linux | macOS | Windows |
|------|-------|-------|---------|
| **Binaries** | `~/.local/bin/` | `~/.local/bin/` | `~/.ppxai/bin/` |
| **App bundle** | - | `/Applications/ppxai.app` | - |
| **Config** | `~/.ppxai/ppxai-config.json` | `~/.ppxai/ppxai-config.json` | `~/.ppxai/ppxai-config.json` |
| **API keys** | `~/.ppxai/.env` | `~/.ppxai/.env` | `~/.ppxai/.env` |
| **Data** | `~/.ppxai/` | `~/.ppxai/` | `~/.ppxai/` |
| **Web UI** | `~/.ppxai/web/` | `~/.ppxai/web/` | `~/.ppxai/web/` |

**Windows structure (`%USERPROFILE%\.ppxai\`):**
```
~/.ppxai/
├── bin/                    # Binaries
│   ├── ppxai.exe          # TUI binary
│   ├── ppxai-server.exe   # Server binary
│   └── ppxai-desktop.exe  # Desktop app binary
├── web/                    # Web UI files (app.js, index.html, lib/)
│   ├── lib/               # JavaScript libraries (js-yaml, toml, hcl2-parser, etc.)
│   └── shared/            # Shared command definitions
├── sessions/              # Saved sessions
├── exports/               # Exported markdown files
├── checkpoints/           # File-based undo snapshots
├── logs/                  # Debug logs
├── usage/                 # Usage statistics
├── ppxai-config.json      # User configuration
└── .env                   # API keys
```

**Linux/macOS structure:**
```
~/.local/bin/
├── ppxai                   # TUI binary
├── ppxai-server            # Server binary
└── ppxai-desktop           # Desktop app binary

~/.ppxai/
├── web/                    # Web UI files
├── sessions/              # Saved sessions
├── exports/               # Exported markdown files
├── checkpoints/           # File-based undo snapshots
├── logs/                  # Debug logs
├── usage/                 # Usage statistics
├── ppxai-config.json      # User configuration
└── .env                   # API keys
```

**When deploying/copying files:**
- **Windows**: Use `~/.ppxai/bin/` for binaries, `~/.ppxai/` for data + web
- **Linux/macOS**: Use `~/.local/bin/` for binaries, `~/.ppxai/` for data + web

The `AppData\Local\ppxai` path exists only as a **search path** for finding binaries, NOT as an installation target.

## Development Setup

### File Encoding: UTF-8 without BOM

**IMPORTANT**: All source files MUST be UTF-8 encoded **without** BOM (Byte Order Mark).

- Windows PowerShell's `Out-File` cmdlet adds BOM by default - avoid using it
- Use `Set-Content -Encoding UTF8` or write files via Python with `encoding='utf-8'`
- The config loader uses `utf-8-sig` to handle BOM gracefully when reading

### Quick Start with uv (recommended)

```bash
# First-time setup
python scripts/bootstrap.py --all

# Or manual setup
uv sync --all-extras

# Configure API keys
cp .env.example .env
# Edit .env and add your API keys

# Run
uv run ppxai           # TUI
uv run ppxai-server    # HTTP server for VSCode

# Test
uv run pytest tests/ -v
```

### Alternative: pip

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python ppxai.py
```

## Architecture

Layered architecture with clear separation of concerns:

```
ppxai/
├── engine/              # Core business logic (no UI)
│   ├── client.py        # EngineClient facade
│   ├── types.py         # Message, Event, UsageStats
│   ├── session.py       # Session management
│   ├── providers/       # Perplexity, OpenAI-compat
│   └── tools/           # Tool system + builtins
├── server/              # HTTP/SSE server for IDE
│   └── http.py          # FastAPI endpoints
├── main.py              # TUI entry point
├── commands.py          # Slash command handlers
└── config.py            # Configuration system

vscode-extension/        # TypeScript VSCode extension
├── src/
│   ├── extension.ts     # Entry point
│   ├── httpClient.ts    # HTTP + SSE client
│   ├── chatPanel.ts     # Webview chat UI
│   └── handlers/        # Extracted handlers (Phase 2-4)
│       ├── eventBus.ts  # Pub/sub communication
│       ├── stream.ts    # Stream event processing
│       ├── consent.ts   # Consent dialog handlers
│       └── agentStateMachine.ts  # Agent loop state
├── media/webview/       # External CSS/JS (Phase 1)
└── package.json
```

### Configuration Files

| File | Purpose | Git |
|------|---------|-----|
| `.env` | API keys (secrets) | ❌ Never commit |
| `ppxai-config.json` | Provider definitions | ✅ Can commit |

## Common Commands

```bash
# Run application
uv run ppxai                    # TUI
uv run ppxai-server             # HTTP server
uv run ppxai-desktop            # Desktop web app

# Testing
uv run pytest tests/ -v

# Build binaries (Windows with corporate proxy)
SSL_CERT_FILE="C:/.ssh/Fortinet_CA_SSL.cer" .uv/uv run pyinstaller ppxai.spec --noconfirm

# Build VSCode extension
cd vscode-extension && npm run compile && npx vsce package --allow-missing-repository

# Copy beta binaries to external drive (Windows)
# Will prompt for destination if not provided
powershell -File scripts/copy-beta.ps1 -TargetDir "I:\Software\ppxai"
```

## Release Process

**CRITICAL: Always use the `/release` skill for releases.**

```bash
/release v1.x.x
# Or: uv run python scripts/release.py v1.x.x
```

**NEVER manually:** update version files, create git tags, run `gh release create`, or upload assets.

### Files Updated by Release Script

| File | Pattern |
|------|---------|
| `pyproject.toml` | `version = "X.Y.Z"` |
| `ppxai/__init__.py` | `__version__ = "X.Y.Z"` |
| `vscode-extension/package.json` | `"version": "X.Y.Z"` |
| `vscode-extension/package-lock.json` | `"version": "X.Y.Z"` |
| `ppxai/common/event_handler.py` | `Version: vX.Y.Z` |
| `README.md` | `ppxai-X.Y.Z.vsix` |
| `vscode-extension/README.md` | `ppxai-X.Y.Z.vsix` |
| `CLAUDE.md` | `**Current Version:** vX.Y.Z` |
| `ROADMAP.md` | `**Current Version**: vX.Y.Z` |

### Pre-Release Checklist

1. Create CHANGELOG entry: `## [X.Y.Z] - YYYY-MM-DD`
2. Write release notes: `docs/RELEASE-NOTES-vX.Y.Z.md`
3. Merge feature branch to master
4. Run: `python scripts/validate-release.py vX.Y.Z`

### Release Assets (Built by CI)

- `ppxai-{version}.vsix` - VSCode extension
- `ppxai-{platform}` - TUI binaries (linux-amd64, macos-arm64, macos-intel, windows.exe)
- `ppxai-server-{platform}` - Server binaries
- `ppxai-desktop-{platform}` - Desktop web app binaries
- `ppxai-{version}-macos-arm64.dmg` - macOS installer

## GitHub CLI Authentication

Use token from `.github/gh-token.env` (gitignored):

```bash
GH_TOKEN=$(cat .github/gh-token.env) gh release list
```

## Key Design Decisions

1. **Layered Architecture** - Engine (no UI) → Server (HTTP/SSE) → Clients (TUI, VSCode, Web)
2. **Provider Abstraction** - All providers implement `BaseProvider` interface
3. **Event-Based Communication** - Engine emits events; clients render them
4. **OpenAI SDK for all providers** - OpenAI-compatible API format
5. **Hybrid config** - Secrets (`.env`) separate from settings (`ppxai-config.json`)
6. **Built-in providers** - Perplexity and Gemini always available without config
7. **Transactional State Management** - Checkpoint/commit/rollback for atomic multi-step operations (v1.15.0)

## Critical Architecture Pattern: Transactional State Management

**Added:** v1.15.0
**Status:** **CRITICAL - Apply to all multi-step state operations**
**Reference:** `docs/ARCHITECTURE.md` (full documentation)

### Problem

AI agents perform multi-step operations that must succeed atomically or fail completely. Partial state updates create inconsistent UI, broken sessions, and user confusion.

### Solution: GitOps-Style Transactions

```python
with status_bar.transaction() as txn:
    txn.add("tokens", "Tokens", "1234")
    txn.update("provider", "ollama")
    txn.remove("cost")
    success, error = txn.commit()
    if not success:
        # All changes rolled back automatically
        notify_user(f"Update failed: {error}")
```

### Pattern Components

1. **Checkpoint** - Automatic backup of current state on transaction enter
2. **Stage Operations** - Chainable operations queued for validation
3. **Validate** - All operations checked before any are applied
4. **Commit** - Atomic application (all succeed or none do)
5. **Rollback** - Restore checkpoint on failure or exception

### Where to Apply

**REQUIRED for:**
- Provider/model switching with related config updates
- Context injection with multiple files
- Session state updates (messages + tokens + cost)
- Multi-step tool execution
- UI state synchronization across multiple widgets

**Example - Provider Switch:**
```python
async def switch_provider(new_provider: str, new_model: str):
    with status_bar.transaction() as txn:
        txn.update("provider", new_provider)
        txn.update("model", new_model)
        # Provider-specific badges
        if new_provider == "perplexity":
            txn.add("web", "Web", "ON")
            txn.remove("thinking")  # If exists
        success, error = txn.commit()
        if not success:
            notify(f"UI update failed: {error}")
            return False

    # Only update engine if UI transaction succeeded
    try:
        await engine_client.set_provider(new_provider)
        await engine_client.set_model(new_model)
        return True
    except Exception as e:
        # Rollback UI if engine update failed
        with status_bar.transaction() as txn:
            txn.update("provider", old_provider)
            txn.update("model", old_model)
            txn.commit()
        notify(f"Engine error: {e}")
        return False
```

### Benefits

- **State Consistency** - No partial updates, system always in valid state
- **Error Recovery** - Automatic rollback with clear error messages
- **User Trust** - Predictable all-or-nothing behavior
- **Debugging** - Clear transaction boundaries identify failures
- **Composability** - Complex workflows from simple atomic units

### Implementation Status

- ✅ StatusBar badge management (`ppxai/tui/widgets/status_bar.py`)
- ⏳ Provider/model switching (planned for Phase 6)
- ⏳ Context injection (planned)
- ⏳ Session state management (planned)

**Rule:** Any operation that modifies multiple related pieces of state MUST use this pattern.

## VSCode Extension

### Installation

Download from [GitHub Releases](https://github.com/rcconsult/ppxai/releases):
- `ppxai-server-{platform}` - Server binary
- `ppxai-{version}.vsix` - Extension

```bash
code --install-extension ppxai-X.Y.Z.vsix
./ppxai-server-{platform}
```

### Extension Settings

- `ppxai.serverUrl` - Server URL (default: `http://127.0.0.1:54320`)
- `ppxai.defaultProvider` - Default AI provider
- `ppxai.defaultModel` - Default model
- `ppxai.enableTools` - Enable AI tools

### Commands

- `ppxai.openChat` - Open chat panel
- `ppxai.explainSelection` - Explain selected code
- `ppxai.generateTests` - Generate tests
- `ppxai.switchProvider` / `ppxai.switchModel` - Switch provider/model

## Known Issues

**Accepted behavior:**
- Perplexity/Gemini may use shell commands for web data instead of native search when tools enabled

**Resolved:** TUI Markdown Tables (v1.10.4), Ctrl-C Message Alternation (v1.10.5)

## ppxaide TUI Implementation (CRITICAL)

The `ppxaide` command launches a Textual-based TUI with syntax-highlighted code editing. This section documents key implementation details that MUST be preserved.

### Syntax Highlighting Requirements

**Dependencies (pyproject.toml):** Syntax highlighting requires tree-sitter packages:
```
tree-sitter>=0.23
tree-sitter-python>=0.25.0
tree-sitter-javascript>=0.25.0
tree-sitter-json>=0.24.8
tree-sitter-yaml>=0.7.2
tree-sitter-toml>=0.7.0
tree-sitter-html>=0.23.2
tree-sitter-css>=0.25.0
tree-sitter-markdown>=0.5.1
tree-sitter-bash>=0.25.1
```

Without these packages, TextArea shows plain text with no syntax colors.

### Two Theme Systems

The TUI has **two separate theme systems** that must stay synchronized:

| System | Purpose | Available Options |
|--------|---------|-------------------|
| **App Theme** | Overall UI colors (Textual CSS) | 17+ themes (catppuccin-mocha, dracula, etc.) |
| **Syntax Theme** | Code highlighting (TextArea) | 5 themes only: dracula, github_light, monokai, vscode_dark, css |

### Theme Synchronization

**Key files:**
- `ppxai/tui/widgets/code_editor.py` - Contains `APP_THEME_TO_SYNTAX` mapping and `get_syntax_theme_for_app_theme()`
- `ppxai/tui/app.py` - Contains `watch_theme()` method that updates all CodeEditor widgets

**How it works:**
1. `CodeEditor.compose()` gets current app theme and selects matching syntax theme
2. `PPXAIDEApp.watch_theme()` is called automatically when theme changes (Ctrl+T or Ctrl+P)
3. All mounted CodeEditor widgets have their `syntax_theme` property updated

**Theme mapping logic:**
```python
# Dark app themes → dark syntax themes
"catppuccin-mocha": "dracula"
"dracula": "dracula"
"tokyo-night": "dracula"
"tron-legacy": "vscode_dark"
"matrix": "vscode_dark"
# Light app themes → light syntax theme
"textual-light": "github_light"
"solarized-light": "github_light"
```

**Framework limitation:** Custom app themes (tron-legacy, matrix) cannot have matching custom syntax themes. Textual's TextArea only supports 5 built-in syntax themes. The best we can do is map to the closest built-in theme (vscode_dark for cyan/green themes).

### Why Markdown Renders Nicely But Code Needs Manual Sync

Textual uses two different rendering approaches:

| Content | Widget | Theme Source | Behavior |
|---------|--------|--------------|----------|
| **Markdown** | `Markdown` widget | CSS variables (`$primary`, `$secondary`, etc.) | Auto-syncs with app theme |
| **Code** | `TextArea` widget | Internal syntax themes (dracula, etc.) | Needs manual `watch_theme()` sync |

The `Markdown` widget styles headers, links, and code blocks using CSS rules like:
```css
Markdown H1 { color: $primary; }
Markdown H2 { color: $secondary; }
```

These CSS variables are redefined by each app theme, so Markdown automatically updates when themes change.

The `TextArea` widget has its own internal rendering engine with hardcoded color palettes that don't use CSS variables. That's why we need the `watch_theme()` → `syntax_theme` chain to manually switch between the 5 available syntax themes.

### Key Bindings

- `Ctrl+T` - Cycle through 8 curated themes
- `Ctrl+P` - Command palette (all 17+ themes)
- `Ctrl+[` / `Ctrl+]` - Resize split panes (macOS compatible)
- `Ctrl+W` - Close side panel
- `F6` / `Ctrl+Tab` - Toggle focus between panes

### DO NOT BREAK

1. **Theme sync chain:** `watch_theme()` → `get_syntax_theme_for_app_theme()` → `CodeEditor.syntax_theme`
2. **Tree-sitter dependencies** in pyproject.toml
3. **Language detection** via `EXTENSION_TO_LANGUAGE` mapping in code_editor.py

## Terminal Image Rendering (v1.15.2)

ppxai supports high-resolution inline image display in terminals that support image protocols.

### Supported Terminals and Protocols

| Terminal | Protocol | ppxaide (Textual) | ppxai (Rich) |
|----------|----------|-------------------|--------------|
| Windows Terminal | Sixel | ✅ textual-image | ✅ textual-image |
| WezTerm | iTerm2 | ✅ ITerm2ImageWidget | ✅ ITerm2Image |
| iTerm2 (macOS) | TGP/iTerm2 | ✅ textual-image | ✅ ITerm2Image |
| Kitty | TGP | ✅ textual-image | ⚠️ Fallback |

### Key Implementation Details

**Textual TUI (ppxaide):**
- Uses `render_lines()` override to inject escape sequences into Textual's rendering pipeline
- Cannot use Rich renderables directly because Textual processes segments differently
- See `ppxai/tui/widgets/iterm2_widget.py` for the implementation pattern

**Rich TUI (ppxai):**
- Uses Rich renderables with the `_NULL_CONTROL` trick to pass escape sequences through
- Terminal detection in `ppxai/rendering/rich_renderer.py`

**The `_NULL_CONTROL` trick:**
```python
_NULL_CONTROL = [(ControlType.CURSOR_FORWARD, 0)]
yield Segment(escape_sequence, control=_NULL_CONTROL)
```
This tells Rich the segment contains control codes, so it passes the content through unchanged.

### WezTerm Configuration

WezTerm requires `TERM_PROGRAM` environment variable for detection:
```lua
-- ~/.wezterm.lua
config.set_environment_variables = {
  TERM_PROGRAM = 'WezTerm',
}
```

### Key Files

- `ppxai/tui/renderable/iterm2.py` - ITerm2Image Rich renderable
- `ppxai/tui/widgets/iterm2_widget.py` - Textual widget using render_lines() injection
- `ppxai/tui/widgets/image_handlers.py` - Terminal detection and widget selection
- `ppxai/rendering/rich_renderer.py` - Rich TUI image rendering

## vLLM/GPT-OSS Tool Calling Reference

**Critical Finding:** Harmony format is **mandatory** for GPT-OSS. From official documentation:
> "GPT-OSS should not be used without using the Harmony format as it will not work correctly."

The model was trained specifically on Harmony's response format with control tokens (`<|recipient|>`, `<|thinking|>`, `<|call|>`, etc.). These tokens are always output—they're not optional. If vLLM doesn't parse them, they leak into responses causing `HarmonyError`.

**Problem:** vLLM with GPT-OSS models can hit `HarmonyError: unexpected tokens remaining in message header` when using native tool calling (`--enable-auto-tool-choice --tool-call-parser openai`). This is a known vLLM/Harmony library issue ([vLLM #23567](https://github.com/vllm-project/vllm/issues/23567)).

**ppxai supports two tool calling modes:**

| Mode | Config | vLLM Flags | Reliability |
|------|--------|------------|-------------|
| **Native** | `native_tool_calling: true` | `--enable-auto-tool-choice --tool-call-parser openai` | ⚠️ HarmonyError risk |
| **Prompt-Based** | `native_tool_calling: false` | None required | ✅ Stable (recommended) |

**Key insight:** vLLM only triggers Harmony parsing when `request.tools` is provided. With `native_tool_calling: false`, ppxai doesn't send `tools` parameter, so vLLM returns plain text that ppxai parses client-side. This bypasses the unstable Harmony parser.

**Implementation details:**
- Tool prompt injection: `ppxai/engine/tools/manager.py:get_tools_prompt()`
- Multi-strategy parser: `ppxai/engine/tools/parser.py:parse_tool_call()`
- GPT-OSS nested unwrapping: `ppxai/engine/tools/parser.py:_normalize_tool_call()`
- Parameter aliasing: `ppxai/engine/tools/manager.py:PARAM_ALIAS_GROUPS`

**Documentation:**
- [docs/vllm-tool-calling-guide.md](docs/vllm-tool-calling-guide.md) - ppxai-specific guide
- [docs/prompt-based-tool-calling.md](docs/prompt-based-tool-calling.md) - General developer guide
- [examples/prompt_based_tools.py](examples/prompt_based_tools.py) - Standalone example

**Current production setup:**
- vLLM 0.11.x nightly with LMCache
- `--tool-call-parser openai` (correct flag)
- Model: `openai/gpt-oss-120b`
- ppxai default: `native_tool_calling: true`

**For developers hitting HarmonyError:** Set `native_tool_calling: false` in provider config, or use the standalone example for non-ppxai applications.

**Known Issue: "I'll use X tool" followed by JSON text (v1.15.2)**

Sometimes GPT-OSS outputs tool calls as JSON text in the response instead of using native tool calling:
```
I'll use the apply_patch tool.
```json
{"tool": "apply_patch", "arguments": {...}}
```

**Root causes:**
1. vLLM's Harmony parser intermittently fails to capture tool calls
2. Model explains what it will do before calling the tool (learned behavior)
3. Long tool calls (e.g., apply_patch with large diffs) may be truncated if no `max_tokens` is set

**Mitigation:**
1. Add `max_tokens: 8192` (or higher) to model config to prevent truncation
2. Add system prompt instruction: "NEVER say 'I'll use X tool' then output JSON - call tools directly"
3. Add AGENTS.md hint: "Do NOT output tool call JSON in your response text"
4. The fallback parser (`ppxai/engine/tools/parser.py`) will attempt to extract tool calls from text responses

**Example config:**
```json
{
  "models": {
    "openai/gpt-oss-120b": {
      "max_tokens": 8192,
      "generation_params": { "temperature": 0.2 }
    }
  }
}
```

## Commit Guidelines

- Do NOT include Claude credits or co-authored-by lines. Keep commit messages clean.
- **Never commit sensitive information:** tokens, API keys, passwords, hostnames, usernames, file paths with usernames, or other environment-specific details.
- In PRs and documentation, use generic placeholders (e.g., `your-token`, `/path/to/project`) instead of real values.
